# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working on the **muster** project.

## Project Overview

**muster** is a TUI-based service orchestrator for local development. It provides a terminal dashboard for starting, stopping, and monitoring multiple services with dependency resolution, health checks, and real-time logs.

## Architecture

```
muster/
├── muster/
│   ├── app.py              # Textual App (MusterApp) + CSS_PATH
│   ├── app.tcss            # Textual CSS stylesheet
│   ├── config.py           # YAML config loader
│   ├── models.py           # dataclasses: Service, Group, EnvCheck, etc.
│   ├── core/
│   │   ├── env.py          # TCP/HTTP/proc environment checks
│   │   ├── process.py      # kill_port_owner
│   │   └── resolver.py     # dependency resolution + port discovery
│   └── widgets/
│       ├── status_bar.py   # Env indicators + mode label
│       ├── service_tree.py # Grouped tree with dynamic colors
│       ├── detail_panel.py # Service info + action buttons
│       └── log_panel.py    # Read-only TextArea for logs
├── example/
│   └── muster-compose.yaml  # Example service orchestration config
├── pyproject.toml
└── README.md
```

## Key Design Decisions

1. **Generic over go-zero**: muster was extracted from a go-zero CRM project but all framework-specific logic (air watch mode, go-zero port regex) has been removed.

2. **Cmd as map**: `Service.cmd` accepts `str | dict[str, str]` for multiple command modes (default, test, prod, etc.).

3. **External CSS**: All styling lives in `app.tcss`, not inline Python strings.

4. **No build_cmd function**: Command building is `svc.cmd_for(mode)` on the model, not a separate utility.

## Common Tasks

### Adding a new widget
1. Create file in `muster/widgets/`
2. Export from `muster/widgets/__init__.py`
3. Import and yield in `muster/app.py::compose()`
4. Add CSS selectors to `muster/app.tcss`

### Adding a new env check type
1. Extend `EnvCheck` model in `models.py` if new fields needed
2. Implement check logic in `muster/core/env.py`
3. Update `check_env()` to handle the new type

### Modifying the config schema
1. Update `models.py` dataclasses
2. Update `config.py::load_config()` parser
3. Update `example/muster-compose.yaml`
4. Update `README.md` docs

## Code Style

- Type hints on all public functions
- `from __future__ import annotations` in every module
- No hardcoded colors/strings in Python — use `MusterConfig` values
- TCSS over inline CSS
- **Docstrings follow the Google Python Style Guide**: all modules, classes, and public methods must have a docstring. Use `Args:`, `Returns:`, `Raises:` sections for anything non-trivial.
- **Comments explain WHY, not WHAT**: complex algorithms, non-obvious edge cases, and subtle invariants must have inline comments. If the implementation is not self-evident from the code, add a brief note.

## Testing Changes

```bash
cd /Users/haha/haha-projects/crm-projects/muster
python3 -m py_compile muster/**/*.py
python3 -c "from muster.config import load_config; load_config('example/muster-compose.yaml')"
python3 -m muster -f example/muster-compose.yaml
```

### Test Structure

Unit / integration tests live in `tests/`. TUI widget tests go in
`tests/widgets/` and must use `WidgetTestApp` from `conftest.py`.

### Coverage Target

Minimum **80%** overall. Run locally before pushing:

```bash
pytest -q --cov=muster --cov-report=term
```

### Widget Testing

Widgets do NOT have `.run_test()` — only `App` does. Wrap every widget in
`WidgetTestApp` (defined in `tests/conftest.py`):

```python
async def test_widget_behavior(self):
    widget = MyWidget()
    app = WidgetTestApp(widget)
    async with app.run_test() as pilot:
        # query widget internals, press keys, etc.
```

To capture messages (e.g. `ServiceHighlighted`), use the `capture_messages`
helper instead of `@app.on()` (Textual App has no `.on()` decorator):

```python
messages = capture_messages(tree, ServiceTree.ServiceHighlighted)
tree.highlight_service("api")
await pilot.pause()
assert messages[0].service.name == "api"
```

### App Integration Testing

Use the `minimal_app` fixture from `conftest.py`. It provides a `MusterApp`
with a mocked `ServiceOrchestrator` (no real subprocesses):

```python
async def test_keyboard_action(self, minimal_app):
    app = minimal_app
    async with app.run_test() as pilot:
        await pilot.press("l")
        await pilot.pause()
        assert app._group_filter == "backend"
```

### Adding Dev Dependencies

Any new test dependency must be added to `[project.optional-dependencies] dev`
in `pyproject.toml`. After editing, install locally:

```bash
pip install -e ".[dev]"
```
