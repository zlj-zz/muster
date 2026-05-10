# Getting Started

## Installation

muster requires **Python 3.10 or later**. Install via the one-liner:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/zlj-zz/muster/main/install.sh)"
```

Or clone and install manually:

```bash
git clone https://github.com/zlj-zz/muster.git
cd muster
pip install -e .
```

## Quick Start

Create a `muster-compose.yaml` in your project root:

```yaml
config:
  groups:
    - id: backend
      label: BACKEND
      color: "#569cd6"
      order: 0
    - id: frontend
      label: FRONTEND
      color: "#ce9178"
      order: 1

  env_checks:
    - name: postgres
      type: tcp
      host: 127.0.0.1
      port: 5432

services:
  - name: api
    cmd:
      default: "cd api && go run main.go"
      test: "cd api && go run main.go -f etc/test.yaml"
    group: backend
    port: 8080
    depends_on: []

  - name: web
    cmd: "cd web && npm run dev"
    group: frontend
    port: 3000
    depends_on: [api]
```

Then run:

```bash
muster
```

## Command Modes

Each service can define multiple command variants:

```yaml
services:
  - name: api
    cmd:
      default: "go run main.go"
      test: "go run main.go -f test.yaml"
      prod: "go run main.go -f prod.yaml"
```

- Press `t` in TUI to cycle through modes shared by all services
- Or start with a specific mode: `muster -m test`
- Services without a given mode fall back to their `default` command

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `↑` / `↓` or `k` / `j` | Navigate services |
| `Enter` | Start / stop selected service |
| `R` | Restart selected service |
| `ctrl+s` | Stop all services |
| `r` | Refresh environment status |
| `t` | Cycle command mode |
| `l` | Cycle group filter |
| `1` / `2` / `3` | Switch to Svc / Env / Yaml tab |
| `ctrl+q` | Quit |

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest -q

# Run tests with coverage
pytest -q --cov=muster --cov-report=term
```
