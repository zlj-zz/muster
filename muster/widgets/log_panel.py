"""Read-only log panel using TextArea for copy/select support.

Unlike a plain ``Static``, ``TextArea`` allows users to select and copy log
lines with standard terminal mouse/keyboard interactions.
"""

from __future__ import annotations

from typing import Optional

from textual.widgets import TextArea

from ..models import Service


class LogPanel(TextArea):
    """Service log viewer with a 2000-line rolling buffer."""

    def __init__(self, **kwargs) -> None:
        super().__init__(read_only=True, show_line_numbers=False, **kwargs)
        self._svc_name: Optional[str] = None

    def on_mount(self) -> None:
        self.border_title = "Logs"
        self.cursor_blink = False

    def set_service(self, svc: Optional[Service]) -> None:
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
            self.text = "\n".join(svc.log_lines)
            self.move_cursor((len(svc.log_lines) - 1, 0))
            self.scroll_end(animate=False)
            self.refresh()

    def append_log(self, svc_name: str, line: str) -> None:
        """Append a single log line if it belongs to the currently shown service.

        Trims the buffer to the last 2000 lines to keep memory bounded.

        Args:
            svc_name: Name of the service that produced the line.
            line: Raw log line text.
        """
        if self._svc_name != svc_name:
            return
        current = self.text
        if current:
            current += "\n"
        current += line
        lines = current.splitlines()
        if len(lines) > 2000:
            current = "\n".join(lines[-2000:])
        self.text = current
        last_line = len(lines) - 1
        if last_line >= 0:
            self.move_cursor((last_line, 0))
            self.scroll_end(animate=False)
            self.refresh()
