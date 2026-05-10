# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
