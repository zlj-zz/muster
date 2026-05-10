"""Tests for LogList widget."""

from __future__ import annotations

from tests.conftest import WidgetTestApp
from muster.widgets.log_panel import LogLine, LogList


class TestLogListSetLines:
    async def test_renders_lines(self):
        app = WidgetTestApp(LogList())
        async with app.run_test() as pilot:
            ll = app.query_one(LogList)
            ll.set_level_parser(lambda _: "INFO")
            ll.set_lines(["a", "b", "c"])
            await pilot.pause()
            assert len(ll.children) == 3
            assert isinstance(ll.children[0], LogLine)
            assert ll.children[0].line_no == 1
            assert ll.children[0].raw_text == "a"

    async def test_level_parser_applied(self):
        app = WidgetTestApp(LogList())
        async with app.run_test() as pilot:
            ll = app.query_one(LogList)
            ll.set_level_parser(lambda t: "ERROR" if "err" in t else "INFO")
            ll.set_lines(["ok", "err!"])
            await pilot.pause()
            assert ll.children[0].level == "INFO"
            assert ll.children[1].level == "ERROR"


class TestLogListAppend:
    async def test_appends_with_incrementing_line_no(self):
        app = WidgetTestApp(LogList())
        async with app.run_test() as pilot:
            ll = app.query_one(LogList)
            ll.set_level_parser(lambda _: "INFO")
            ll.set_lines(["a"])
            await pilot.pause()
            ll.append("b")
            await pilot.pause()
            assert len(ll.children) == 2
            assert ll.children[1].line_no == 2


class TestLogListClear:
    async def test_clear_removes_all(self):
        app = WidgetTestApp(LogList())
        async with app.run_test() as pilot:
            ll = app.query_one(LogList)
            ll.set_lines(["a", "b"])
            await pilot.pause()
            ll.remove_children()
            await pilot.pause()
            assert len(ll.children) == 0


class TestLogListHighlight:
    async def test_highlight_index_adds_active_class(self):
        app = WidgetTestApp(LogList())
        async with app.run_test() as pilot:
            ll = app.query_one(LogList)
            ll.set_lines(["a", "b", "c"])
            await pilot.pause()
            ll.highlight_index(1)
            assert "active" in ll.children[1].classes
            assert "active" not in ll.children[0].classes
            assert "active" not in ll.children[2].classes

    async def test_highlight_out_of_range_clears_only(self):
        app = WidgetTestApp(LogList())
        async with app.run_test() as pilot:
            ll = app.query_one(LogList)
            ll.set_lines(["a"])
            await pilot.pause()
            ll.highlight_index(0)
            ll.highlight_index(99)
            assert "active" not in ll.children[0].classes
