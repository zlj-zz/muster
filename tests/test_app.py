"""Integration tests for MusterApp."""

from __future__ import annotations

from muster.widgets.detail_panel import DetailPanel
from muster.widgets.log_panel import LogPanel
from muster.widgets.service_tree import ServiceTree
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


class TestAppActions:
    """Global keyboard actions."""

    async def test_cycle_group_filter(self, minimal_app):
        app = minimal_app
        async with app.run_test() as pilot:
            assert app._group_filter is None
            await pilot.press("l")
            await pilot.pause()
            assert app._group_filter == "backend"

    async def test_stop_all_no_running(self, minimal_app):
        app = minimal_app
        async with app.run_test() as pilot:
            # All services are STOPPED by default
            await pilot.press("ctrl+s")
            await pilot.pause()
            # Should show a toast -- no orchestrator calls made
            assert app._stop_pending is False
