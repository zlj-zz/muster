"""Compact single-line status bar showing env checks and mode."""

from textual.widgets import Static

from ..core.env import check_env
from ..models import MusterConfig


class StatusBar(Static):
    """Top bar: environment indicators + current mode label.

    Refreshes every 5 seconds from the App's interval timer.
    """

    def __init__(self, config: MusterConfig, **kwargs) -> None:
        super().__init__(**kwargs)
        self._config = config
        self._env_text = ""
        self._mode_text = ""

    def on_mount(self) -> None:
        self.refresh_status()
        self.set_mode("DEFAULT | ALL")

    def refresh_status(self) -> None:
        """Re-run environment checks and update the indicator dots."""
        results = check_env(self._config.env_checks)
        indicators = []
        for name, ok in results:
            color = (
                self._config.status_colors.get("running", "#4ec9b0")
                if ok
                else self._config.status_colors.get("failed", "#f44747")
            )
            dot = "●" if ok else "○"
            indicators.append(f"[{color}]{dot} {name}[/{color}]")
        self._env_text = "  ".join(indicators)
        self._update_display()

    def set_mode(self, mode: str) -> None:
        """Update the right-hand mode label.

        Args:
            mode: Mode string (e.g. ``"DEFAULT | ALL"``).
        """
        self._mode_text = f"[dim]{mode}[/]"
        self._update_display()

    def _update_display(self) -> None:
        """Compose the final render text from env + mode segments."""
        env = getattr(self, "_env_text", "")
        mode = getattr(self, "_mode_text", "")
        if env and mode:
            text = f"{env}    {mode}"
        elif env:
            text = env
        elif mode:
            text = mode
        else:
            text = ""
        self.update(text)
