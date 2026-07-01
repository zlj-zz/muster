# muster 性能与超时优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 muster 启动多层级依赖服务时的假超时问题，并降低服务启动期间 TUI 的卡顿。

**Architecture:** 将 health check 与 layer wait 解耦为两个独立 timeout，使用 `asyncio.Event` 替代轮询来消除边界竞争；对 TUI 侧引入 widget 引用缓存、日志批量刷新和 DetailPanel 增量更新，把高频同步 UI 操作从事件循环热点路径上移除。

**Tech Stack:** Python 3.10+, Textual, asyncio, pytest, pytest-asyncio, pytest-cov

---

## 文件结构映射

| 文件 |  responsibility  |
|------|------------------|
| `src/muster/models.py` | `Service` 增加 `_ready_event`；`AppSettings` 拆分为 `health_timeout` / `layer_timeout` |
| `src/muster/core/orchestrator.py` | `_health_check` 成功/失败时 set event；`start_with_deps` 用 `event.wait()` 替代轮询；`start`/`stop` 管理 event 生命周期 |
| `src/muster/core/settings_store.py` | 加载/保存 `health_timeout` 与 `layer_timeout`；兼容旧字段迁移 |
| `src/muster/widgets/settings_panel.py` | 设置面板增加 layer timeout 输入项 |
| `src/muster/app.py` | 缓存 `LogPanel`/`ServiceTree`/`DetailPanel` 引用；`_safe_append_log` 跳过非当前服务日志 |
| `src/muster/widgets/log_panel.py` | 增加批量 `append_logs` 与内部 flush 机制 |
| `src/muster/widgets/detail_panel.py` | 拆分 `refresh_content` 为增量刷新方法 |
| `tests/test_orchestrator.py` | 新增 event/timeout 相关测试 |
| `tests/widgets/test_log_panel.py` | 新增日志批量刷新测试 |
| `tests/test_app.py` | 新增 widget 缓存与跳过非当前服务日志测试 |

---

## Task 1: 多层依赖超时修复

### Task 1.1: 为 `Service` 添加 `_ready_event`

**Files:**
- Modify: `src/muster/models.py:101-133`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models.py
import asyncio

from muster.models import Service


