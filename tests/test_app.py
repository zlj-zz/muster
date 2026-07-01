"""Integration tests for MusterApp."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from muster.models import AppSettings, Status
from muster.widgets.detail_panel import DetailPanel
from muster.widgets.log_panel import LogPanel
from muster.widgets.service_tree import ServiceTree
from muster.widgets.settings_panel import SettingsPanel
from tests.conftest import capture_messages


class TestAppLayout:
    """Initial layout and tab switching."""

    async def test_initial_tab_is_svc(self, minimal_app):
        app = minimal_app
        async with app.run_test():
            assert app.query_one("#left-svc").display is True
            assert app.query_one("#right-svc").display is True
            assert app.query_one("#left-env").display is False
            assert app.query_one("#left-yaml").display is False

    async def test_switch_tab_to_env(self, minimal_app):
        app = minimal_app
        async with app.run_test() as pilot:
            await pilot.click("#tab-env")
            await pilot.pause()
            assert app.query_one("#left-env").display is True
            assert app.query_one("#left-svc").display is False
            assert app.query_one("#activity-bar").active_tab == "env"

    async def test_switch_tab_to_yaml(self, minimal_app):
        app = minimal_app
        async with app.run_test() as pilot:
            await pilot.press("3")
            await pilot.pause()
            assert app.query_one("#left-yaml").display is True
            assert app.query_one("#left-svc").display is False
            assert app.query_one("#activity-bar").active_tab == "yaml"


class TestAppServiceInteraction:
    """ServiceTree -> DetailPanel / LogPanel linkage."""

    async def test_select_service_updates_detail(self, minimal_app):
        app = minimal_app
        async with app.run_test() as pilot:
            tree = app.query_one("#service-tree", ServiceTree)
            tree.highlight_service("api")
            await pilot.pause()

            detail = app.query_one("#detail", DetailPanel)
            assert detail.current_service is not None
            assert detail.current_service.name == "api"

    async def test_select_service_loads_log(self, minimal_app):
        app = minimal_app
        async with app.run_test() as pilot:
            tree = app.query_one("#service-tree", ServiceTree)
            tree.highlight_service("web")
            await pilot.pause()

            log = app.query_one("#log", LogPanel)
            assert log._svc_name == "web"

    async def test_detail_panel_button_message(self, minimal_app):
        app = minimal_app
        async with app.run_test() as pilot:
            detail = app.query_one("#detail", DetailPanel)
            messages = capture_messages(detail, DetailPanel.ActionTriggered)
            tree = app.query_one("#service-tree", ServiceTree)
            tree.highlight_service("api")
            await pilot.pause()
            await pilot.click("#btn-start")
            await pilot.pause()
            assert len(messages) == 1
            assert messages[0].action == "start"
            assert messages[0].service.name == "api"


class TestAppCursor:
    """Cursor navigation."""

    async def test_cursor_down_and_up(self, minimal_app):
        app = minimal_app
        async with app.run_test() as pilot:
            tree = app.query_one("#service-tree", ServiceTree)
            tree.highlight_service("api")
            await pilot.pause()
            initial = tree.cursor_node
            app.action_cursor_down()
            assert tree.cursor_node != initial
            app.action_cursor_up()
            assert tree.cursor_node == initial


class TestAppToggleService:
    """Enter key toggles start/stop."""

    async def test_toggle_stopped_service_starts(self, minimal_app):
        app = minimal_app
        async with app.run_test() as pilot:
            tree = app.query_one("#service-tree", ServiceTree)
            tree.highlight_service("api")
            await pilot.pause()
            app.action_toggle_service()
            app._orchestrator.start_with_deps.assert_called_once()

    async def test_toggle_running_service_stops(self, minimal_app):
        app = minimal_app
        async with app.run_test() as pilot:
            tree = app.query_one("#service-tree", ServiceTree)
            tree.highlight_service("api")
            await pilot.pause()
            tree.current_service.status = Status.RUNNING
            app.action_toggle_service()
            app._orchestrator.stop.assert_called_once()


class TestAppStopAll:
    """Ctrl+s double-tap stop-all."""

    async def test_stop_all_double_tap(self, minimal_app):
        app = minimal_app
        async with app.run_test() as pilot:
            # Set a service to RUNNING so stop_all has something to do
            app.all_services[0].status = Status.RUNNING
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert app._stop_pending is True
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert app._stop_pending is False
            app._orchestrator.stop.assert_called()

    async def test_stop_all_no_running(self, minimal_app):
        app = minimal_app
        async with app.run_test() as pilot:
            # All services are STOPPED by default
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert app._stop_pending is False


class TestAppRestart:
    """R key restarts selected service."""

    async def test_restart_service(self, minimal_app):
        app = minimal_app
        async with app.run_test() as pilot:
            tree = app.query_one("#service-tree", ServiceTree)
            tree.highlight_service("api")
            await pilot.pause()
            await pilot.press("R")
            await pilot.pause()
            app._orchestrator.restart.assert_called_once()


class TestAppCycleMode:
    """t key cycles command mode."""

    async def test_cycle_cmd_mode(self, minimal_app):
        app = minimal_app
        async with app.run_test() as pilot:
            initial = app.cmd_mode
            await pilot.press("t")
            await pilot.pause()
            # Only one mode available (default), so mode stays the same
            # but the action still runs
            assert app.cmd_mode == initial


class TestAppCycleGroup:
    """l key cycles group filter."""

    async def test_cycle_to_backend(self, minimal_app):
        app = minimal_app
        async with app.run_test() as pilot:
            assert app._group_filter is None
            await pilot.press("l")
            await pilot.pause()
            assert app._group_filter == "backend"

    async def test_cycle_to_frontend(self, minimal_app):
        app = minimal_app
        async with app.run_test() as pilot:
            await pilot.press("l")
            await pilot.press("l")
            await pilot.pause()
            assert app._group_filter == "frontend"

    async def test_cycle_back_to_all(self, minimal_app):
        app = minimal_app
        async with app.run_test() as pilot:
            await pilot.press("l")
            await pilot.press("l")
            await pilot.press("l")
            await pilot.pause()
            assert app._group_filter is None


class TestAppRefreshEnv:
    """r key refreshes environment status."""

    async def test_refresh_env(self, minimal_app):
        app = minimal_app
        async with app.run_test() as pilot:
            await pilot.press("r")
            await pilot.pause()
            # Action runs without error; check env indicator exists
            assert app.query_one("#env-indicator") is not None


class TestAppMount:
    """on_mount initialisation."""

    async def test_on_mount_auto_selects_first_service(self, minimal_app):
        app = minimal_app
        async with app.run_test() as pilot:
            tree = app.query_one("#service-tree", ServiceTree)
            assert tree.current_service is not None

    async def test_footer_text(self, minimal_app):
        app = minimal_app
        async with app.run_test() as pilot:
            footer = app.query_one("#footer-keys")
            text = footer.render()
            assert "quit" in str(text)
            assert "stop-all" in str(text)

    async def test_mode_label(self, minimal_app):
        app = minimal_app
        async with app.run_test() as pilot:
            mode = app.query_one("#footer-mode")
            text = mode.render()
            assert "DEFAULT" in str(text)
            assert "ALL" in str(text)


class TestAppWidgetCache:
    """Widget references are cached after mount."""

    async def test_log_panel_cached_after_mount(self, minimal_app):
        app = minimal_app
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._log_panel is not None
            assert app._service_tree is not None
            assert app._detail_panel is not None


class TestAppLogBatching:
    """High-frequency log lines are batched into a single UI update."""

    async def test_log_lines_are_batched_within_timer_window(self, minimal_app):
        app = minimal_app
        async with app.run_test() as pilot:
            tree = app.query_one("#service-tree", ServiceTree)
            tree.highlight_service("api")
            await pilot.pause()
            app._update_detail()
            await pilot.pause()

            log_panel = app._log_panel
            log_panel.append_logs = lambda svc_name, lines: setattr(
                log_panel, "_batched_calls", getattr(log_panel, "_batched_calls", 0) + 1
            )

            for i in range(10):
                app._safe_append_log("api", f"line {i}")

            await asyncio.sleep(0.06)
            assert getattr(log_panel, "_batched_calls", 0) == 1

    async def test_safe_append_log_ignores_hidden_service(self, minimal_app):
        app = minimal_app
        async with app.run_test() as pilot:
            tree = app.query_one("#service-tree", ServiceTree)
            tree.highlight_service("api")
            await pilot.pause()
            app._update_detail()
            await pilot.pause()

            app._safe_append_log("web", "should be ignored")
            assert app._pending_log_lines == {}


class TestAppSettings:
    """Settings change handling."""

    async def test_settings_unchanged_does_not_save(self, minimal_app):
        app = minimal_app
        async with app.run_test() as pilot:
            settings_panel = app.query_one("#right-settings", SettingsPanel)
            with patch("muster.core.settings_store.save_settings") as mock_save:
                settings_panel.post_message(
                    SettingsPanel.SettingsChanged(app._settings)
                )
                await pilot.pause()
                mock_save.assert_not_called()

    async def test_settings_changed_applies_and_saves(self, minimal_app):
        app = minimal_app
        async with app.run_test() as pilot:
            settings_panel = app.query_one("#right-settings", SettingsPanel)
            new_settings = AppSettings(env_refresh_interval=10)
            with patch("muster.core.settings_store.save_settings") as mock_save:
                settings_panel.post_message(
                    SettingsPanel.SettingsChanged(new_settings)
                )
                await pilot.pause()
                assert app._settings.env_refresh_interval == 10
                mock_save.assert_called_once()


class TestAppMisc:
    """Miscellaneous helper methods and edge cases."""

    def test_scan_yaml_files(self, minimal_config, tmp_path):
        yaml_file = tmp_path / "muster-compose.yaml"
        yaml_file.write_text("services: []\n", encoding="utf-8")
        from muster.app import MusterApp

        registry = {}
        app = MusterApp(
            config=minimal_config,
            services=[],
            registry=registry,
            config_path=yaml_file,
        )
        assert "muster-compose.yaml" in app._scan_yaml_files()

    def test_common_cmd_modes_empty_services(self, minimal_config):
        from muster.app import MusterApp

        app = MusterApp(
            config=minimal_config,
            services=[],
            registry={},
        )
        assert app._common_cmd_modes == ["default"]

    async def test_refresh_resources_no_proc(self, minimal_app):
        app = minimal_app
        async with app.run_test() as pilot:
            tree = app.query_one("#service-tree", ServiceTree)
            tree.highlight_service("api")
            await pilot.pause()
            await app._refresh_resources()
