"""Tests for ServiceTree widget."""

from __future__ import annotations

import pytest

from muster.models import Group, Service, Status
from muster.widgets.service_tree import ServiceTree
from tests.conftest import WidgetTestApp, capture_messages


@pytest.fixture
def sample_tree():
    groups = [
        Group(id="backend", label="BACKEND", color="#569cd6", order=0),
        Group(id="frontend", label="FRONTEND", color="#ce9178", order=1),
    ]
    services = [
        Service(name="api", cmd="go run api.go", group="backend", port=8080),
        Service(name="worker", cmd="go run worker.go", group="backend", port=8081),
        Service(name="web", cmd="npm run dev", group="frontend", port=3000),
    ]
    status_colors = {"stopped": "#5c6370", "running": "#98c379"}
    return ServiceTree(services, groups, status_colors)


class TestServiceTreeBuild:
    """Tree construction from services and groups."""

    async def test_builds_group_nodes(self, sample_tree):
        app = WidgetTestApp(sample_tree)
        async with app.run_test() as pilot:
            tree = app.query_one(ServiceTree)
            root_children = tree.root.children
            assert len(root_children) == 2
            labels = [str(n.label) for n in root_children]
            assert "BACKEND" in labels[0]
            assert "FRONTEND" in labels[1]

    async def test_builds_service_leaves(self, sample_tree):
        app = WidgetTestApp(sample_tree)
        async with app.run_test() as pilot:
            tree = app.query_one(ServiceTree)
            backend_node = tree.root.children[0]
            assert len(backend_node.children) == 2
            names = [str(n.label) for n in backend_node.children]
            assert any("api" in n for n in names)
            assert any("worker" in n for n in names)

    async def test_empty_services_no_groups(self):
        tree = ServiceTree([], [Group("g", "G", "#fff", 0)], {})
        app = WidgetTestApp(tree)
        async with app.run_test() as pilot:
            tree = app.query_one(ServiceTree)
            assert len(tree.root.children) == 0


class TestServiceTreeSelection:
    """Node selection and message posting."""

    async def test_select_service_moves_cursor(self, sample_tree):
        app = WidgetTestApp(sample_tree)
        async with app.run_test() as pilot:
            tree = app.query_one(ServiceTree)
            tree.select_service("api")
            await pilot.pause()
            assert tree.current_service is not None
            assert tree.current_service.name == "api"

    async def test_highlight_service(self, sample_tree):
        app = WidgetTestApp(sample_tree)
        async with app.run_test() as pilot:
            tree = app.query_one(ServiceTree)
            tree.highlight_service("web")
            await pilot.pause()
            assert tree.current_service is not None
            assert tree.current_service.name == "web"

    async def test_service_highlighted_message(self, sample_tree):
        app = WidgetTestApp(sample_tree)
        async with app.run_test() as pilot:
            tree = app.query_one(ServiceTree)
            messages = capture_messages(tree, ServiceTree.ServiceHighlighted)
            tree.highlight_service("api")
            await pilot.pause()
            assert len(messages) == 1
            assert messages[0].service.name == "api"


class TestServiceTreeRefresh:
    """Dynamic label updates."""

    async def test_refresh_node_updates_label(self, sample_tree):
        app = WidgetTestApp(sample_tree)
        async with app.run_test() as pilot:
            tree = app.query_one(ServiceTree)
            svc = tree.services[0]
            svc.status = Status.RUNNING
            tree.refresh_node(svc)
            node = tree._node_map["api"]
            label_text = str(node.label)
            assert "api" in label_text
