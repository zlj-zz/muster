"""Compact mode indicator bar.

Displays the current command mode / group filter as a subtle right-aligned
badge.  Environment checks have been moved to EnvIndicator in the left panel.
"""

from __future__ import annotations

from textual.widgets import Static


class StatusBar(Static):
    """Right-aligned command mode / group filter indicator.

    Attributes:
        _mode_text: Cached Rich markup for the mode badge.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._mode_text = ""

    def on_mount(self) -> None:
        """Show default mode on mount."""
        self.set_mode("DEFAULT | ALL")

    def set_mode(self, mode: str) -> None:
        """Update the mode label.

        Args:
            mode: Mode string (e.g. ``"DEFAULT | ALL"``).
        """
        self._mode_text = f"[bold #abb2bf on #3e4451] {mode} [/bold #abb2bf on #3e4451]"
        self.update(self._mode_text)
