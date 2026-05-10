# muster

[![Coverage](https://codecov.io/gh/zlj-zz/muster/branch/main/graph/badge.svg)](https://codecov.io/gh/zlj-zz/muster)

A TUI-based service orchestrator for local development. Think of it as a mini dashboard for starting, stopping, and monitoring all the services in your project — directly in the terminal.

<img width="978" alt="Image" src="https://github.com/user-attachments/assets/da43f353-be93-4183-b746-d2d551f8b8c6" />

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/zlj-zz/muster/main/install.sh)"
muster -f muster-compose.yaml
```

## Features

- **Tree view** — services grouped by configurable categories (e.g., domain / aggregation / api)
- **Dependency-aware startup** — auto-resolves and starts dependencies in the correct order
- **Real-time logs** — per-service logs with auto-scroll and copy support
- **Health checks** — TCP, HTTP, and process checks with latency measurement
- **Environment monitoring** — live indicators for etcd, MySQL, Redis, or any custom dependency
- **Multiple command modes** — each service can define `default`, `test`, `prod`, or any custom command map
- **Port auto-discovery** — extract listening ports from your service config files

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

## Configuration Reference

See [`example/muster-compose.yaml`](example/muster-compose.yaml) for a full-featured example.

### `config.groups`

Define service groups. Each group gets its own section in the tree view.

| Field | Description |
|-------|-------------|
| `id` | Unique identifier (referenced by services) |
| `label` | Display name in the UI |
| `color` | Hex color for group heading and detail panel |
| `order` | Sort order (ascending) |

### `config.env_checks`

Define environment dependencies to monitor in the top status bar.

| Field | Description | Applies to |
|-------|-------------|------------|
| `name` | Display name | all |
| `type` | `tcp`, `http`, or `proc` | all |
| `host` | TCP host (default: `127.0.0.1`) | `tcp` |
| `port` | TCP port | `tcp` |
| `url` | Full URL to request | `http` |
| `method` | HTTP method (default: `GET`) | `http` |
| `expect_status` | Expected HTTP status code (default: `200`) | `http` |
| `pattern` | Regex pattern matched against process names | `proc` |

**TCP example:**

```yaml
env_checks:
  - name: postgres
    type: tcp
    host: 127.0.0.1
    port: 5432
```

**HTTP example:**

```yaml
env_checks:
  - name: api-health
    type: http
    url: http://127.0.0.1:8080/health
    method: GET
    expect_status: 200
```

**Process example:**

```yaml
env_checks:
  - name: nginx
    type: proc
    pattern: nginx
```

### `config.port_discovery`

Enable automatic port extraction from service config files.

| Field | Description |
|-------|-------------|
| `enabled` | Toggle auto-discovery |
| `config_dir` | Relative directory inside each service (e.g., `etc`) |
| `config_pattern` | Glob pattern for config files |
| `exclude_pattern` | Regex for files to skip |
| `rules` | List of regex patterns with a capture group for the port number |

### `services[].cmd`

Either a plain string (shorthand for `{"default": "..."}`) or a map:

```yaml
cmd: "npm run dev"                       # string shorthand
cmd:
  default: "npm run dev"                # explicit map
  test: "npm run test:watch"
```

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest -q

# Run tests with coverage
pytest -q --cov=muster --cov-report=term
```

## License

MIT
