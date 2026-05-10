"""Environment dependency checking (tcp / http / proc).

Runs lightweight checks against external infrastructure (etcd, MySQL, Redis, etc.)
and returns pass/fail results for display in the TUI status bar.
"""

from __future__ import annotations

import os
import re
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import lru_cache
from urllib.error import URLError
from urllib.request import Request, urlopen

from ..models import EnvCheck


def _measure_latency(start: float) -> int:
    """Return elapsed time since *start* in milliseconds."""
    return int((time.perf_counter() - start) * 1000)


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
            return True, _measure_latency(start)
    except OSError:
        return False, None


def check_http(
    url: str,
    method: str = "GET",
    expect_status: int = 200,
    timeout: float = 2.0,
) -> tuple[bool, int | None]:
    """Perform an HTTP request and verify the response status code.

    Args:
        url: Full URL to request (e.g. ``http://127.0.0.1:8080/health``).
        method: HTTP method (default ``GET``).
        expect_status: Expected HTTP status code (default ``200``).
        timeout: Request timeout in seconds.

    Returns:
        A tuple of ``(is_ok, latency_ms)``.  ``latency_ms`` is ``None``
        when the request fails.
    """
    try:
        start = time.perf_counter()
        req = Request(url, method=method.upper())
        with urlopen(req, timeout=timeout) as resp:
            return resp.getcode() == expect_status, _measure_latency(start)
    except (URLError, OSError):
        return False, None


@lru_cache(maxsize=64)
def _compile_pattern(pattern: str) -> re.Pattern:
    """Compile and cache a regex pattern for process-name matching."""
    return re.compile(pattern)


def _list_processes() -> list[str]:
    """Return a list of process names, platform-agnostic.

    Uses ``tasklist`` on Windows and ``ps`` on Unix/macOS.
    """
    try:
        if os.name == "nt":
            proc = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=5.0,
                check=False,
            )
            return [
                line.split(",")[0].strip('"')
                for line in proc.stdout.splitlines()
                if line
            ]
        else:
            proc = subprocess.run(
                ["ps", "-A", "-o", "comm="],
                capture_output=True,
                text=True,
                timeout=5.0,
                check=False,
            )
            return [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    except (OSError, subprocess.TimeoutExpired):
        return []


def check_proc(pattern: str) -> bool:
    """Check whether at least one running process matches *pattern*.

    Uses ``ps`` on Unix/macOS and ``tasklist`` on Windows.

    Args:
        pattern: Regex string matched against process names.

    Returns:
        ``True`` if any process name matches.
    """
    if not pattern:
        return False
    compiled = _compile_pattern(pattern)
    return any(compiled.search(name) for name in _list_processes())


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
        ok, latency = check_http(
            ec.url or "",
            ec.method,
            ec.expect_status,
        )
    elif ec.type == "proc":
        ok = check_proc(ec.pattern or "")
    else:
        ok = False

    ec.last_checked = datetime.now()
    ec.latency_ms = latency
    ec.history.append(ok)
    ec.latency_history.append(latency)
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
