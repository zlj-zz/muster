"""Tests for EnvList widget."""

from __future__ import annotations

import pytest

from muster.models import EnvCheck, Group, MusterConfig, PortDiscovery
from muster.widgets.env_list import EnvList
from tests.conftest import WidgetTestApp, capture_messages


@pytest.fixture
def sample_env_config():
    return MusterConfig(
        env_checks=[
            EnvCheck(name="etcd", type="tcp", host="127.0.0.1", port=2379),
            EnvCheck(name="mysql", type="tcp", host="127.0.0.1", port=3306),
        ],
        groups=[Group(id="backend", label="BACKEND", color="#569cd6", order=0)],
        port_discovery=PortDiscovery(enabled=False),
    )


class TestEnvListBuild:
    """Tree construction from env checks."""

    async def test_builds_env_nodes(self, sample_env_config):
        env_list = EnvList(sample_env_config)
        app = WidgetTestApp(env_list)
        async with app.run_test() as pilot:
            env_list = app.query_one(EnvList)
            assert len(env_list.root.children) == 2
            names = [str(n.label) for n in env_list.root.children]
            assert any("etcd" in n for n in names)
            assert any("mysql" in n for n in names)

    async def test_empty_checks_no_nodes(self):
        config = MusterConfig(
            env_checks=[],
            groups=[Group(id="g", label="G", color="#fff", order=0)],
            port_discovery=PortDiscovery(enabled=False),
        )
        env_list = EnvList(config)
        app = WidgetTestApp(env_list)
        async with app.run_test() as pilot:
            env_list = app.query_one(EnvList)
            assert len(env_list.root.children) == 0


class TestEnvListRefresh:
    """Status refresh."""

    async def test_refresh_updates_labels(self, sample_env_config):
        env_list = EnvList(sample_env_config)
        app = WidgetTestApp(env_list)
        async with app.run_test() as pilot:
            env_list = app.query_one(EnvList)
            env_list.refresh_checks([("etcd", True), ("mysql", False)])
            etcd_node = env_list._node_map["etcd"]
            mysql_node = env_list._node_map["mysql"]
            assert "ok" in str(etcd_node.label)
            assert "fail" in str(mysql_node.label)


class TestEnvListSelection:
    """Node selection and messages."""

    async def test_env_highlighted_message(self, sample_env_config):
        env_list = EnvList(sample_env_config)
        app = WidgetTestApp(env_list)
        async with app.run_test() as pilot:
            env_list = app.query_one(EnvList)
            messages = capture_messages(env_list, EnvList.EnvHighlighted)
            env_list.select_node(env_list.root.children[0])
            await pilot.pause()
            assert len(messages) == 1
            assert messages[0].env_check.name == "etcd"

    async def test_current_env_returns_selected(self, sample_env_config):
        env_list = EnvList(sample_env_config)
        app = WidgetTestApp(env_list)
        async with app.run_test() as pilot:
            env_list = app.query_one(EnvList)
            env_list.select_node(env_list.root.children[0])
            assert env_list.current_env is not None
            assert env_list.current_env.name == "etcd"