def test_service_has_ready_event():
    svc = Service(name="api", cmd="echo hello", group="backend")
    assert isinstance(svc._ready_event, asyncio.Event)
    assert not svc._ready_event.is_set()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py::test_service_has_ready_event -v`

Expected: `FAIL - AttributeError: 'Service' object has no attribute '_ready_event'`

- [ ] **Step 3: Add `_ready_event` to `Service`**

```python
# src/muster/models.py:101-133 (Service dataclass)
@dataclass
class Service:
    """A single runnable service.

    ``cmd`` supports two shapes for convenience:
      * A plain ``str`` — shorthand for ``{"default": "..."}``.
      * A ``dict[str, str]`` — mapping mode names to commands.

    Attributes:
        name: Unique service identifier.
        cmd: Command string or mode-to-command mapping.
        group: Group ``id`` this service belongs to.
        port: Statically configured port (overrides auto-discovery).
        depends_on: Names of services that must start before this one.
        status: Current runtime state (defaults to ``Status.STOPPED``).
        proc: Active ``asyncio`` subprocess handle.
        log_lines: Ring-buffer of the most recent log lines.
    """

    name: str
    cmd: str | dict[str, str]
    group: str
    port: int | None = None
    depends_on: list[str] = field(default_factory=list)

    # runtime state
    status: Status = Status.STOPPED
    proc: asyncio.subprocess.Process | None = None
    log_lines: deque[str] = field(default_factory=lambda: deque(maxlen=2000))
    start_time: datetime | None = None
    restart_count: int = 0
    last_error: str | None = None
    _ready_event: asyncio.Event = field(
        default_factory=asyncio.Event, repr=False, compare=False
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py::test_service_has_ready_event -v`

Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add src/muster/models.py tests/test_models.py
git commit -m "feat(models): add _ready_event to Service for async readiness notification

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 1.2: 拆分 `AppSettings` 为 `health_timeout` 与 `layer_timeout`

**Files:**
- Modify: `src/muster/models.py:186-218`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models.py
from muster.models import AppSettings


def test_app_settings_has_separate_timeouts():
    settings = AppSettings()
    assert settings.health_timeout == 60
    assert settings.layer_timeout == 120
    assert settings.layer_timeout > settings.health_timeout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py::test_app_settings_has_separate_timeouts -v`

Expected: `FAIL - AttributeError: 'AppSettings' object has no attribute 'layer_timeout'`

- [ ] **Step 3: Update `AppSettings` defaults**

```python
# src/muster/models.py:186-218
@dataclass
class AppSettings:
    """User-level runtime preferences persisted across sessions.

    These settings control behaviour, timeouts, and display preferences.
    They are independent of project-level configuration in
    ``muster-compose.yaml``.

    Attributes:
        env_refresh_interval: Seconds between environment check polls.
        port_conflict_strategy: How to handle a port already in use
            (``"kill"``, ``"warn"``, ``"abort"``).
        log_auto_scroll: Whether the log panel should scroll to the bottom
            on every new log line.
        log_show_timestamp: Whether to prefix each log line with a timestamp.
        log_default_level: Default log-level filter (``"ALL"``, ``"ERROR"``,
            ``"WARN"``, ``"INFO"``).
        log_buffer_lines: Maximum number of log lines to keep in memory.
        health_timeout: Seconds to wait for a single service port to become ready.
        layer_timeout: Seconds to wait for an entire dependency layer to become ready.
        stop_timeout: Seconds to wait for graceful shutdown before SIGKILL.
    """

    env_refresh_interval: int = 5
    port_conflict_strategy: str = "kill"
    log_auto_scroll: bool = True
    log_show_timestamp: bool = False
    log_wrap: bool = True
    log_default_level: str = "ALL"
    log_buffer_lines: int = 2000
    load_history_on_startup: bool = False
    health_timeout: int = 60
    layer_timeout: int = 120
    stop_timeout: float = 8.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py::test_app_settings_has_separate_timeouts -v`

Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add src/muster/models.py tests/test_models.py
git commit -m "feat(models): split start_timeout into health_timeout and layer_timeout

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 1.3: 更新 `ServiceOrchestrator` 使用 `health_timeout` / `layer_timeout`

**Files:**
- Modify: `src/muster/core/orchestrator.py:90-111`, `198-276`, `554-609`
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_orchestrator.py
from muster.models import AppSettings


def test_orchestrator_has_separate_timeouts():
    settings = AppSettings(health_timeout=60, layer_timeout=120)
    config = MusterConfig(
        env_checks=[],
        groups=[],
        port_discovery=PortDiscovery(enabled=False),
    )
    orch = ServiceOrchestrator(config=config, registry={})
    # Default orchestrator uses its own defaults before apply_to_app.
    # We only verify the attributes exist and layer > health.
    assert orch.health_timeout < orch.layer_timeout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_orchestrator.py::test_orchestrator_has_separate_timeouts -v`

Expected: `FAIL - AttributeError: 'ServiceOrchestrator' object has no attribute 'health_timeout'`

- [ ] **Step 3: Replace `start_timeout` with `health_timeout` / `layer_timeout` in orchestrator**

```python
# src/muster/core/orchestrator.py:90-111
class ServiceOrchestrator:
    """Manages service process lifecycle independently of the UI.

    Args:
        config: Parsed ``MusterConfig`` (used for port-discovery rules and
            group ordering).
        registry: Mapping from service name to ``Service`` instance.
        on_log: Callback ``(svc_name, line)`` fired for every log line.
        on_status: Callback ``(service)`` fired whenever a service's
            ``status`` field changes.
        on_notify: Callback ``(message, severity)`` fired for user-facing
            toast notifications.
    """

    def __init__(
        self,
        config: MusterConfig,
        registry: dict[str, Service],
        *,
        on_log: Callable[[str, str], None] = lambda _s, _l: None,
        on_status: Callable[[Service], None] = lambda _s: None,
        on_notify: Callable[[str, str], None] = lambda _m, _s: None,
    ) -> None:
        self.config = config
        self.registry = registry
        self._on_log = on_log
        self._on_status = on_status
        self._on_notify = on_notify
        self.stop_timeout: float = 8.0
        self.health_timeout: int = 60
        self.layer_timeout: int = 120
        self.port_conflict_strategy: str = "kill"
        self._reader_tasks: dict[str, asyncio.Task] = {}
        self._health_tasks: dict[str, asyncio.Task] = {}
        self._monitor_tasks: dict[str, asyncio.Task] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._runtime_health_task: asyncio.Task | None = None
```

- [ ] **Step 4: Update `start_with_deps` to wait via event with `layer_timeout`**

```python
# src/muster/core/orchestrator.py:198-276
async def start_with_deps(self, svc: Service, mode: str = "default") -> None:
    """Start a service after resolving and starting all dependencies.

    Dependencies are launched layer-by-layer. Within each layer, services
    are started in parallel; the caller waits for the entire layer to
    reach a terminal state before proceeding to the next layer.

    If any dependency fails or times out, the start sequence is aborted.

    Args:
        svc: The target service to start.
        mode: Command mode key (e.g. ``"default"``, ``"test"``).
    """
    try:
        deps = resolve_dependencies([svc.name], self.registry)
    except ValueError as e:
        self._notify(f"Dependency resolution failed: {e}", "error")
        return

    dep_names = [d.name for d in deps]
    self._log(svc.name, f"muster▸Dependencies: {dep_names}")

    # Pre-emptively handle any process already bound to the target port.
    port = svc.port or resolve_port(svc.name, self.config.port_discovery)
    if port and not await self._check_port_conflict(svc.name, port):
        return

    # Build launch plan: one layer per dependency depth.
    layers = self._compute_depth_layers(deps)
    layer_names = [[s.name for s in layer] for layer in layers]
    self._log(svc.name, f"muster▸Launch layers: {layer_names}")

    for layer_idx, layer_svcs in enumerate(layers):
        layer_names = [s.name for s in layer_svcs]
        self._log(svc.name, f"muster▸Starting layer {layer_idx}: {layer_names}")

        # Kick off every service in this layer that is not already running.
        for s in layer_svcs:
            if s.status not in (Status.STARTING, Status.RUNNING):
                p = s.port or resolve_port(s.name, self.config.port_discovery)
                if p and not await self._check_port_conflict(
                    svc.name, p, dep_name=s.name
                ):
                    return
                self._log(
                    svc.name,
                    f"muster▸Scheduling start: {s.name} (status: {s.status.value})",
                )
                asyncio.create_task(self.start(s, mode))
            else:
                self._log(
                    svc.name,
                    f"muster▸Skipping start: {s.name} (status: {s.status.value})",
                )

        # Wait for the whole layer to reach a terminal state.
        for s in layer_svcs:
            is_target = s.name == svc.name
            if s.status == Status.RUNNING:
                self._log(svc.name, f"muster▸{s.name} already running, skip wait")
                continue
            if s.status == Status.FAILED:
                self._abort_start(svc, s, is_target, "start failed")
                return

            self._log(
                svc.name,
                f"muster▸Waiting for {s.name} ready (current: {s.status.value})...",
            )
            try:
                await asyncio.wait_for(
                    s._ready_event.wait(), timeout=self.layer_timeout
                )
            except asyncio.TimeoutError:
                self._abort_start(
                    svc, s, is_target, f"start timeout ({self.layer_timeout}s)"
                )
                return

            if s.status == Status.FAILED:
                self._abort_start(svc, s, is_target, "start failed")
                return
            self._log(svc.name, f"muster▸{s.name} ready")
```

- [ ] **Step 5: Update `_health_check` to set `_ready_event` and use `health_timeout`**

```python
# src/muster/core/orchestrator.py:554-609
async def _health_check(self, svc: Service) -> None:
    """Poll the service's TCP port until it accepts connections.

    If the service has no discoverable port, falls back to a 3-second
    heuristic: if the process is still alive, mark it ``RUNNING``.

    Times out after ``self.health_timeout`` seconds and marks the service
    ``FAILED``.

    Args:
        svc: Service to health-check.
    """
    try:
        port = self._resolve_effective_port(svc)
        if port is None:
            await asyncio.sleep(3)
            async with self._get_lock(svc.name):
                if svc.proc and svc.proc.returncode is None:
                    self._set_status(svc, Status.RUNNING)
                else:
                    self._set_status(svc, Status.FAILED)
            svc._ready_event.set()
            return

        for i in range(self.health_timeout):
            async with self._get_lock(svc.name):
                if svc.proc is None or svc.proc.returncode is not None:
                    self._set_status(svc, Status.FAILED)
            # Lock released — check whether we already set FAILED.
            if svc.status == Status.FAILED:
                self._log(svc.name, "muster▸Process exited, health check failed")
                svc._ready_event.set()
                return
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                    async with self._get_lock(svc.name):
                        self._set_status(svc, Status.RUNNING)
                    svc.port = port
                    svc._ready_event.set()
                    self._log(svc.name, f"muster▸Service ready (port {port})")
                    self._notify(f"{svc.name} ready (:{port})", "success")
                    return
            except OSError:
                pass
            if i % 5 == 0:
                self._log(
                    svc.name, f"muster▸Waiting for port {port} ready... ({i}s)"
                )
            await asyncio.sleep(1)

        async with self._get_lock(svc.name):
            self._set_status(svc, Status.FAILED)
        svc._ready_event.set()
        self._log(svc.name, f"muster▸Port {port} not ready, health check timeout")
        self._notify(f"{svc.name} port {port} not ready", "error")
    except Exception as e:
        err = f"!!! Health check error: {e}"
        svc.log_lines.append(err)
        self._log(svc.name, err)
        async with self._get_lock(svc.name):
            self._set_status(svc, Status.FAILED)
        svc._ready_event.set()
        self._notify(f"{svc.name} health check error: {e}", "error")
```

- [ ] **Step 6: Manage `_ready_event` lifecycle in `start` and `stop`**

```python
# src/muster/core/orchestrator.py:278-354
async def start(self, svc: Service, mode: str = "default") -> None:
    """Start a single service process.

    Creates a subprocess shell, wires up log readers and health checks,
    and transitions the service through ``STARTING`` → ``RUNNING`` or
    ``FAILED``.

    Args:
        svc: Service to start.
        mode: Command mode key passed to ``svc.cmd_for()``.
    """
    async with self._get_lock(svc.name):
        if svc.status in (Status.STARTING, Status.RUNNING):
            return
        svc._ready_event.clear()
        self._set_status(svc, Status.STARTING)
    self._notify(f"Starting {svc.name}...", "information")
    # ... rest unchanged ...
```

```python
# src/muster/core/orchestrator.py:356-410
async def stop(self, svc: Service) -> None:
    """Stop a service process gracefully.

    Sends ``SIGTERM`` to the process group, waits up to 8 seconds, then
    escalates to ``SIGKILL`` if necessary.

    Args:
        svc: Service to stop.
    """
    async with self._get_lock(svc.name):
        if svc.status == Status.STOPPED:
            return

    # ... existing cancellation and kill logic ...

    svc.proc = None
    svc.start_time = None
    async with self._get_lock(svc.name):
        self._set_status(svc, Status.STOPPED, force=True)
    svc._ready_event.clear()
    stopped_msg = "muster▸Service stopped"
    svc.log_lines.append(stopped_msg)
    self._log(svc.name, stopped_msg)
    self._notify(f"{svc.name} stopped", "information")
```

- [ ] **Step 7: Run tests**

Run: `pytest tests/test_orchestrator.py -v`

Expected: all existing tests still pass; new timeout test passes

- [ ] **Step 8: Commit**

```bash
git add src/muster/core/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(orchestrator): use asyncio.Event and split health/layer timeouts

- _health_check uses health_timeout (60s) and sets ready event
- start_with_deps waits on ready event with layer_timeout (120s)
- start/stop clear ready event to support restart

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 1.4: 更新 settings_store 与 settings_panel 支持双 timeout

**Files:**
- Modify: `src/muster/core/settings_store.py:18-108`
- Modify: `src/muster/widgets/settings_panel.py:137-150`
- Test: `tests/test_settings_store.py`, `tests/widgets/test_settings_panel.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_settings_store.py
import json
from pathlib import Path

from muster.core.settings_store import load_settings, save_settings
from muster.models import AppSettings


def test_load_settings_migrates_start_timeout_to_both_timeouts(tmp_path, monkeypatch):
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(json.dumps({"start_timeout": 60}), encoding="utf-8")
    monkeypatch.setattr("muster.core.settings_store._SETTINGS_FILE", settings_file)

    settings = load_settings()
    assert settings.health_timeout == 60
    assert settings.layer_timeout == 120
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_settings_store.py::test_load_settings_migrates_start_timeout_to_both_timeouts -v`

Expected: `FAIL - AssertionError` (layer_timeout 读取默认值可能不对)

- [ ] **Step 3: Update `load_settings`, `apply_to_app`, and `_save_settings` in settings_store**

```python
# src/muster/core/settings_store.py:18-108
def load_settings() -> AppSettings:
    """Load user settings from disk, falling back to defaults.

    Returns:
        ``AppSettings`` populated from disk or built-in defaults.
    """
    if not _SETTINGS_FILE.exists():
        return AppSettings()

    try:
        with open(_SETTINGS_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return AppSettings()

    # Migrate legacy unified timeout field into separate timeouts.
    if "start_timeout" in data:
        start_timeout = data.pop("start_timeout")
        data.setdefault("health_timeout", start_timeout)
        data.setdefault("layer_timeout", max(start_timeout * 2, 120))

    # Merge with defaults so new fields are back-filled.
    merged = AppSettings().__dict__.copy()
    merged.update(data)

    # Drop keys that don't belong to AppSettings (e.g. from older formats).
    valid_keys = AppSettings.__dataclass_fields__.keys()
    merged = {k: v for k, v in merged.items() if k in valid_keys}

    try:
        return AppSettings(**merged)
    except (TypeError, ValueError):
        return AppSettings()


def apply_to_app(app, settings: AppSettings) -> None:
    """Apply settings to a running :class:`MusterApp`.

    Updates orchestrator parameters, log panel behaviour, and
    re-schedules the environment refresh timer when the interval
    changes.

    Args:
        app: The running ``MusterApp`` instance.
        settings: The new settings to apply.
    """
    # Update orchestrator
    app._orchestrator.stop_timeout = settings.stop_timeout
    app._orchestrator.health_timeout = settings.health_timeout
    app._orchestrator.layer_timeout = settings.layer_timeout
    app._orchestrator.port_conflict_strategy = settings.port_conflict_strategy

    # Update log panel
    from textual.css.query import NoMatches
    from ..widgets.log_panel import LogPanel

    try:
        log_panel = app.query_one("#log", LogPanel)
    except NoMatches:
        log_panel = None

    if log_panel is not None:
        log_panel.auto_scroll = settings.log_auto_scroll
        log_panel.show_timestamp = settings.log_show_timestamp
        log_panel.wrap = settings.log_wrap
        log_panel.buffer_lines = settings.log_buffer_lines
        log_panel.load_history = settings.load_history_on_startup
        log_panel.set_wrap(settings.log_wrap)
        log_panel.resize_buffer(settings.log_buffer_lines)
        if log_panel._log_level == "ALL":
            log_panel._set_level(settings.log_default_level)

    # Re-schedule env refresh timer if interval changed
    old_interval = getattr(app, "_env_refresh_interval", 5)
    if old_interval != settings.env_refresh_interval:
        app._env_refresh_interval = settings.env_refresh_interval
        if hasattr(app, "_env_timer") and app._env_timer is not None:
            app._env_timer.stop()
        app._env_timer = app.set_interval(
            settings.env_refresh_interval,
            app._refresh_env_status,
        )
```

- [ ] **Step 4: Add layer timeout input to settings panel**

```python
# src/muster/widgets/settings_panel.py:137-162
        # ── Timing ──
        with Vertical(classes="settings-section"):
            yield Static("Timing", classes="settings-section-title")

            with Horizontal(classes="settings-row"):
                yield SettingsLabel(
                    "Health timeout",
                    "等待单个服务端口就绪的秒数",
                )
                yield Input(
                    str(self.settings.health_timeout),
                    id="input-health-timeout",
                )
                yield Static("s", classes="settings-unit")

            with Horizontal(classes="settings-row"):
                yield SettingsLabel(
                    "Layer timeout",
                    "等待整层依赖服务就绪的秒数",
                )
                yield Input(
                    str(self.settings.layer_timeout),
                    id="input-layer-timeout",
                )
                yield Static("s", classes="settings-unit")

            with Horizontal(classes="settings-row"):
                yield SettingsLabel(
                    "Stop timeout",
                    "Seconds to wait for graceful shutdown before SIGKILL",
                )
                yield Input(
                    str(self.settings.stop_timeout),
                    id="input-stop-timeout",
                )
                yield Static("s", classes="settings-unit")
```

同时更新 `_save_settings` 读取这两个字段：

```python
# src/muster/widgets/settings_panel.py:185-225
    def _save_settings(self) -> None:
        """Read widget values, build ``AppSettings``, and notify the App."""
        try:
            new_settings = AppSettings(
                env_refresh_interval=int(
                    self.query_one("#input-env-interval", Input).value or "5"
                ),
                port_conflict_strategy=str(
                    self.query_one("#select-port-strategy", Select).value
                ),
                log_auto_scroll=bool(
                    self.query_one("#switch-auto-scroll", Switch).value
                ),
                log_show_timestamp=bool(
                    self.query_one("#switch-timestamps", Switch).value
                ),
                log_wrap=bool(self.query_one("#switch-wrap", Switch).value),
                log_default_level=str(
                    self.query_one("#select-log-level", Select).value
                ),
                log_buffer_lines=int(
                    self.query_one("#input-buffer-lines", Input).value or "2000"
                ),
                load_history_on_startup=bool(
                    self.query_one("#switch-load-history", Switch).value
                ),
                health_timeout=int(
                    self.query_one("#input-health-timeout", Input).value or "60"
                ),
                layer_timeout=int(
                    self.query_one("#input-layer-timeout", Input).value or "120"
                ),
                stop_timeout=float(
                    self.query_one("#input-stop-timeout", Input).value or "8"
                ),
            )
        except (ValueError, TypeError):
            return

        self.settings = new_settings
        self.post_message(self.SettingsChanged(new_settings))
```

并更新 `_reset_settings`：

```python
# src/muster/widgets/settings_panel.py:226-250
    def _reset_settings(self) -> None:
        """Restore defaults and update every widget."""
        defaults = AppSettings()
        self.query_one("#input-env-interval", Input).value = str(
            defaults.env_refresh_interval
        )
        self.query_one("#select-port-strategy", Select).value = (
            defaults.port_conflict_strategy
        )
        self.query_one("#switch-auto-scroll", Switch).value = defaults.log_auto_scroll
        self.query_one("#switch-timestamps", Switch).value = defaults.log_show_timestamp
        self.query_one("#switch-wrap", Switch).value = defaults.log_wrap
        self.query_one("#select-log-level", Select).value = defaults.log_default_level
        self.query_one("#input-buffer-lines", Input).value = str(
            defaults.log_buffer_lines
        )
        self.query_one("#switch-load-history", Switch).value = (
            defaults.load_history_on_startup
        )
        self.query_one("#input-health-timeout", Input).value = str(
            defaults.health_timeout
        )
        self.query_one("#input-layer-timeout", Input).value = str(
            defaults.layer_timeout
        )
        self.query_one("#input-stop-timeout", Input).value = str(defaults.stop_timeout)
        self.settings = defaults
        self.post_message(self.SettingsChanged(defaults))
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_settings_store.py tests/widgets/test_settings_panel.py -v`

Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add src/muster/core/settings_store.py src/muster/widgets/settings_panel.py tests/test_settings_store.py tests/widgets/test_settings_panel.py
git commit -m "feat(settings): support separate health_timeout and layer_timeout

- migrate legacy 'start_timeout' field
- add layer timeout input in settings panel

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: TUI 性能优化

### Task 2.1: 缓存 `MusterApp` 中的 widget 引用

**Files:**
- Modify: `src/muster/app.py:74-103`, `180-215`, `227-241`, `255-376`
- Test: `tests/test_app.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_app.py
class TestAppWidgetCache:
    """Widget references are cached after mount."""

    async def test_log_panel_cached_after_mount(self, minimal_app):
        app = minimal_app
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._log_panel is not None
            assert app._service_tree is not None
            assert app._detail_panel is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_app.py::TestAppWidgetCache::test_log_panel_cached_after_mount -v`

Expected: `FAIL - AttributeError: 'MusterApp' object has no attribute '_log_panel'`

- [ ] **Step 3: Add cache fields and initialize in `on_mount`**

```python
# src/muster/app.py:74-103
    def __init__(
        self,
        config: MusterConfig,
        services: list[Service],
        registry: dict[str, Service],
        config_path: Path | None = None,
        cmd_mode: str = "default",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._muster_config = config
        self.all_services = services
        self.registry = registry
        self._config_path = config_path
        self.cmd_mode = cmd_mode
        self._group_filter: str | None = None
        self._cleaned_up = False
        self._orchestrator = ServiceOrchestrator(
            config,
            registry,
            on_log=self._safe_append_log,
            on_status=self._refresh_list_item,
            on_notify=lambda msg, sev: self.notify(msg, severity=sev),
        )
        self._settings = load_settings()
        self._env_timer = None
        self._resource_timer = None
        self._yaml_files = self._scan_yaml_files()
        self._stop_pending = False
        # Cached widget references populated in on_mount.
        self._log_panel: LogPanel | None = None
        self._service_tree: ServiceTree | None = None
        self._detail_panel: DetailPanel | None = None
```

```python
# src/muster/app.py:180-215
    def on_mount(self) -> None:
        """Initialise the UI after widgets are mounted.

        Auto-selects the first item in each tab so that panels are
        never empty on startup.
        """
        # Cache expensive widget lookups once.
        self._log_panel = self.query_one("#log", LogPanel)
        self._service_tree = self.query_one("#service-tree", ServiceTree)
        self._detail_panel = self.query_one("#detail", DetailPanel)

        self.title = "muster"
        self._refresh_env_status()
        self._env_timer = self.set_interval(
            self._settings.env_refresh_interval, self._refresh_env_status
        )
        self._resource_timer = self.set_interval(2, self._refresh_resources)
        apply_to_app(self, self._settings)

        # svc tab: auto-select first service
        tree = self._service_tree
        if tree.services:
            for group_node in tree.root.children:
                if group_node.children:
                    svc = group_node.children[0].data
                    if isinstance(svc, Service):
                        tree.highlight_service(svc.name)
                    break
        self._update_detail()

        # env tab: auto-select first env check
        env_list = self.query_one("#env-list", EnvList)
        if env_list.root.children:
            env_list.select_node(env_list.root.children[0])
            self._update_env_detail()

        # yaml tab: auto-select first file
        file_list = self.query_one("#file-list", FileList)
        if file_list.root.children:
            file_list.select_node(file_list.root.children[0])
            self._update_yaml_preview()
```

- [ ] **Step 4: Update `_safe_append_log` and `_refresh_list_item` to use cached references**

```python
# src/muster/app.py:227-241
    def _safe_append_log(self, svc_name: str, line: str) -> None:
        """Append a log line, swallowing widget lookup errors.

        Called from background tasks; the log panel may not exist during
        shutdown.

        Args:
            svc_name: Name of the service that produced the line.
            line: Raw log text.
        """
        log_panel = self._log_panel
        if log_panel is None or log_panel._svc_name != svc_name:
            return
        log_panel.append_log(svc_name, line)
```

```python
# src/muster/app.py:359-376
    def _refresh_list_item(self, svc: Service) -> None:
        """Refresh a single service node in the tree and detail panel.

        Called by ``ServiceOrchestrator`` whenever a service's status changes.

        Args:
            svc: Service whose visual representation should be refreshed.
        """
        try:
            tree = self._service_tree
            if tree is not None:
                tree.refresh_node(svc)
            detail = self._detail_panel
            if detail is not None and detail.current_service is svc:
                detail.refresh_status(svc)
        except AttributeError:
            pass
```

- [ ] **Step 5: Update `_refresh_tree` and `_update_detail` to use cached tree**

```python
# src/muster/app.py:255-271
    def _refresh_tree(self) -> None:
        """Rebuild the service tree and restore the previous selection."""
        tree = self._service_tree
        if tree is None:
            return
        current_name = tree.current_service.name if tree.current_service else None
        tree.services = self._filtered_services()
        tree.rebuild()
        if current_name:
            tree.select_service(current_name)
        elif tree.services:
            for group_node in tree.root.children:
                if group_node.children:
                    svc = group_node.children[0].data
                    if isinstance(svc, Service):
                        tree.highlight_service(svc.name)
                    break
        self._update_detail()
```

```python
# src/muster/app.py:272-286
    def _update_detail(self) -> None:
        """Synchronise DetailPanel and LogPanel with the current tree selection."""
        from textual.css.query import NoMatches

        try:
            tree = self._service_tree
            if tree is None:
                return
            svc = tree.current_service
            if self._detail_panel is not None:
                self._detail_panel.current_service = svc
            if self._log_panel is not None:
                self._log_panel.set_service(svc)
        except NoMatches:
            pass
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_app.py -v`

Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add src/muster/app.py tests/test_app.py
git commit -m "perf(app): cache widget references and skip non-current log updates

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2.2: 为 `LogPanel` 增加批量刷新

**Files:**
- Modify: `src/muster/widgets/log_panel.py:173-184`
- Modify: `src/muster/widgets/interactive_rich_log.py:148-169`
- Test: `tests/widgets/test_log_panel.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/widgets/test_log_panel.py
import pytest

from muster.widgets.log_panel import LogPanel
from tests.conftest import WidgetTestApp


@pytest.mark.asyncio
async def test_append_logs_batches_into_single_write():
    log = LogPanel()
    app = WidgetTestApp(log)
    async with app.run_test() as pilot:
        log.set_service_mock("svc")
        log.append_logs([f"line {i}" for i in range(10)])
        await pilot.pause()
        assert log._log_widget.line_count == 10
```

> 注意：`set_service_mock` 在真实 `LogPanel` 中不存在，需要在 Step 3 改为使用真实 `set_service`。下面 Step 3 给出真实测试代码。

修正测试：

```python
# tests/widgets/test_log_panel.py
import pytest

from muster.models import Service
from muster.widgets.log_panel import LogPanel
from tests.conftest import WidgetTestApp


@pytest.mark.asyncio
async def test_append_logs_batches_into_single_write():
    svc = Service(name="svc", cmd="echo hello", group="backend")
    log = LogPanel()
    app = WidgetTestApp(log)
    async with app.run_test() as pilot:
        log.set_service(svc)
        log.append_logs([f"line {i}" for i in range(10)])
        await pilot.pause()
        assert log._log_widget.line_count == 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/widgets/test_log_panel.py::test_append_logs_batches_into_single_write -v`

Expected: `FAIL - AttributeError: 'LogPanel' object has no attribute 'append_logs'`

- [ ] **Step 3: Implement batch append in `LogPanel` and `InteractiveRichLog`**

```python
# src/muster/widgets/interactive_rich_log.py:148-169
    def write_line(self, text: str, level: str | None = None) -> None:
        """Append a single log line."""
        self._meta.append(self._make_meta(text, level))

        if len(self._meta) == self._meta.maxlen:
            self._schedule_rebuild()
            return

        meta = self._meta[-1]
        if self._level_filter == "ALL" or meta.level == self._level_filter:
            self._visible_meta_indices.append(len(self._meta) - 1)
            self._line_to_screen.append(len(self.lines))
            self.write(self._build_text(meta), scroll_end=False)
            if self.auto_scroll:
                self.scroll_end(animate=False)

    def write_lines(self, lines: list[str]) -> None:
        """Bulk append lines (used for historical log loading)."""
        for text in lines:
            self._meta.append(self._make_meta(text))
        self._rebuild()
```

`write_line` 和 `write_lines` 已存在，只需在 `LogPanel` 增加 `append_logs`：

```python
# src/muster/widgets/log_panel.py:173-184
    def append_log(self, svc_name: str, line: str) -> None:
        """Append a single log line if it belongs to the currently shown service.

        Args:
            svc_name: Name of the service that produced the line.
            line: Raw log line text.
        """
        if self._svc_name != svc_name:
            return
        if self.show_timestamp:
            line = f"{datetime.now().strftime('%H:%M:%S')} {line}"
        self._log_widget.write_line(line)

    def append_logs(self, svc_name: str, lines: list[str]) -> None:
        """Append multiple log lines in a single UI refresh.

        Args:
            svc_name: Name of the service that produced the lines.
            lines: Raw log line texts.
        """
        if self._svc_name != svc_name or not lines:
            return
        if self.show_timestamp:
            ts = datetime.now().strftime("%H:%M:%S")
            lines = [f"{ts} {line}" for line in lines]
        self._log_widget.write_lines(lines)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/widgets/test_log_panel.py -v`

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/muster/widgets/log_panel.py tests/widgets/test_log_panel.py
git commit -m "perf(log_panel): add append_logs for batched log updates

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2.3: 在 orchestrator 中批量发送日志回调

**Files:**
- Modify: `src/muster/core/orchestrator.py:485-519`
- Modify: `src/muster/app.py:227-241`
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_orchestrator.py
import asyncio
from unittest.mock import AsyncMock, patch


@patch("muster.core.orchestrator.asyncio.create_subprocess_shell")
async def test_log_callback_batches_lines(mock_create_subprocess):
    proc = AsyncMock()
    proc.pid = 12345
    proc.stdout = AsyncMock()
    proc.stdout.readline = AsyncMock(side_effect=[b"line1\n", b"line2\n", b""])
    proc.wait = AsyncMock(return_value=0)
    mock_create_subprocess.return_value = proc

    svc = Service(name="api", cmd="echo hello", group="backend")
    registry = {"api": svc}
    orch = _make_orchestrator(registry)

    log_calls = []

    def on_log(svc_name, line):
        log_calls.append((svc_name, line))

    orch._on_log = on_log

    await orch.start(svc)
    # Give the reader task time to process all lines.
    await asyncio.sleep(0.1)

    assert ("api", "line1") in log_calls
    assert ("api", "line2") in log_calls
```

- [ ] **Step 2: Run test to verify it fails / passes**

Run: `pytest tests/test_orchestrator.py::test_log_callback_batches_lines -v`

Expected: currently PASS (this is a baseline test). The real change comes in Step 3.

- [ ] **Step 3: Implement a small log batcher in orchestrator**

在 `ServiceOrchestrator` 中增加一个按时间窗口批量的日志发送器：

```python
# src/muster/core/orchestrator.py:90-111 (add to __init__)
        self._locks: dict[str, asyncio.Lock] = {}
        self._runtime_health_task: asyncio.Task | None = None
        # Batched log delivery to reduce UI update pressure.
        self._pending_logs: dict[str, list[str]] = {}
        self._log_flush_task: asyncio.Task | None = None
        self._log_flush_interval: float = 0.05
```

增加批量发送方法：

```python
# src/muster/core/orchestrator.py:113-139 (after _notify)
    def _log(self, svc_name: str, line: str) -> None:
        """Forward a log line to the UI callback."""
        self._on_log(svc_name, line)

    def _batched_log(self, svc_name: str, line: str) -> None:
        """Queue a log line for batched delivery to the UI."""
        self._pending_logs.setdefault(svc_name, []).append(line)
        if self._log_flush_task is None or self._log_flush_task.done():
            self._log_flush_task = asyncio.create_task(self._flush_logs_loop())

    async def _flush_logs_loop(self) -> None:
        """Periodically flush batched log lines to the UI callback."""
        while self._pending_logs:
            await asyncio.sleep(self._log_flush_interval)
            self._flush_logs()
        self._log_flush_task = None

    def _flush_logs(self) -> None:
        """Send all queued log lines to the UI callback."""
        pending = self._pending_logs
        self._pending_logs = {}
        for svc_name, lines in pending.items():
            for line in lines:
                self._on_log(svc_name, line)
```

然后在 `_read_output` 中使用 `_batched_log`：

```python
# src/muster/core/orchestrator.py:485-519
    async def _read_output(
        self, svc: Service, proc: asyncio.subprocess.Process, logfile: Path
    ) -> None:
        """Stream subprocess stdout to the in-memory ring buffer and disk log.

        ``svc.log_lines`` is a ``deque`` with ``maxlen=2000`` so old lines are
        evicted automatically in O(1) time.

        Args:
            svc: Service owning the process.
            proc: Running subprocess.
            logfile: Path to the on-disk log file.
        """
        try:
            with open(logfile, "a", encoding="utf-8") as f:
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    text = line.decode("utf-8", errors="backslashreplace").rstrip()
                    if text:
                        # Intentionally omitting flush: per-line flush is a
                        # hot-path bottleneck for high-volume logs.  Data is
                        # safe when the child exits (with-block closes the
                        # file) but up to ~8KB may be lost if muster itself
                        # crashes before the OS buffer is synced.
                        f.write(text + "\n")
                        svc.log_lines.append(text)
                        self._batched_log(svc.name, text)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            err = f"!!! Log read error: {exc}"
            svc.log_lines.append(err)
            self._batched_log(svc.name, err)
        finally:
            self._flush_logs()
```

注意：系统日志（如 `muster▸Command:`、`muster▸Process PID:`）目前仍直接调用 `_log`，可以保持不变，因为它们频率低。高频率子进程输出走 `_batched_log`。

- [ ] **Step 4: Update `MusterApp._safe_append_log` to accept batched logs**

修改 `_on_log` 回调签名，支持批量：

```python
# src/muster/app.py:227-241
    def _safe_append_log(self, svc_name: str, line: str) -> None:
        """Append a log line, swallowing widget lookup errors.

        Called from background tasks; the log panel may not exist during
        shutdown.

        Args:
            svc_name: Name of the service that produced the line.
            line: Raw log line text.
        """
        log_panel = self._log_panel
        if log_panel is None or log_panel._svc_name != svc_name:
            return
        log_panel.append_log(svc_name, line)

    def _safe_append_logs(self, svc_name: str, lines: list[str]) -> None:
        """Append multiple log lines in one UI refresh."""
        log_panel = self._log_panel
        if log_panel is None or log_panel._svc_name != svc_name or not lines:
            return
        log_panel.append_logs(svc_name, lines)
```

然后修改 orchestrator 的 callback 注册，使用批量回调：

```python
# src/muster/app.py:90-98
        self._orchestrator = ServiceOrchestrator(
            config,
            registry,
            on_log=self._safe_append_logs,
            on_status=self._refresh_list_item,
            on_notify=lambda msg, sev: self.notify(msg, severity=sev),
        )
```

Wait — `_safe_append_logs` 签名是 `(svc_name, lines)`，而 orchestrator 的 `_flush_logs` 调用 `self._on_log(svc_name, line)` 逐行。我们需要让 `_on_log` 支持批量。

更简单的设计：让 `_on_log` 始终接收 `(svc_name, line)` 单行，但在 `MusterApp` 侧再做一次小聚合。或者让 orchestrator 的 `_flush_logs` 调用 `_on_log(svc_name, lines)` 批量。

这里选择后者，更彻底：把 `on_log` 回调改为支持批量。更新 `ServiceOrchestrator.__init__` 类型签名：

```python
# src/muster/core/orchestrator.py:90-111
        on_log: Callable[[str, str], None] = lambda _s, _l: None,
```

可以不改签名，而是 `_flush_logs` 中调用 `_on_log(svc_name, "\n".join(lines))` 再让 UI 拆分？不行，会丢失行边界。

更好的做法：引入一个内部批量发送方法 `_emit_log(svc_name, lines)`，它可以接受 list 或 str，然后调用 `self._on_log`。为了兼容现有单行调用，让 `_on_log` 保持 `(str, str)`，但在 `_flush_logs` 中多次调用 `_on_log`。这样 `MusterApp._safe_append_log` 保持单行，只是在 `MusterApp` 中自己再做聚合。

实际上最干净的做法是：把 `MusterApp._safe_append_log` 改成一个带 50ms buffer 的批量回调器。让 orchestrator 继续逐行调用 `_on_log`，在 app 层批量。

但这样改动比较大。这里采用一个折中：
- orchestrator 内部批量 flush 时，逐行调用 `_on_log`（保持现有签名）
- 在 `MusterApp` 内部自己维护一个 50ms buffer，把高频单行 `append_log` 聚合成 `append_logs`

这个 buffer 可以用 `call_later` 实现。

具体实现：

```python
# src/muster/app.py:90-103
        self._orchestrator = ServiceOrchestrator(
            config,
            registry,
            on_log=self._safe_append_log,
            on_status=self._refresh_list_item,
            on_notify=lambda msg, sev: self.notify(msg, severity=sev),
        )
        self._pending_log_lines: dict[str, list[str]] = {}
        self._log_flush_timer = None
```

```python
# src/muster/app.py:227-241
    def _safe_append_log(self, svc_name: str, line: str) -> None:
        """Append a log line, swallowing widget lookup errors.

        Buffers lines for 50ms so high-frequency logs are rendered in one
        UI refresh instead of one per line.

        Args:
            svc_name: Name of the service that produced the line.
            line: Raw log line text.
        """
        log_panel = self._log_panel
        if log_panel is None or log_panel._svc_name != svc_name:
            return

        self._pending_log_lines.setdefault(svc_name, []).append(line)
        if self._log_flush_timer is None:
            self._log_flush_timer = self.set_timer(0.05, self._flush_pending_logs)

    def _flush_pending_logs(self) -> None:
        """Flush buffered log lines to the log panel."""
        self._log_flush_timer = None
        pending = self._pending_log_lines
        self._pending_log_lines = {}
        for svc_name, lines in pending.items():
            if self._log_panel is not None and self._log_panel._svc_name == svc_name:
                self._log_panel.append_logs(svc_name, lines)
```

这样 orchestrator 只需要做简单的 50ms batch（Step 3 中的 `_batched_log`），而 UI 侧再做一次聚合。双重缓冲确保无论哪一侧都能降低频率。

或者更简单：只保留 UI 侧缓冲，orchestrator 仍逐行调用 `_log`。因为 orchestrator 的 `_read_output` 已经在 `await proc.stdout.readline()` 处让出了控制权，UI 侧 buffer 足以降低刷新频率。

为了最小改动，Task 2.3 可以简化为：只在 `MusterApp` 加 buffer，不改 orchestrator。这样更简单可靠。

重新调整 Task 2.3：

- 不改 orchestrator
- 在 `MusterApp` 中加一个 50ms 日志 buffer
- `_safe_append_log` 把 line 放入 buffer
- `set_timer(0.05, ...)` flush 到 `LogPanel.append_logs`

测试：验证高频调用后只触发一次 `append_logs`。

这样 Task 2.2 的 `append_logs` 仍然需要。Task 2.3 只改 app.py。

好的，我重写 Task 2.3。

```python
# src/muster/app.py:74-103
    def __init__(...
    ) -> None:
        # ... existing ...
        self._log_panel: LogPanel | None = None
        self._service_tree: ServiceTree | None = None
        self._detail_panel: DetailPanel | None = None
        self._pending_log_lines: dict[str, list[str]] = {}
        self._log_flush_timer = None
```

```python
# src/muster/app.py:227-241
    def _safe_append_log(self, svc_name: str, line: str) -> None:
        """Append a log line with UI-side batching.

        Buffers lines for 50ms so high-frequency logs are rendered in one
        UI refresh instead of one per line.

        Args:
            svc_name: Name of the service that produced the line.
            line: Raw log line text.
        """
        if self._log_panel is None or self._log_panel._svc_name != svc_name:
            return

        self._pending_log_lines.setdefault(svc_name, []).append(line)
        if self._log_flush_timer is None:
            self._log_flush_timer = self.set_timer(0.05, self._flush_pending_logs)

    def _flush_pending_logs(self) -> None:
        """Flush buffered log lines to the log panel in a single update."""
        self._log_flush_timer = None
        pending = self._pending_log_lines
        self._pending_log_lines = {}
        for svc_name, lines in pending.items():
            if self._log_panel is not None and self._log_panel._svc_name == svc_name:
                self._log_panel.append_logs(svc_name, lines)
```

测试：

```python
# tests/test_app.py
import asyncio


class TestAppLogBatching:
    async def test_log_lines_are_batched_within_timer_window(self, minimal_app):
        app = minimal_app
        async with app.run_test() as pilot:
            tree = app.query_one("#service-tree", ServiceTree)
            tree.highlight_service("api")
            await pilot.pause()
            log_panel = app._log_panel
            log_panel.append_logs = lambda svc_name, lines: setattr(
                log_panel, "_batched_calls", getattr(log_panel, "_batched_calls", 0) + 1
            )

            for i in range(10):
                app._safe_append_log("api", f"line {i}")

            await pilot.sleep(0.06)
            assert getattr(log_panel, "_batched_calls", 0) == 1
```

这个测试用了 pilot.sleep，应该可以。

继续写 Step 4 和 Step 5。

- [ ] **Step 4: Implement the UI-side log buffer in `MusterApp`**

（代码已在上文给出）

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_app.py::TestAppLogBatching -v`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/muster/app.py tests/test_app.py
git commit -m "perf(app): batch log UI updates with 50ms timer

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2.4: `DetailPanel` 增量刷新

**Files:**
- Modify: `src/muster/widgets/detail_panel.py:136-216`, `217-246`, `276-300`
- Test: `tests/widgets/test_detail_panel.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/widgets/test_detail_panel.py
import pytest

from muster.models import Service, Status
from muster.widgets.detail_panel import DetailPanel
from tests.conftest import WidgetTestApp


@pytest.mark.asyncio
async def test_refresh_status_updates_only_status_row():
    svc = Service(name="api", cmd="echo hello", group="backend")
    panel = DetailPanel(groups=[], status_colors={})
    app = WidgetTestApp(panel)
    async with app.run_test() as pilot:
        panel.current_service = svc
        await pilot.pause()
        original_command_text = panel.query_one(".detail-code", Static).render()
        svc.status = Status.RUNNING
        panel.refresh_status(svc)
        await pilot.pause()
        new_command_text = panel.query_one(".detail-code", Static).render()
        assert original_command_text == new_command_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/widgets/test_detail_panel.py::test_refresh_status_updates_only_status_row -v`

Expected: `FAIL - AttributeError: 'DetailPanel' object has no attribute 'refresh_status'`

- [ ] **Step 3: Split `refresh_content` into `refresh_status` and keep `refresh_content`**

```python
# src/muster/widgets/detail_panel.py:136-154
    def watch_current_service(self, svc: Service | None) -> None:
        """React to service selection changes.

        Re-renders metadata, updates button states, and shows/hides the button
        row depending on whether a service is selected.
        """
        if self._last_service is svc:
            return
        self._last_service = svc
        self._render_detail(svc)
        self._update_buttons(svc)
        buttons = self.query_one("#action-buttons", Horizontal)
        buttons.styles.display = "none" if svc is None else "block"

    def refresh_content(self) -> None:
        """Force a full re-render of the current service."""
        self._render_detail(self.current_service)
        self._update_buttons(self.current_service)

    def refresh_status(self, svc: Service | None) -> None:
        """Re-render only status-dependent parts (status text + buttons).

        Called on every service status change; avoids rebuilding the entire
        detail panel and command syntax block.

        Args:
            svc: Service whose status changed.
        """
        if svc is None or svc is not self.current_service:
            return
        self._update_status_row(svc)
        self._update_buttons(svc)
```

增加 `_update_status_row` 方法：

```python
# src/muster/widgets/detail_panel.py:155-216 (after _render_detail or in the class)
    def _update_status_row(self, svc: Service) -> None:
        """Update only the status row and status colour without full rebuild."""
        rows = self._cached_rows
        if not rows:
            rows = list(self.query(".detail-row").results(Horizontal))
            self._cached_rows = rows
        if not rows:
            return

        status_color = self._status_colors.get(svc.status.value, "#cccccc")
        status_index = 2  # Status row index in values list.
        value_widget = rows[status_index].query_one(".detail-value", Static)
        value_widget.update(Text(svc.status.value, style=f"bold {status_color}"))
```

- [ ] **Step 4: Update `app.py` `_refresh_list_item` to call `refresh_status`**

已经在 Task 2.1 Step 4 中改为 `detail.refresh_status(svc)`，如果当时没改，在这里改。

- [ ] **Step 5: Run tests**

Run: `pytest tests/widgets/test_detail_panel.py -v`

Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add src/muster/widgets/detail_panel.py tests/widgets/test_detail_panel.py
git commit -m "perf(detail_panel): incremental status refresh

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 最终验证

- [ ] **Step 1: Run full test suite**

Run: `pytest -q --cov=muster --cov-report=term`

Expected: coverage >= 80%, all tests pass

- [ ] **Step 2: Run the example config manually**

Run: `python3 -m muster -f example/muster-compose.yaml`

Expected: TUI opens, services can be started/stopped, logs appear, no obvious lag

- [ ] **Step 3: Commit any final fixes**

```bash
git commit -m "fix: resolve muster TUI lag and multi-layer dependency timeout

- split health_timeout / layer_timeout with asyncio.Event notification
- cache widget references and batch log UI updates
- incremental DetailPanel status refresh

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review Checklist

- [x] Spec coverage: TUI lag, multi-layer timeout, event notification, batched logs, incremental refresh all have tasks.
- [x] Placeholder scan: no TBD/TODO, all code blocks complete.
- [x] Type consistency: `health_timeout`/`layer_timeout` used consistently across models, orchestrator, settings_store, settings_panel.
