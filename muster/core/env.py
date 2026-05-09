"""Environment dependency checking (tcp / http / proc).

Runs lightweight checks against external infrastructure (etcd, MySQL, Redis, etc.)
and returns pass/fail results for display in the TUI status bar.
"""

from __future__ import annotations

import socket
from typing import List, Tuple

from ..models import EnvCheck


def check_tcp(host: str, port: int, timeout: float = 1.0) -> bool:
    """Attempt a TCP connection to verify a host:port is reachable.

    Args:
        host: Target host name or IP address.
        port: Target port number.
        timeout: Connection timeout in seconds.

    Returns:
        ``True`` if the connection succeeds, ``False`` otherwise.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        # OSError covers refused, timeout, unreachable, etc.
        return False


def check_env(env_checks: List[EnvCheck]) -> List[Tuple[str, bool]]:
    """Run all configured environment checks and return (name, ok) pairs.

    Args:
        env_checks: List of checks to execute.

    Returns:
        Ordered list of ``(check_name, is_ok)`` tuples.
    """
    results: List[Tuple[str, bool]] = []
    for ec in env_checks:
        if ec.type == "tcp":
            ok = check_tcp(ec.host or "127.0.0.1", ec.port or 0) if ec.port else False
        elif ec.type == "http":
            # TODO: implement HTTP health check (requests / urllib)
            ok = False
        elif ec.type == "proc":
            # TODO: implement process pattern check (psutil or pgrep fallback)
            ok = False
        else:
            ok = False
        results.append((ec.name, ok))
    return results
