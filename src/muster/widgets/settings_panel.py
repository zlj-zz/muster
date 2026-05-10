"""Settings panel for runtime preferences.

A single full-width panel with collapsible sections (General, Logs, Timing)
and a Save / Reset action bar at the bottom.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Input, Select, Static, Switch

from ..models import AppSettings


class SettingsLabel(Static):
    """A settings row label with an optional tooltip."""

    def __init__(self, text: str, tooltip: str = "", **kwargs) -> None:
        super().__init__(text, classes="settings-label", **kwargs)
        self.tooltip = tooltip


class SettingsPanel(VerticalScroll):
    """Editable settings form posted inside the right-content switcher.

    Attributes:
        settings: The current ``AppSettings`` instance reflected by the form.
    """

    def __init__(self, settings: AppSettings, **kwargs) -> None:
        super().__init__(**kwargs)
        self.settings = settings

    def compose(self) -> ComposeResult:
        """Build the three-section form."""
        # ── General ──
        with Vertical(classes="settings-section"):
            yield Static("General", classes="settings-section-title")

            with Horizontal(classes="settings-row"):
                yield SettingsLabel(
                    "Env refresh",
                    "Seconds between environment health check polls",
                )
                yield Input(
                    str(self.settings.env_refresh_interval),
                    id="input-env-interval",
                )
                yield Static("s", classes="settings-unit")

            with Horizontal(classes="settings-row"):
                yield SettingsLabel(
                    "Port conflict",
                    "What to do when a service port is already in use",
                )
                yield Select(
                    [("Auto kill", "kill"), ("Warn only", "warn"), ("Abort", "abort")],
                    allow_blank=False,
                    classes="-textual-compact",
                    id="select-port-strategy",
                )

        # ── Logs ──
        with Vertical(classes="settings-section"):
            yield Static("Logs", classes="settings-section-title")

            with Horizontal(classes="settings-row"):
                yield SettingsLabel(
                    "Auto-scroll",
                    "Scroll to the bottom on every new log line",
                )
                yield Switch(
                    value=self.settings.log_auto_scroll,
                    id="switch-auto-scroll",
                )

            with Horizontal(classes="settings-row"):
                yield SettingsLabel(
                    "Timestamps",
                    "Prefix each log line with the current time",
                )
                yield Switch(
                    value=self.settings.log_show_timestamp,
                    id="switch-timestamps",
                )

            with Horizontal(classes="settings-row"):
                yield SettingsLabel(
                    "Wrap lines",
                    "Soft-wrap long log lines instead of truncating",
                )
                yield Switch(
                    value=self.settings.log_wrap,
                    id="switch-wrap",
                )

            with Horizontal(classes="settings-row"):
                yield SettingsLabel(
                    "Default level",
                    "Initial log-level filter shown in the log panel",
                )
                yield Select(
                    [
                        ("ALL", "ALL"),
                        ("ERROR", "ERROR"),
                        ("WARN", "WARN"),
                        ("INFO", "INFO"),
                        ("DEBUG", "DEBUG"),
                    ],
                    allow_blank=False,
                    classes="-textual-compact",
                    id="select-log-level",
                )

            with Horizontal(classes="settings-row"):
                yield SettingsLabel(
                    "Buffer lines",
                    "Maximum number of log lines kept in memory",
                )
                yield Input(
                    str(self.settings.log_buffer_lines),
                    id="input-buffer-lines",
                )

            with Horizontal(classes="settings-row"):
                yield SettingsLabel(
                    "Load history",
                    "Load today's disk logs when viewing a service for the first time",
                )
                yield Switch(
                    value=self.settings.load_history_on_startup,
                    id="switch-load-history",
                )

        # ── Timing ──
        with Vertical(classes="settings-section"):
            yield Static("Timing", classes="settings-section-title")

            with Horizontal(classes="settings-row"):
                yield SettingsLabel(
                    "Health timeout",
                    "Seconds to wait for a service port to become ready",
                )
                yield Input(
                    str(self.settings.health_timeout),
                    id="input-health-timeout",
                )
                yield Static("s", classes="settings-unit")

            with Horizontal(classes="settings-row"):
                yield SettingsLabel(
                    "Stop timeout",
                    "Seconds to wait for graceful shutdown before SIGKILL",
                )
                yield Input(
                    str(self.settings.stop_timeout),
                    id="input-stop-timeout",
                )
                yield Static("s", classes="settings-unit")

        # ── Actions ──
        with Horizontal(classes="settings-row"):
            yield Button.success("Save", flat=True, id="btn-save")
            yield Button.warning("Reset", flat=True, id="btn-reset")

    def on_mount(self) -> None:
        """Set initial Select values after mount to avoid validation issues."""
        self.border_title = "Settings"
        self.query_one("#select-port-strategy", Select).value = (
            self.settings.port_conflict_strategy
        )
        self.query_one("#select-log-level", Select).value = (
            self.settings.log_default_level
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle Save / Reset clicks."""
        if event.button.id == "btn-save":
            self._save_settings()
        elif event.button.id == "btn-reset":
            self._reset_settings()

    def _save_settings(self) -> None:
        """Read widget values, build ``AppSettings``, and notify the App."""
        try:
            new_settings = AppSettings(
                env_refresh_interval=int(
                    self.query_one("#input-env-interval", Input).value or "5"
                ),
                port_conflict_strategy=str(
                    self.query_one("#select-port-strategy", Select).value
                ),
                log_auto_scroll=bool(
                    self.query_one("#switch-auto-scroll", Switch).value
                ),
                log_show_timestamp=bool(
                    self.query_one("#switch-timestamps", Switch).value
                ),
                log_wrap=bool(self.query_one("#switch-wrap", Switch).value),
                log_default_level=str(
                    self.query_one("#select-log-level", Select).value
                ),
                log_buffer_lines=int(
                    self.query_one("#input-buffer-lines", Input).value or "2000"
                ),
                load_history_on_startup=bool(
                    self.query_one("#switch-load-history", Switch).value
                ),
                health_timeout=int(
                    self.query_one("#input-health-timeout", Input).value or "60"
                ),
                stop_timeout=float(
                    self.query_one("#input-stop-timeout", Input).value or "8"
                ),
            )
        except (ValueError, TypeError):
            # Invalid input — silently keep current settings.
            # In a future iteration we could show a toast here.
            return

        self.settings = new_settings
        self.post_message(self.SettingsChanged(new_settings))

    def _reset_settings(self) -> None:
        """Restore defaults and update every widget."""
        defaults = AppSettings()
        self.query_one("#input-env-interval", Input).value = str(
            defaults.env_refresh_interval
        )
        self.query_one("#select-port-strategy", Select).value = (
            defaults.port_conflict_strategy
        )
        self.query_one("#switch-auto-scroll", Switch).value = defaults.log_auto_scroll
        self.query_one("#switch-timestamps", Switch).value = defaults.log_show_timestamp
        self.query_one("#switch-wrap", Switch).value = defaults.log_wrap
        self.query_one("#select-log-level", Select).value = defaults.log_default_level
        self.query_one("#input-buffer-lines", Input).value = str(
            defaults.log_buffer_lines
        )
        self.query_one("#switch-load-history", Switch).value = (
            defaults.load_history_on_startup
        )
        self.query_one("#input-health-timeout", Input).value = str(
            defaults.health_timeout
        )
        self.query_one("#input-stop-timeout", Input).value = str(defaults.stop_timeout)
        self.settings = defaults
        self.post_message(self.SettingsChanged(defaults))

    class SettingsChanged(Message):
        """Message sent when the user presses Save or Reset.

        Attributes:
            settings: The new ``AppSettings`` to apply.
        """

        def __init__(self, settings: AppSettings) -> None:
            self.settings = settings
            super().__init__()
