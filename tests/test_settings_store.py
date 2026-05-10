"""Tests for settings persistence and runtime application."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from muster.core.settings_store import (
    _SETTINGS_FILE,
    apply_to_app,
    load_settings,
    save_settings,
)
from textual.css.query import NoMatches

from muster.models import AppSettings


class TestLoadSettings:
    """Reading settings from disk."""

    def test_load_defaults_when_file_missing(self):
        with patch.object(_SETTINGS_FILE.__class__, "exists", return_value=False):
            settings = load_settings()
        assert settings == AppSettings()

    def test_load_valid_file(self, tmp_path, monkeypatch):
        custom = tmp_path / "settings.json"
        custom.write_text(
            json.dumps({"env_refresh_interval": 10, "log_auto_scroll": False}),
            encoding="utf-8",
        )
        monkeypatch.setattr("muster.core.settings_store._SETTINGS_FILE", custom)

        settings = load_settings()
        assert settings.env_refresh_interval == 10
        assert settings.log_auto_scroll is False
        # Missing keys fall back to defaults
        assert settings.health_timeout == 60

    def test_load_corrupt_file_returns_defaults(self, tmp_path, monkeypatch):
        custom = tmp_path / "settings.json"
        custom.write_text("not-json", encoding="utf-8")
        monkeypatch.setattr("muster.core.settings_store._SETTINGS_FILE", custom)

        settings = load_settings()
        assert settings == AppSettings()

    def test_load_extra_keys_ignored(self, tmp_path, monkeypatch):
        """Unknown keys in the JSON should not crash loading."""
        custom = tmp_path / "settings.json"
        custom.write_text(
            json.dumps({"env_refresh_interval": 10, "unknown_key": 42}),
            encoding="utf-8",
        )
        monkeypatch.setattr("muster.core.settings_store._SETTINGS_FILE", custom)

        settings = load_settings()
        assert settings.env_refresh_interval == 10


class TestSaveSettings:
    """Writing settings to disk."""

    def test_save_creates_file(self, tmp_path, monkeypatch):
        custom = tmp_path / "settings.json"
        monkeypatch.setattr("muster.core.settings_store._SETTINGS_FILE", custom)

        settings = AppSettings(env_refresh_interval=15)
        save_settings(settings)

        assert custom.exists()
        data = json.loads(custom.read_text(encoding="utf-8"))
        assert data["env_refresh_interval"] == 15


class TestApplyToApp:
    """Applying settings to a running MusterApp."""

    def test_applies_orchestrator_params(self):
        app = MagicMock()
        app._orchestrator = MagicMock()
        app.query_one.side_effect = NoMatches("no log panel")

        settings = AppSettings(
            stop_timeout=12.0,
            health_timeout=90,
            port_conflict_strategy="warn",
        )
        apply_to_app(app, settings)

        assert app._orchestrator.stop_timeout == 12.0
        assert app._orchestrator.health_timeout == 90
        assert app._orchestrator.port_conflict_strategy == "warn"

    def test_restarts_env_timer_on_interval_change(self):
        app = MagicMock()
        app._orchestrator = MagicMock()
        app.query_one.side_effect = NoMatches("no log panel")
        app._env_refresh_interval = 5
        old_timer = MagicMock()
        app._env_timer = old_timer

        settings = AppSettings(env_refresh_interval=10)
        apply_to_app(app, settings)

        old_timer.stop.assert_called_once()
        app.set_interval.assert_called_once_with(10, app._refresh_env_status)
        assert app._env_refresh_interval == 10

    def test_no_timer_restart_when_interval_unchanged(self):
        app = MagicMock()
        app._orchestrator = MagicMock()
        app.query_one.side_effect = NoMatches("no log panel")
        app._env_refresh_interval = 5
        app._env_timer = MagicMock()

        settings = AppSettings(env_refresh_interval=5)
        apply_to_app(app, settings)

        app._env_timer.stop.assert_not_called()
        app.set_interval.assert_not_called()
