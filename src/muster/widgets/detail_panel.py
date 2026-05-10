"""Service detail panel with action buttons.

Displays structured metadata for the currently selected service (name, group,
status, port, dependencies, runtime stats, and command snippets) and provides
``Start``, ``Stop``, ``Restart`` buttons whose disabled state tracks the
service status.
"""

from __future__ import annotations

from datetime import datetime

from rich.syntax import Syntax
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Button, Collapsible, Static

from ..models import Group, Service, Status


def _fmt_uptime(start: datetime | None) -> str:
    """Format elapsed time since start."""
    if start is None:
        return "—"
    delta = datetime.now() - start
    total = int(delta.total_seconds())
    if total < 60:
        return f"{total}s"
    if total < 3600:
        return f"{total // 60}m {total % 60}s"
    return f"{total // 3600}h {(total % 3600) // 60}m"


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
        self._last_service: Service | None = None
        self._cached_rows: list[Horizontal] | None = None
        self._cached_buttons: tuple[Button, Button, Button] | None = None
        self._cached_cpu_widget: Static | None = None
        self._cached_mem_widget: Static | None = None
        self._last_cpu: float | None = None
        self._last_mem: float | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="detail-container"):
            with Horizontal(id="detail-top"):
                with VerticalScroll(id="detail-meta"):
                    yield Horizontal(
                        Static("Name", classes="detail-key"),
                        Static("", classes="detail-value"),
                        classes="detail-row",
                    )
                    yield Horizontal(
                        Static("Group", classes="detail-key"),
                        Static("", classes="detail-value"),
                        classes="detail-row",
                    )
                    yield Horizontal(
                        Static("Status", classes="detail-key"),
                        Static("", classes="detail-value"),
                        classes="detail-row",
                    )
                    yield Horizontal(
                        Static("Port", classes="detail-key"),
                        Static("", classes="detail-value"),
                        classes="detail-row",
                    )
                    yield Horizontal(
                        Static("Deps", classes="detail-key"),
                        Static("", classes="detail-value"),
                        classes="detail-row",
                    )
                    yield Horizontal(
                        Static("PID", classes="detail-key"),
                        Static("", classes="detail-value"),
                        classes="detail-row",
                    )
                    yield Horizontal(
                        Static("Started", classes="detail-key"),
                        Static("", classes="detail-value"),
                        classes="detail-row",
                    )
                    yield Horizontal(
                        Static("Uptime", classes="detail-key"),
                        Static("", classes="detail-value"),
                        classes="detail-row",
                    )
                    yield Horizontal(
                        Static("Restarts", classes="detail-key"),
                        Static("", classes="detail-value"),
                        classes="detail-row",
                    )
                    yield Horizontal(
                        Static("Last Error", classes="detail-key"),
                        Static("", classes="detail-value"),
                        classes="detail-row",
                    )
                with Vertical(id="detail-resources"):
                    yield Static("Resources", classes="detail-section-title")
                    yield Horizontal(
                        Static("CPU", classes="resource-label"),
                        Static("", classes="resource-value", id="res-cpu"),
                        classes="resource-row",
                    )
                    yield Horizontal(
                        Static("MEM", classes="resource-label"),
                        Static("", classes="resource-value", id="res-mem"),
                        classes="resource-row",
                    )
            with Collapsible(title="Command", collapsed=True, id="detail-command"):
                yield Static("", classes="detail-code")
            with Horizontal(id="action-buttons"):
                yield Button.success("Start", flat=True, id="btn-start")
                yield Button.error("Stop", flat=True, id="btn-stop")
                yield Button.warning("Restart", flat=True, id="btn-restart")

    def watch_current_service(self, svc: Service | None) -> None:
        """React to service selection changes.

        Re-renders metadata, updates button states, and shows/hides the button
        row depending on whether a service is selected.
        """
        if self._last_service is svc:
            return
        self._last_service = svc
        self._render_detail(svc)
        self._update_buttons(svc)
        buttons = self.query_one("#action-buttons", Horizontal)
        buttons.styles.display = "none" if svc is None else "block"

    def refresh_content(self) -> None:
        """Force a full re-render of the current service."""
        self._render_detail(self.current_service)
        self._update_buttons(self.current_service)

    def _render_detail(self, svc: Service | None) -> None:
        """Build and display the key/value metadata block.

        Args:
            svc: Service to render, or ``None`` to clear the panel.
        """
        rows = self._cached_rows
        if not rows:
            rows = list(self.query(".detail-row").results(Horizontal))
            self._cached_rows = rows
        if svc is None:
            for row in rows:
                row.styles.display = "none"
            self.query_one("#detail-top", Horizontal).styles.display = "none"
            self.query_one("#detail-command", Collapsible).styles.display = "none"
            return

        for row in rows:
            row.styles.display = "block"
        self.query_one("#detail-top", Horizontal).styles.display = "block"
        self.query_one("#detail-command", Collapsible).styles.display = "block"

        group = next((g for g in self._groups if g.id == svc.group), None)
        group_color = group.color if group else "#cccccc"
        status_color = self._status_colors.get(svc.status.value, "#cccccc")

        values = [
            Text(svc.name),
            Text(group.label if group else svc.group, style=f"bold {group_color}"),
            Text(svc.status.value, style=f"bold {status_color}"),
            Text(str(svc.port) if svc.port else "unresolved"),
            Text(", ".join(svc.depends_on) if svc.depends_on else "none"),
            Text(str(svc.proc.pid) if svc.proc else "—"),
            Text(svc.start_time.strftime("%H:%M:%S") if svc.start_time else "—"),
            Text(_fmt_uptime(svc.start_time)),
            Text(str(svc.restart_count)),
            Text(svc.last_error or "—", style="#e06c75" if svc.last_error else ""),
        ]

        for row, value in zip(rows, values):
            value_widget = row.query_one(".detail-value", Static)
            value_widget.update(value)

        # Command block
        cmd = svc.cmd_for("default")
        if isinstance(svc.cmd, dict):
            lines = []
            for mode, c in svc.cmd.items():
                label = f"$ {c}" if mode == "default" else f"$ {c}  # {mode}"
                lines.append(label)
            cmd_text = "\n".join(lines)
        else:
            cmd_text = f"$ {cmd}"

        code_widget = self.query_one(".detail-code", Static)
        code_widget.update(
            Syntax(cmd_text, "bash", theme="monokai", background_color="default")
        )

        if not svc.proc:
            self.update_resources(None, None)

    def update_resources(self, cpu: float | None, mem: float | None) -> None:
        """Update the resource card with new CPU and MEM values.

        Args:
            cpu: CPU percentage (0-100+), or ``None`` if unavailable.
            mem: Memory percentage (0-100+), or ``None`` if unavailable.
        """
        if self._cached_cpu_widget is None:
            self._cached_cpu_widget = self.query_one("#res-cpu", Static)
            self._cached_mem_widget = self.query_one("#res-mem", Static)

        if (
            cpu is not None
            and mem is not None
            and cpu == self._last_cpu
            and mem == self._last_mem
        ):
            return
        self._last_cpu = cpu
        self._last_mem = mem

        if cpu is None or mem is None:
            self._cached_cpu_widget.update("—")
            self._cached_mem_widget.update("—")
            return

        self._cached_cpu_widget.update(self._resource_text(cpu))
        self._cached_mem_widget.update(self._resource_text(mem))

    @staticmethod
    def _resource_text(percent: float) -> Text:
        """Build a coloured progress-bar Text for a resource metric.

        Args:
            percent: Percentage value (0-100+).

        Returns:
            A ``RichText`` with a block-char bar and percentage.
        """
        width = 10
        filled = int(width * percent / 100)
        filled = min(filled, width)
        bar = "█" * filled + "░" * (width - filled)

        if percent >= 95:
            color = "#e06c75"
        elif percent >= 80:
            color = "#e5c07b"
        else:
            color = "#98c379"

        return Text.assemble(
            (f"[{bar}] ", color),
            (f"{percent:.1f}%", f"bold {color}"),
        )

    def _update_buttons(self, svc: Service | None) -> None:
        """Enable/disable action buttons based on service state.

        Args:
            svc: Currently selected service.
        """
        btns = self._cached_buttons
        if not btns:
            btns = (
                self.query_one("#btn-start", Button),
                self.query_one("#btn-stop", Button),
                self.query_one("#btn-restart", Button),
            )
            self._cached_buttons = btns
        start_btn, stop_btn, restart_btn = btns

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
