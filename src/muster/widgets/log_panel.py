"""Read-only log panel with search, level filtering, and colour highlighting.

Uses :class:`InteractiveRichLog` underneath so only visible rows are rendered,
making it suitable for high-frequency log output.
"""

from __future__ import annotations

import re
from collections import deque
from datetime import datetime

from textual import events, on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, Static

from ..core.orchestrator import load_today_logs
from ..models import Service
from .interactive_rich_log import InteractiveRichLog

#: Regex patterns for parsing Go-style log levels.
LEVEL_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(?:\[)?(?:FATAL|PANIC)(?:\]|\s)", re.I), "ERROR"),
    (re.compile(r"(?:\[)?(?:ERROR|ERRO)(?:\]|\s)", re.I), "ERROR"),
    (re.compile(r"(?:\[)?(?:WARN|WARNING)(?:\]|\s)", re.I), "WARN"),
    (re.compile(r"(?:\[)?(?:INFO)(?:\]|\s)", re.I), "INFO"),
    (re.compile(r"(?:\[)?(?:DEBUG|DEBU)(?:\]|\s)", re.I), "DEBUG"),
]

#: Prefixes that identify muster system log lines.
SYS_PREFIXES = ("muster▸", "!!!")

#: Bidirectional mapping between widget IDs and level strings.
_LEVEL_MAP: dict[str, str] = {
    "level-all": "ALL",
    "level-err": "ERROR",
    "level-warn": "WARN",
    "level-info": "INFO",
    "level-debug": "DEBUG",
}


