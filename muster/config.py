"""Configuration loader for muster.

Handles parsing of ``muster-compose.yaml`` into typed dataclasses, including
backwards-compatible conversion of legacy keys such as ``layer`` → ``group``
and the top-level ``cmd_test`` shorthand.
"""

from pathlib import Path
from typing import List, Tuple

import yaml

from .models import EnvCheck, Group, MusterConfig, PortDiscovery, Service

DEFAULT_STATUS_COLORS = {
    "stopped": "#6e7681",
    "starting": "#dcdcaa",
    "running": "#4ec9b0",
    "failed": "#f44747",
}

DEFAULT_GROUPS = [
    Group(id="domain", label="DOMAIN", color="#569cd6", order=0),
    Group(id="aggregation", label="AGGREGATION", color="#c586c0", order=1),
    Group(id="api", label="API", color="#ce9178", order=2),
]

DEFAULT_ENV_CHECKS = [
    EnvCheck(name="etcd", type="tcp", host="127.0.0.1", port=2379),
    EnvCheck(name="mysql", type="tcp", host="127.0.0.1", port=3306),
    EnvCheck(name="redis", type="tcp", host="127.0.0.1", port=6379),
]

DEFAULT_PORT_DISCOVERY = PortDiscovery(
    enabled=False,
    rules=[
        {"regex": r"^\s*ListenOn:\s*.*:(\d+)\s*$"},
        {"regex": r"^\s*Port:\s*(\d+)\s*$"},
    ],
)


def load_config(yaml_path: Path) -> Tuple[MusterConfig, List[Service]]:
    """Load muster configuration and service registry from a YAML file.

    Args:
        yaml_path: Path to the ``muster-compose.yaml`` file.

    Returns:
        A tuple of ``(MusterConfig, list[Service])``.

    Raises:
        FileNotFoundError: If ``yaml_path`` does not exist.
    """
    if not yaml_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {yaml_path}")

    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    config_data = data.get("config", {})

    # env_checks
    raw_env_checks = config_data.get("env_checks")
    if raw_env_checks:
        env_checks = [EnvCheck(**item) for item in raw_env_checks]
    else:
        env_checks = [EnvCheck(**ec.__dict__) for ec in DEFAULT_ENV_CHECKS]

    # groups
    raw_groups = config_data.get("groups")
    if raw_groups:
        groups = [Group(**item) for item in raw_groups]
    else:
        groups = [Group(**g.__dict__) for g in DEFAULT_GROUPS]

    # port_discovery
    raw_pd = config_data.get("port_discovery", {})
    if raw_pd.get("enabled", False):
        port_discovery = PortDiscovery(
            enabled=True,
            config_dir=raw_pd.get("config_dir", "etc"),
            config_pattern=raw_pd.get("config_pattern", "*.yaml"),
            exclude_pattern=raw_pd.get(
                "exclude_pattern", DEFAULT_PORT_DISCOVERY.exclude_pattern
            ),
            rules=raw_pd.get("rules", [r.copy() for r in DEFAULT_PORT_DISCOVERY.rules]),
        )
    else:
        port_discovery = PortDiscovery(enabled=False)

    config = MusterConfig(
        env_checks=env_checks,
        groups=groups,
        port_discovery=port_discovery,
    )

    # services (backward-compat: accept "layer" as alias for "group")
    services: List[Service] = []
    for item in data.get("services", []):
        group_id = item.get("group") or item.get("layer", "")
        # backward-compat: "cmd_test" top-level key -> merge into cmd dict
        cmd = item.get("cmd", "")
        if isinstance(cmd, str) and "cmd_test" in item:
            cmd = {"default": cmd, "test": item["cmd_test"]}
        services.append(
            Service(
                name=item["name"],
                cmd=cmd,
                group=group_id,
                port=item.get("port"),
                depends_on=item.get("depends_on", []),
            )
        )

    return config, services
