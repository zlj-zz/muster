"""Tests for LogPanel widget."""

from __future__ import annotations

from collections import deque

from muster.models import Service
from muster.widgets.log_panel import LogPanel
from tests.conftest import WidgetTestApp


def _meta_text(panel: LogPanel) -> list[str]:
    """Return raw text of all lines stored in the log widget."""
    return [m.raw for m in panel._log_widget._meta]


def _visible_text(panel: LogPanel) -> list[str]:
    """Return raw text of currently visible lines."""
    meta = panel._log_widget._meta
    return [meta[i].raw for i in panel._log_widget._visible_meta_indices]


class TestLogPanelSetService:
    """Loading a service's logs."""

    async def test_set_service_loads_logs(self):
        app = WidgetTestApp(LogPanel())
        async with app.run_test() as pilot:
            panel = app.query_one(LogPanel)
            svc = Service(name="api", cmd="go run api.go", group="backend")
            svc.log_lines = deque(["line 1", "line 2", "ERROR broken"])
            panel.set_service(svc)
            await pilot.pause()

            assert panel._svc_name == "api"
            assert panel.border_title == "Logs: api"
            text = _meta_text(panel)
            assert "line 1" in text
            assert "ERROR broken" in text

    async def test_set_none_clears_panel(self):
        app = WidgetTestApp(LogPanel())
        async with app.run_test() as pilot:
            panel = app.query_one(LogPanel)
            svc = Service(name="api", cmd="go run api.go", group="backend")
            svc.log_lines = deque(["hello"])
            panel.set_service(svc)
            await pilot.pause()
            panel.set_service(None)
            await pilot.pause()

            assert panel._svc_name is None
            assert panel.border_title == "Logs"
            assert _meta_text(panel) == []


class TestLogPanelAppend:
    """Appending log lines."""

    async def test_append_visible_service(self):
        app = WidgetTestApp(LogPanel())
        async with app.run_test() as pilot:
            panel = app.query_one(LogPanel)
            svc = Service(name="api", cmd="go run api.go", group="backend")
            panel.set_service(svc)
            await pilot.pause()
            panel.append_log("api", "new line")
            await pilot.pause()

            assert "new line" in _meta_text(panel)

    async def test_append_hidden_service_ignored(self):
        app = WidgetTestApp(LogPanel())
        async with app.run_test() as pilot:
            panel = app.query_one(LogPanel)
            svc = Service(name="api", cmd="go run api.go", group="backend")
            panel.set_service(svc)
            await pilot.pause()
            panel.append_log("other", "should not appear")
            await pilot.pause()

            assert "should not appear" not in _meta_text(panel)


class TestLogPanelBatchAppend:
    """Bulk log line appending."""

    async def test_append_logs_batches_into_single_write(self):
        app = WidgetTestApp(LogPanel())
        async with app.run_test() as pilot:
            panel = app.query_one(LogPanel)
            svc = Service(name="svc", cmd="go run api.go", group="backend")
            panel.set_service(svc)
            await pilot.pause()

            panel.append_logs("svc", [f"line {i}" for i in range(10)])
            await pilot.pause()

            text = _meta_text(panel)
            for i in range(10):
                assert f"line {i}" in text


class TestLogPanelLevelFilter:
    """Filtering by log level."""

    async def test_level_filter_error(self):
        app = WidgetTestApp(LogPanel())
        async with app.run_test() as pilot:
            panel = app.query_one(LogPanel)
            svc = Service(name="api", cmd="go run api.go", group="backend")
            svc.log_lines = deque(["INFO hello", "ERROR broken", "INFO world"])
            panel.set_service(svc)
            await pilot.pause()

            panel._set_level("ERROR")
            await pilot.pause()

            visible = _visible_text(panel)
            assert "ERROR broken" in visible
            assert "INFO hello" not in visible
            assert "INFO world" not in visible

    async def test_level_filter_warn(self):
        app = WidgetTestApp(LogPanel())
        async with app.run_test() as pilot:
            panel = app.query_one(LogPanel)
            svc = Service(name="api", cmd="go run api.go", group="backend")
            svc.log_lines = deque(["INFO hello", "WARN caution", "ERROR broken"])
            panel.set_service(svc)
            await pilot.pause()

            panel._set_level("WARN")
            await pilot.pause()

            visible = _visible_text(panel)
            assert "WARN caution" in visible
            assert "INFO hello" not in visible
            assert "ERROR broken" not in visible

    async def test_level_filter_all_shows_everything(self):
        app = WidgetTestApp(LogPanel())
        async with app.run_test() as pilot:
            panel = app.query_one(LogPanel)
            svc = Service(name="api", cmd="go run api.go", group="backend")
            svc.log_lines = deque(["INFO hello", "ERROR broken"])
            panel.set_service(svc)
            await pilot.pause()

            panel._set_level("ALL")
            await pilot.pause()

            visible = _visible_text(panel)
            assert "INFO hello" in visible
            assert "ERROR broken" in visible

    async def test_level_filter_debug(self):
        app = WidgetTestApp(LogPanel())
        async with app.run_test() as pilot:
            panel = app.query_one(LogPanel)
            svc = Service(name="api", cmd="go run api.go", group="backend")
            svc.log_lines = deque(["INFO hello", "DEBUG details", "ERROR broken"])
            panel.set_service(svc)
            await pilot.pause()

            panel._set_level("DEBUG")
            await pilot.pause()

            visible = _visible_text(panel)
            assert "DEBUG details" in visible
            assert "INFO hello" not in visible
            assert "ERROR broken" not in visible


