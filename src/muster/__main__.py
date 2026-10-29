"""Entry point: ``python -m muster``.

Parses CLI arguments, loads the YAML configuration, resolves ports, and
launches the Textual TUI.
"""

import argparse
import sys
from pathlib import Path

from .app import MusterApp
from .config import load_config
from .core.procfile import parse_procfile, procfile_to_compose
from .core.resolver import resolve_port
from .core.validator import ConfigError, validate_config


def main() -> None:
    """Parse arguments and run the Muster TUI."""
    if len(sys.argv) > 1 and sys.argv[1] == "import":
        _run_import(sys.argv[2:])
        return
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
    except FileNotFoundError:
        print(
            f"muster: config file not found: {yaml_path}\n"
            f"\n"
            f"  Create one with:\n"
            f"    cp example/muster-compose.yaml ./{yaml_path.name}\n"
            f"\n"
            f"  Or specify a different file:\n"
            f"    muster -f <path>\n",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        warnings = validate_config(config, services)
        for w in warnings:
            print(f"muster: warning: {w}", file=sys.stderr)
    except ConfigError as exc:
        print(f"muster: config error: {exc}", file=sys.stderr)
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


def _run_import(argv: list[str]) -> None:
    """Convert a foreman-style Procfile into a muster-compose.yaml."""
    parser = argparse.ArgumentParser(
        prog="muster import",
        description="Convert a Procfile into a muster-compose.yaml",
    )
    parser.add_argument(
        "procfile", nargs="?", default="Procfile", help="Path to Procfile"
    )
    parser.add_argument(
        "-o",
        "--out",
        default="muster-compose.yaml",
        help="Output path (default: muster-compose.yaml)",
    )
    parser.add_argument(
        "--force", action="store_true", help="Overwrite an existing output file"
    )
    args = parser.parse_args(argv)

    procfile = Path(args.procfile)
    out = Path(args.out)
    try:
        services = parse_procfile(procfile.read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"muster: cannot read {procfile}: {exc}", file=sys.stderr)
        sys.exit(1)
    except ValueError as exc:
        print(f"muster: {exc}", file=sys.stderr)
        sys.exit(1)

    if out.exists() and not args.force:
        print(
            f"muster: {out} already exists (use --force to overwrite)",
            file=sys.stderr,
        )
        sys.exit(1)

    out.write_text(procfile_to_compose(services), encoding="utf-8")
    print(
        f"muster: imported {len(services)} service(s) "
        f"from {procfile} -> {out}\n"
        f"  Ports are not inferred — run `muster -f {out}` and add"
        " `port:`/`healthcheck:` entries as needed."
    )


if __name__ == "__main__":
    main()
