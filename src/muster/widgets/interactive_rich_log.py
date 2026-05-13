"""High-performance log component based on RichLog with per-line interactions.

Inherits RichLog's virtual scrolling (only visible rows are rendered) while
preserving single-line capabilities: click-to-copy, level colouring, search
highlight, and level filtering.
"""

from __future__ import annotations

import bisect
import re
import subprocess
import sys
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from rich.segment import Segment
from rich.style import Style
from rich.text import Text as RichText
from textual.strip import Strip
from textual import events, on
from textual.events import Click
from textual.widgets import RichLog

#: Colour mapping for log levels (Rich style strings).
_LEVEL_COLORS: dict[str, str] = {
    "ERROR": "bold #e06c75",
    "WARN": "#e5c07b",
    "INFO": "#f0ead6",
    "DEBUG": "#f0ead6",
    "SYS": "#61afef",
}

_ACTIVE_BG = "#636772"
_ACTIVE_BG_STYLE = Style(bgcolor=_ACTIVE_BG)

#: JSON syntax highlighting styles (Catppuccin Mocha palette).
_JSON_STYLES: dict[str, str] = {
    "key": "bold #b4befe",
    "string": "#a6e3a1",
    "bool": "#f9e2af",
    "number": "#f5c2e7",
    "punct": "#6c7086",
}

#: Token pattern for JSON syntax highlighting (keys, strings, bools/null, numbers, punctuation).
_JSON_TOKEN_RE = re.compile(
    r'"(?:\\.|[^"\\])*"(?=\s*:)|"(?:\\.|[^"\\])*"|\b(?:true|false|null)\b|-?\d+\.?\d*(?:[eE][+-]?\d+)?|[{}\[\]:,]'
)


def _is_json_like(text: str) -> bool:
    """Fast O(1) heuristic: check if text looks like JSON (starts with `{` or `[`)."""
    i = 0
    n = len(text)
    while i < n and text[i] in " \t\n\r":
        i += 1
    return n - i > 1 and text[i] in "{[" and text[-1] in "}]"


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


@dataclass(frozen=True, slots=True)
class _LineMeta:
    """Metadata for a single log line."""

    raw: str
    level: str
    line_no: int
    is_json: bool = False


