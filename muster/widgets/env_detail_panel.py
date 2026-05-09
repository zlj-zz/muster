"""Environment detail panel for the env tab's right panel.

Displays structured metadata for a selected environment check and its
most recent test results.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widgets import Static

from ..models import EnvCheck


class EnvDetailPanel(Static):
    """Environment check details panel.

    Attributes:
        current_env: The env check currently shown; reactive so UI updates
            are automatic when it changes.
    """

    current_env: reactive[EnvCheck | None] = reactive(None)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.border_title = "Environment Detail"

    def compose(self) -> ComposeResult:
        """Build the widget hierarchy."""
        yield Static(id="env-detail-content")

    def watch_current_env(self, env: EnvCheck | None) -> None:
        """React to env check selection changes."""
        self._render_detail(env)

    def _render_detail(self, env: EnvCheck | None) -> None:
        """Build and display the key/value metadata block.

        Args:
            env: Env check to render, or ``None`` to clear the panel.
        """
        content = self.query_one("#env-detail-content", Static)
        if env is None:
            content.update("")
            return

        def kv(key: str, value: str, value_style: str = "") -> Text:
            """Helper to build a single aligned key/value line."""
            line = Text()
            line.append(f"{key:<10} ", style="dim bold")
            if value_style:
                line.append(value, style=value_style)
            else:
                line.append(value)
            return line

        addr = f"{env.host or '127.0.0.1'}:{env.port}" if env.port else (env.host or "")

        lines: list[Text] = [
            kv("Name", env.name),
            kv("Type", env.type),
            kv("Host", env.host or "127.0.0.1"),
            kv("Port", str(env.port) if env.port else "N/A"),
            kv("Address", addr),
        ]

        content.update(Text("\n").join(lines))
