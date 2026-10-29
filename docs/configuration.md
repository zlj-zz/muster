# Configuration Reference

See [`example/muster-compose.yaml`](https://github.com/zlj-zz/muster/blob/main/example/muster-compose.yaml) for a full-featured example.

## `config.groups`

Define service groups. Each group gets its own section in the tree view.

| Field | Description |
|-------|-------------|
| `id` | Unique identifier (referenced by services) |
| `label` | Display name in the UI |
| `color` | Hex color for group heading and detail panel |
| `order` | Sort order (ascending) |

## `config.env_checks`

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

### TCP example

```yaml
env_checks:
  - name: postgres
    type: tcp
    host: 127.0.0.1
    port: 5432
```

### HTTP example

```yaml
env_checks:
  - name: api-health
    type: http
    url: http://127.0.0.1:8080/health
    method: GET
    expect_status: 200
```

### Process example

```yaml
env_checks:
  - name: nginx
    type: proc
    pattern: nginx
```

## `config.port_discovery`

Enable automatic port extraction from service config files.

| Field | Description |
|-------|-------------|
| `enabled` | Toggle auto-discovery |
| `config_dir` | Relative directory inside each service (e.g., `etc`) |
| `config_pattern` | Glob pattern for config files |
| `exclude_pattern` | Regex for files to skip |
| `rules` | List of regex patterns with a capture group for the port number |

## `services[].cmd`

Either a plain string (shorthand for `{"default": "..."}`) or a map:

```yaml
cmd: "npm run dev"                       # string shorthand
cmd:
  default: "npm run dev"                # explicit map
  test: "npm run test:watch"
```

## `services[].restart`

Crash restart policy — `off` (default) or `on-failure`.

```yaml
services:
  - name: api
    cmd: "go run main.go"
    group: backend
    restart: on-failure
```

With `on-failure`, muster restarts the service after an abnormal exit
(non-zero code), up to 3 attempts with linear backoff. The attempt
counter resets when the service reaches `RUNNING` again. Manual (`R`)
and automatic restarts are counted separately (`restart_count` vs
`auto_restart_count`).

## `services[].healthcheck`

Readiness probe — `tcp` (default), `none`, or `http`.

```yaml
services:
  - name: worker
    cmd: "python worker.py"
    group: backend
    healthcheck: none          # no gate: RUNNING right after spawn

  - name: api
    cmd: "go run main.go"
    group: backend
    healthcheck:
      type: http
      url: http://127.0.0.1:8080/health
      expect_status: 200       # poll until this status is returned
```

With `none`, the service is marked RUNNING immediately after spawn —
use it for workers that never listen on a port. With `http`, muster
polls the URL (2s request timeout) until it returns `expect_status`,
within the configured health timeout.
