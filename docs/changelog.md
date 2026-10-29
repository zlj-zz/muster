# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.0] - 2026-10-28

### Added
- `services[].restart` crash policy (`off` default, `on-failure`): auto-restart
  on abnormal exit, max 3 attempts with linear backoff, attempt budget resets
  when the service passes its health check; auto restarts counted separately
  (`auto_restart_count`)
- `a` key: interleaved all-services log view with per-service coloured
  prefixes; footer and `?` help overlay updated

### Changed
- Manual restart (`R`) increments `restart_count` only on success
- Settings timeout clamp now runs only as one-time legacy migration;
  user-saved short timeouts are respected verbatim
- Log storage split into `core/logstore.py`; `core` no longer imports
  `widgets` (enforced by a regression test)

### Fixed
- Blocking socket probes (env refresh, port-conflict check, health check) no
  longer stall the UI event loop
- Dropped illegal status transitions are logged instead of silently ignored
- Removed dead code: unused `DEFAULT_STATUS_COLORS` and `StatusBar` widget
- CI enforces an 80% coverage gate

## [0.3.0] - 2026-10-28

### Added
- `?` help overlay listing every keybinding (including hidden ones: `1/2/3/4`,
  `j/k`), opened via `?` and closed with `?` or `esc`; footer now shows a
  `? help` hint
- Real-subprocess integration tests covering layered dependency startup,
  fast-fail propagation on spawn errors, and port release after stop
  (orchestrator coverage 49% → 73%)

## [0.2.3] - 2026-10-28

### Fixed
- Wake dependency waiters when a service fails to spawn, so `start_with_deps`
  no longer stalls the whole layer for `layer_timeout` (was up to 300s)
- Run environment checks via `asyncio.to_thread` so unreachable hosts no
  longer freeze the UI event loop during auto-refresh
- Route stop-failure messages through the log callback instead of writing
  to stderr, which corrupted the TUI display

### Changed
- Pin `textual` to `>=8,<9` (was `>=0.50.0` with no upper bound, while the
  lockfile already resolved 8.x)

## [0.2.2] - 2026-05-11

### Added
- CPU/memory resource monitoring with `psutil`
- Environment detail panel with health history and latency statistics
- Interactive rich log viewer with virtual scrolling (`InteractiveRichLog`)
- Coloured log lines with custom `LogLine` widget
- Log level filter and system log prefix beautify
- Log search with unified accent color `#eab459`
- Tooltips for SettingsPanel labels
- Lazy-load historical logs from disk with opt-in setting
- Daily log rotation and deque-based ring buffer
- Config validation (`validate_config`) with fail-fast checks
- Settings tab with persistent runtime configuration
- `asyncio.Lock` protection for `svc.status` with tightened exception handling
- HTTP and process environment checks (`http`, `proc` types)

### Fixed
- Show zero resource bar for stopped services instead of dash
- Graceful port cleanup and zombie process reaping
- Friendlier error message when config file is missing

## [0.2.1] - 2026-05-10

### Added
- Double-tap confirmation for stop-all
- Refined activity bar icons, tooltips, and tooltip delay
- DetailPanel rewrite with runtime telemetry and visual polish

### Changed
- Unified accent color to `#eab459`

## [0.2.0] - 2026-05-09

### Added
- Orange accent theme with round corners
- Unified dark theme with orange borders and bold white titles
- Activity bar layout with env/yaml tabs
- Scrollbar styling

### Changed
- Adopt `src/` layout and dynamic versioning per Hatch guide
- Modernize type annotations to Python 3.10 syntax
- Adjust keybindings

## [0.1.0] - 2026-05-09

### Added
- Initial release: muster — TUI service orchestrator
