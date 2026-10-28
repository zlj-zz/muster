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

    # One-time migration of the legacy unified timeout field: split into
    # health/layer timeouts and raise unreasonably short values so that
    # compile-heavy services do not falsely fail on first start. Only runs
    # when the legacy key is present — afterwards user-saved timeouts are
    # respected verbatim.
    if "start_timeout" in data:
        start_timeout = data.pop("start_timeout")
        health = data.setdefault("health_timeout", start_timeout)
        if health <= 120:
            data["health_timeout"] = 300
        layer = data.setdefault("layer_timeout", max(start_timeout * 2, 120))
        if layer <= 120:
            data["layer_timeout"] = 300

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
