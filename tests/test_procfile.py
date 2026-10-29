"""Tests for Procfile parsing and compose generation."""

from __future__ import annotations

import pytest

from muster.config import load_config
from muster.core.procfile import parse_procfile, procfile_to_compose


class TestParseProcfile:
    def test_parses_services_in_order(self):
        text = "web: npm start\napi: go run main.go\n"
        services = parse_procfile(text)
        assert services == {"web": "npm start", "api": "go run main.go"}
        assert list(services)[0] == "web"  # declaration order preserved

    def test_comments_and_blank_lines_ignored(self):
        text = "# comment\n\nweb: npm start\n  \n# another\n"
        assert parse_procfile(text) == {"web": "npm start"}

    def test_invalid_line_raises(self):
        with pytest.raises(ValueError, match="line 2"):
            parse_procfile("web: npm start\nno-colon-here\n")

    def test_empty_procfile_raises(self):
        with pytest.raises(ValueError, match="no services"):
            parse_procfile("# only comments\n")

    def test_command_may_contain_colons(self):
        text = "web: python -m http.server 8000 --bind 127.0.0.1:8000\n"
        assert parse_procfile(text)["web"] == (
            "python -m http.server 8000 --bind 127.0.0.1:8000"
        )


class TestComposeRoundTrip:
    def test_generated_yaml_loads_back(self, tmp_path):
        services = parse_procfile("web: npm start\napi: go run .\n")
        out = tmp_path / "muster-compose.yaml"
        out.write_text(procfile_to_compose(services), encoding="utf-8")

        config, loaded = load_config(out)
        assert [s.name for s in loaded] == ["web", "api"]
        assert loaded[0].cmd == "npm start"
        assert loaded[0].group == "default"
        assert config.groups[0].id == "default"
