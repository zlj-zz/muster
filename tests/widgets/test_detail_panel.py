"""Tests for DetailPanel widget."""

from __future__ import annotations

import pytest
from textual.widgets import Button, Static

from muster.models import Group, Service, Status
from muster.widgets.detail_panel import DetailPanel
from tests.conftest import WidgetTestApp, capture_messages


@pytest.fixture
def detail_panel():
    groups = [Group(id="backend", label="BACKEND", color="#569cd6", order=0)]
    status_colors = {"stopped": "#5c6370", "running": "#98c379"}
    return DetailPanel(groups, status_colors)


class TestDetailPanelRender:
    """Metadata rendering when current_service changes."""

    async def test_set_service_renders_detail(self, detail_panel):
        app = WidgetTestApp(detail_panel)
        async with app.run_test() as pilot:
            panel = app.query_one(DetailPanel)
            svc = Service(name="api", cmd="go run api.go", group="backend", port=8080)
            panel.current_service = svc
            await pilot.pause()

            buttons = panel.query_one("#action-buttons")
            assert buttons.styles.display != "none"

    async def test_no_service_hides_buttons(self, detail_panel):
        app = WidgetTestApp(detail_panel)
        async with app.run_test() as pilot:
            panel = app.query_one(DetailPanel)
            panel.current_service = Service(name="tmp", cmd="echo", group="backend")
            await pilot.pause()
            panel.current_service = None
            await pilot.pause()
            buttons = panel.query_one("#action-buttons")
            assert buttons.styles.display == "none"


class TestDetailPanelButtons:
    """Button disabled states."""

    async def test_buttons_disabled_when_no_service(self, detail_panel):
        app = WidgetTestApp(detail_panel)
        async with app.run_test() as pilot:
            panel = app.query_one(DetailPanel)
            panel.current_service = Service(name="tmp", cmd="echo", group="backend")
            await pilot.pause()
            panel.current_service = None
            await pilot.pause()
            start = panel.query_one("#btn-start", Button)
            stop = panel.query_one("#btn-stop", Button)
            restart = panel.query_one("#btn-restart", Button)
            assert start.disabled
            assert stop.disabled
            assert restart.disabled

    async def test_buttons_state_running(self, detail_panel):
        app = WidgetTestApp(detail_panel)
        async with app.run_test() as pilot:
            panel = app.query_one(DetailPanel)
            svc = Service(name="api", cmd="go run api.go", group="backend")
            svc.status = Status.RUNNING
            panel.current_service = svc
            await pilot.pause()

            start = panel.query_one("#btn-start", Button)
            stop = panel.query_one("#btn-stop", Button)
            restart = panel.query_one("#btn-restart", Button)
            assert start.disabled
            assert not stop.disabled
            assert not restart.disabled

    async def test_buttons_state_stopped(self, detail_panel):
        app = WidgetTestApp(detail_panel)
        async with app.run_test() as pilot:
            panel = app.query_one(DetailPanel)
            svc = Service(name="api", cmd="go run api.go", group="backend")
            svc.status = Status.STOPPED
            panel.current_service = svc
            await pilot.pause()

            start = panel.query_one("#btn-start", Button)
            stop = panel.query_one("#btn-stop", Button)
            restart = panel.query_one("#btn-restart", Button)
            assert not start.disabled
            assert stop.disabled
            assert restart.disabled


class TestDetailPanelMessages:
    """Action button messages."""

    async def test_start_button_posts_action(self, detail_panel):
        app = WidgetTestApp(detail_panel)
        async with app.run_test() as pilot:
            panel = app.query_one(DetailPanel)
            messages = capture_messages(panel, DetailPanel.ActionTriggered)
            svc = Service(name="api", cmd="go run api.go", group="backend")
            panel.current_service = svc
            await pilot.pause()
            await pilot.click("#btn-start")
            await pilot.pause()
            assert len(messages) == 1
            assert messages[0].action == "start"
            assert messages[0].service.name == "api"

    async def test_stop_button_posts_action(self, detail_panel):
        app = WidgetTestApp(detail_panel)
        async with app.run_test() as pilot:
            panel = app.query_one(DetailPanel)
            messages = capture_messages(panel, DetailPanel.ActionTriggered)
            svc = Service(name="api", cmd="go run api.go", group="backend")
            svc.status = Status.RUNNING
            panel.current_service = svc
            await pilot.pause()
            await pilot.click("#btn-stop")
            await pilot.pause()
            assert len(messages) == 1
            assert messages[0].action == "stop"

    async def test_restart_button_posts_action(self, detail_panel):
        app = WidgetTestApp(detail_panel)
        async with app.run_test() as pilot:
            panel = app.query_one(DetailPanel)
            messages = capture_messages(panel, DetailPanel.ActionTriggered)
            svc = Service(name="api", cmd="go run api.go", group="backend")
            svc.status = Status.RUNNING
            panel.current_service = svc
            await pilot.pause()
            await pilot.click("#btn-restart")
            await pilot.pause()
            assert len(messages) == 1
            assert messages[0].action == "restart"


class TestDetailPanelResources:
    """Resource card display."""

    async def test_resources_show_zero_bar_when_stopped(self, detail_panel):
        app = WidgetTestApp(detail_panel)
        async with app.run_test() as pilot:
            panel = app.query_one(DetailPanel)
            panel.update_resources(None, None)
            await pilot.pause()

            cpu = panel.query_one("#res-cpu", Static)
            mem = panel.query_one("#res-mem", Static)
            assert "0.0%" in cpu.content.plain
            assert "0.0%" in mem.content.plain
            assert "#5c6370" in str(cpu.content.spans)

    async def test_resources_render_values(self, detail_panel):
        app = WidgetTestApp(detail_panel)
        async with app.run_test() as pilot:
            panel = app.query_one(DetailPanel)
            panel.update_resources(45.0, 30.0)
            await pilot.pause()

            cpu = panel.query_one("#res-cpu", Static)
            mem = panel.query_one("#res-mem", Static)
            assert "45.0%" in cpu.content.plain
            assert "30.0%" in mem.content.plain

    @pytest.mark.parametrize(
        "value,expected_color",
        [
            (45.0, "#98c379"),
            (85.0, "#e5c07b"),
            (95.0, "#e06c75"),
        ],
    )
    async def test_resource_color(self, detail_panel, value, expected_color):
        app = WidgetTestApp(detail_panel)
        async with app.run_test() as pilot:
            panel = app.query_one(DetailPanel)
            panel.update_resources(value, value)
            await pilot.pause()

            cpu = panel.query_one("#res-cpu", Static)
            assert expected_color in str(cpu.content.spans)
