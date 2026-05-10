"""User preference persistence and runtime application.

Settings are stored in ``~/.config/muster/settings.json`` and are completely
independent of project-level ``muster-compose.yaml``.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..models import AppSettings

_SETTINGS_DIR = Path.home() / ".config" / "muster"
_SETTINGS_FILE = _SETTINGS_DIR / "settings.json"


def load_settings() -> AppSettings:
    """Load user settings from disk, falling back to defaults.

    Returns:
        ``AppSettings`` populated from disk or built-in defaults.
    """
    if not _SETTINGS_FILE.exists():
        return AppSettings()

    try:
        with open(_SETTINGS_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return AppSettings()

    # Merge with defaults so new fields are back-filled.
    merged = AppSettings().__dict__.copy()
    merged.update(data)

    # Drop keys that don't belong to AppSettings (e.g. from older formats).
    valid_keys = AppSettings.__dataclass_fields__.keys()
    merged = {k: v for k, v in merged.items() if k in valid_keys}

    try:
        return AppSettings(**merged)
    except (TypeError, ValueError):
        return AppSettings()


def save_settings(settings: AppSettings) -> None:
    """Persist settings to ``~/.config/muster/settings.json``.

    Args:
        settings: The settings instance to save.
    """
    _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings.__dict__, f, indent=2)


def apply_to_app(app, settings: AppSettings) -> None:
    """Apply settings to a running :class:`MusterApp`.

    Updates orchestrator parameters, log panel behaviour, and
    re-schedules the environment refresh timer when the interval
    changes.

    Args:
        app: The running ``MusterApp`` instance.
        settings: The new settings to apply.
    """
    # Update orchestrator
    app._orchestrator.stop_timeout = settings.stop_timeout
    app._orchestrator.health_timeout = settings.health_timeout
    app._orchestrator.port_conflict_strategy = settings.port_conflict_strategy

    # Update log panel (attributes may not exist until Task #44)
    from ..widgets.log_panel import LogPanel

    try:
        log_panel = app.query_one("#log", LogPanel)
    except Exception:
        log_panel = None

    if log_panel is not None:
        log_panel.auto_scroll = settings.log_auto_scroll
        log_panel.show_timestamp = settings.log_show_timestamp
        log_panel.buffer_lines = settings.log_buffer_lines
        log_panel.load_history = settings.load_history_on_startup
        if log_panel._buffer.maxlen != settings.log_buffer_lines:
            old = list(log_panel._buffer)
            from collections import deque

            log_panel._buffer = deque(old, maxlen=settings.log_buffer_lines)
        if log_panel._log_level == "ALL":
            log_panel._set_level(settings.log_default_level)

    # Re-schedule env refresh timer if interval changed
    old_interval = getattr(app, "_env_refresh_interval", 5)
    if old_interval != settings.env_refresh_interval:
        app._env_refresh_interval = settings.env_refresh_interval
        if hasattr(app, "_env_timer") and app._env_timer is not None:
            app._env_timer.stop()
        app._env_timer = app.set_interval(
            settings.env_refresh_interval,
            app._refresh_env_status,
        )
