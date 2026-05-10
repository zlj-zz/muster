"""Configuration validation for muster-compose.yaml.

Performs fail-fast checks before the TUI starts so that structural
errors (cycles, missing groups, duplicate names, etc.) are reported
with clear messages instead of surfacing at runtime.
"""

from __future__ import annotations

from collections import defaultdict

from ..models import EnvCheck, MusterConfig, Service
from .resolver import resolve_dependencies


class ConfigError(ValueError):
    """Raised when the configuration contains a fatal validation error."""


# Mapping from env-check type to the attribute name that must be present.
_ENV_CHECK_FIELDS = {
    "tcp": "port",
    "http": "url",
    "proc": "pattern",
}


def validate_config(config: MusterConfig, services: list[Service]) -> list[str]:
    """Validate a loaded configuration.

    Fatal problems raise :class:`ConfigError` with a descriptive message.
    Non-fatal problems are returned as a list of warning strings.

    Args:
        config: The parsed top-level configuration.
        services: All services defined in the YAML.

    Returns:
        List of warning strings (e.g. port conflicts).
    """
    warnings: list[str] = []

    _validate_name_uniqueness(services)
    registry = {s.name: s for s in services}
    _validate_cmds(services)
    _validate_groups(services, config)
    _validate_dependencies(services, registry)
    _validate_cycles(registry)
    warnings.extend(_validate_ports(services))
    warnings.extend(_validate_env_checks(config.env_checks))

    return warnings


def _validate_name_uniqueness(services: list[Service]) -> None:
    seen: set[str] = set()
    for svc in services:
        if svc.name in seen:
            raise ConfigError(f"duplicate service name: {svc.name!r}")
        seen.add(svc.name)


def _validate_cmds(services: list[Service]) -> None:
    for svc in services:
        if isinstance(svc.cmd, dict):
            if not svc.cmd:
                raise ConfigError(
                    f"service {svc.name!r}: cmd dict must not be empty"
                )
            for mode, cmd in svc.cmd.items():
                if not cmd or not cmd.strip():
                    raise ConfigError(
                        f"service {svc.name!r}: cmd for mode {mode!r} is empty"
                    )
        elif not svc.cmd or not svc.cmd.strip():
            raise ConfigError(f"service {svc.name!r}: cmd is empty")


def _validate_groups(services: list[Service], config: MusterConfig) -> None:
    valid_groups = {g.id for g in config.groups}
    for svc in services:
        if svc.group not in valid_groups:
            raise ConfigError(
                f"service {svc.name!r}: group {svc.group!r} is not defined"
            )


def _validate_dependencies(
    services: list[Service], registry: dict[str, Service]
) -> None:
    for svc in services:
        for dep in svc.depends_on:
            if dep not in registry:
                raise ConfigError(
                    f"service {svc.name!r}: depends_on {dep!r} does not exist"
                )


def _validate_cycles(registry: dict[str, Service]) -> None:
    try:
        resolve_dependencies(list(registry.keys()), registry)
    except ValueError as exc:
        raise ConfigError(f"dependency error: {exc}") from exc


def _validate_ports(services: list[Service]) -> list[str]:
    warnings: list[str] = []
    port_names: dict[int, list[str]] = defaultdict(list)

    for svc in services:
        if svc.port is None:
            continue
        if not isinstance(svc.port, int) or not (1 <= svc.port <= 65535):
            raise ConfigError(
                f"service {svc.name!r}: port {svc.port!r} is out of range (1-65535)"
            )
        port_names[svc.port].append(svc.name)

    for port, names in port_names.items():
        if len(names) > 1:
            warnings.append(
                f"port {port} is declared by multiple services: {', '.join(names)}"
            )

    return warnings


def _validate_env_checks(env_checks: list[EnvCheck]) -> list[str]:
    warnings: list[str] = []
    valid_types = set(_ENV_CHECK_FIELDS)

    for check in env_checks:
        if check.type not in valid_types:
            warnings.append(
                f"env check {check.name!r}: unknown type {check.type!r} "
                f"(expected tcp, http, or proc)"
            )
            continue

        required_field = _ENV_CHECK_FIELDS[check.type]
        if getattr(check, required_field) in (None, ""):
            raise ConfigError(
                f"env check {check.name!r} ({check.type}): "
                f"{required_field} is required"
            )

    return warnings