class TestLogPanelSearch:
    """Search functionality."""

    async def test_search_finds_matches(self):
        app = WidgetTestApp(LogPanel())
        async with app.run_test() as pilot:
            panel = app.query_one(LogPanel)
            svc = Service(name="api", cmd="go run api.go", group="backend")
            svc.log_lines = deque(["foo bar", "baz qux", "foo qux"])
            panel.set_service(svc)
            await pilot.pause()

            panel._search_input.value = "foo"
            panel._do_search("foo")
            await pilot.pause()

            assert panel._log_widget.match_count() == 2
            assert panel._log_widget.current_match_index() == 0
            assert "1/2" in panel.border_title

    async def test_search_no_matches(self):
        app = WidgetTestApp(LogPanel())
        async with app.run_test() as pilot:
            panel = app.query_one(LogPanel)
            svc = Service(name="api", cmd="go run api.go", group="backend")
            svc.log_lines = deque(["hello world"])
            panel.set_service(svc)
            await pilot.pause()

            panel._do_search("xyz")
            await pilot.pause()

            assert panel._log_widget.match_count() == 0
            assert "no matches" in panel.border_title

    async def test_next_match_wraps(self):
        app = WidgetTestApp(LogPanel())
        async with app.run_test() as pilot:
            panel = app.query_one(LogPanel)
            svc = Service(name="api", cmd="go run api.go", group="backend")
            svc.log_lines = deque(["foo", "bar", "foo"])
            panel.set_service(svc)
            await pilot.pause()

            panel._search_input.value = "foo"
            panel._do_search("foo")
            await pilot.pause()

            assert panel._log_widget.current_match_index() == 0
            panel._log_widget.next_match()
            assert panel._log_widget.current_match_index() == 1
            panel._log_widget.next_match()
            assert panel._log_widget.current_match_index() == 0

    async def test_previous_match_wraps(self):
        app = WidgetTestApp(LogPanel())
        async with app.run_test() as pilot:
            panel = app.query_one(LogPanel)
            svc = Service(name="api", cmd="go run api.go", group="backend")
            svc.log_lines = deque(["foo", "bar", "foo"])
            panel.set_service(svc)
            await pilot.pause()

            panel._search_input.value = "foo"
            panel._do_search("foo")
            await pilot.pause()

            panel._log_widget.prev_match()
            assert panel._log_widget.current_match_index() == 1


class TestLogPanelHistoricalLoad:
    """Lazy disk log loading on set_service."""

    async def test_loads_from_disk_when_empty_and_enabled(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "muster.core.orchestrator._logfile_path",
            lambda svc, now=None: tmp_path / f"{svc}.log",
        )
        logfile = tmp_path / "api.log"
        logfile.write_text("historical line 1\nhistorical line 2\n", encoding="utf-8")

        app = WidgetTestApp(LogPanel())
        async with app.run_test() as pilot:
            panel = app.query_one(LogPanel)
            panel.load_history = True
            svc = Service(name="api", cmd="go run api.go", group="backend")
            panel.set_service(svc)
            await pilot.pause()

            assert "historical line 1" in _meta_text(panel)
            assert "historical line 2" in _meta_text(panel)

    async def test_skips_disk_when_disabled(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "muster.core.orchestrator._logfile_path",
            lambda svc, now=None: tmp_path / f"{svc}.log",
        )
        logfile = tmp_path / "api.log"
        logfile.write_text("disk line\n", encoding="utf-8")

        app = WidgetTestApp(LogPanel())
        async with app.run_test() as pilot:
            panel = app.query_one(LogPanel)
            panel.load_history = False
            svc = Service(name="api", cmd="go run api.go", group="backend")
            panel.set_service(svc)
            await pilot.pause()

            assert _meta_text(panel) == []

    async def test_skips_disk_when_already_loaded(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "muster.core.orchestrator._logfile_path",
            lambda svc, now=None: tmp_path / f"{svc}.log",
        )
        logfile = tmp_path / "api.log"
        logfile.write_text("disk line\n", encoding="utf-8")

        app = WidgetTestApp(LogPanel())
        async with app.run_test() as pilot:
            panel = app.query_one(LogPanel)
            panel.load_history = True
            svc = Service(name="api", cmd="go run api.go", group="backend")
            svc.log_lines.append("live line")
            panel.set_service(svc)
            await pilot.pause()

            assert "live line" in _meta_text(panel)
            assert "disk line" not in _meta_text(panel)
