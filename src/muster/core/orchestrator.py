"""Service orchestration: lifecycle, health checks, log streaming.

``ServiceOrchestrator`` manages subprocess creation, monitoring, and teardown
independently of the TUI.  It communicates state changes back to the UI via
callback injection so that the module remains reusable in headless contexts.
"""

from __future__ import annotations

import asyncio
import os
import signal
import socket
from collections import deque
from datetime import datetime
from pathlib import Path
from collections.abc import Callable

from ..models import MusterConfig, Service, Status
from .env import check_tcp
from .process import kill_port_owner
from .resolver import resolve_dependencies, resolve_port

_LOG_RETENTION_DAYS = 7
_RUNTIME_HEALTH_INTERVAL = 30.0

#: Valid status transitions.  stop() may force any transition.
_VALID_TRANSITIONS: dict[Status, set[Status]] = {
    Status.STOPPED: {Status.STARTING},
    Status.STARTING: {Status.RUNNING, Status.FAILED},
    Status.RUNNING: {Status.STOPPED, Status.FAILED},
    Status.FAILED: {Status.STARTING, Status.STOPPED},
}


def _logfile_path(svc_name: str, now: datetime | None = None) -> Path:
    today = (now or datetime.now()).strftime("%Y-%m-%d")
    return Path("muster_logs") / svc_name / f"{today}.log"


def _cleanup_old_logs(svc_name: str) -> None:
    """Remove log files older than ``_LOG_RETENTION_DAYS`` for a service."""
    log_dir = Path("muster_logs") / svc_name
    cutoff = datetime.now().timestamp() - _LOG_RETENTION_DAYS * 86400
    for f in log_dir.glob("*.log"):
        if f.stat().st_mtime < cutoff:
            f.unlink()


def load_today_logs(svc_name: str, maxlen: int = 2000) -> deque[str]:
    """Load the last *maxlen* lines from today's on-disk log file.

    Called lazily when a service is first viewed in the TUI after a restart.
    If the file does not exist or cannot be read, returns an empty deque.

    Args:
        svc_name: Name of the service whose logs to load.
        maxlen: Maximum number of lines to retain (matches ``Service.log_lines``).

    Returns:
        A deque containing up to *maxlen* lines from the log file.
    """
    logfile = _logfile_path(svc_name)
    try:
        with open(logfile, "r", encoding="utf-8", errors="backslashreplace") as f:
            # Use a plain loop instead of a generator so the deque eviction
            # is inlined and avoids the generator protocol overhead.
            lines: deque[str] = deque(maxlen=maxlen)
            for ln in f:
                lines.append(ln.rstrip("\n\r"))
            return lines
    except OSError:
        return deque(maxlen=maxlen)