class LogPanel(Vertical):
    """Service log viewer with a rolling buffer, search, and level filter."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._svc_name: str | None = None
        self._log_level: str = "ALL"
        self._level_buttons: dict[str, Static] = {}
        self.auto_scroll: bool = True
        self.show_timestamp: bool = False
        self.wrap: bool = True
        self.buffer_lines: int = 2000
        self.load_history: bool = False
        self._search_dirty: bool = True

    def compose(self) -> ComposeResult:
        with Horizontal(id="log-level-row"):
            yield Static("ALL", classes="log-level-btn active", id="level-all")
            yield Static("ERR", classes="log-level-btn", id="level-err")
            yield Static("WARN", classes="log-level-btn", id="level-warn")
            yield Static("INFO", classes="log-level-btn", id="level-info")
            yield Static("DEBUG", classes="log-level-btn", id="level-debug")
        with Horizontal(id="log-search-row"):
            yield Static("❯ ", id="log-search-prefix")
            yield Input(
                placeholder="Search logs...",
                id="log-search",
            )
            yield Static("", id="log-search-count")
        yield InteractiveRichLog(
            id="log-scroll", max_lines=self.buffer_lines, wrap=self.wrap
        )

    def on_mount(self) -> None:
        self.border_title = "Logs"
        self._log_widget.set_level_parser(self._parse_level)
        for widget_id, level in _LEVEL_MAP.items():
            self._level_buttons[level] = self.query_one(f"#{widget_id}", Static)

    @property
    def _log_widget(self) -> InteractiveRichLog:
        return self.query_one("#log-scroll", InteractiveRichLog)

    @property
    def _search_input(self) -> Input:
        return self.query_one("#log-search", Input)

    @property
    def _search_count(self) -> Static:
        return self.query_one("#log-search-count", Static)

    def set_wrap(self, wrap: bool) -> None:
        """Toggle word wrapping in the log widget."""
        self.wrap = wrap
        self._log_widget.set_wrap(wrap)

    def resize_buffer(self, maxlen: int) -> None:
        """Delegate buffer resize to the underlying log widget."""
        self._log_widget.resize_buffer(maxlen)

    def _update_search_count(self) -> None:
        """Refresh the match counter badge in the search row."""
        count = self._log_widget.match_count()
        if not count:
            self._search_count.update("")
            return
        current = self._log_widget.current_match_index() + 1
        self._search_count.update(f"{current}/{count}")

    def _parse_level(self, line: str) -> str:
        for pattern, level in LEVEL_PATTERNS:
            if pattern.search(line):
                return level
        if any(line.startswith(p) for p in SYS_PREFIXES):
            return "SYS"
        return "INFO"

    def _set_level(self, level: str) -> None:
        """Switch log level filter and refresh display."""
        if self._log_level == level:
            return
        self._log_level = level
        self._update_level_buttons()
        self._log_widget.set_level_filter(level)
        self._update_search_count()
        self._refresh_title()

    def _update_level_buttons(self) -> None:
        for level, btn in self._level_buttons.items():
            if level == self._log_level:
                btn.add_class("active")
            else:
                btn.remove_class("active")

    @on(events.Click)
    def on_level_click(self, event: events.Click) -> None:
        widget = event.control
        if widget is None or widget.id not in _LEVEL_MAP:
            return
        self._set_level(_LEVEL_MAP[widget.id])
        event.stop()

    def clear(self) -> None:
        """Clear logs, search state, and match highlights."""
        self._log_widget.clear()
        self._search_input.value = ""
        self._update_search_count()

    def set_service(self, svc: Service | None) -> None:
        """Switch the panel to display a different service's logs.

        Args:
            svc: Service to display, or ``None`` to clear the panel.
        """
        self.clear()
        if svc is None:
            self._svc_name = None
            self.border_title = "Logs"
            return

        self._svc_name = svc.name
        self.border_title = f"Logs: {svc.name}"

        if not svc.log_lines and self.load_history:
            svc.log_lines = load_today_logs(svc.name, maxlen=self.buffer_lines)

        if svc.log_lines:
            self._log_widget.write_lines(list(svc.log_lines))

    def append_log(self, svc_name: str, line: str) -> None:
        """Append a single log line if it belongs to the currently shown service.

        Args:
            svc_name: Name of the service that produced the line.
            line: Raw log line text.
        """
        if self._svc_name != svc_name:
            return
        if self.show_timestamp:
            line = f"{datetime.now().strftime('%H:%M:%S')} {line}"
        self._log_widget.write_line(line)

    @on(Input.Changed, "#log-search")
    def on_search_changed(self, event: Input.Changed) -> None:
        self._search_dirty = True

    def on_key(self, event: events.Key) -> None:
        """Handle *Enter* / *Shift+Enter* in the search box.

        *Enter* jumps to the next match (or runs a new search if the query
        changed).  *Shift+Enter* jumps to the previous match.
        """
        if self.screen.focused is not self._search_input:
            return
        if event.key not in ("enter", "shift+enter"):
            return

        query = self._search_input.value.strip()
        if self._search_dirty or not self._log_widget.match_count():
            self._do_search(query)
            self._search_dirty = False
        elif event.key == "shift+enter":
            self._log_widget.prev_match()
            self._update_search_count()
            self._refresh_title()
        else:
            self._log_widget.next_match()
            self._update_search_count()
            self._refresh_title()

        event.stop()
        event.prevent_default()

    def _do_search(self, query: str) -> None:
        """Find all lines matching *query* and jump to the first match."""
        self._log_widget.set_search_query(query)
        self._update_search_count()
        count = self._log_widget.match_count()
        if not query:
            self.border_title = self._log_prefix
        elif count:
            current = self._log_widget.current_match_index() + 1
            self.border_title = f"{self._log_prefix} ({current}/{count})"
        else:
            self.border_title = f"{self._log_prefix} (no matches)"

    def _refresh_title(self) -> None:
        """Sync border title after match navigation (query already known)."""
        prefix = self._log_prefix
        count = self._log_widget.match_count()
        if not count:
            self.border_title = prefix
            return
        current = self._log_widget.current_match_index() + 1
        self.border_title = f"{prefix} ({current}/{count})"

    @property
    def _log_prefix(self) -> str:
        """Return the base log panel title prefix."""
        return f"Logs: {self._svc_name}" if self._svc_name else "Logs"
