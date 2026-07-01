"""Core data models for muster.

This module defines the domain objects used throughout the application,
including service definitions, configuration structures, and runtime state.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Status(Enum):
    """Lifecycle states of a managed service process."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    FAILED = "failed"


@dataclass
class Group:
    """A logical grouping for services, rendered as a tree branch.

    Replaces the earlier hard-coded ``Layer`` enum with fully configurable
    groups defined in ``muster-compose.yaml``.

    Attributes:
        id: Machine identifier used in YAML (e.g. ``domain``).
        label: Human-readable label shown in the UI (e.g. ``DOMAIN``).
        color: Hex colour for the group header in the service tree.
        order: Sorting priority; lower values appear first.
    """

    id: str
    label: str
    color: str
    order: int


@dataclass
class EnvCheck:
    """A single external dependency check (TCP port, HTTP endpoint, or process).

    Attributes:
        name: Display name (e.g. ``mysql``).
        type: Kind of check: ``tcp``, ``http``, or ``proc``.
        host: Target host; defaults to ``127.0.0.1`` for TCP checks.
        port: Target port for TCP checks.
        url: Full URL for HTTP checks.
        method: HTTP method (default ``GET``).
        expect_status: Expected HTTP status code.
        pattern: Regex pattern for process-name matching (``proc`` type).
    """

    name: str
    type: str  # tcp | http | proc
    host: str | None = None
    port: int | None = None
    url: str | None = None
    method: str | None = None
    expect_status: int | None = None
    pattern: str | None = None

    # runtime state
    last_checked: datetime | None = None
    latency_ms: int | None = None
    consecutive_failures: int = 0
    history: deque[bool] = field(default_factory=lambda: deque(maxlen=30))
    latency_history: deque[int | None] = field(
        default_factory=lambda: deque(maxlen=720)
    )


@dataclass
class PortDiscovery:
    """Configuration for auto-discovering service ports from config files.

    When enabled, ``muster`` scans each service's ``etc/`` directory for YAML
    files and applies the configured regex rules to extract the listening port.

    Attributes:
        enabled: Whether discovery is active.
        config_dir: Sub-directory inside each service to scan (default ``etc``).
        config_pattern: Glob for matching config files (default ``*.yaml``).
        exclude_pattern: Regex for files to skip (e.g. environment-specific).
        rules: Ordered list of regex dicts; the first match wins.
    """

    enabled: bool = False
    config_dir: str = "etc"
    config_pattern: str = "*.yaml"
    exclude_pattern: str = r"_(test|prod|pre)\.yaml$"
    rules: list[dict[str, str]] = field(default_factory=list)


@dataclass
class Service:
    """A single runnable service.

    ``cmd`` supports two shapes for convenience:
      * A plain ``str`` — shorthand for ``{"default": "..."}``.
      * A ``dict[str, str]`` — mapping mode names to commands.

    Attributes:
        name: Unique service identifier.
        cmd: Command string or mode-to-command mapping.
        group: Group ``id`` this service belongs to.
        port: Statically configured port (overrides auto-discovery).
        depends_on: Names of services that must start before this one.
        status: Current runtime state (defaults to ``Status.STOPPED``).
        proc: Active ``asyncio`` subprocess handle.
        log_lines: Ring-buffer of the most recent log lines.
    """

    name: str
    cmd: str | dict[str, str]
    group: str
    port: int | None = None
    depends_on: list[str] = field(default_factory=list)

    # runtime state
    status: Status = Status.STOPPED
    proc: asyncio.subprocess.Process | None = None
    log_lines: deque[str] = field(default_factory=lambda: deque(maxlen=2000))
    start_time: datetime | None = None
    restart_count: int = 0
    last_error: str | None = None
    _ready_event: asyncio.Event = field(
        default_factory=asyncio.Event, repr=False, compare=False
    )

    def cmd_for(self, mode: str) -> str:
        """Return the command string for the given mode.

        Falls back to the ``default`` key when the requested mode is absent.

        Args:
            mode: Mode name (e.g. ``"default"``, ``"test"``).

        Returns:
            The shell command, or an empty string if none is configured.
        """
        if isinstance(self.cmd, dict):
            return self.cmd.get(mode, self.cmd.get("default", ""))
        return self.cmd

    @property
    def cmd_modes(self) -> list[str]:
        """Return all available command mode names.

        Returns:
            A list of mode keys when ``cmd`` is a dict, otherwise ``["default"]``.
        """
        if isinstance(self.cmd, dict):
            return list(self.cmd.keys())
        return ["default"]


@dataclass
class MusterConfig:
    """Top-level configuration loaded from ``muster-compose.yaml``.

    Attributes:
        status_colors: Mapping from status value to hex colour.  Defaults to
            the built-in TRAE palette and cannot be overridden via YAML.
        env_checks: List of environment checks shown in the status bar.
        groups: Ordered list of service groups.
        port_discovery: Rules for automatic port extraction.
    """

    env_checks: list[EnvCheck]
    groups: list[Group]
    port_discovery: PortDiscovery
    status_colors: dict[str, str] = field(
        default_factory=lambda: {
            "stopped": "#5c6370",
            "starting": "#e5c07b",
            "running": "#98c379",
            "failed": "#e06c75",
        }
    )


@dataclass
class AppSettings:
    """User-level runtime preferences persisted across sessions.

    These settings control behaviour, timeouts, and display preferences.
    They are independent of project-level configuration in
    ``muster-compose.yaml``.

    Attributes:
        env_refresh_interval: Seconds between environment check polls.
        port_conflict_strategy: How to handle a port already in use
            (``"kill"``, ``"warn"``, ``"abort"``).
        log_auto_scroll: Whether the log panel should scroll to the bottom
            on every new line.
        log_show_timestamp: Whether to prefix each log line with a timestamp.
        log_default_level: Default log-level filter (``"ALL"``, ``"ERROR"``,
            ``"WARN"``, ``"INFO"``).
        log_buffer_lines: Maximum number of log lines to keep in memory.
        health_timeout: Seconds to wait for a single service port to become ready.
        layer_timeout: Seconds to wait for an entire dependency layer to become ready.
        stop_timeout: Seconds to wait for graceful shutdown before SIGKILL.
    """

    env_refresh_interval: int = 5
    port_conflict_strategy: str = "kill"
    log_auto_scroll: bool = True
    log_show_timestamp: bool = False
    log_wrap: bool = True
    log_default_level: str = "ALL"
    log_buffer_lines: int = 2000
    load_history_on_startup: bool = False
    health_timeout: int = 120
    layer_timeout: int = 120
    stop_timeout: float = 8.0
