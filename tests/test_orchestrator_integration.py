"""Integration tests for ServiceOrchestrator with real subprocesses.

Unlike ``test_orchestrator.py`` (fully mocked), these tests spawn real
child processes so layered startup, failure propagation, and port release
are exercised end to end. Timing-heavy assertions use generous timeouts
to stay stable on shared CI runners.
"""

from __future__ import annotations

import asyncio
import socket
import sys
import time

from muster.core.orchestrator import ServiceOrchestrator
from muster.models import MusterConfig, PortDiscovery, Service, Status


def _make_orchestrator(registry: dict[str, Service]) -> ServiceOrchestrator:
    """Build an orchestrator with no-op UI callbacks and no port discovery."""
    config = MusterConfig(
        env_checks=[],
        groups=[],
        port_discovery=PortDiscovery(enabled=False),
    )
    return ServiceOrchestrator(
        config=config,
        registry=registry,
        on_log=lambda _s, _l: None,
        on_status=lambda _s: None,
        on_notify=lambda _m, _sev: None,
    )


def _free_port() -> int:
    """Grab an ephemeral port from the kernel and release it."""
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _port_holder_cmd(port: int) -> str:
    """Command that listens on *port* (readiness-probe friendly) then idles."""
    script = (
        "import socket,time;"
        "s=socket.socket();"
        "s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);"
        f"s.bind(('127.0.0.1',{port}));"
        "s.listen(5);"
        "print('listening',flush=True);"
        "time.sleep(60)"
    )
    return f'{sys.executable} -c "{script}"'


class TestLayeredStartup:
    """Dependency-chain startup with real child processes."""

    async def test_dep_starts_before_dependent(self):
        """start_with_deps gates the dependent until its dep is RUNNING."""
        dep_port = _free_port()
        dep = Service(
            name="dep",
            cmd=_port_holder_cmd(dep_port),
            group="backend",
            port=dep_port,
        )
        app_port = _free_port()
        app = Service(
            name="app",
            cmd=_port_holder_cmd(app_port),
            group="backend",
            port=app_port,
            depends_on=["dep"],
        )
        orch = _make_orchestrator({"dep": dep, "app": app})
        orch.health_timeout = 20
        orch.layer_timeout = 30
        try:
            await asyncio.wait_for(orch.start_with_deps(app), timeout=45)
            assert dep.status == Status.RUNNING
            assert app.status == Status.RUNNING
            assert dep.start_time is not None
            # The dependent is only spawned after the dep passed its health
            # check, so its start_time must be the later one.
            assert app.start_time >= dep.start_time
        finally:
            await orch.stop_all([dep, app])


class TestFailurePropagation:
    """Failed dependencies must abort the chain without stalling."""

    async def test_spawn_failure_fails_fast(self):
        """A dep that fails before spawn wakes waiters instead of stalling.

        Regression test for C1: a cmd dict without a "default" key makes
        ``cmd_for()`` raise inside ``start()``. Before the fix the whole
        layer waited for the full ``layer_timeout``.
        """
        dep = Service(name="dep", cmd={"test": "echo hi"}, group="backend")
        app = Service(
            name="app", cmd="sleep 60", group="backend", depends_on=["dep"]
        )
        orch = _make_orchestrator({"dep": dep, "app": app})
        orch.layer_timeout = 15
        started = time.monotonic()
        await asyncio.wait_for(orch.start_with_deps(app), timeout=30)
        elapsed = time.monotonic() - started

        assert dep.status == Status.FAILED
        assert dep._ready_event.is_set()
        # Aborted before the target was ever spawned.
        assert app.status == Status.STOPPED
        # Must abort well before the layer timeout (regression guard).
        assert elapsed < orch.layer_timeout


class TestStopReleasesPort:
    """Stopping a service must free its listening port."""

    async def test_stop_releases_port(self):
        port = _free_port()
        svc = Service(
            name="solo",
            cmd=_port_holder_cmd(port),
            group="backend",
            port=port,
        )
        orch = _make_orchestrator({"solo": svc})
        orch.health_timeout = 20
        try:
            await asyncio.wait_for(orch.start(svc), timeout=30)
            # start() spawns and returns; readiness arrives via _health_check.
            await asyncio.wait_for(svc._ready_event.wait(), timeout=25)
            assert svc.status == Status.RUNNING
        finally:
            await orch.stop(svc)
        assert svc.status == Status.STOPPED
        # The port must be bindable again; OSError means the child kept it.
        with socket.socket() as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", port))


class TestAutoRestartRecovery:
    """restart: on-failure recovers a service that crashes once."""

    async def test_crash_then_recover(self, tmp_path):
        marker = tmp_path / "crashed.once"
        script = (
            "import pathlib,sys,time;"
            f"p=pathlib.Path({str(marker)!r});"
            "(p.touch(), sys.exit(3)) if not p.exists() else time.sleep(60)"
        )
        svc = Service(
            name="flappy",
            cmd=f'{sys.executable} -c "{script}"',
            group="backend",
            restart="on-failure",
        )
        orch = _make_orchestrator({"flappy": svc})
        orch.auto_restart_backoff = 0.1
        try:
            await asyncio.wait_for(orch.start(svc), timeout=30)

            async def _poll() -> None:
                # The ready event fires twice (first liveness failure, then
                # recovery), so poll the status instead.
                while svc.status != Status.RUNNING:
                    await asyncio.sleep(0.2)

            await asyncio.wait_for(_poll(), timeout=30)
            assert svc.status == Status.RUNNING
            assert svc.auto_restart_count == 1
        finally:
            await orch.stop(svc)
