"""Tests for ActivityBar / ActivityTab widgets."""

from __future__ import annotations

from muster.widgets.activity_bar import ActivityBar, ActivityTab
from tests.conftest import WidgetTestApp, capture_messages


class TestActivityBar:
    """ActivityBar tab switching and visual state."""

    async def test_initial_active_tab_is_svc(self):
        app = WidgetTestApp(ActivityBar())
        async with app.run_test() as pilot:
            bar = app.query_one(ActivityBar)
            assert bar.active_tab == "svc"
            svc_tab = bar.query_one("#tab-svc", ActivityTab)
            assert "active" in svc_tab.classes

    async def test_click_env_tab_posts_message(self):
        app = WidgetTestApp(ActivityBar())
        async with app.run_test() as pilot:
            bar = app.query_one(ActivityBar)
            tab = bar.query_one("#tab-env", ActivityTab)
            messages = capture_messages(tab, ActivityTab.TabClicked)
            tab.on_click()
            await pilot.pause()
            assert len(messages) == 1
            assert messages[0].tab_id == "env"

    async def test_click_yaml_tab_posts_message(self):
        app = WidgetTestApp(ActivityBar())
        async with app.run_test() as pilot:
            bar = app.query_one(ActivityBar)
            tab = bar.query_one("#tab-yaml", ActivityTab)
            messages = capture_messages(tab, ActivityTab.TabClicked)
            tab.on_click()
            await pilot.pause()
            assert len(messages) == 1
            assert messages[0].tab_id == "yaml"

    async def test_programmatic_set_active_tab(self):
        app = WidgetTestApp(ActivityBar())
        async with app.run_test() as pilot:
            bar = app.query_one(ActivityBar)
            bar.active_tab = "env"
            await pilot.pause()
            assert "active" in bar.query_one("#tab-env", ActivityTab).classes
            assert "active" not in bar.query_one("#tab-svc", ActivityTab).classes
