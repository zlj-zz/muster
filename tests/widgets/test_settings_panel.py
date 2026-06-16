"""Tests for the SettingsPanel widget."""

from __future__ import annotations

from muster.models import AppSettings
from muster.widgets.settings_panel import SettingsPanel
from tests.conftest import WidgetTestApp, capture_messages


class TestSettingsPanel:
    """Form rendering and value changes."""

    async def test_initial_values_rendered(self):
        settings = AppSettings(
            env_refresh_interval=10,
            port_conflict_strategy="warn",
            log_auto_scroll=False,
            log_show_timestamp=True,
            log_default_level="ERROR",
            log_buffer_lines=500,
            start_timeout=45,
            stop_timeout=3.5,
        )
        panel = SettingsPanel(settings)
        app = WidgetTestApp(panel)
        async with app.run_test() as pilot:
            await pilot.pause()

            # Numeric inputs
            assert app.query_one("#input-env-interval").value == "10"
            assert app.query_one("#input-buffer-lines").value == "500"
            assert app.query_one("#input-start-timeout").value == "45"
            assert app.query_one("#input-stop-timeout").value == "3.5"

            # Selects
            assert app.query_one("#select-port-strategy").value == "warn"
            assert app.query_one("#select-log-level").value == "ERROR"

            # Switches
            assert app.query_one("#switch-auto-scroll").value is False
            assert app.query_one("#switch-timestamps").value is True

    async def test_save_posts_settings_changed(self):
        panel = SettingsPanel(AppSettings())
        app = WidgetTestApp(panel)
        async with app.run_test() as pilot:
            await pilot.pause()

            messages = capture_messages(panel, SettingsPanel.SettingsChanged)

            # Change a few values
            app.query_one("#input-env-interval").value = "20"
            app.query_one("#switch-timestamps").value = True

            await pilot.click("#btn-save")
            await pilot.pause()

            assert len(messages) == 1
            assert messages[0].settings.env_refresh_interval == 20
            assert messages[0].settings.log_show_timestamp is True

    async def test_reset_restores_defaults(self):
        panel = SettingsPanel(
            AppSettings(env_refresh_interval=99, log_auto_scroll=False)
        )
        app = WidgetTestApp(panel)
        async with app.run_test() as pilot:
            await pilot.pause()

            messages = capture_messages(panel, SettingsPanel.SettingsChanged)

            await pilot.click("#btn-reset")
            await pilot.pause()

            assert len(messages) == 1
            assert messages[0].settings.env_refresh_interval == 5
            assert messages[0].settings.log_auto_scroll is True

            # Widgets should reflect defaults
            assert app.query_one("#input-env-interval").value == "5"
            assert app.query_one("#switch-auto-scroll").value is True
