"""Tests for LogPanel widget."""

from __future__ import annotations

from collections import deque

from muster.models import Service
from muster.widgets.log_panel import LogPanel
from tests.conftest import WidgetTestApp


class TestLogPanelSetService:
    """Loading a service's logs."""

    async def test_set_service_loads_logs(self):
        app = WidgetTestApp(LogPanel())
        async with app.run_test() as pilot:
            panel = app.query_one(LogPanel)
            svc = Service(name="api", cmd="go run api.go", group="backend")
            svc.log_lines = deque(["line 1", "line 2", "ERROR broken"])
            panel.set_service(svc)
            assert panel._svc_name == "api"
            assert panel.border_title == "Logs: api"
            assert len(panel._buffer) == 3
            text = panel._text_area.text
            assert "line 1" in text
            assert "ERROR broken" in text

    async def test_set_none_clears_panel(self):
        app = WidgetTestApp(LogPanel())
        async with app.run_test() as pilot:
            panel = app.query_one(LogPanel)
            svc = Service(name="api", cmd="go run api.go", group="backend")
            svc.log_lines = deque(["hello"])
            panel.set_service(svc)
            panel.set_service(None)
            assert panel._svc_name is None
            assert panel.border_title == "Logs"
            assert panel._text_area.text == ""


class TestLogPanelAppend:
    """Appending log lines."""

    async def test_append_visible_service(self):
        app = WidgetTestApp(LogPanel())
        async with app.run_test() as pilot:
            panel = app.query_one(LogPanel)
            svc = Service(name="api", cmd="go run api.go", group="backend")
            panel.set_service(svc)
            panel.append_log("api", "new line")
            assert "new line" in panel._text_area.text
            assert len(panel._buffer) == 1

    async def test_append_hidden_service_ignored(self):
        app = WidgetTestApp(LogPanel())
        async with app.run_test() as pilot:
            panel = app.query_one(LogPanel)
            svc = Service(name="api", cmd="go run api.go", group="backend")
            panel.set_service(svc)
            panel.append_log("other", "should not appear")
            assert "should not appear" not in panel._text_area.text
            assert len(panel._buffer) == 0


class TestLogPanelLevelFilter:
    """Filtering by log level."""

    async def test_level_filter_error(self):
        app = WidgetTestApp(LogPanel())
        async with app.run_test() as pilot:
            panel = app.query_one(LogPanel)
            svc = Service(name="api", cmd="go run api.go", group="backend")
            svc.log_lines = deque(["INFO hello", "ERROR broken", "INFO world"])
            panel.set_service(svc)

            panel._set_level("ERROR")
            text = panel._text_area.text
            assert "ERROR broken" in text
            assert "INFO hello" not in text
            assert "INFO world" not in text

    async def test_level_filter_warn(self):
        app = WidgetTestApp(LogPanel())
        async with app.run_test() as pilot:
            panel = app.query_one(LogPanel)
            svc = Service(name="api", cmd="go run api.go", group="backend")
            svc.log_lines = deque(["INFO hello", "WARN caution", "ERROR broken"])
            panel.set_service(svc)

            panel._set_level("WARN")
            text = panel._text_area.text
            assert "WARN caution" in text
            assert "INFO hello" not in text
            assert "ERROR broken" not in text

    async def test_level_filter_all_shows_everything(self):
        app = WidgetTestApp(LogPanel())
        async with app.run_test() as pilot:
            panel = app.query_one(LogPanel)
            svc = Service(name="api", cmd="go run api.go", group="backend")
            svc.log_lines = deque(["INFO hello", "ERROR broken"])
            panel.set_service(svc)

            panel._set_level("ALL")
            text = panel._text_area.text
            assert "INFO hello" in text
            assert "ERROR broken" in text

    async def test_level_filter_debug(self):
        app = WidgetTestApp(LogPanel())
        async with app.run_test() as pilot:
            panel = app.query_one(LogPanel)
            svc = Service(name="api", cmd="go run api.go", group="backend")
            svc.log_lines = deque(["INFO hello", "DEBUG details", "ERROR broken"])
            panel.set_service(svc)

            panel._set_level("DEBUG")
            text = panel._text_area.text
            assert "DEBUG details" in text
            assert "INFO hello" not in text
            assert "ERROR broken" not in text


class TestLogPanelSearch:
    """Search functionality."""

    async def test_search_finds_matches(self):
        app = WidgetTestApp(LogPanel())
        async with app.run_test() as pilot:
            panel = app.query_one(LogPanel)
            svc = Service(name="api", cmd="go run api.go", group="backend")
            svc.log_lines = deque(["foo bar", "baz qux", "foo qux"])
            panel.set_service(svc)

            panel._search_input.value = "foo"
            panel._do_search("foo")
            assert len(panel._matches) == 2
            assert panel._match_idx == 0
            assert "1/2" in panel.border_title

    async def test_search_no_matches(self):
        app = WidgetTestApp(LogPanel())
        async with app.run_test() as pilot:
            panel = app.query_one(LogPanel)
            svc = Service(name="api", cmd="go run api.go", group="backend")
            svc.log_lines = deque(["hello world"])
            panel.set_service(svc)

            panel._do_search("xyz")
            assert len(panel._matches) == 0
            assert "no matches" in panel.border_title

    async def test_next_match_wraps(self):
        app = WidgetTestApp(LogPanel())
        async with app.run_test() as pilot:
            panel = app.query_one(LogPanel)
            svc = Service(name="api", cmd="go run api.go", group="backend")
            svc.log_lines = deque(["foo", "bar", "foo"])
            panel.set_service(svc)

            panel._search_input.value = "foo"
            panel._do_search("foo")
            assert panel._match_idx == 0
            panel._next_match()
            assert panel._match_idx == 1
            panel._next_match()
            assert panel._match_idx == 0

    async def test_previous_match_wraps(self):
        app = WidgetTestApp(LogPanel())
        async with app.run_test() as pilot:
            panel = app.query_one(LogPanel)
            svc = Service(name="api", cmd="go run api.go", group="backend")
            svc.log_lines = deque(["foo", "bar", "foo"])
            panel.set_service(svc)

            panel._search_input.value = "foo"
            panel._do_search("foo")
            panel._previous_match()
            assert panel._match_idx == 1


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
            assert "historical line 1" in panel._text_area.text
            assert "historical line 2" in panel._text_area.text
            assert len(panel._buffer) == 2

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
            assert panel._text_area.text == ""
            assert len(panel._buffer) == 0

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
            assert "live line" in panel._text_area.text
            assert "disk line" not in panel._text_area.text
