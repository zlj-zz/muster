"""Service detail panel with action buttons.

Displays structured metadata for the currently selected service (name, group,
status, port, dependencies, and command snippets) and provides ``Start``,
``Stop``, ``Restart`` buttons whose disabled state tracks the service status.
"""

from __future__ import annotations


from rich.syntax import Syntax
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Button, DataTable, Static

from ..models import Group, Service, Status


class DetailPanel(Static):
    """Service details + action buttons.

    Attributes:
        current_service: The service currently shown; reactive so that UI
            updates are automatic when it changes.
    """

    current_service: reactive[Service | None] = reactive(None)

    def __init__(
        self, groups: list[Group], status_colors: dict[str, str], **kwargs
    ) -> None:
        super().__init__(**kwargs)
        self._groups = groups
        self._status_colors = status_colors
        self.border_title = "Detail"

    def compose(self) -> ComposeResult:
        with Vertical(id="detail-container"):
            yield DataTable(show_header=False, zebra_stripes=False, id="detail-content")
            with Horizontal(id="action-buttons"):
                yield Button.success("Start", flat=True, id="btn-start")
                yield Button.error("Stop", flat=True, id="btn-stop")
                yield Button.warning("Restart", flat=True, id="btn-restart")

    def watch_current_service(self, svc: Service | None) -> None:
        """React to service selection changes.

        Re-renders metadata, updates button states, and shows/hides the button
        row depending on whether a service is selected.
        """
        if getattr(self, "_last_service", None) is svc:
            return
        self._last_service = svc
        self._render_detail(svc)
        self._update_buttons(svc)
        buttons = self.query_one("#action-buttons", Horizontal)
        buttons.styles.display = "none" if svc is None else "block"

    def _render_detail(self, svc: Service | None) -> None:
        """Build and display the key/value metadata block.

        Args:
            svc: Service to render, or ``None`` to clear the panel.
        """
        table = self.query_one("#detail-content", DataTable)
        table.clear()

        if svc is None:
            return

        # Ensure columns are defined once.
        if not table.columns:
            table.add_column("key", width=10)
            table.add_column("value")

        deps = ", ".join(svc.depends_on) if svc.depends_on else "none"
        port = str(svc.port) if svc.port else "unresolved"
        group = next((g for g in self._groups if g.id == svc.group), None)
        group_color = group.color if group else "#cccccc"
        status_color = self._status_colors.get(svc.status.value, "#cccccc")

        # Basic metadata rows.
        table.add_row(Text("Name", style="dim bold"), Text(svc.name))
        table.add_row(
            Text("Group", style="dim bold"),
            Text(group.label if group else svc.group, style=f"bold {group_color}"),
        )
        table.add_row(
            Text("Status", style="dim bold"),
            Text(svc.status.value, style=f"bold {status_color}"),
        )
        table.add_row(Text("Port", style="dim bold"), Text(port))
        table.add_row(Text("Deps", style="dim bold"), Text(deps))

        # Command rows.
        if isinstance(svc.cmd, dict):
            for mode, cmd in svc.cmd.items():
                label = "Command" if mode == "default" else f"Command ({mode})"
                self._add_command_block(table, label, cmd)
        else:
            self._add_command_block(table, "Command", svc.cmd)

    def _add_command_block(self, table: DataTable, label: str, cmd: str) -> None:
        """Add a command block (spacer + label + syntax) to the table."""
        table.add_row("", "")
        table.add_row(Text(label, style="bold"), "")
        table.add_row(
            "",
            Syntax(cmd, "bash", theme="monokai", background_color="default"),
        )

    def _update_buttons(self, svc: Service | None) -> None:
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
