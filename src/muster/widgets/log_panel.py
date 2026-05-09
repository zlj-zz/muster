"""Read-only log panel with search.

Layout: ``Input`` (search) on top, ``TextArea`` (logs) below.
The search box filters lines in-place; pressing *Enter* jumps to the first
match and the panel title shows the match counter.
"""

from __future__ import annotations

from collections import deque

from textual import events, on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, Static, TextArea

from ..models import Service


class LogPanel(Vertical):
    """Service log viewer with a 2000-line rolling buffer and search."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._svc_name: str | None = None
        self._buffer: deque[str] = deque(maxlen=2000)
        self._matches: list[int] = []
        self._match_idx: int = -1
        self._search_dirty: bool = True

    def compose(self) -> ComposeResult:
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
        self._search_count.update(
            f"{self._match_idx + 1}/{len(self._matches)}"
        )

    def clear(self) -> None:
        self._text_area.clear()
        self._buffer.clear()
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
            self._buffer = deque(svc.log_lines, maxlen=2000)
            self._text_area.text = "\n".join(self._buffer)
            self._text_area.move_cursor((len(self._buffer) - 1, 0))
            self._text_area.scroll_end(animate=False)

    def append_log(self, svc_name: str, line: str) -> None:
        """Append a single log line if it belongs to the currently shown service.

        Args:
            svc_name: Name of the service that produced the line.
            line: Raw log line text.
        """
        if self._svc_name != svc_name:
            return
        self._buffer.append(line)
        self._text_area.text = "\n".join(self._buffer)
        self._text_area.move_cursor((len(self._buffer) - 1, 0))
        self._text_area.scroll_end(animate=False)

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
        if not query or not self._buffer:
            self.border_title = self._log_prefix
            return

        lines = list(self._buffer)
        self._matches = [i for i, ln in enumerate(lines) if query in ln]

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

        line_text = self._buffer[line_idx]
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
