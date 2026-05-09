"""YAML content preview for the yaml tab's right panel.

Displays the contents of a YAML file in a read-only ``TextArea``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import Static, TextArea


class YamlPreview(Vertical):
    """YAML file preview with read-only text area.

    Attributes:
        current_file: Path to the currently displayed file.
    """

    current_file: reactive[Optional[str]] = reactive(None)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

    def compose(self) -> ComposeResult:
        yield Static("Preview", id="yaml-title")
        yield TextArea(read_only=True, language="yaml", id="yaml-text")

    def watch_current_file(self, file_path: Optional[str]) -> None:
        """React to file selection changes.

        Reads the file from disk and updates the text area.
        """
        title = self.query_one("#yaml-title", Static)
        text_area = self.query_one("#yaml-text", TextArea)

        if file_path is None:
            title.update("Preview")
            text_area.text = ""
            return

        title.update(file_path)
        try:
            content = Path(file_path).read_text(encoding="utf-8")
        except OSError as exc:
            text_area.text = f"Failed to read {file_path}: {exc}"
            return

        text_area.text = content
