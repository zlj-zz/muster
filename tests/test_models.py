"""Unit tests for muster data models."""

from __future__ import annotations

import pytest

from muster.models import Service, Status


class TestServiceCmdFor:
    """Service.cmd_for() behaviour."""

    def test_dict_returns_correct_mode(self):
        svc = Service(name="api", cmd={"default": "go run main.go", "test": "go test"}, group="backend")
        assert svc.cmd_for("test") == "go test"

    def test_dict_falls_back_to_default(self):
        svc = Service(name="api", cmd={"default": "go run main.go", "test": "go test"}, group="backend")
        assert svc.cmd_for("prod") == "go run main.go"

    def test_dict_returns_empty_when_nothing_found(self):
        svc = Service(name="api", cmd={"test": "go test"}, group="backend")
        assert svc.cmd_for("default") == ""

    def test_str_returns_itself_for_any_mode(self):
        svc = Service(name="api", cmd="go run main.go", group="backend")
        assert svc.cmd_for("default") == "go run main.go"
        assert svc.cmd_for("test") == "go run main.go"


class TestServiceCmdModes:
    """Service.cmd_modes property."""

    def test_dict_returns_keys(self):
        svc = Service(name="api", cmd={"default": "go run main.go", "test": "go test"}, group="backend")
        assert set(svc.cmd_modes) == {"default", "test"}

    def test_str_returns_default_only(self):
        svc = Service(name="api", cmd="go run main.go", group="backend")
        assert svc.cmd_modes == ["default"]


class TestServiceDefaults:
    """Service constructor defaults."""

    def test_default_status_is_stopped(self):
        svc = Service(name="api", cmd="go run main.go", group="backend")
        assert svc.status == Status.STOPPED

    def test_default_depends_on_is_empty(self):
        svc = Service(name="api", cmd="go run main.go", group="backend")
        assert svc.depends_on == []

    def test_default_port_is_none(self):
        svc = Service(name="api", cmd="go run main.go", group="backend")
        assert svc.port is None
