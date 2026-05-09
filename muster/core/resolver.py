"""Dependency resolution and port discovery.

Provides a depth-first-search (DFS) topological sort for service dependencies
and regex-based port extraction from per-service YAML configuration files.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..models import Group, PortDiscovery, Service


def resolve_dependencies(
    target_names: list[str], registry: dict[str, Service]
) -> list[Service]:
    """Topologically sort services via DFS dependency resolution.

    Traverses the dependency graph starting from ``target_names``, visiting
    each dependency recursively. The resulting list is ordered so that every
    service appears *after* its dependencies.

    Args:
        target_names: Names of the services to start from.
        registry: Mapping from service name to ``Service`` instance.

    Returns:
        A list of ``Service`` objects in dependency-first order.

    Raises:
        ValueError: If a circular dependency is detected.
    """
    visited: set[str] = set()
    result: list[Service] = []

    def dfs(name: str, path: set[str]) -> None:
        """Recursive DFS helper.

        Args:
            name: Current service name being visited.
            path: Set of names currently on the recursion stack; used to detect
                cycles.

        Raises:
            ValueError: When a cycle is detected.
        """
        if name in path:
            raise ValueError(f"circular dependency: {' -> '.join(path)} -> {name}")
        if name in visited:
            return
        if name not in registry:
            return
        visited.add(name)
        svc = registry[name]
        for dep in svc.depends_on:
            dfs(dep, path | {name})
        result.append(svc)

    for target in target_names:
        dfs(target, set())

    return result


def sort_by_group(services: list[Service], groups: list[Group]) -> list[Service]:
    """Sort services by their group's ``order`` field.

    Args:
        services: Services to reorder.
        groups: Group definitions carrying ``order`` values.

    Returns:
        Services sorted by group order, then by insertion order within the group.
    """
    order_map = {g.id: g.order for g in groups}
    return sorted(services, key=lambda s: order_map.get(s.group, 999))


def resolve_port(svc_name: str, discovery: PortDiscovery) -> int | None:
    """Auto-discover a service's listening port from its configuration files.

    Scans ``<svc_name>/etc/*.yaml`` (excluding environment-specific files) and
    applies the regex rules defined in ``discovery`` until the first match.

    Args:
        svc_name: Directory name of the service.
        discovery: Port discovery rules and settings.

    Returns:
        The discovered port number, or ``None`` if no match is found.
    """
    if not discovery.enabled:
        return None

    cfg_dir = Path(svc_name) / discovery.config_dir
    if not cfg_dir.exists():
        return None

    yaml_file: Path | None = None
    # Pick the first non-excluded YAML file alphabetically.
    for f in sorted(cfg_dir.glob(discovery.config_pattern)):
        if re.search(discovery.exclude_pattern, str(f)):
            continue
        yaml_file = f
        break
    if not yaml_file:
        return None

    content = yaml_file.read_text(encoding="utf-8")
    for rule in discovery.rules:
        pattern = rule.get("regex", "")
        if not pattern:
            continue
        m = re.search(pattern, content, re.MULTILINE)
        if m:
            return int(m.group(1))
    return None
