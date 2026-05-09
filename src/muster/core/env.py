"""Environment dependency checking (tcp / http / proc).

Runs lightweight checks against external infrastructure (etcd, MySQL, Redis, etc.)
and returns pass/fail results for display in the TUI status bar.
"""

from __future__ import annotations

import socket
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from ..models import EnvCheck


def check_tcp(host: str, port: int, timeout: float = 1.0) -> tuple[bool, int | None]:
    """Attempt a TCP connection to verify a host:port is reachable.

    Args:
        host: Target host name or IP address.
        port: Target port number.
        timeout: Connection timeout in seconds.

    Returns:
        A tuple of ``(is_reachable, latency_ms)``.  ``latency_ms`` is ``None``
        when the connection fails.
    """
    try:
        start = time.perf_counter()
        with socket.create_connection((host, port), timeout=timeout):
            latency_ms = int((time.perf_counter() - start) * 1000)
            return True, latency_ms
    except OSError:
        return False, None


def _check_one(ec: EnvCheck) -> tuple[str, bool]:
    """Run a single environment check and update its runtime state.

    Args:
        ec: The check to run.

    Returns:
        ``(check_name, is_ok)`` tuple.
    """
    latency: int | None = None
    if ec.type == "tcp":
        ok, latency = (
            check_tcp(ec.host or "127.0.0.1", ec.port or 0)
            if ec.port
            else (False, None)
        )
    elif ec.type == "http":
        ok = False
    elif ec.type == "proc":
        ok = False
    else:
        ok = False

    ec.last_checked = datetime.now()
    ec.latency_ms = latency
    if ok:
        ec.consecutive_failures = 0
    else:
        ec.consecutive_failures += 1

    return ec.name, ok


def check_env(env_checks: list[EnvCheck]) -> list[tuple[str, bool]]:
    """Run all configured environment checks concurrently.

    Updates each :class:`EnvCheck` in-place with ``last_checked``,
    ``latency_ms``, and ``consecutive_failures``.

    Args:
        env_checks: List of checks to execute.

    Returns:
        Ordered list of ``(check_name, is_ok)`` tuples.
    """
    with ThreadPoolExecutor(max_workers=4) as executor:
        return list(executor.map(_check_one, env_checks))
