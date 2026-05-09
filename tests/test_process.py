"""Unit tests for process lifecycle utilities."""

from __future__ import annotations

import asyncio
import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from muster.core.process import _kill_port_owner_unix, kill_port_owner


class TestKillPortOwnerUnix:
    """Unix port cleanup: SIGTERM -> wait -> SIGKILL."""

    @pytest.fixture
    def mock_shell_proc(self):
        """Return a mock asyncio process whose communicate() yields a PID."""
        proc = AsyncMock()
        proc.communicate.return_value = (b"12345\n", b"")
        return proc

    @patch("muster.core.process.os.kill")
    @patch("muster.core.process.asyncio.create_subprocess_shell")
    @patch("muster.core.process.asyncio.sleep", new_callable=AsyncMock)
    async def test_sends_sigterm_then_sigkill(
        self, mock_sleep, mock_create_subprocess, mock_kill, mock_shell_proc
    ):
        mock_create_subprocess.return_value = mock_shell_proc
        await _kill_port_owner_unix(8080)

        # First pass: SIGTERM
        mock_kill.assert_any_call(12345, signal.SIGTERM)
        # Should have slept for grace period
        mock_sleep.assert_awaited_once_with(2.0)
        # Second pass: SIGKILL
        mock_kill.assert_any_call(12345, signal.SIGKILL)
        assert mock_kill.call_count == 2

    @patch("muster.core.process.asyncio.create_subprocess_shell")
    async def test_no_pids_no_kill(self, mock_create_subprocess):
        proc = AsyncMock()
        proc.communicate.return_value = (b"", b"")
        mock_create_subprocess.return_value = proc
        with patch("muster.core.process.os.kill") as mock_kill:
            await _kill_port_owner_unix(8080)
            mock_kill.assert_not_called()

    @patch("muster.core.process.asyncio.create_subprocess_shell")
    async def test_re_raises_cancelled_error(self, mock_create_subprocess):
        mock_create_subprocess.side_effect = asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            await _kill_port_owner_unix(8080)

    @patch("muster.core.process.os.kill")
    @patch("muster.core.process.asyncio.create_subprocess_shell")
    @patch("muster.core.process.asyncio.sleep", new_callable=AsyncMock)
    async def test_ignores_process_lookup_error(
        self, mock_sleep, mock_create_subprocess, mock_kill, mock_shell_proc
    ):
        from unittest.mock import call

        mock_create_subprocess.return_value = mock_shell_proc
        # SIGTERM succeeds but process exits before SIGKILL
        mock_kill.side_effect = [None, PermissionError("permission denied")]
        # Should not raise
        await _kill_port_owner_unix(8080)
        assert mock_kill.call_count == 2


class TestKillPortOwnerDispatch:
    """Platform dispatch in kill_port_owner."""

    @patch("muster.core.process.os.name", "posix")
    @patch("muster.core.process._kill_port_owner_unix", new_callable=AsyncMock)
    async def test_dispatches_to_unix(self, mock_unix):
        await kill_port_owner(8080)
        mock_unix.assert_awaited_once_with(8080)

    @patch("muster.core.process.os.name", "nt")
    @patch("muster.core.process._kill_port_owner_windows", new_callable=AsyncMock)
    async def test_dispatches_to_windows(self, mock_windows):
        await kill_port_owner(8080)
        mock_windows.assert_awaited_once_with(8080)
