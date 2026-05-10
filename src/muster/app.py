"""Main Textual App for muster.

``MusterApp`` is the root TUI application.  It owns the layout, keyboard
bindings, and widget coordination, but delegates all process lifecycle work to
``ServiceOrchestrator``.
"""

from __future__ import annotations

import asyncio
import glob
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import ContentSwitcher, Static

from .core.env import check_env
from .core.orchestrator import ServiceOrchestrator
from .core.settings_store import apply_to_app, load_settings
from .models import Group, MusterConfig, Service, Status
from .widgets import (
    ActivityBar,
    ActivityTab,
    DetailPanel,
    EnvDetailPanel,
    EnvIndicator,
    EnvList,
    FileList,
    LogPanel,
    ServiceTree,
    SettingsPanel,
    YamlPreview,
)


class MusterApp(App):
    """TUI service orchestrator with Activity Bar layout.

    Manages the three-column layout (activity bar, left panel, right panel)
    and forwards user actions to ``ServiceOrchestrator``.

    Attributes:
        all_services: Full list of services loaded from config.
        registry: Name-to-service lookup map.
        cmd_mode: Currently active command mode (e.g. ``"default"``).
    """

    CSS_PATH = "app.tcss"
    SHOW_HEADER = False
    SHOW_FOOTER = False
    TOOLTIP_DELAY = 0.15

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+s", "stop_all", "Stop All"),
        Binding("r", "refresh_env", "Refresh Env"),
        Binding("enter", "toggle_service", "Toggle"),
        Binding("R", "restart_service", "Restart"),
        Binding("t", "cycle_cmd_mode", "Mode"),
        Binding("l", "cycle_group", "Filter Group"),
        Binding("1", "switch_tab('svc')", "Svc", show=False),
        Binding("2", "switch_tab('env')", "Env", show=False),
        Binding("3", "switch_tab('yaml')", "Yaml", show=False),
        Binding("4", "switch_tab('settings')", "Settings", show=False),
        Binding("j,down", "cursor_down", "Down", show=False),
        Binding("k,up", "cursor_up", "Up", show=False),
    ]

    def __init__(
        self,
        config: MusterConfig,
        services: list[Service],
        registry: dict[str, Service],
        config_path: Path | None = None,
        cmd_mode: str = "default",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._muster_config = config
        self.all_services = services
        self.registry = registry
        self._config_path = config_path
        self.cmd_mode = cmd_mode
        self._group_filter: str | None = None
        self._cleaned_up = False
        self._orchestrator = ServiceOrchestrator(
            config,
            registry,
            on_log=self._safe_append_log,
            on_status=self._refresh_list_item,
            on_notify=lambda msg, sev: self.notify(msg, severity=sev),
        )
        self._settings = load_settings()
        self._env_timer = None
        self._yaml_files = self._scan_yaml_files()
        self._stop_pending = False

    def _scan_yaml_files(self) -> list[str]:
        """Scan for YAML files in the config directory."""
        if self._config_path is None:
            return []
        yaml_dir = self._config_path.parent
        files = sorted(glob.glob(str(yaml_dir / "*.yaml")))
        return [Path(f).name for f in files]

    @property
    def _common_cmd_modes(self) -> list[str]:
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
        with Vertical(id="main"):
            with Horizontal(id="body"):
                yield ActivityBar(id="activity-bar")

                with ContentSwitcher(initial="left-svc", id="left-content"):
                    with Vertical(id="left-svc"):
                        yield ServiceTree(
                            self._filtered_services(),
                            self._muster_config.groups,
                            self._muster_config.status_colors,
                            id="service-tree",
                        )
                        yield EnvIndicator(self._muster_config, id="env-indicator")
                    with Vertical(id="left-env"):
                        yield EnvList(self._muster_config, id="env-list")
                    with Vertical(id="left-yaml"):
                        yield FileList(self._yaml_files, id="file-list")
                    with Vertical(id="left-settings"):
                        yield Static("")

                with ContentSwitcher(initial="right-svc", id="right-content"):
                    with Vertical(id="right-svc"):
                        yield DetailPanel(
                            self._muster_config.groups,
                            self._muster_config.status_colors,
                            id="detail",
                        )
                        yield LogPanel(id="log")
                    yield EnvDetailPanel(id="right-env")
                    yield YamlPreview(id="right-yaml")
                    yield SettingsPanel(self._settings, id="right-settings")

            # Custom footer bar with shortcut hints and mode badge
            with Horizontal(id="footer-bar"):
                yield Static(self._footer_text(), id="footer-keys")
                yield Static(self._mode_label(), id="footer-mode")

    def _footer_text(self) -> str:
        """Build the footer shortcut hint text with Rich markup."""
        return (
            "[#eab459]^q[/] quit  "
            "[#eab459]^s[/] stop-all  "
            "[#eab459]r[/] refresh  "
            "[#eab459]enter[/] toggle  "
            "[#eab459]R[/] restart  "
            "[#eab459]t[/] mode  "
            "[#eab459]l[/] filter"
        )

    def on_mount(self) -> None:
        """Initialise the UI after widgets are mounted.

        Auto-selects the first item in each tab so that panels are
        never empty on startup.
        """
        self.title = "muster"
        self._refresh_env_status()
        self._env_timer = self.set_interval(
            self._settings.env_refresh_interval, self._refresh_env_status
        )
        apply_to_app(self, self._settings)

        # svc tab: auto-select first service
        tree = self.query_one("#service-tree", ServiceTree)
        if tree.services:
            for group_node in tree.root.children:
                if group_node.children:
                    svc = group_node.children[0].data
                    if isinstance(svc, Service):
                        tree.highlight_service(svc.name)
                    break
        self._update_detail()

        # env tab: auto-select first env check
        env_list = self.query_one("#env-list", EnvList)
        if env_list.root.children:
            env_list.select_node(env_list.root.children[0])
            self._update_env_detail()

        # yaml tab: auto-select first file
        file_list = self.query_one("#file-list", FileList)
        if file_list.root.children:
            file_list.select_node(file_list.root.children[0])
            self._update_yaml_preview()

    def _mode_label(self) -> str:
        """Build the subtitle string shown in the mode badge.

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
        from textual.css.query import NoMatches

        try:
            self.query_one("#log", LogPanel).append_log(svc_name, line)
        except NoMatches:
            pass

    def _filtered_services(self) -> list[Service]:
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
        from textual.css.query import NoMatches

        try:
            tree = self.query_one("#service-tree", ServiceTree)
            svc = tree.current_service
            self.query_one("#detail", DetailPanel).current_service = svc
            try:
                self.query_one("#log", LogPanel).set_service(svc)
            except NoMatches:
                pass
        except NoMatches:
            pass

    def _update_env_detail(self) -> None:
        """Synchronise EnvDetailPanel with the current env list selection."""
        from textual.css.query import NoMatches

        try:
            env_list = self.query_one("#env-list", EnvList)
            env = env_list.current_env
            self.query_one("#right-env", EnvDetailPanel).current_env = env
        except NoMatches:
            pass

    def _update_yaml_preview(self) -> None:
        """Synchronise YamlPreview with the current file list selection."""
        from textual.css.query import NoMatches

        try:
            file_list = self.query_one("#file-list", FileList)
            file_path = file_list.current_file
            if file_path and self._config_path:
                full_path = str(self._config_path.parent / file_path)
                self.query_one("#right-yaml", YamlPreview).current_file = full_path
            else:
                self.query_one("#right-yaml", YamlPreview).current_file = None
        except NoMatches:
            pass

    def _refresh_env_status(self) -> None:
        """Poll environment checks and refresh all indicators."""
        from textual.css.query import NoMatches

        try:
            results = check_env(self._muster_config.env_checks)
        except (OSError, RuntimeError, AttributeError) as e:
            self.log.error(f"env check failed: {e}")
            return

        try:
            self.query_one("#env-indicator", EnvIndicator).refresh_indicators(results)
            self.query_one("#env-list", EnvList).refresh_checks(results)
            detail = self.query_one("#right-env", EnvDetailPanel)
            if detail.current_env is not None:
                detail.refresh_content()
            self.query_one("#footer-mode", Static).update(self._mode_label())
        except NoMatches:
            pass

    def _refresh_list_item(self, svc: Service) -> None:
        """Refresh a single service node in the tree and detail panel.

        Called by ``ServiceOrchestrator`` whenever a service's status changes.

        Args:
            svc: Service whose visual representation should be refreshed.
        """
        from textual.css.query import NoMatches

        try:
            tree = self.query_one("#service-tree", ServiceTree)
            tree.refresh_node(svc)
            detail = self.query_one("#detail", DetailPanel)
            if detail.current_service is svc:
                detail.refresh_content()
        except (NoMatches, AttributeError):
            pass

    # ---------- event handlers ----------

    def on_activity_tab_tab_clicked(self, event: ActivityTab.TabClicked) -> None:
        """Switch tabs when an activity bar tab is clicked."""
        self.action_switch_tab(event.tab_id)

    def on_service_tree_service_highlighted(
        self, event: ServiceTree.ServiceHighlighted
    ) -> None:
        """Update detail/log panels when the user highlights a new service."""
        self._update_detail()

    def on_env_list_env_highlighted(self, event: EnvList.EnvHighlighted) -> None:
        """Update env detail panel when the user highlights a new env check."""
        self._update_env_detail()

    def on_file_list_file_highlighted(self, event: FileList.FileHighlighted) -> None:
        """Update yaml preview when the user highlights a new file."""
        self._update_yaml_preview()

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

    def on_settings_panel_settings_changed(
        self, event: SettingsPanel.SettingsChanged
    ) -> None:
        """Apply new settings and persist them."""
        from .core.settings_store import save_settings

        if event.settings == self._settings:
            return
        self._settings = event.settings
        apply_to_app(self, self._settings)
        save_settings(self._settings)
        self.notify("Settings saved", severity="success")

    # ---------- actions ----------

    def action_switch_tab(self, tab: str) -> None:
        """Switch to the specified activity tab."""
        # Update activity bar visual state
        activity_bar = self.query_one("#activity-bar", ActivityBar)
        activity_bar.active_tab = tab

        # Update left and right content switchers
        left = self.query_one("#left-content", ContentSwitcher)
        right = self.query_one("#right-content", ContentSwitcher)
        left.current = f"left-{tab}"
        right.current = f"right-{tab}"

        # Settings uses a single full-width panel; hide the left column.
        left.styles.display = "none" if tab == "settings" else "block"

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

    def action_stop_all(self) -> None:
        """Stop every service across all groups (double-tap confirmation).

        First press shows a warning toast; press again within 5 seconds
        to confirm and stop all running services.
        """
        running = [s for s in self.all_services if s.status != Status.STOPPED]
        if not running:
            self.notify("No services are running", severity="information")
            return

        if self._stop_pending:
            self._stop_pending = False
            for svc in running:
                asyncio.create_task(self._orchestrator.stop(svc))
            self.notify("Stopping all services...", severity="information")
            return

        self._stop_pending = True
        self.notify(
            f"Press [b]^s[/b] again to stop {len(running)} service(s)",
            severity="warning",
            timeout=5,
        )
        self.set_timer(5, self._reset_stop_pending)

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

    def _reset_stop_pending(self) -> None:
        """Cancel the pending stop-all confirmation after timeout."""
        self._stop_pending = False

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
