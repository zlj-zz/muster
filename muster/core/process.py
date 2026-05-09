"""Process lifecycle helpers.

Cross-platform utilities for managing OS processes, primarily used to clean up
stale listeners before starting a service.
"""

from __future__ import annotations

import asyncio
import os
import signal


async def kill_port_owner(port: int) -> None:
    """Kill any process currently listening on the given port.

    Dispatches to a platform-specific implementation:
      * Unix/macOS — ``lsof`` + ``SIGKILL``.
      * Windows — ``netstat`` + ``SIGTERM``.

    All errors are silently swallowed so that a failure to clean up never
    blocks the user's workflow.

    Args:
        port: The TCP port to free.
    """
    if os.name == "nt":
        await _kill_port_owner_windows(port)
    else:
        await _kill_port_owner_unix(port)


async def _kill_port_owner_unix(port: int) -> None:
    """Unix implementation using ``lsof``.

    Uses the user's preferred ``$SHELL`` (falling back to ``/bin/sh``) so that
    shell builtins and aliases are available.
    """
    try:
        shell = os.environ.get("SHELL", "/bin/sh")
        proc = await asyncio.create_subprocess_shell(
            f"lsof -t -i :{port}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            executable=shell,
        )
        stdout, _ = await proc.communicate()
        for pid_str in stdout.decode("utf-8", errors="replace").strip().splitlines():
            try:
                pid = int(pid_str.strip())
                os.kill(pid, signal.SIGKILL)
            except (ValueError, ProcessLookupError, PermissionError):
                # Process may have exited between listing and kill, or we may
                # lack permission. Either way, continue to the next PID.
                pass
    except Exception:
        pass


async def _kill_port_owner_windows(port: int) -> None:
    """Windows implementation using ``netstat`` and ``os.kill``.

    Parses ``netstat -ano`` output to extract PIDs associated with the port,
    then sends ``SIGTERM`` to each unique PID.
    """
    try:
        proc = await asyncio.create_subprocess_shell(
            f"netstat -ano | findstr :{port}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        pids = set()
        for line in stdout.decode("utf-8", errors="replace").strip().splitlines():
            parts = line.split()
            if len(parts) >= 5:
                try:
                    pids.add(int(parts[-1]))
                except ValueError:
                    continue
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
    except Exception:
        pass
