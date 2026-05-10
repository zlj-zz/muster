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
from .process import kill_port_owner
from .resolver import resolve_dependencies, resolve_port

_LOG_RETENTION_DAYS = 7


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
        self.health_timeout: int = 60
        self.port_conflict_strategy: str = "kill"
        self._reader_tasks: dict[str, asyncio.Task] = {}
        self._health_tasks: dict[str, asyncio.Task] = {}

    # ---------- internal helpers ----------

    def _log(self, svc_name: str, line: str) -> None:
        """Forward a log line to the UI callback."""
        self._on_log(svc_name, line)

    def _set_status(self, svc: Service, status: Status) -> None:
        """Update a service's status and notify the UI."""
        svc.status = status
        self._on_status(svc)

    def _notify(self, msg: str, severity: str = "information") -> None:
        """Forward a notification to the UI callback."""
        self._on_notify(msg, severity)

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

    # ---------- public API ----------

    async def start_with_deps(self, svc: Service, mode: str = "default") -> None:
        """Start a service after resolving and starting all dependencies.

        Dependencies are launched layer-by-layer (group order).  Within each
        layer, services are started in parallel; the caller then waits for the
        entire layer to become ``RUNNING`` before proceeding to the next layer.

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

        # Build launch plan: one layer per group, ordered by group.order.
        order_map = {g.id: g.order for g in self.config.groups}
        layers = sorted(set(d.group for d in deps), key=lambda g: order_map.get(g, 999))
        self._log(svc.name, f"muster▸Groups: {layers}")

        for layer in layers:
            layer_svcs = [d for d in deps if d.group == layer]
            layer_names = [s.name for s in layer_svcs]
            self._log(svc.name, f"muster▸Starting [{layer}] group: {layer_names}")

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

            # Wait for the whole layer to reach a terminal state.
            for s in layer_svcs:
                is_target = s.name == svc.name
                if s.status in (Status.RUNNING, Status.FAILED):
                    if s.status == Status.FAILED:
                        self._abort_start(svc, s, is_target, "start failed")
                        return
                    self._log(svc.name, f"muster▸{s.name} already running, skip wait")
                    continue
                self._log(
                    svc.name,
                    f"muster▸Waiting for {s.name} ready (current: {s.status.value})...",
                )
                for _ in range(180):
                    if s.status == Status.RUNNING:
                        self._log(svc.name, f"muster▸{s.name} ready")
                        break
                    if s.status == Status.FAILED:
                        self._abort_start(svc, s, is_target, "start failed")
                        return
                    await asyncio.sleep(0.5)
                if s.status != Status.RUNNING:
                    self._abort_start(svc, s, is_target, "start timeout (90s)")
                    return

    async def start(self, svc: Service, mode: str = "default") -> None:
        """Start a single service process.

        Creates a subprocess shell, wires up log readers and health checks,
        and transitions the service through ``STARTING`` → ``RUNNING`` or
        ``FAILED``.

        Args:
            svc: Service to start.
            mode: Command mode key passed to ``svc.cmd_for()``.
        """
        if svc.status in (Status.STARTING, Status.RUNNING):
            return

        try:
            self._set_status(svc, Status.STARTING)
            self._notify(f"Starting {svc.name}...", "information")

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
            asyncio.create_task(self._health_check(svc))
        except Exception as e:
            err_msg = f"!!! Start error: {e}"
            svc.log_lines.append(err_msg)
            svc.last_error = str(e)
            self._log(svc.name, err_msg)
            self._set_status(svc, Status.FAILED)
            self._notify(f"Start {svc.name} failed: {e}", "error")

    async def stop(self, svc: Service) -> None:
        """Stop a service process gracefully.

        Sends ``SIGTERM`` to the process group, waits up to 8 seconds, then
        escalates to ``SIGKILL`` if necessary.

        Args:
            svc: Service to stop.
        """
        if svc.status == Status.STOPPED:
            return

        stop_msg = "muster▸Stopping service..."
        svc.log_lines.append(stop_msg)
        self._log(svc.name, stop_msg)

        for task_dict in (self._reader_tasks, self._health_tasks):
            task = task_dict.pop(svc.name, None)
            if task:
                task.cancel()

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
        self._set_status(svc, Status.STOPPED)
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
        """Stop all given services.

        Args:
            services: Iterable of services to stop.
        """
        for svc in services:
            if svc.status != Status.STOPPED:
                await self.stop(svc)

    async def cleanup(self) -> None:
        """Cancel all background tasks (log readers, health checks, etc.)."""
        for task in list(self._reader_tasks.values()) + list(
            self._health_tasks.values()
        ):
            task.cancel()

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

        Times out after 60 seconds and marks the service ``FAILED``.

        Args:
            svc: Service to health-check.
        """
        import socket

        try:
            port = svc.port or resolve_port(svc.name, self.config.port_discovery)
            if port is None:
                await asyncio.sleep(3)
                if svc.proc and svc.proc.returncode is None:
                    self._set_status(svc, Status.RUNNING)
                else:
                    self._set_status(svc, Status.FAILED)
                return

            for i in range(self.health_timeout):
                if svc.proc is None or svc.proc.returncode is not None:
                    self._set_status(svc, Status.FAILED)
                    self._log(svc.name, "muster▸Process exited, health check failed")
                    return
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                        self._set_status(svc, Status.RUNNING)
                        svc.port = port
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

            self._set_status(svc, Status.FAILED)
            self._log(svc.name, f"muster▸Port {port} not ready, health check timeout")
            self._notify(f"{svc.name} port {port} not ready", "error")
        except Exception as e:
            err = f"!!! Health check error: {e}"
            svc.log_lines.append(err)
            self._log(svc.name, err)
            self._set_status(svc, Status.FAILED)
            self._notify(f"{svc.name} health check error: {e}", "error")
