"""Environment detail panel for the env tab's right panel.

Displays structured metadata for a selected environment check, its
most recent test results, and a health-history bar.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import Static

from ..models import EnvCheck

_PASS_COLOR = "#98c379"
_FAIL_COLOR = "#e06c75"
_BLOCK = "■"


def _latency_style(ms: int) -> str:
    """Return a colour for the given latency in milliseconds."""
    if ms < 50:
        return _PASS_COLOR
    if ms < 200:
        return "#e5c07b"
    return _FAIL_COLOR


class EnvDetailPanel(Static):
    """Environment check details panel with health history.

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
        with Vertical(id="env-detail-content"):
            yield Static(id="env-detail-meta")
            yield Static(id="env-detail-history")
            yield Static(id="env-detail-latency-stats")
            yield Static(id="env-detail-stats")

    def on_mount(self) -> None:
        """Cache widget references to avoid repeated DOM queries."""
        self._meta = self.query_one("#env-detail-meta", Static)
        self._history = self.query_one("#env-detail-history", Static)
        self._latency_stats = self.query_one("#env-detail-latency-stats", Static)
        self._stats = self.query_one("#env-detail-stats", Static)

    def refresh_content(self) -> None:
        """Force a full re-render of the current env check."""
        self._render_detail(self.current_env)

    def watch_current_env(self, env: EnvCheck | None) -> None:
        """React to env check selection changes."""
        self._render_detail(env)

    def _render_detail(self, env: EnvCheck | None) -> None:
        """Build and display metadata, history, and stats.

        Args:
            env: Env check to render, or ``None`` to clear the panel.
        """
        if env is None:
            self._meta.update("")
            self._history.update("")
            self._latency_stats.update("")
            self._stats.update("")
            return

        self._meta.update(self._build_meta(env))
        self._history.update(self._build_history(env))
        self._latency_stats.update(self._build_latency_stats(env))
        self._stats.update(self._build_stats(env))

    def _build_meta(self, env: EnvCheck) -> Text:
        """Build the key/value metadata block."""
        addr = f"{env.host or '127.0.0.1'}:{env.port}" if env.port else (env.host or "")

        lines: list[Text] = [
            _kv("Name", env.name),
            _kv("Type", env.type),
            _kv("Host", env.host or "127.0.0.1"),
            _kv("Port", str(env.port) if env.port else "N/A"),
            _kv("Address", addr),
        ]

        if env.last_checked is not None:
            delta = datetime.now() - env.last_checked
            seconds = int(delta.total_seconds())
            if seconds < 1:
                checked = "just now"
            elif seconds < 60:
                checked = f"{seconds}s ago"
            else:
                checked = f"{seconds // 60}m {seconds % 60}s ago"
            lines.append(_kv("Checked", checked, "dim"))

        if env.latency_ms is not None:
            lines.append(
                _kv("Latency", f"{env.latency_ms}ms", _latency_style(env.latency_ms))
            )

        if env.consecutive_failures > 0:
            lines.append(_kv("Failures", str(env.consecutive_failures), "#e06c75 bold"))

        return Text("\n").join(lines)

    @staticmethod
    def _build_history(env: EnvCheck) -> Text:
        """Build a coloured block-bar from the check history."""
        hist: deque[bool] = env.history
        if not hist:
            return Text("")

        label = Text("History    ", style="dim bold")
        bar = Text()
        for ok in hist:
            bar.append(_BLOCK, style=_PASS_COLOR if ok else _FAIL_COLOR)
        return Text.assemble(label, bar)

    @staticmethod
    def _build_latency_stats(env: EnvCheck) -> Text:
        """Build a latency statistics summary (min / max / avg / last)."""
        latencies = [lat for lat in env.latency_history if lat is not None]
        if not latencies:
            return Text("")

        minimum = min(latencies)
        maximum = max(latencies)
        average = sum(latencies) / len(latencies)
        last = latencies[-1]

        parts: list[Text] = [
            _stat("min", minimum, _latency_style(minimum)),
            _stat("avg", int(average), _latency_style(int(average))),
            _stat("max", maximum, _latency_style(maximum)),
            _stat("last", last, _latency_style(last)),
        ]
        label = Text("Recent     ", style="dim bold")
        return Text.assemble(label, Text("  ").join(parts))

    @staticmethod
    def _build_stats(env: EnvCheck) -> Text:
        """Build a one-line stats summary from the check history."""
        hist: deque[bool] = env.history
        if not hist:
            return Text("")

        total = len(hist)
        passed = sum(1 for ok in hist if ok)
        pct = passed / total * 100

        lines: list[Text] = []
        stat = Text()
        stat.append(f"{passed}/{total} passing", style="dim")
        if total >= 5:
            stat.append(f"  ({pct:.0f}%)", style="dim")
        lines.append(stat)

        if env.consecutive_failures > 0:
            lines.append(
                Text(
                    f"{env.consecutive_failures} consecutive failure(s)",
                    style="#e06c75",
                )
            )

        return Text("\n").join(lines)


def _kv(key: str, value: str, value_style: str = "") -> Text:
    """Build a single aligned key/value line."""
    line = Text()
    line.append(f"{key:<10} ", style="dim bold")
    if value_style:
        line.append(value, style=value_style)
    else:
        line.append(value)
    return line


def _stat(label: str, value: int, style: str = "") -> Text:
    """Build a single latency stat label/value pair."""
    line = Text()
    line.append(f"{label:<6}", style="dim")
    line.append(f"{value}ms", style=style or "default")
    return line
