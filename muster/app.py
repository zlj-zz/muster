"""Main Textual App for muster.

``MusterApp`` is the root TUI application.  It owns the layout, keyboard
bindings, and widget coordination, but delegates all process lifecycle work to
``ServiceOrchestrator``.
"""

from __future__ import annotations

import asyncio
from typing import Dict, List, Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer

from .core.env import check_env
from .core.orchestrator import ServiceOrchestrator
from .models import Group, MusterConfig, Service, Status
from .widgets import DetailPanel, LogPanel, ServiceTree, StatusBar


class MusterApp(App):
    """TUI service orchestrator.

    Manages the four-panel layout (service tree, status bar, detail panel,
    log panel) and forwards user actions to ``ServiceOrchestrator``.

    Attributes:
        all_services: Full list of services loaded from config.
        registry: Name-to-service lookup map.
        cmd_mode: Currently active command mode (e.g. ``"default"``).
    """

    CSS_PATH = "app.tcss"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh_env", "Refresh Env"),
        Binding("a", "start_all", "Start All"),
        Binding("s", "stop_all", "Stop All"),
        Binding("enter", "toggle_service", "Toggle"),
        Binding("R", "restart_service", "Restart"),
        Binding("t", "cycle_cmd_mode", "Mode"),
        Binding("l", "cycle_group", "Filter Group"),
        Binding("j,down", "cursor_down", "Down", show=False),
        Binding("k,up", "cursor_up", "Up", show=False),
    ]

    def __init__(
        self,
        config: MusterConfig,
        services: List[Service],
        registry: Dict[str, Service],
        cmd_mode: str = "default",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._muster_config = config
        self.all_services = services
        self.registry = registry
        self.cmd_mode = cmd_mode
        self._group_filter: Optional[str] = None
        self._cleaned_up = False
        self._orchestrator = ServiceOrchestrator(
            config,
            registry,
            on_log=self._safe_append_log,
            on_status=self._refresh_list_item,
            on_notify=lambda msg, sev: self.notify(msg, severity=sev),
        )

    @property
    def _common_cmd_modes(self) -> List[str]:
        """Return cmd modes shared by all services (for cycling).

        The intersection of every service's ``cmd_modes`` gives the set of
        modes that can be applied globally without errors.

        Returns:
            Sorted list of common mode names, with ``"default"`` first.
        """
        if not self.all_services:
            return ["default"]
        modes = set(self.all_services[0].cmd_modes)
        for svc in self.all_services[1:]:
            modes &= set(svc.cmd_modes)
        return sorted(modes, key=lambda m: (m != "default", m))

    def compose(self) -> ComposeResult:
        """Build the widget hierarchy."""
        with Horizontal(id="body"):
            yield ServiceTree(
                self._filtered_services(),
                self._muster_config.groups,
                self._muster_config.status_colors,
                id="service-tree",
            )
            with Vertical(id="right-panel"):
                yield StatusBar(self._muster_config, id="status-bar")
                yield DetailPanel(
                    self._muster_config.groups,
                    self._muster_config.status_colors,
                    id="detail",
                )
                yield LogPanel(id="log")
        yield Footer()

    def on_mount(self) -> None:
        """Initialise the UI after widgets are mounted.

        Auto-selects the first service so that the detail and log panels are
        never empty on startup.
        """
        self.title = "muster"
        self._refresh_env_status()
        self.set_interval(5, self._refresh_env_status)
        tree = self.query_one("#service-tree", ServiceTree)
        if tree.services:
            for group_node in tree.root.children:
                if group_node.children:
                    svc = group_node.children[0].data
                    if isinstance(svc, Service):
                        tree.highlight_service(svc.name)
                    break
        self._update_detail()

    def _mode_label(self) -> str:
        """Build the subtitle string shown in the header.

        Returns:
            String like ``"DEFAULT | ALL"`` or ``"TEST | DOMAIN"``.
        """
        parts = [self.cmd_mode.upper()]
        parts.append(self._group_filter.upper() if self._group_filter else "ALL")
        return " | ".join(parts)

    def _safe_append_log(self, svc_name: str, line: str) -> None:
        """Append a log line, swallowing widget lookup errors.

        Called from background tasks; the log panel may not exist during
        shutdown.

        Args:
            svc_name: Name of the service that produced the line.
            line: Raw log text.
        """
        try:
            self.query_one("#log", LogPanel).append_log(svc_name, line)
        except Exception as e:
            self.log.error(f"append_log failed: {e}")

    def _filtered_services(self) -> List[Service]:
        """Return services matching the current group filter.

        Returns:
            All services when no filter is active, otherwise only services
            whose ``group`` equals ``_group_filter``.
        """
        if self._group_filter is None:
            return self.all_services
        return [s for s in self.all_services if s.group == self._group_filter]

    def _refresh_tree(self) -> None:
        """Rebuild the service tree and restore the previous selection."""
        tree = self.query_one("#service-tree", ServiceTree)
        current_name = tree.current_service.name if tree.current_service else None
        tree.services = self._filtered_services()
        tree.rebuild()
        if current_name:
            tree.select_service(current_name)
        elif tree.services:
            for group_node in tree.root.children:
                if group_node.children:
                    svc = group_node.children[0].data
                    if isinstance(svc, Service):
                        tree.highlight_service(svc.name)
                    break
        self._update_detail()

    def _update_detail(self) -> None:
        """Synchronise DetailPanel and LogPanel with the current tree selection."""
        tree = self.query_one("#service-tree", ServiceTree)
        svc = tree.current_service
        self.query_one("#detail", DetailPanel).current_service = svc
        try:
            self.query_one("#log", LogPanel).set_service(svc)
        except Exception as e:
            self.log.error(f"update_detail failed: {e}")

    def _refresh_env_status(self) -> None:
        """Poll environment checks and refresh the status bar."""
        try:
            bar = self.query_one("#status-bar", StatusBar)
            bar.refresh_status()
            bar.set_mode(self._mode_label())
        except Exception as e:
            self.log.error(f"refresh env status failed: {e}")

    def _refresh_list_item(self, svc: Service) -> None:
        """Refresh a single service node in the tree and detail panel.

        Called by ``ServiceOrchestrator`` whenever a service's status changes.

        Args:
            svc: Service whose visual representation should be refreshed.
        """
        try:
            tree = self.query_one("#service-tree", ServiceTree)
            tree.refresh_node(svc)
            detail = self.query_one("#detail", DetailPanel)
            if detail.current_service is svc:
                detail.watch_current_service(svc)
        except Exception as exc:
            self.log.error(f"refresh_list_item failed: {exc}")

    # ---------- event handlers ----------

    def on_service_tree_service_highlighted(
        self, event: ServiceTree.ServiceHighlighted
    ) -> None:
        """Update detail/log panels when the user highlights a new service."""
        self._update_detail()

    def on_detail_panel_action_triggered(
        self, event: DetailPanel.ActionTriggered
    ) -> None:
        """Forward button clicks from the detail panel to the orchestrator."""
        svc = event.service
        if event.action == "start":
            asyncio.create_task(self._orchestrator.start_with_deps(svc, self.cmd_mode))
        elif event.action == "stop":
            asyncio.create_task(self._orchestrator.stop(svc))
        elif event.action == "restart":
            asyncio.create_task(self._orchestrator.restart(svc, self.cmd_mode))

    # ---------- actions ----------

    def action_cursor_down(self) -> None:
        """Move tree cursor down and update detail panel."""
        tree = self.query_one("#service-tree", ServiceTree)
        tree.action_cursor_down()
        self._update_detail()

    def action_cursor_up(self) -> None:
        """Move tree cursor up and update detail panel."""
        tree = self.query_one("#service-tree", ServiceTree)
        tree.action_cursor_up()
        self._update_detail()

    def action_toggle_service(self) -> None:
        """Start or stop the currently selected service."""
        tree = self.query_one("#service-tree", ServiceTree)
        svc = tree.current_service
        if not svc:
            return
        if svc.status == Status.RUNNING:
            asyncio.create_task(self._orchestrator.stop(svc))
        else:
            asyncio.create_task(self._orchestrator.start_with_deps(svc, self.cmd_mode))

    def action_start_all(self) -> None:
        """Start every service in the current group filter."""
        for svc in self._filtered_services():
            if svc.status != Status.RUNNING:
                asyncio.create_task(self._orchestrator.start_with_deps(svc, self.cmd_mode))
        self.notify("Starting all services...", severity="information")

    def action_stop_all(self) -> None:
        """Stop every service across all groups."""
        for svc in self.all_services:
            if svc.status != Status.STOPPED:
                asyncio.create_task(self._orchestrator.stop(svc))
        self.notify("Stopping all services...", severity="information")

    def action_restart_service(self) -> None:
        """Restart the currently selected service."""
        tree = self.query_one("#service-tree", ServiceTree)
        svc = tree.current_service
        if not svc:
            return
        asyncio.create_task(self._orchestrator.restart(svc, self.cmd_mode))
        self.notify(f"Restarting {svc.name}...", severity="information")

    def action_cycle_cmd_mode(self) -> None:
        """Rotate through the common command modes shared by all services."""
        modes = self._common_cmd_modes
        if len(modes) <= 1:
            self.notify("Only one command mode available", severity="information")
            return
        idx = modes.index(self.cmd_mode) if self.cmd_mode in modes else 0
        self.cmd_mode = modes[(idx + 1) % len(modes)]
        self._refresh_env_status()
        self.notify(f"Mode: {self.cmd_mode.upper()}", severity="information")

    def action_cycle_group(self) -> None:
        """Rotate through group filters (ALL → group1 → group2 → ...)."""
        group_ids = [None] + [g.id for g in self._muster_config.groups]
        idx = group_ids.index(self._group_filter)
        self._group_filter = group_ids[(idx + 1) % len(group_ids)]
        label = self._group_filter.upper() if self._group_filter else "ALL"
        self.notify(f"Group filter: {label}", severity="information")
        self._refresh_tree()

    def action_refresh_env(self) -> None:
        """Manually trigger an environment status refresh."""
        self._refresh_env_status()

    async def action_quit(self) -> None:
        """Gracefully shut down before exiting the application."""
        self.notify("Stopping all services...", severity="warning")
        await self._cleanup()
        await super().action_quit()

    async def _cleanup(self) -> None:
        """Stop all services and cancel background tasks.

        Guarded by ``_cleaned_up`` so it is safe to call multiple times
        (e.g. from ``action_quit`` and ``on_unmount``).
        """
        if self._cleaned_up:
            return
        self._cleaned_up = True
        await self._orchestrator.stop_all(self.all_services)
        await self._orchestrator.cleanup()

    async def on_unmount(self) -> None:
        """Ensure cleanup runs even if the app crashes or is force-closed."""
        await self._cleanup()
