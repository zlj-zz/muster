"""Environment detail panel for the env tab's right panel.

Displays structured metadata for a selected environment check and its
most recent test results.
"""

from __future__ import annotations

from datetime import datetime

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

    def refresh_content(self) -> None:
        """Force a full re-render of the current env check."""
        self._render_detail(self.current_env)

    def watch_current_env(self, env: EnvCheck | None) -> None:
        """React to env check selection changes."""
        self._render_detail(env)

    @staticmethod
    def _latency_style(ms: int) -> str:
        """Return a colour for the given latency in milliseconds."""
        if ms < 50:
            return "#98c379"
        if ms < 200:
            return "#e5c07b"
        return "#e06c75"

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

        # --- runtime state ---
        if env.last_checked is not None:
            delta = datetime.now() - env.last_checked
            seconds = int(delta.total_seconds())
            if seconds < 1:
                checked = "just now"
            elif seconds < 60:
                checked = f"{seconds}s ago"
            else:
                checked = f"{seconds // 60}m {seconds % 60}s ago"
            lines.append(kv("Checked", checked, "dim"))

        if env.latency_ms is not None:
            lines.append(
                kv(
                    "Latency",
                    f"{env.latency_ms}ms",
                    self._latency_style(env.latency_ms),
                )
            )

        if env.consecutive_failures > 0:
            lines.append(kv("Failures", str(env.consecutive_failures), "#e06c75 bold"))

        content.update(Text("\n").join(lines))
