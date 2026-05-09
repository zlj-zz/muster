"""Entry point: ``python -m muster``.

Parses CLI arguments, loads the YAML configuration, resolves ports, and
launches the Textual TUI.
"""

import argparse
import sys
from pathlib import Path

from .app import MusterApp
from .config import load_config
from .core.resolver import resolve_port


def main() -> None:
    """Parse arguments and run the Muster TUI."""
    parser = argparse.ArgumentParser(description="muster — TUI service orchestrator")
    parser.add_argument(
        "-f",
        "--file",
        default="muster-compose.yaml",
        help="Path to config file (default: muster-compose.yaml)",
    )
    parser.add_argument(
        "-m",
        "--mode",
        default="default",
        help="Default command mode (default: default)",
    )
    args = parser.parse_args()

    yaml_path = Path(args.file)
    try:
        config, services = load_config(yaml_path)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Auto-resolve ports if port_discovery is enabled in the config.
    for svc in services:
        if svc.port is None:
            svc.port = resolve_port(svc.name, config.port_discovery)

    registry = {svc.name: svc for svc in services}
    app = MusterApp(
        config=config,
        services=services,
        registry=registry,
        config_path=yaml_path,
        cmd_mode=args.mode,
    )
    app.run()


if __name__ == "__main__":
    main()
