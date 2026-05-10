"""Read-only log panel with search, level filtering, and color highlighting.

Layout: level filter row on top, ``Input`` (search) below, then a
``LogList`` containing one ``LogLine`` widget per log line.
Each ``LogLine`` renders its content as Rich Text so log levels are
colour-coded and long lines soft-wrap automatically.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections import deque
from collections.abc import Callable
from datetime import datetime

from rich.text import Text as RichText
from textual import events, on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Input, Static

from ..core.orchestrator import load_today_logs
from ..models import Service


def _copy_to_clipboard(text: str) -> None:
    """Copy *text* to the system clipboard (best-effort, silent on failure)."""
    try:
        if sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=text.encode(), check=False)
        elif sys.platform == "win32":
            subprocess.run(["clip"], input=text.encode("utf-16le"), check=False)
        else:
            for cmd in (
                ["xclip", "-selection", "clipboard"],
                ["xsel", "--clipboard", "--input"],
            ):
                result = subprocess.run(cmd, input=text.encode(), check=False)
                if result.returncode == 0:
                    break
    except FileNotFoundError:
        pass


#: Colour mapping for log levels (Rich style strings).
_LEVEL_COLORS: dict[str, str] = {
    "ERROR": "bold #e06c75",
    "WARN": "#e5c07b",
    "INFO": "#98c379",
    "DEBUG": "#5c6370",
    "SYS": "#61afef",
}


class LogLine(Static):
    """A single log line rendered with optional colour highlighting.

    Attributes:
        line_no: 1-based line number shown in the left gutter.
        raw_text: The raw log text (without timestamp prefix).
        level: Parsed level string (INFO, ERROR, etc.).
    """

    def __init__(self, line_no: int, text: str, level: str, **kwargs) -> None:
        self.line_no = line_no
        self.raw_text = text
        self.level = level
        self.match_query: str | None = None
        super().__init__(**kwargs)

    def render(self) -> RichText:
        """Return a Rich Text with dim line number + coloured content."""
        lineno = RichText(f"{self.line_no:4d} │ ", style="dim")
        content = RichText(self.raw_text)
        color = _LEVEL_COLORS.get(self.level)
        if color:
            content.stylize(color)
        if self.match_query:
            idx = self.raw_text.find(self.match_query)
            if idx >= 0:
                content.stylize("bold #eab459", idx, idx + len(self.match_query))
        return RichText.assemble(lineno, content)

    @on(events.Click)
    def _on_click(self, event: events.Click) -> None:
        """Copy the raw log line to the system clipboard."""
        _copy_to_clipboard(self.raw_text)
        self.notify("Copied to clipboard", timeout=1.5)
        event.stop()


class LogList(VerticalScroll):
    """Scrollable list of coloured log lines."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._level_parser: Callable[[str], str] = lambda _line: "INFO"
        self._highlighted_idx: int = -1

    def set_level_parser(self, parser: Callable[[str], str]) -> None:
        """Set the callback used to determine a line's log level."""
        self._level_parser = parser

    def set_lines(self, lines: list[str]) -> None:
        """Replace the entire list with *lines*."""
        self._highlighted_idx = -1
        self.remove_children()
        widgets = [
            LogLine(i + 1, text, self._level_parser(text))
            for i, text in enumerate(lines)
        ]
        if widgets:
            self.mount(*widgets)

    def append(self, text: str, level: str | None = None) -> LogLine:
        """Append a single line at the end.  Line number = current count + 1."""
        level = level or self._level_parser(text)
        widget = LogLine(len(self.children) + 1, text, level)
        self.mount(widget)
        return widget

    def _unhighlight_current(self) -> None:
        """Remove highlight from the currently highlighted widget, if any."""
        if self._highlighted_idx < 0 or self._highlighted_idx >= len(self.children):
            return
        widget = self.children[self._highlighted_idx]
        widget.remove_class("active")
        if widget.match_query is not None:
            widget.match_query = None
            widget.refresh()

    def highlight_index(self, index: int, query: str | None = None) -> None:
        """Highlight line at *index*, optionally mark matched *query* text."""
        self._unhighlight_current()
        self._highlighted_idx = index
        if 0 <= index < len(self.children):
            widget = self.children[index]
            widget.add_class("active")
            if query and widget.match_query != query:
                widget.match_query = query
                widget.refresh()
            self.scroll_to_widget(widget)

    def clear_highlight(self) -> None:
        self._unhighlight_current()
        self._highlighted_idx = -1


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
        self.load_history: bool = False

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
        yield LogList(id="log-scroll")

    def on_mount(self) -> None:
        self.border_title = "Logs"
        self._log_list.set_level_parser(self._parse_level)
        for widget_id, level in _LEVEL_MAP.items():
            self._level_buttons[level] = self.query_one(f"#{widget_id}", Static)

    @property
    def _log_list(self) -> LogList:
        return self.query_one("#log-scroll", LogList)

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

    def _sync_display(self) -> None:
        """Push ``_displayed_lines`` into the log list and optionally scroll."""
        self._log_list.set_lines(self._displayed_lines)
        if self._displayed_lines and self.auto_scroll:
            self._log_list.scroll_end(animate=False)

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
        self._sync_display()

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
        self._log_list.remove_children()
        self._log_list.clear_highlight()
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

        if not svc.log_lines and self.load_history:
            svc.log_lines = load_today_logs(svc.name, maxlen=self.buffer_lines)

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
        else:
            level = self._parse_level(line)
            if self._log_level == "ALL" or level == self._log_level:
                self._displayed_lines.append(line)
                self._log_list.append(line, level)
                if self.auto_scroll:
                    self._log_list.scroll_end(animate=False)

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
        """Scroll to the current match line and highlight it."""
        if not self._matches or self._match_idx < 0:
            return
        query = self._search_input.value.strip()
        self._log_list.highlight_index(self._matches[self._match_idx], query)
        total = len(self._matches)
        current = self._match_idx + 1
        self.border_title = f"{self._log_prefix} ({current}/{total})"
        self._update_search_count()

    @property
    def _log_prefix(self) -> str:
        """Return the base log panel title prefix."""
        return f"Logs: {self._svc_name}" if self._svc_name else "Logs"
