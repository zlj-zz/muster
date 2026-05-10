"""Read-only log panel with search and level filtering.

Layout: level filter row on top, ``Input`` (search) below, then
``TextArea`` (logs).  The search box filters lines in-place; pressing
*Enter* jumps to the first match and the panel title shows the match
counter.  Level filter buttons restrict visible lines by parsed severity.
"""

from __future__ import annotations

import re
from collections import deque
from datetime import datetime

from textual import events, on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, Static, TextArea

from ..models import Service

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
}


class LogPanel(Vertical):
    """Service log viewer with a 2000-line rolling buffer, search, and level filter."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._svc_name: str | None = None
        self._buffer: deque[str] = deque(maxlen=2000)
        self._displayed_lines: list[str] = []
        self._matches: list[int] = []
        self._match_idx: int = -1
        self._search_dirty: bool = True
        self._log_level: str = "ALL"
        self._level_buttons: dict[str, Static] = {}
        self.auto_scroll: bool = True
        self.show_timestamp: bool = False
        self.buffer_lines: int = 2000

    def compose(self) -> ComposeResult:
        with Horizontal(id="log-level-row"):
            yield Static("ALL", classes="log-level-btn active", id="level-all")
            yield Static("ERR", classes="log-level-btn", id="level-err")
            yield Static("WARN", classes="log-level-btn", id="level-warn")
            yield Static("INFO", classes="log-level-btn", id="level-info")
        with Horizontal(id="log-search-row"):
            yield Static("❯ ", id="log-search-prefix")
            yield Input(
                placeholder="Search logs...",
                id="log-search",
            )
            yield Static("", id="log-search-count")
        yield TextArea(read_only=True, show_line_numbers=True, id="log-text")

    def on_mount(self) -> None:
        self.border_title = "Logs"
        for widget_id, level in _LEVEL_MAP.items():
            self._level_buttons[level] = self.query_one(f"#{widget_id}", Static)

    @property
    def _text_area(self) -> TextArea:
        return self.query_one("#log-text", TextArea)

    @property
    def _search_input(self) -> Input:
        return self.query_one("#log-search", Input)

    @property
    def _search_count(self) -> Static:
        return self.query_one("#log-search-count", Static)

    def _update_search_count(self) -> None:
        """Refresh the match counter badge in the search row."""
        if not self._matches:
            self._search_count.update("")
            return
        self._search_count.update(f"{self._match_idx + 1}/{len(self._matches)}")

    def _sync_text_area(self) -> None:
        """Push ``_displayed_lines`` into the TextArea and optionally scroll."""
        self._text_area.text = "\n".join(self._displayed_lines)
        if self._displayed_lines and self.auto_scroll:
            self._text_area.move_cursor((len(self._displayed_lines) - 1, 0))
            self._text_area.scroll_end(animate=False)

    def _parse_level(self, line: str) -> str:
        for pattern, level in LEVEL_PATTERNS:
            if pattern.search(line):
                return level
        if any(line.startswith(p) for p in SYS_PREFIXES):
            return "SYS"
        return "INFO"

    def _is_visible(self, line: str) -> bool:
        level = self._parse_level(line)
        if self._log_level == "ALL":
            return True
        return level == self._log_level

    def _rebuild_display(self) -> None:
        """Rebuild displayed lines from buffer using current filter."""
        self._displayed_lines = [ln for ln in self._buffer if self._is_visible(ln)]
        self._sync_text_area()

    def _set_level(self, level: str) -> None:
        """Switch log level filter and refresh display."""
        if self._log_level == level:
            return
        self._log_level = level
        self._update_level_buttons()
        self._rebuild_display()
        self._matches = []
        self._match_idx = -1
        query = self._search_input.value.strip()
        if query:
            self._do_search(query)
        else:
            self.border_title = self._log_prefix
            self._update_search_count()

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
        self._text_area.clear()
        self._buffer.clear()
        self._displayed_lines = []
        self._matches = []
        self._match_idx = -1
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
        if svc.log_lines:
            self._buffer = deque(svc.log_lines, maxlen=self.buffer_lines)
            self._rebuild_display()

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
        was_full = len(self._buffer) == self._buffer.maxlen
        self._buffer.append(line)
        if was_full:
            self._rebuild_display()
        elif self._is_visible(line):
            self._displayed_lines.append(line)
            self._sync_text_area()

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
        if self._search_dirty or not self._matches:
            self._do_search(query)
            self._search_dirty = False
        elif event.key == "shift+enter":
            self._previous_match()
        else:
            self._next_match()

        event.stop()
        event.prevent_default()

    def _do_search(self, query: str) -> None:
        """Find all lines matching *query* and jump to the first match."""
        self._matches = []
        self._match_idx = -1
        if not query or not self._displayed_lines:
            self.border_title = self._log_prefix
            return

        self._matches = [i for i, ln in enumerate(self._displayed_lines) if query in ln]

        if self._matches:
            self._match_idx = 0
            self._goto_match()
        else:
            self.border_title = f"{self._log_prefix} (no matches)"
        self._update_search_count()

    def _next_match(self) -> None:
        """Jump to the next search match (wraps around)."""
        if not self._matches:
            return
        self._match_idx = (self._match_idx + 1) % len(self._matches)
        self._goto_match()

    def _previous_match(self) -> None:
        """Jump to the previous search match (wraps around)."""
        if not self._matches:
            return
        self._match_idx = (self._match_idx - 1) % len(self._matches)
        self._goto_match()

    def _goto_match(self) -> None:
        """Scroll the TextArea to the current match line and highlight the keyword."""
        if not self._matches or self._match_idx < 0:
            return
        line_idx = self._matches[self._match_idx]
        ta = self._text_area
        query = self._search_input.value.strip()

        if not query:
            ta.move_cursor((line_idx, 0))
            return

        line_text = self._displayed_lines[line_idx]
        col_idx = line_text.find(query)
        if col_idx >= 0:
            end_col = col_idx + len(query)
            ta.selection = ((line_idx, col_idx), (line_idx, end_col))
        else:
            ta.move_cursor((line_idx, 0))

        total = len(self._matches)
        current = self._match_idx + 1
        self.border_title = f"{self._log_prefix} ({current}/{total})"
        self._update_search_count()

    @property
    def _log_prefix(self) -> str:
        """Return the base log panel title prefix."""
        return f"Logs: {self._svc_name}" if self._svc_name else "Logs"
