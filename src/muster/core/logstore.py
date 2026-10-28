"""On-disk service log storage: daily files, retention, lazy reload.

Split out of the orchestrator because the TUI log panel reads the same
files; persistence does not belong to process orchestration.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime
from pathlib import Path

#: Days of per-service log files to keep on disk.
_LOG_RETENTION_DAYS = 7

#: Root directory for per-service daily log files (relative to CWD).
_LOG_ROOT = Path("muster_logs")


def _logfile_path(svc_name: str, now: datetime | None = None) -> Path:
    """Return today's log file path for *svc_name*."""
    today = (now or datetime.now()).strftime("%Y-%m-%d")
    return _LOG_ROOT / svc_name / f"{today}.log"


def _cleanup_old_logs(svc_name: str) -> None:
    """Remove log files older than ``_LOG_RETENTION_DAYS`` for a service."""
    log_dir = _LOG_ROOT / svc_name
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
