"""Core data models for muster.

This module defines the domain objects used throughout the application,
including service definitions, configuration structures, and runtime state.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Union


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
    host: Optional[str] = None
    port: Optional[int] = None
    url: Optional[str] = None
    method: Optional[str] = None
    expect_status: Optional[int] = None
    pattern: Optional[str] = None


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
    rules: List[Dict[str, str]] = field(default_factory=list)


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
    cmd: Union[str, Dict[str, str]]
    group: str
    port: Optional[int] = None
    depends_on: List[str] = field(default_factory=list)

    # runtime state
    status: Status = Status.STOPPED
    proc: Optional[asyncio.subprocess.Process] = None
    log_lines: List[str] = field(default_factory=list)

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
    def cmd_modes(self) -> List[str]:
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

    env_checks: List[EnvCheck]
    groups: List[Group]
    port_discovery: PortDiscovery
    status_colors: Dict[str, str] = field(
        default_factory=lambda: {
            "stopped": "#6e7681",
            "starting": "#dcdcaa",
            "running": "#4ec9b0",
            "failed": "#f44747",
        }
    )
