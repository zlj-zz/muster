"""Procfile import: convert a foreman-style Procfile into muster-compose.yaml.

Grammar: one ``name: command`` pair per line; blank lines and ``#`` comments
are ignored. Ports are intentionally not inferred — imported services rely
on the liveness readiness heuristic unless ports are added manually.
"""

from __future__ import annotations

import yaml

#: Group id assigned to every imported service.
PROCFILE_GROUP = "default"


def parse_procfile(text: str) -> dict[str, str]:
    """Parse Procfile content into an ordered name → command mapping.

    Args:
        text: Raw Procfile content.

    Returns:
        Mapping of service name to command string, in declaration order.

    Raises:
        ValueError: If a non-empty line lacks the ``name: command`` shape,
            or the file defines no services.
    """
    services: dict[str, str] = {}
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, command = line.partition(":")
        if not sep or not name.strip() or not command.strip():
            raise ValueError(f"Procfile line {line_no}: expected 'name: command'")
        services[name.strip()] = command.strip()
    if not services:
        raise ValueError("Procfile defines no services")
    return services


def procfile_to_compose(services: dict[str, str]) -> str:
    """Render a muster-compose.yaml document from Procfile services.

    Args:
        services: Ordered name → command mapping (from :func:`parse_procfile`).

    Returns:
        YAML text with a single ``default`` group and one service per entry.
    """
    doc = {
        "config": {
            "groups": [
                {
                    "id": PROCFILE_GROUP,
                    "label": "DEFAULT",
                    "color": "#569cd6",
                    "order": 0,
                }
            ]
        },
        "services": [
            {"name": name, "cmd": cmd, "group": PROCFILE_GROUP}
            for name, cmd in services.items()
        ],
    }
    return yaml.safe_dump(doc, sort_keys=False, default_flow_style=False)
