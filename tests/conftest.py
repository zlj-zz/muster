"""Shared pytest fixtures for muster tests."""

from __future__ import annotations

from typing import TypeVar
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from textual.app import App, ComposeResult

from muster.models import EnvCheck, Group, MusterConfig, PortDiscovery, Service, Status

T = TypeVar("T")


class WidgetTestApp(App):
    """Minimal app wrapper for testing a single widget."""

    CSS = "Screen { align: center middle; }"

    def __init__(self, widget, **kwargs) -> None:
        super().__init__(**kwargs)
        self._widget = widget

    def compose(self) -> ComposeResult:
        yield self._widget


def capture_messages(widget, msg_type: type[T]) -> list[T]:
    """Monkey-patch *widget.post_message* to capture messages of *msg_type*."""
    captured: list[T] = []
    _orig = widget.post_message

    def _hook(msg):
        if isinstance(msg, msg_type):
            captured.append(msg)
        return _orig(msg)

    widget.post_message = _hook
    return captured


@pytest.fixture(autouse=True)
def _patch_check_env():
    """Patch ``check_env`` so App ``on_mount`` never makes real TCP calls."""
    with patch("muster.app.check_env", return_value=[("etcd", True)]):
        yield


@pytest.fixture
def sample_config() -> MusterConfig:
    """Return a minimal MusterConfig with two groups and two env checks."""
    return MusterConfig(
        env_checks=[
            EnvCheck(name="etcd", type="tcp", host="127.0.0.1", port=2379),
            EnvCheck(name="mysql", type="tcp", host="127.0.0.1", port=3306),
        ],
        groups=[
            Group(id="backend", label="BACKEND", color="#569cd6", order=0),
            Group(id="frontend", label="FRONTEND", color="#ce9178", order=1),
        ],
        port_discovery=PortDiscovery(enabled=False),
    )


@pytest.fixture
def sample_services() -> list[Service]:
    """Return a list of Service instances for resolver/orchestrator tests."""
    return [
        Service(
            name="api", cmd="go run api.go", group="backend", port=8080, depends_on=[]
        ),
        Service(
            name="worker",
            cmd="go run worker.go",
            group="backend",
            port=8081,
            depends_on=["api"],
        ),
        Service(
            name="web",
            cmd="npm run dev",
            group="frontend",
            port=3000,
            depends_on=["api"],
        ),
    ]


@pytest.fixture
def tmp_yaml(tmp_path):
    """Write a temporary muster-compose.yaml and return the Path."""

    def _write(content: str) -> None:
        path = tmp_path / "muster-compose.yaml"
        path.write_text(content, encoding="utf-8")
        return path

    return _write


# --- TUI fixtures ---


@pytest.fixture
def minimal_config() -> MusterConfig:
    """Return a minimal MusterConfig for TUI tests."""
    return MusterConfig(
        env_checks=[
            EnvCheck(name="etcd", type="tcp", host="127.0.0.1", port=2379),
        ],
        groups=[
            Group(id="backend", label="BACKEND", color="#569cd6", order=0),
            Group(id="frontend", label="FRONTEND", color="#ce9178", order=1),
        ],
        port_discovery=PortDiscovery(enabled=False),
    )


@pytest.fixture
def minimal_services() -> list[Service]:
    """Return a minimal service list for TUI tests."""
    return [
        Service(name="api", cmd="go run api.go", group="backend", port=8080),
        Service(name="web", cmd="npm run dev", group="frontend", port=3000),
    ]


@pytest.fixture
def minimal_app(minimal_config, minimal_services):
    """Return a MusterApp with a mocked orchestrator for TUI tests.

    The orchestrator is replaced with a MagicMock so that no real subprocesses
    are created during App tests.
    """
    from muster.app import MusterApp

    registry = {s.name: s for s in minimal_services}
    app = MusterApp(
        config=minimal_config,
        services=minimal_services,
        registry=registry,
    )
    app._orchestrator = MagicMock()
    app._orchestrator.stop_all = AsyncMock()
    app._orchestrator.cleanup = AsyncMock()
    app._orchestrator.start_with_deps = AsyncMock()
    app._orchestrator.stop = AsyncMock()
    app._orchestrator.restart = AsyncMock()
    return app
