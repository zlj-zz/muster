"""Tests for the configuration validator."""

from __future__ import annotations

import pytest

from muster.core.validator import ConfigError, validate_config
from muster.models import EnvCheck, Group, MusterConfig, PortDiscovery, Service


class TestValidateConfig:
    """Fatal errors raise ValueError; warnings are returned as strings."""

    def test_valid_config_no_warnings(self, sample_config, sample_services):
        warnings = validate_config(sample_config, sample_services)
        assert warnings == []

    def test_duplicate_service_name(self, sample_config):
        services = [
            Service(name="api", cmd="a", group="backend"),
            Service(name="api", cmd="b", group="frontend"),
        ]
        with pytest.raises(ConfigError, match="duplicate service name: 'api'"):
            validate_config(sample_config, services)

    def test_empty_cmd_string(self, sample_config):
        services = [Service(name="api", cmd="", group="backend")]
        with pytest.raises(ConfigError, match="cmd is empty"):
            validate_config(sample_config, services)

    def test_empty_cmd_dict(self, sample_config):
        services = [Service(name="api", cmd={}, group="backend")]
        with pytest.raises(ConfigError, match="cmd dict must not be empty"):
            validate_config(sample_config, services)

    def test_empty_cmd_dict_value(self, sample_config):
        services = [Service(name="api", cmd={"default": ""}, group="backend")]
        with pytest.raises(ConfigError, match="cmd for mode 'default' is empty"):
            validate_config(sample_config, services)

    def test_missing_group(self, sample_config):
        services = [Service(name="api", cmd="go run", group="unknown")]
        with pytest.raises(ConfigError, match="group 'unknown' is not defined"):
            validate_config(sample_config, services)

    def test_missing_dependency(self, sample_config):
        services = [
            Service(name="api", cmd="go run", group="backend"),
            Service(
                name="worker", cmd="go run", group="backend", depends_on=["missing"]
            ),
        ]
        with pytest.raises(ConfigError, match="depends_on 'missing' does not exist"):
            validate_config(sample_config, services)

    def test_circular_dependency(self, sample_config):
        services = [
            Service(name="a", cmd="a", group="backend", depends_on=["b"]),
            Service(name="b", cmd="b", group="backend", depends_on=["a"]),
        ]
        with pytest.raises(ConfigError, match="circular dependency"):
            validate_config(sample_config, services)

    @pytest.mark.parametrize(
        "bad_port",
        [0, -1, 65536, 100000],
    )
    def test_port_out_of_range(self, sample_config, bad_port):
        services = [Service(name="api", cmd="go run", group="backend", port=bad_port)]
        with pytest.raises(ConfigError, match="out of range"):
            validate_config(sample_config, services)

    def test_port_conflict_warning(self, sample_config):
        services = [
            Service(name="api", cmd="a", group="backend", port=8080),
            Service(name="worker", cmd="b", group="backend", port=8080),
        ]
        warnings = validate_config(sample_config, services)
        assert len(warnings) == 1
        assert "port 8080 is declared by multiple services" in warnings[0]

    def test_env_check_unknown_type_warning(self):
        config = MusterConfig(
            env_checks=[EnvCheck(name="x", type="ftp")],
            groups=[Group(id="g", label="G", color="#fff", order=0)],
            port_discovery=PortDiscovery(enabled=False),
        )
        warnings = validate_config(config, [Service(name="s", cmd="c", group="g")])
        assert any("unknown type 'ftp'" in w for w in warnings)

    def test_env_check_tcp_missing_port(self):
        config = MusterConfig(
            env_checks=[EnvCheck(name="x", type="tcp")],
            groups=[Group(id="g", label="G", color="#fff", order=0)],
            port_discovery=PortDiscovery(enabled=False),
        )
        with pytest.raises(ConfigError, match="port is required"):
            validate_config(config, [Service(name="s", cmd="c", group="g")])

    def test_env_check_http_missing_url(self):
        config = MusterConfig(
            env_checks=[EnvCheck(name="x", type="http")],
            groups=[Group(id="g", label="G", color="#fff", order=0)],
            port_discovery=PortDiscovery(enabled=False),
        )
        with pytest.raises(ConfigError, match="url is required"):
            validate_config(config, [Service(name="s", cmd="c", group="g")])

    def test_env_check_proc_missing_pattern(self):
        config = MusterConfig(
            env_checks=[EnvCheck(name="x", type="proc")],
            groups=[Group(id="g", label="G", color="#fff", order=0)],
            port_discovery=PortDiscovery(enabled=False),
        )
        with pytest.raises(ConfigError, match="pattern is required"):
            validate_config(config, [Service(name="s", cmd="c", group="g")])
