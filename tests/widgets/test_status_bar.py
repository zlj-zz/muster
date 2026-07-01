"""Tests for StatusBar widget."""

from __future__ import annotations

from muster.widgets.status_bar import StatusBar
from tests.conftest import WidgetTestApp


class TestStatusBar:
    """Mode indicator badge."""

    async def test_default_mode_on_mount(self):
        app = WidgetTestApp(StatusBar())
        async with app.run_test() as pilot:
            bar = app.query_one(StatusBar)
            await pilot.pause()
            assert "DEFAULT | ALL" in str(bar.content)

    async def test_set_mode_updates_text(self):
        app = WidgetTestApp(StatusBar())
        async with app.run_test() as pilot:
            bar = app.query_one(StatusBar)
            bar.set_mode("TEST | BACKEND")
            await pilot.pause()
            assert "TEST | BACKEND" in str(bar.content)
