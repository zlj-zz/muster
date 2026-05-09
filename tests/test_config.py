"""Unit tests for muster configuration loading."""

from __future__ import annotations

import pytest

from muster.config import (
    DEFAULT_ENV_CHECKS,
    DEFAULT_GROUPS,
    load_config,
)


class TestLoadConfigMinimal:
    """Happy-path loading of a minimal config."""

    def test_minimal(self, tmp_yaml):
        path = tmp_yaml("""
config:
  groups:
    - id: backend
      label: BACKEND
      color: "#569cd6"
      order: 0
  env_checks:
    - name: etcd
      type: tcp
      host: 127.0.0.1
      port: 2379

services:
  - name: api
    cmd: go run api.go
    group: backend
    port: 8080
""")
        config, services = load_config(path)
        assert len(config.groups) == 1
        assert config.groups[0].id == "backend"
        assert len(services) == 1
        assert services[0].name == "api"
        assert services[0].port == 8080

    def test_empty_yaml_falls_back_to_defaults(self, tmp_yaml):
        path = tmp_yaml("")
        config, services = load_config(path)
        assert len(config.env_checks) == len(DEFAULT_ENV_CHECKS)
        assert len(config.groups) == len(DEFAULT_GROUPS)
        assert len(services) == 0


class TestLoadConfigEnvChecks:
    """Parsing of all env check types."""

    def test_tcp(self, tmp_yaml):
        path = tmp_yaml("""
config:
  env_checks:
    - name: redis
      type: tcp
      host: 127.0.0.1
      port: 6379
""")
        config, _ = load_config(path)
        assert config.env_checks[0].type == "tcp"
        assert config.env_checks[0].port == 6379

    def test_http(self, tmp_yaml):
        path = tmp_yaml("""
config:
  env_checks:
    - name: health
      type: http
      url: http://127.0.0.1:8080/health
      method: GET
      expect_status: 200
""")
        config, _ = load_config(path)
        assert config.env_checks[0].type == "http"
        assert config.env_checks[0].url == "http://127.0.0.1:8080/health"
        assert config.env_checks[0].method == "GET"
        assert config.env_checks[0].expect_status == 200

    def test_proc(self, tmp_yaml):
        path = tmp_yaml("""
config:
  env_checks:
    - name: nginx
      type: proc
      pattern: nginx
""")
        config, _ = load_config(path)
        assert config.env_checks[0].type == "proc"
        assert config.env_checks[0].pattern == "nginx"


class TestLoadConfigBackwardCompat:
    """Backward-compatible parsing of legacy keys."""

    def test_layer_alias_for_group(self, tmp_yaml):
        path = tmp_yaml("""
config:
  groups:
    - id: backend
      label: BACKEND
      color: "#569cd6"
      order: 0

services:
  - name: api
    cmd: go run api.go
    layer: backend
""")
        _, services = load_config(path)
        assert services[0].group == "backend"

    def test_cmd_test_merged_into_dict(self, tmp_yaml):
        path = tmp_yaml("""
config:
  groups:
    - id: backend
      label: BACKEND
      color: "#569cd6"
      order: 0

services:
  - name: api
    cmd: go run main.go
    cmd_test: go test
    group: backend
""")
        _, services = load_config(path)
        assert isinstance(services[0].cmd, dict)
        assert services[0].cmd["default"] == "go run main.go"
        assert services[0].cmd["test"] == "go test"


class TestLoadConfigMissingFile:
    """Error handling."""

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "does-not-exist.yaml")


class TestLoadConfigPortDiscovery:
    """Port discovery parsing."""

    def test_enabled_populates_rules(self, tmp_yaml):
        path = tmp_yaml("""
config:
  port_discovery:
    enabled: true
    config_dir: etc
    config_pattern: "*.yaml"
    exclude_pattern: '_(test|prod)\\.yaml$'
    rules:
      - regex: '^\\s*ListenOn:\\s*.*:(\\d+)\\s*$'
""")
        config, _ = load_config(path)
        assert config.port_discovery.enabled is True
        assert config.port_discovery.config_dir == "etc"
        assert len(config.port_discovery.rules) == 1

    def test_disabled(self, tmp_yaml):
        path = tmp_yaml("""
config:
  port_discovery:
    enabled: false
""")
        config, _ = load_config(path)
        assert config.port_discovery.enabled is False
