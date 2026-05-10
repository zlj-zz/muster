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
                yield Static("Env refresh", classes="settings-label")
                yield Input(
                    str(self.settings.env_refresh_interval),
                    id="input-env-interval",
                )
                yield Static("s", classes="settings-unit")

            with Horizontal(classes="settings-row"):
                yield Static("Port conflict", classes="settings-label")
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
                yield Static("Auto-scroll", classes="settings-label")
                yield Switch(
                    value=self.settings.log_auto_scroll,
                    id="switch-auto-scroll",
                )

            with Horizontal(classes="settings-row"):
                yield Static("Timestamps", classes="settings-label")
                yield Switch(
                    value=self.settings.log_show_timestamp,
                    id="switch-timestamps",
                )

            with Horizontal(classes="settings-row"):
                yield Static("Default level", classes="settings-label")
                yield Select(
                    [
                        ("ALL", "ALL"),
                        ("ERROR", "ERROR"),
                        ("WARN", "WARN"),
                        ("INFO", "INFO"),
                    ],
                    allow_blank=False,
                    classes="-textual-compact",
                    id="select-log-level",
                )

            with Horizontal(classes="settings-row"):
                yield Static("Buffer lines", classes="settings-label")
                yield Input(
                    str(self.settings.log_buffer_lines),
                    id="input-buffer-lines",
                )

        # ── Timing ──
        with Vertical(classes="settings-section"):
            yield Static("Timing", classes="settings-section-title")

            with Horizontal(classes="settings-row"):
                yield Static("Health timeout", classes="settings-label")
                yield Input(
                    str(self.settings.health_timeout),
                    id="input-health-timeout",
                )
                yield Static("s", classes="settings-unit")

            with Horizontal(classes="settings-row"):
                yield Static("Stop timeout", classes="settings-label")
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
                log_default_level=str(
                    self.query_one("#select-log-level", Select).value
                ),
                log_buffer_lines=int(
                    self.query_one("#input-buffer-lines", Input).value or "2000"
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
        self.query_one("#select-log-level", Select).value = defaults.log_default_level
        self.query_one("#input-buffer-lines", Input).value = str(
            defaults.log_buffer_lines
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
