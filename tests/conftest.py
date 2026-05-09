"""Shared pytest fixtures for muster tests."""

from __future__ import annotations

import pytest

from muster.models import EnvCheck, Group, MusterConfig, PortDiscovery, Service, Status


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
        Service(name="api", cmd="go run api.go", group="backend", port=8080, depends_on=[]),
        Service(name="worker", cmd="go run worker.go", group="backend", port=8081, depends_on=["api"]),
        Service(name="web", cmd="npm run dev", group="frontend", port=3000, depends_on=["api"]),
    ]


@pytest.fixture
def tmp_yaml(tmp_path):
    """Write a temporary muster-compose.yaml and return the Path."""

    def _write(content: str) -> None:
        path = tmp_path / "muster-compose.yaml"
        path.write_text(content, encoding="utf-8")
        return path

    return _write
