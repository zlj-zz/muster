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
