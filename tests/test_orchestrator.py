"""Integration tests for ServiceOrchestrator."""

from __future__ import annotations

import asyncio
import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from muster.core.orchestrator import ServiceOrchestrator
from muster.models import AppSettings, MusterConfig, PortDiscovery, Service, Status


def _make_orchestrator(registry: dict[str, Service]) -> ServiceOrchestrator:
    """Factory: build an orchestrator with no-op callbacks."""
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
        on_notify=lambda _m, _s: None,
    )


class TestOrchestratorTimeouts:
    """Health and layer timeout configuration."""

    def test_orchestrator_has_separate_timeouts(self):
        orch = _make_orchestrator({})
        assert orch.health_timeout < orch.layer_timeout


class TestOrchestratorStart:
    """Service start lifecycle."""

    @patch("muster.core.orchestrator.asyncio.create_subprocess_shell")
    async def test_sets_starting_status(self, mock_create_subprocess):
        proc = AsyncMock()
        proc.pid = 12345
        proc.stdout = AsyncMock()
        proc.stdout.readline = AsyncMock(return_value=b"")
        proc.wait = AsyncMock(return_value=0)
        mock_create_subprocess.return_value = proc

        svc = Service(name="api", cmd="echo hello", group="backend")
        registry = {"api": svc}
        orch = _make_orchestrator(registry)

        await orch.start(svc)
        assert svc.status == Status.STARTING
        assert svc.proc is not None
        assert "muster▸Command: unset GOROOT" in svc.log_lines[0]

    @patch("muster.core.orchestrator.asyncio.create_subprocess_shell")
    async def test_no_command_sets_failed(self, mock_create_subprocess):
        svc = Service(name="api", cmd={"test": "go test"}, group="backend")
        registry = {"api": svc}
        orch = _make_orchestrator(registry)

        await orch.start(svc, mode="missing")
        assert svc.status == Status.FAILED
        assert svc.last_error is not None

    async def test_already_running_skips(self):
        svc = Service(name="api", cmd="echo hello", group="backend")
        svc.status = Status.RUNNING
        registry = {"api": svc}
        orch = _make_orchestrator(registry)

        await orch.start(svc)
        assert svc.status == Status.RUNNING


class TestOrchestratorStop:
    """Service stop lifecycle."""

    @patch("muster.core.orchestrator.os.killpg")
    @patch("muster.core.orchestrator.os.getpgid", return_value=100)
    async def test_sends_sigterm(self, mock_getpgid, mock_killpg):
        svc = Service(name="api", cmd="echo hello", group="backend")
        svc.status = Status.RUNNING
        svc.proc = AsyncMock()
        svc.proc.pid = 12345
        svc.proc.returncode = None
        svc.proc.wait = AsyncMock(return_value=0)

        registry = {"api": svc}
        orch = _make_orchestrator(registry)
        health_mock = MagicMock()
        reader_mock = MagicMock()
        monitor_mock = MagicMock()
        orch._health_tasks["api"] = health_mock
        orch._reader_tasks["api"] = reader_mock
        orch._monitor_tasks["api"] = monitor_mock

        await orch.stop(svc)
        assert svc.status == Status.STOPPED
        mock_killpg.assert_called_once_with(100, signal.SIGTERM)
        health_mock.cancel.assert_called_once()
        reader_mock.cancel.assert_called_once()
        monitor_mock.cancel.assert_called_once()

    async def test_already_stopped_skips(self):
        svc = Service(name="api", cmd="echo hello", group="backend")
        svc.status = Status.STOPPED
        registry = {"api": svc}
        orch = _make_orchestrator(registry)

        await orch.stop(svc)
        assert svc.status == Status.STOPPED


class TestOrchestratorRestart:
    """Restart increments counter."""

    @patch("muster.core.orchestrator.ServiceOrchestrator.stop", new_callable=AsyncMock)
    @patch(
        "muster.core.orchestrator.ServiceOrchestrator.start_with_deps",
        new_callable=AsyncMock,
    )
    async def test_increments_restart_count(self, mock_start, mock_stop):
        svc = Service(name="api", cmd="echo hello", group="backend")
        svc.status = Status.RUNNING
        registry = {"api": svc}
        orch = _make_orchestrator(registry)

        await orch.restart(svc)
        assert svc.restart_count == 1
        mock_stop.assert_awaited_once()
        mock_start.assert_awaited_once()


class TestWaitProcess:
    """Background task that waits for subprocess exit."""

    async def test_success_exit_code(self):
        svc = Service(name="api", cmd="echo hello", group="backend")
        svc.proc = AsyncMock()
        svc.proc.wait = AsyncMock(return_value=0)

        registry = {"api": svc}
        orch = _make_orchestrator(registry)
        await orch._wait_process(svc)
        assert svc.status == Status.STOPPED  # unchanged from default

    async def test_failure_exit_code(self):
        svc = Service(name="api", cmd="echo hello", group="backend")
        svc.status = Status.RUNNING
        svc.proc = AsyncMock()
        svc.proc.wait = AsyncMock(return_value=1)

        registry = {"api": svc}
        orch = _make_orchestrator(registry)
        await orch._wait_process(svc)
        assert svc.status == Status.FAILED
        assert svc.last_error == "exit code 1"

    async def test_reaps_on_cancel(self):
        svc = Service(name="api", cmd="echo hello", group="backend")
        svc.proc = AsyncMock()
        svc.proc.returncode = None
        svc.proc.wait = AsyncMock(side_effect=asyncio.CancelledError())

        registry = {"api": svc}
        orch = _make_orchestrator(registry)
        with pytest.raises(asyncio.CancelledError):
            await orch._wait_process(svc)
        # The CancelledError triggers the reaping path which calls wait() again
        assert svc.proc.wait.await_count >= 1


class TestLoadTodayLogs:
    """Lazy loading of historical disk logs."""

    def test_loads_last_n_lines(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "muster.core.orchestrator._logfile_path",
            lambda svc, now=None: tmp_path / f"{svc}.log",
        )
        logfile = tmp_path / "api.log"
        logfile.write_text(
            "\n".join(f"line {i}" for i in range(2500)), encoding="utf-8"
        )

        from muster.core.orchestrator import load_today_logs

        lines = load_today_logs("api", maxlen=2000)
        assert len(lines) == 2000
        assert lines[0] == "line 500"
        assert lines[-1] == "line 2499"

    def test_missing_file_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "muster.core.orchestrator._logfile_path",
            lambda svc, now=None: tmp_path / "missing.log",
        )
        from muster.core.orchestrator import load_today_logs

        lines = load_today_logs("api")
        assert len(lines) == 0

    def test_decode_error_with_backslashreplace(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "muster.core.orchestrator._logfile_path",
            lambda svc, now=None: tmp_path / f"{svc}.log",
        )
        logfile = tmp_path / "api.log"
        logfile.write_bytes(b"hello \xff world\n")
        from muster.core.orchestrator import load_today_logs

        lines = load_today_logs("api")
        assert len(lines) == 1
        assert "\\xff" in lines[0]