class ServiceOrchestrator:
    """Manages service process lifecycle independently of the UI.

    Args:
        config: Parsed ``MusterConfig`` (used for port-discovery rules and
            group ordering).
        registry: Mapping from service name to ``Service`` instance.
        on_log: Callback ``(svc_name, line)`` fired for every log line.
        on_status: Callback ``(service)`` fired whenever a service's
            ``status`` field changes.
        on_notify: Callback ``(message, severity)`` fired for user-facing
            toast notifications.
    """

    def __init__(
        self,
        config: MusterConfig,
        registry: dict[str, Service],
        *,
        on_log: Callable[[str, str], None] = lambda _s, _l: None,
        on_status: Callable[[Service], None] = lambda _s: None,
        on_notify: Callable[[str, str], None] = lambda _m, _s: None,
    ) -> None:
        self.config = config
        self.registry = registry
        self._on_log = on_log
        self._on_status = on_status
        self._on_notify = on_notify
        self.stop_timeout: float = 8.0
        self.health_timeout: int = 300
        self.layer_timeout: int = 300
        self.port_conflict_strategy: str = "kill"
        self._reader_tasks: dict[str, asyncio.Task] = {}
        self._health_tasks: dict[str, asyncio.Task] = {}
        self._monitor_tasks: dict[str, asyncio.Task] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._runtime_health_task: asyncio.Task | None = None

    # ---------- internal helpers ----------

    def _log(self, svc_name: str, line: str) -> None:
        """Forward a log line to the UI callback."""
        self._on_log(svc_name, line)

    def _get_lock(self, svc_name: str) -> asyncio.Lock:
        """Return the asyncio.Lock for *svc_name*, creating one if necessary."""
        return self._locks.setdefault(svc_name, asyncio.Lock())

    def _set_status(self, svc: Service, status: Status, *, force: bool = False) -> None:
        """Update a service's status and notify the UI.

        Guards against illegal transitions unless *force* is ``True``.
        """
        if status == svc.status:
            return
        if not force:
            valid_next = _VALID_TRANSITIONS.get(svc.status, set())
            if status not in valid_next:
                return
        svc.status = status
        self._on_status(svc)

    def _notify(self, msg: str, severity: str = "information") -> None:
        """Forward a notification to the UI callback."""
        self._on_notify(msg, severity)

    def _resolve_effective_port(self, svc: Service) -> int | None:
        """Return the TCP port to use for health checks, or ``None``.

        Prefers ``svc.port`` if already known, otherwise resolves via config.
        """
        return svc.port or resolve_port(svc.name, self.config.port_discovery)

    def _abort_start(
        self, target: Service, dep: Service, is_target: bool, reason: str
    ) -> None:
        """Log and notify that a service (or its dependency) failed to start.

        Args:
            target: The service the user originally requested to start.
            dep: The specific service that caused the abort.
            is_target: ``True`` if ``dep`` is the same as ``target``.
            reason: Human-readable failure reason (e.g. "start failed").
        """
        label = "" if is_target else f"Dep {dep.name} "
        msg = f"{label}{reason}, aborting {target.name} start"
        self._log(target.name, f"muster▸{msg}")
        self._notify(msg, "error")

    def _compute_depth_layers(self, deps: list[Service]) -> list[list[Service]]:
        """Group services by dependency depth for parallel launch.

        Depth 0 = no dependencies. Depth N = all direct dependencies
        have depth <= N-1, and at least one has depth N-1.
        """
        depth_map: dict[str, int] = {}

        def depth(svc: Service) -> int:
            if svc.name in depth_map:
                return depth_map[svc.name]
            if not svc.depends_on:
                depth_map[svc.name] = 0
                return 0
            # depth = 1 + max(depth of all dependencies)
            d = 1 + max(
                depth(self.registry[dep]) for dep in svc.depends_on
                if dep in self.registry
            )
            depth_map[svc.name] = d
            return d

        for svc in deps:
            depth(svc)

        # Group by depth
        max_depth = max(depth_map.values()) if depth_map else -1
        layers: list[list[Service]] = [[] for _ in range(max_depth + 1)]
        for svc in deps:
            layers[depth_map[svc.name]].append(svc)
        return layers

    # ---------- public API ----------

    async def start_with_deps(self, svc: Service, mode: str = "default") -> None:
        """Start a service after resolving and starting all dependencies.

        Dependencies are launched layer-by-layer. Within each layer, services
        are started in parallel; the caller waits for the entire layer to
        reach a terminal state before proceeding to the next layer.

        If any dependency fails or times out, the start sequence is aborted.

        Args:
            svc: The target service to start.
            mode: Command mode key (e.g. ``"default"``, ``"test"``).
        """
        try:
            deps = resolve_dependencies([svc.name], self.registry)
        except ValueError as e:
            self._notify(f"Dependency resolution failed: {e}", "error")
            return

        dep_names = [d.name for d in deps]
        self._log(svc.name, f"muster▸Dependencies: {dep_names}")

        # Pre-emptively handle any process already bound to the target port.
        port = svc.port or resolve_port(svc.name, self.config.port_discovery)
        if port and not await self._check_port_conflict(svc.name, port):
            return

        # Build launch plan: one layer per dependency depth.
        layers = self._compute_depth_layers(deps)
        layer_names = [[s.name for s in layer] for layer in layers]
        self._log(svc.name, f"muster▸Launch layers: {layer_names}")

        for layer_idx, layer_svcs in enumerate(layers):
            layer_names = [s.name for s in layer_svcs]
            self._log(svc.name, f"muster▸Starting layer {layer_idx}: {layer_names}")

            # Kick off every service in this layer that is not already running.
            for s in layer_svcs:
                if s.status not in (Status.STARTING, Status.RUNNING):
                    p = s.port or resolve_port(s.name, self.config.port_discovery)
                    if p and not await self._check_port_conflict(
                        svc.name, p, dep_name=s.name
                    ):
                        return
                    self._log(
                        svc.name,
                        f"muster▸Scheduling start: {s.name} (status: {s.status.value})",
                    )
                    asyncio.create_task(self.start(s, mode))
                else:
                    self._log(
                        svc.name,
                        f"muster▸Skipping start: {s.name} (status: {s.status.value})",
                    )

            # Wait for the whole layer to reach a terminal state in parallel.
            # Each service has its own ready event; waiting serially would
            # multiply the timeout by the layer size, so we gather them.
            self._log(
                svc.name,
                f"muster▸Waiting for layer {layer_idx} to become ready (timeout: {self.layer_timeout}s)...",
            )
            layer_waiters: list[tuple[Service, asyncio.Task]] = []
            for s in layer_svcs:
                is_target = s.name == svc.name
                if s.status == Status.RUNNING:
                    self._log(
                        svc.name, f"muster▸{s.name} already running, skip wait"
                    )
                    continue
                if s.status == Status.FAILED:
                    self._abort_start(svc, s, is_target, "start failed")
                    return

                self._log(
                    svc.name,
                    f"muster▸Waiting for {s.name} ready (current: {s.status.value})...",
                )
                waiter = asyncio.create_task(
                    asyncio.wait_for(
                        s._ready_event.wait(), timeout=self.layer_timeout
                    )
                )
                layer_waiters.append((s, waiter))

            if layer_waiters:
                results = await asyncio.gather(
                    *[task for _, task in layer_waiters], return_exceptions=True
                )
                for (s, _), result in zip(layer_waiters, results):
                    is_target = s.name == svc.name
                    if isinstance(result, asyncio.TimeoutError):
                        self._abort_start(
                            svc,
                            s,
                            is_target,
                            f"start timeout ({self.layer_timeout}s)",
                        )
                        return
                    if s.status == Status.FAILED:
                        self._abort_start(svc, s, is_target, "start failed")
                        return
                    elapsed = (
                        datetime.now() - s.start_time
                    ).total_seconds() if s.start_time else 0.0
                    self._log(
                        svc.name,
                        f"muster▸{s.name} ready (startup took {elapsed:.1f}s)",
                    )

    async def start(self, svc: Service, mode: str = "default") -> None:
        """Start a single service process.

        Creates a subprocess shell, wires up log readers and health checks,
        and transitions the service through ``STARTING`` → ``RUNNING`` or
        ``FAILED``.

        Args:
            svc: Service to start.
            mode: Command mode key passed to ``svc.cmd_for()``.
        """
        async with self._get_lock(svc.name):
            if svc.status in (Status.STARTING, Status.RUNNING):
                return
            svc._ready_event.clear()
            self._set_status(svc, Status.STARTING)
        self._notify(f"Starting {svc.name}...", "information")

        try:

            now = datetime.now()
            cmd = svc.cmd_for(mode)
            if not cmd:
                raise RuntimeError("no command available for mode")
            # Unset GOROOT to avoid conflicts with local Go toolchains.
            cmd = f"unset GOROOT && {cmd}"

            logfile = _logfile_path(svc.name, now)
            logfile.parent.mkdir(parents=True, exist_ok=True)
            _cleanup_old_logs(svc.name)

            # Write restart separator to on-disk log.
            with open(logfile, "a", encoding="utf-8") as f:
                f.write(f"\n=== muster restart {now.isoformat()} ===\n\n")

            svc.log_lines.clear()
            svc.log_lines.extend(
                [
                    f"muster▸Command: {cmd}",
                    "muster▸Compiling (first start may take a few seconds)...",
                ]
            )
            for line in svc.log_lines:
                self._log(svc.name, line)

            shell = os.environ.get("SHELL", "/bin/sh")
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
                executable=shell,
            )
            svc.proc = proc
            svc.start_time = now
            pid_msg = f"muster▸Process PID: {proc.pid}"
            svc.log_lines.append(pid_msg)
            self._log(svc.name, pid_msg)

            self._reader_tasks[svc.name] = asyncio.create_task(
                self._read_output(svc, proc, logfile)
            )
            self._health_tasks[svc.name] = asyncio.create_task(self._wait_process(svc))
            self._monitor_tasks[svc.name] = asyncio.create_task(self._health_check(svc))
            if self._runtime_health_task is None or self._runtime_health_task.done():
                self._runtime_health_task = asyncio.create_task(
                    self._runtime_health_loop()
                )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            err_msg = f"!!! Start error: {e}"
            svc.log_lines.append(err_msg)
            svc.last_error = str(e)
            self._log(svc.name, err_msg)
            async with self._get_lock(svc.name):
                self._set_status(svc, Status.FAILED)
            self._notify(f"Start {svc.name} failed: {e}", "error")

    async def stop(self, svc: Service) -> None:
        """Stop a service process gracefully.

        Sends ``SIGTERM`` to the process group, waits up to 8 seconds, then
        escalates to ``SIGKILL`` if necessary.

        Args:
            svc: Service to stop.
        """
        async with self._get_lock(svc.name):
            if svc.status == Status.STOPPED:
                return

        stop_msg = "muster▸Stopping service..."
        svc.log_lines.append(stop_msg)
        self._log(svc.name, stop_msg)

        for task_dict in (self._reader_tasks, self._health_tasks, self._monitor_tasks):
            task = task_dict.pop(svc.name, None)
            if task:
                task.cancel()

        # Cancel the global runtime health loop only when no services remain.
        if self._runtime_health_task and not any(
            s.status in (Status.STARTING, Status.RUNNING) for s in self.registry.values()
        ):
            self._runtime_health_task.cancel()
            self._runtime_health_task = None

        if svc.proc and svc.proc.returncode is None:
            try:
                os.killpg(os.getpgid(svc.proc.pid), signal.SIGTERM)
                await asyncio.wait_for(svc.proc.wait(), timeout=self.stop_timeout)
            except asyncio.TimeoutError:
                try:
                    os.killpg(os.getpgid(svc.proc.pid), signal.SIGKILL)
                    await asyncio.wait_for(svc.proc.wait(), timeout=2.0)
                except Exception as e:
                    # Log to stderr since the logger may already be torn down.
                    import sys

                    print(f"SIGKILL failed for {svc.name}: {e}", file=sys.stderr)
            except Exception as e:
                import sys

                print(f"stop_service failed for {svc.name}: {e}", file=sys.stderr)

        svc.proc = None
        svc.start_time = None
        async with self._get_lock(svc.name):
            self._set_status(svc, Status.STOPPED, force=True)
        svc._ready_event.clear()
        stopped_msg = "muster▸Service stopped"
        svc.log_lines.append(stopped_msg)
        self._log(svc.name, stopped_msg)
        self._notify(f"{svc.name} stopped", "information")

    async def _check_port_conflict(
        self, target_name: str, port: int, dep_name: str | None = None
    ) -> bool:
        """Handle a port already in use according to the configured strategy.

        Args:
            target_name: Name of the service being started.
            port: The port to check.
            dep_name: Name of the dependency (if checking a dep), otherwise None.

        Returns:
            ``True`` if it is safe to proceed, ``False`` if the start should abort.
        """
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                pass  # port is occupied
        except OSError:
            return True  # port is free

        label = f"Dep {dep_name} " if dep_name else ""
        msg = f"{label}port {port} in use"

        if self.port_conflict_strategy == "kill":
            self._log(target_name, f"muster▸{msg}, cleaning up...")
            await kill_port_owner(port)
            return True
        elif self.port_conflict_strategy == "warn":
            self._log(target_name, f"muster▸{msg}, skipping kill (warn mode)")
            return True
        else:  # "abort"
            self._log(target_name, f"muster▸{msg}, aborting start")
            self._notify(f"{msg}, start aborted", "error")
            return False

    async def restart(self, svc: Service, mode: str = "default") -> None:
        """Restart a service.

        Args:
            svc: Service to restart.
            mode: Command mode key.
        """
        svc.restart_count += 1
        await self.stop(svc)
        await asyncio.sleep(0.5)
        await self.start_with_deps(svc, mode)

    async def stop_all(self, services: list[Service]) -> None:
        """Stop all given services in parallel.

        Args:
            services: Iterable of services to stop.
        """
        await asyncio.gather(
            *[self.stop(svc) for svc in services if svc.status != Status.STOPPED],
            return_exceptions=True,
        )

    async def cleanup(self) -> None:
        """Cancel and await all background tasks (log readers, health checks, etc.)."""
        tasks = (
            list(self._reader_tasks.values())
            + list(self._health_tasks.values())
            + list(self._monitor_tasks.values())
        )
        if self._runtime_health_task:
            tasks.append(self._runtime_health_task)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # ---------- background tasks ----------

    async def _read_output(
        self, svc: Service, proc: asyncio.subprocess.Process, logfile: Path
    ) -> None:
        """Stream subprocess stdout to the in-memory ring buffer and disk log.

        ``svc.log_lines`` is a ``deque`` with ``maxlen=2000`` so old lines are
        evicted automatically in O(1) time.

        Args:
            svc: Service owning the process.
            proc: Running subprocess.
            logfile: Path to the on-disk log file.
        """
        try:
            with open(logfile, "a", encoding="utf-8") as f:
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    text = line.decode("utf-8", errors="backslashreplace").rstrip()
                    if text:
                        # Intentionally omitting flush: per-line flush is a
                        # hot-path bottleneck for high-volume logs.  Data is
                        # safe when the child exits (with-block closes the
                        # file) but up to ~8KB may be lost if muster itself
                        # crashes before the OS buffer is synced.
                        f.write(text + "\n")
                        svc.log_lines.append(text)
                        self._log(svc.name, text)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            err = f"!!! Log read error: {exc}"
            svc.log_lines.append(err)
            self._log(svc.name, err)

    async def _wait_process(self, svc: Service) -> None:
        """Wait for the subprocess to exit and update status if it failed.

        Args:
            svc: Service whose process is being monitored.
        """
        if svc.proc is None:
            return
        try:
            returncode = await svc.proc.wait()
            exit_msg = f"muster▸Process exit code: {returncode}"
            svc.log_lines.append(exit_msg)
            self._log(svc.name, exit_msg)

            if returncode != 0 and svc.status != Status.STOPPED:
                svc.last_error = f"exit code {returncode}"
                async with self._get_lock(svc.name):
                    self._set_status(svc, Status.FAILED)
                self._notify(
                    f"{svc.name} process exited abnormally (code={returncode})", "error"
                )
        except asyncio.CancelledError:
            # Ensure the subprocess is reaped so it doesn't become a zombie.
            # If stop() has already sent SIGTERM/SIGKILL, this returns quickly.
            # Capture proc locally: stop() may set svc.proc to None concurrently.
            proc = svc.proc
            if proc and proc.returncode is None:
                try:
                    await asyncio.wait_for(proc.wait(), timeout=3.0)
                except asyncio.TimeoutError:
                    pass
            raise

    async def _health_check(self, svc: Service) -> None:
        """Poll the service's TCP port until it accepts connections.

        If the service has no discoverable port, falls back to a 3-second
        heuristic: if the process is still alive, mark it ``RUNNING``.

        Times out after ``self.health_timeout`` seconds and marks the service
        ``FAILED``.

        Args:
            svc: Service to health-check.
        """
        try:
            port = self._resolve_effective_port(svc)
            if port is None:
                self._log(
                    svc.name,
                    "muster▸No discoverable port, using process liveness heuristic",
                )
                await asyncio.sleep(3)
                async with self._get_lock(svc.name):
                    if svc.proc and svc.proc.returncode is None:
                        self._set_status(svc, Status.RUNNING)
                    else:
                        self._set_status(svc, Status.FAILED)
                svc._ready_event.set()
                return

            self._log(
                svc.name,
                f"muster▸Health check started for port {port} (timeout: {self.health_timeout}s)",
            )

            for i in range(self.health_timeout):
                async with self._get_lock(svc.name):
                    if svc.proc is None or svc.proc.returncode is not None:
                        self._set_status(svc, Status.FAILED)
                # Lock released — check whether we already set FAILED.
                if svc.status == Status.FAILED:
                    self._log(svc.name, "muster▸Process exited, health check failed")
                    svc._ready_event.set()
                    return
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                        async with self._get_lock(svc.name):
                            self._set_status(svc, Status.RUNNING)
                        svc.port = port
                        svc._ready_event.set()
                        self._log(svc.name, f"muster▸Service ready (port {port})")
                        self._notify(f"{svc.name} ready (:{port})", "success")
                        return
                except OSError:
                    pass
                if i % 5 == 0:
                    self._log(
                        svc.name, f"muster▸Waiting for port {port} ready... ({i}s)"
                    )
                await asyncio.sleep(1)

            async with self._get_lock(svc.name):
                self._set_status(svc, Status.FAILED)
            svc._ready_event.set()
            self._log(svc.name, f"muster▸Port {port} not ready, health check timeout")
            self._notify(f"{svc.name} port {port} not ready", "error")
        except Exception as e:
            err = f"!!! Health check error: {e}"
            svc.log_lines.append(err)
            self._log(svc.name, err)
            async with self._get_lock(svc.name):
                self._set_status(svc, Status.FAILED)
            svc._ready_event.set()
            self._notify(f"{svc.name} health check error: {e}", "error")

    async def _runtime_health_loop(self) -> None:
        """Periodically check TCP connectivity for all RUNNING services."""
        while True:
            try:
                await asyncio.sleep(_RUNTIME_HEALTH_INTERVAL)
            except asyncio.CancelledError:
                return

            running = [
                (svc, port)
                for svc in self.registry.values()
                if svc.status == Status.RUNNING
                and (port := self._resolve_effective_port(svc)) is not None
            ]
            if not running:
                continue

            results = await asyncio.gather(
                *[
                    asyncio.to_thread(check_tcp, "127.0.0.1", port)
                    for _, port in running
                ],
                return_exceptions=True,
            )

            for (svc, port), result in zip(running, results):
                if isinstance(result, Exception):
                    err_msg = f"muster▸Runtime health check error: {result}"
                    svc.log_lines.append(err_msg)
                    self._log(svc.name, err_msg)
                    continue
                ok, _latency = result
                if ok:
                    ok_msg = f"muster▸Health check ok (port {port})"
                    svc.log_lines.append(ok_msg)
                    self._log(svc.name, ok_msg)
                    continue
                async with self._get_lock(svc.name):
                    if svc.status != Status.RUNNING:
                        continue
                    svc.last_error = (
                        f"runtime health check failed (port {port})"
                    )
                    self._set_status(svc, Status.FAILED)
                msg = (
                    f"muster▸Runtime health check failed (port {port}),"
                    " marking FAILED"
                )
                svc.log_lines.append(msg)
                self._log(svc.name, msg)
                self._notify(
                    f"{svc.name} health check failed", "error"
                )
