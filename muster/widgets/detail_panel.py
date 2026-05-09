"""Service detail panel with action buttons.

Displays structured metadata for the currently selected service (name, group,
status, port, dependencies, and command snippets) and provides ``Start``,
``Stop``, ``Restart`` buttons whose disabled state tracks the service status.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from rich.console import Console, ConsoleOptions, RenderResult, RenderableType
from rich.segment import Segment
from rich.syntax import Syntax
from rich.text import Text
from textual import on
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Button, Static

from ..models import Group, Service, Status


class VStack:
    """Vertically stack multiple Rich renderables with blank-line separators.

    Replaces Rich's ``Group`` which has a hard positional-argument limit in
    newer versions.
    """

    def __init__(self, items: list[RenderableType]) -> None:
        self.items = items

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        for i, item in enumerate(self.items):
            if i > 0:
                yield Segment.line()
            yield from console.render(item, options)


class DetailPanel(Static):
    """Service details + action buttons.

    Attributes:
        current_service: The service currently shown; reactive so that UI
            updates are automatic when it changes.
    """

    current_service: reactive[Optional[Service]] = reactive(None)

    def __init__(
        self, groups: List[Group], status_colors: Dict[str, str], **kwargs
    ) -> None:
        super().__init__(**kwargs)
        self._groups = groups
        self._status_colors = status_colors
        self.border_title = Text("Detail", style="bold white")

    def compose(self) -> ComposeResult:
        with Vertical(id="detail-container"):
            yield Static(id="detail-content")
            with Horizontal(id="action-buttons"):
                yield Button("Start", id="btn-start")
                yield Button("Stop", id="btn-stop")
                yield Button("Restart", id="btn-restart")

    def watch_current_service(self, svc: Optional[Service]) -> None:
        """React to service selection changes.

        Re-renders metadata, updates button states, and shows/hides the button
        row depending on whether a service is selected.
        """
        self._render_detail(svc)
        self._update_buttons(svc)
        buttons = self.query_one("#action-buttons", Horizontal)
        buttons.styles.display = "none" if svc is None else "block"

    def _render_detail(self, svc: Optional[Service]) -> None:
        """Build and display the key/value metadata block.

        Args:
            svc: Service to render, or ``None`` to clear the panel.
        """
        content = self.query_one("#detail-content", Static)
        if svc is None:
            content.update("")
            return

        deps = ", ".join(svc.depends_on) if svc.depends_on else "none"
        port = str(svc.port) if svc.port else "unresolved"
        group = next((g for g in self._groups if g.id == svc.group), None)
        group_color = group.color if group else "#cccccc"
        status_color = self._status_colors.get(svc.status.value, "#cccccc")

        def kv(key: str, value: str, value_style: str = "") -> Text:
            """Helper to build a single aligned key/value line."""
            line = Text()
            line.append(f"{key:<8} ", style="dim bold")
            if value_style:
                line.append(value, style=value_style)
            else:
                line.append(value)
            return line

        lines: List[Text | Syntax] = [
            kv("Name", svc.name),
            kv("Group", group.label if group else svc.group, f"bold {group_color}"),
            kv("Status", svc.status.value, f"bold {status_color}"),
            kv("Port", port),
            kv("Deps", deps),
        ]

        # Render all available command modes as syntax-highlighted blocks.
        if isinstance(svc.cmd, dict):
            for mode, cmd in svc.cmd.items():
                lines.append(Text())
                label = "Command" if mode == "default" else f"Command ({mode})"
                lines.append(Text(label, style="bold"))
                lines.append(
                    Syntax(cmd, "bash", theme="monokai", background_color="default")
                )
        else:
            lines.append(Text())
            lines.append(Text("Command", style="bold"))
            lines.append(
                Syntax(svc.cmd, "bash", theme="monokai", background_color="default")
            )

        content.update(VStack(lines))

    def _update_buttons(self, svc: Optional[Service]) -> None:
        """Enable/disable action buttons based on service state.

        Args:
            svc: Currently selected service.
        """
        start_btn = self.query_one("#btn-start", Button)
        stop_btn = self.query_one("#btn-stop", Button)
        restart_btn = self.query_one("#btn-restart", Button)

        disabled = (True, True, True)
        if svc is not None:
            if svc.status == Status.STARTING:
                disabled = (True, True, True)
            elif svc.status == Status.RUNNING:
                disabled = (True, False, False)
            else:
                disabled = (False, True, True)
        start_btn.disabled, stop_btn.disabled, restart_btn.disabled = disabled

    @on(Button.Pressed, "#btn-start")
    def on_start(self) -> None:
        """Fire a start action message when the Start button is pressed."""
        if self.current_service:
            self.post_message(self.ActionTriggered(self.current_service, "start"))

    @on(Button.Pressed, "#btn-stop")
    def on_stop(self) -> None:
        """Fire a stop action message when the Stop button is pressed."""
        if self.current_service:
            self.post_message(self.ActionTriggered(self.current_service, "stop"))

    @on(Button.Pressed, "#btn-restart")
    def on_restart(self) -> None:
        """Fire a restart action message when the Restart button is pressed."""
        if self.current_service:
            self.post_message(self.ActionTriggered(self.current_service, "restart"))

    class ActionTriggered(Message):
        """Message sent when a detail-panel action button is pressed.

        Attributes:
            service: The service the action applies to.
            action: One of ``"start"``, ``"stop"``, ``"restart"``.
        """

        def __init__(self, service: Service, action: str) -> None:
            self.service = service
            self.action = action
            super().__init__()
