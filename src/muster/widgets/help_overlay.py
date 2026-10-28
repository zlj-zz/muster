"""Modal help screen listing every keyboard shortcut."""

from __future__ import annotations

from rich.table import Table
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static


class HelpOverlay(ModalScreen):
    """Modal overlay showing all app-level key bindings.

    Bindings are injected from the app so the help text can never drift
    from the real key map (hidden bindings included — discoverability is
    the whole point of this screen).
    """

    BINDINGS = [
        Binding("question_mark,escape", "dismiss_help", "Close", show=False),
    ]

    def __init__(
        self, bindings: list[Binding], screen_title: str = "Keybindings", **kwargs
    ) -> None:
        super().__init__(**kwargs)
        # Skip the help binding itself — "?" closing "?" is implicit.
        self._help_bindings = [b for b in bindings if "help" not in b.action]
        self._screen_title = screen_title

    def key_rows(self) -> list[tuple[str, str]]:
        """Return ``(keys, description)`` rows for the bindings table.

        Returns:
            One tuple per binding, in declaration order.
        """
        return [(b.key, b.description or b.action) for b in self._help_bindings]

    def compose(self) -> ComposeResult:
        rows = Table.grid(padding=(0, 3))
        rows.add_column(justify="right", style="bold")
        rows.add_column()
        for keys, description in self.key_rows():
            rows.add_row(keys.replace(",", ", "), description)
        with VerticalScroll(id="help-body"):
            yield Static(f"[bold]{self._screen_title}[/bold]", id="help-title")
            yield Static(rows, id="help-keys")

    def action_dismiss_help(self) -> None:
        """Close the overlay."""
        self.dismiss()
