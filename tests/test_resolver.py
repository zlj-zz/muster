"""Unit tests for dependency resolution and port discovery."""

from __future__ import annotations

import pytest

from muster.core.resolver import resolve_dependencies, resolve_port, sort_by_group
from muster.models import Group, PortDiscovery, Service


class TestResolveDependencies:
    """Topological ordering via DFS."""

    def test_linear_chain(self):
        svcs = [
            Service("c", "cmd", "g", depends_on=["b"]),
            Service("b", "cmd", "g", depends_on=["a"]),
            Service("a", "cmd", "g"),
        ]
        registry = {s.name: s for s in svcs}
        result = resolve_dependencies(["c"], registry)
        names = [s.name for s in result]
        assert names == ["a", "b", "c"]

    def test_diamond_graph(self):
        svcs = [
            Service("bottom", "cmd", "g", depends_on=["left", "right"]),
            Service("left", "cmd", "g", depends_on=["top"]),
            Service("right", "cmd", "g", depends_on=["top"]),
            Service("top", "cmd", "g"),
        ]
        registry = {s.name: s for s in svcs}
        result = resolve_dependencies(["bottom"], registry)
        names = [s.name for s in result]
        assert names.index("top") < names.index("left")
        assert names.index("top") < names.index("right")
        assert names.index("left") < names.index("bottom")
        assert names.index("right") < names.index("bottom")
        assert len(names) == 4  # no duplicates

    def test_cycle_raises(self):
        svcs = [
            Service("a", "cmd", "g", depends_on=["b"]),
            Service("b", "cmd", "g", depends_on=["a"]),
        ]
        registry = {s.name: s for s in svcs}
        with pytest.raises(ValueError, match="circular dependency"):
            resolve_dependencies(["a"], registry)

    def test_unknown_service_ignored(self):
        svcs = [Service("a", "cmd", "g")]
        registry = {s.name: s for s in svcs}
        result = resolve_dependencies(["a", "missing"], registry)
        assert [s.name for s in result] == ["a"]

    def test_already_visited_skipped(self):
        svcs = [
            Service("a", "cmd", "g"),
            Service("b", "cmd", "g", depends_on=["a"]),
            Service("c", "cmd", "g", depends_on=["a"]),
        ]
        registry = {s.name: s for s in svcs}
        result = resolve_dependencies(["b", "c"], registry)
        names = [s.name for s in result]
        assert names == ["a", "b", "c"]  # a appears once


class TestSortByGroup:
    """Ordering by group order field."""

    def test_sorts_by_group_order(self):
        groups = [
            Group("infra", "INFRA", "#fff", 0),
            Group("app", "APP", "#fff", 1),
        ]
        svcs = [
            Service("web", "cmd", "app"),
            Service("db", "cmd", "infra"),
        ]
        result = sort_by_group(svcs, groups)
        assert [s.name for s in result] == ["db", "web"]

    def test_unknown_group_goes_last(self):
        groups = [Group("a", "A", "#fff", 0)]
        svcs = [
            Service("z", "cmd", "z"),
            Service("a", "cmd", "a"),
        ]
        result = sort_by_group(svcs, groups)
        assert [s.name for s in result] == ["a", "z"]


class TestResolvePort:
    """Auto-discovery from YAML config files."""

    def test_found(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        svc_dir = tmp_path / "svc" / "etc"
        svc_dir.mkdir(parents=True)
        (svc_dir / "svc.yaml").write_text("ListenOn: 0.0.0.0:8080\n")
        discovery = PortDiscovery(
            enabled=True,
            rules=[{"regex": r"^\s*ListenOn:\s*.*:(\d+)\s*$"}],
        )
        assert resolve_port("svc", discovery) == 8080

    def test_disabled_returns_none(self, tmp_path):
        discovery = PortDiscovery(enabled=False)
        assert resolve_port("svc", discovery) is None

    def test_no_match_returns_none(self, tmp_path):
        svc_dir = tmp_path / "svc" / "etc"
        svc_dir.mkdir(parents=True)
        (svc_dir / "svc.yaml").write_text("Foo: bar\n")
        discovery = PortDiscovery(
            enabled=True,
            rules=[{"regex": r"^\s*ListenOn:\s*.*:(\d+)\s*$"}],
        )
        assert resolve_port("svc", discovery) is None

    def test_excluded_file_skipped(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        svc_dir = tmp_path / "svc" / "etc"
        svc_dir.mkdir(parents=True)
        (svc_dir / "svc_test.yaml").write_text("ListenOn: 0.0.0.0:8080\n")
        (svc_dir / "svc.yaml").write_text("ListenOn: 0.0.0.0:9090\n")
        discovery = PortDiscovery(
            enabled=True,
            exclude_pattern=r"_(test|prod)\.yaml$",
            rules=[{"regex": r"^\s*ListenOn:\s*.*:(\d+)\s*$"}],
        )
        assert resolve_port("svc", discovery) == 9090

    def test_no_config_dir_returns_none(self, tmp_path):
        discovery = PortDiscovery(enabled=True)
        assert resolve_port("nonexistent", discovery) is None