class InteractiveRichLog(RichLog):
    """Scrollable log with virtual rendering, level filter, search, and click-to-copy.

    Internally maintains a deque of ``_LineMeta`` (up to ``max_lines``).  Only
    lines matching the current level filter are rendered into ``self.lines``.
    ``render_line`` draws line numbers, level colours, search highlights, and
    the active-match background on demand.
    """

    def __init__(self, max_lines: int = 2000, **kwargs) -> None:
        super().__init__(max_lines=max_lines, **kwargs)
        self._meta: deque[_LineMeta] = deque(maxlen=max_lines)
        self._visible_meta_indices: list[int] = []
        self._level_filter: str = "ALL"
        self._search_query: str = ""
        self._line_parser: Callable[[str], str] = lambda _line: "INFO"
        self._matches: list[int] = []
        self._match_idx: int = -1
        self._current_match_screen_y: int = -1
        self._rebuild_scheduled: bool = False
        self._line_to_screen: list[int] = []

    # ---------- public API ----------

    def set_level_parser(self, parser: Callable[[str], str]) -> None:
        """Set the callback used to determine a line's log level."""
        self._line_parser = parser

    def set_wrap(self, wrap: bool) -> None:
        """Toggle word wrapping and rebuild the display.

        Args:
            wrap: ``True`` to wrap long lines, ``False`` to truncate.
        """
        if self.wrap == wrap:
            return
        self.wrap = wrap
        self._rebuild()

    def resize_buffer(self, maxlen: int) -> None:
        """Resize the internal meta deque and RichLog's line limit.

        Args:
            maxlen: New maximum number of lines to retain.
        """
        if self._meta.maxlen == maxlen:
            return
        self._meta = deque(self._meta, maxlen=maxlen)
        self.max_lines = maxlen
        self._rebuild()

    def _make_meta(self, text: str, level: str | None = None) -> _LineMeta:
        """Create a _LineMeta for *text*, inferring level if not provided."""
        level = level or self._line_parser(text)
        line_no = len(self._meta) + 1
        return _LineMeta(text, level, line_no, _is_json_like(text))

    def write_line(self, text: str, level: str | None = None) -> None:
        """Append a single log line."""
        self._meta.append(self._make_meta(text, level))

        if len(self._meta) == self._meta.maxlen:
            # deque just dropped the oldest line; schedule a full rebuild.
            self._schedule_rebuild()
            return

        meta = self._meta[-1]
        if self._level_filter == "ALL" or meta.level == self._level_filter:
            self._visible_meta_indices.append(len(self._meta) - 1)
            self._line_to_screen.append(len(self.lines))
            self.write(self._build_text(meta), scroll_end=False)
            if self.auto_scroll:
                self.scroll_end(animate=False)

    def write_lines(self, lines: list[str]) -> None:
        """Bulk append lines (used for historical log loading)."""
        for text in lines:
            self._meta.append(self._make_meta(text))
        self._rebuild()

    def clear(self) -> InteractiveRichLog:  # type: ignore[override]
        """Clear all logs."""
        self._rebuild_scheduled = False
        self._meta.clear()
        self._visible_meta_indices.clear()
        self._matches.clear()
        self._match_idx = -1
        self._current_match_screen_y = -1
        self._search_query = ""
        self._line_to_screen.clear()
        return super().clear()

    def set_level_filter(self, level: str) -> None:
        """Switch level filter and refresh display."""
        if self._level_filter == level:
            return
        self._level_filter = level
        self._rebuild()

    def set_search_query(self, query: str) -> None:
        """Update search query and refresh highlights."""
        if self._search_query == query:
            return
        self._search_query = query
        self._rebuild()

    def next_match(self) -> None:
        """Jump to the next search match (wraps around)."""
        if not self._matches:
            return
        self._match_idx = (self._match_idx + 1) % len(self._matches)
        self._goto_match()

    def prev_match(self) -> None:
        """Jump to the previous search match (wraps around)."""
        if not self._matches:
            return
        self._match_idx = (self._match_idx - 1) % len(self._matches)
        self._goto_match()

    def match_count(self) -> int:
        """Return the number of search matches."""
        return len(self._matches)

    def current_match_index(self) -> int:
        """Return 0-based current match index, or -1 if none."""
        return self._match_idx

    # ---------- internals ----------

    def _build_text(self, meta: _LineMeta) -> RichText:
        """Build a RichText with line number, level colour, and search highlight."""
        lineno = RichText(f"{meta.line_no:4d} │ ", style="dim")

        if meta.is_json:
            content = self._highlight_json(meta.raw)
        else:
            content = RichText(meta.raw)
            color = _LEVEL_COLORS.get(meta.level)
            if color:
                content.stylize(color)

        if self._search_query:
            idx = meta.raw.find(self._search_query)
            if idx >= 0:
                content.stylize("bold #eab459", idx, idx + len(self._search_query))
        return RichText.assemble(lineno, content)

    def _highlight_json(self, text: str) -> RichText:
        """Return a RichText with JSON syntax highlighting.

        Uses a single-pass regex tokenizer.  Keys, strings, booleans/null,
        numbers, and punctuation each get their own style.
        """
        result = RichText()
        last_end = 0
        for m in _JSON_TOKEN_RE.finditer(text):
            start, end = m.span()
            if start > last_end:
                result.append(text[last_end:start], "default")

            token = m.group()
            if token.startswith('"'):
                # key vs string: key is immediately followed by ':'
                style = (
                    _JSON_STYLES["key"]
                    if text[end : end + 1].strip() == ":"
                    else _JSON_STYLES["string"]
                )
            elif token in ("true", "false", "null"):
                style = _JSON_STYLES["bool"]
            elif token[0].isdigit() or token[0] == "-":
                style = _JSON_STYLES["number"]
            else:
                style = _JSON_STYLES["punct"]
            result.append(token, style)
            last_end = end

        if last_end < len(text):
            result.append(text[last_end:], "default")
        return result

    def _schedule_rebuild(self) -> None:
        if self._rebuild_scheduled:
            return
        self._rebuild_scheduled = True
        self.call_later(self._flush_rebuild)

    def _flush_rebuild(self) -> None:
        self._rebuild_scheduled = False
        self._rebuild()

    def _rebuild(self) -> None:
        """Rebuild visible lines from _meta using current filter."""
        super().clear()
        self._visible_meta_indices = [
            i for i, m in enumerate(self._meta) if self._is_visible(m)
        ]
        self._line_to_screen = []
        screen_line = 0
        for meta_idx in self._visible_meta_indices:
            self._line_to_screen.append(screen_line)
            prev_count = len(self.lines)
            self.write(self._build_text(self._meta[meta_idx]), scroll_end=False)
            screen_line += len(self.lines) - prev_count
        self._update_matches()
        # Only auto-scroll when no search is active; matches take scroll priority.
        if self.auto_scroll and not self._matches:
            self.scroll_end(animate=False)

    def _is_visible(self, meta: _LineMeta) -> bool:
        if self._level_filter == "ALL":
            return True
        return meta.level == self._level_filter

    def _update_matches(self) -> None:
        """Find all visible lines matching _search_query."""
        self._matches = []
        self._match_idx = -1
        self._current_match_screen_y = -1
        if not self._search_query:
            self.refresh()
            return
        for vis_idx, meta_idx in enumerate(self._visible_meta_indices):
            meta = self._meta[meta_idx]
            if self._search_query in meta.raw:
                self._matches.append(self._line_to_screen[vis_idx])
        if self._matches:
            self._match_idx = 0
            self._goto_match()
        else:
            self.refresh()

    def _goto_match(self) -> None:
        if not self._matches or self._match_idx < 0:
            return
        self._current_match_screen_y = self._matches[self._match_idx]
        self.scroll_to(y=self._current_match_screen_y, animate=False)
        self.refresh()

    # ---------- rendering ----------

    def render_line(self, y: int) -> Strip:
        """Render line *y*, adding active-match background if needed."""
        strip = super().render_line(y)
        scroll_y = self.scroll_offset.y
        if scroll_y + y == self._current_match_screen_y:
            segs = [
                Segment(s.text, (s.style or Style()) + _ACTIVE_BG_STYLE, s.control)
                for s in strip._segments
            ]
            return Strip(segs, strip.cell_length)
        return strip

    # ---------- interactions ----------

    @on(Click)
    def _on_click(self, event: Click) -> None:
        """Copy the clicked log line to clipboard."""
        scroll_y = self.scroll_offset.y
        screen_y = scroll_y + event.y
        # Map screen line back to logical visible line via _line_to_screen.
        if not self._line_to_screen:
            event.stop()
            return
        vis_idx = bisect.bisect_right(self._line_to_screen, screen_y) - 1
        if 0 <= vis_idx < len(self._visible_meta_indices):
            meta = self._meta[self._visible_meta_indices[vis_idx]]
            _copy_to_clipboard(meta.raw)
            self.notify("Copied to clipboard", timeout=1.5)
        event.stop()
