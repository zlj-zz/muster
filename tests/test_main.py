"""Tests for __main__ CLI entry point."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from muster.__main__ import main

_MINIMAL_YAML = """
config:
  groups:
    - id: backend
      label: BACKEND
      color: "#569cd6"
      order: 0
services:
  - name: api
    cmd: echo hello
    group: backend
"""


class TestMain:
    """CLI argument parsing and app launch."""

    def test_main_runs_app(self, tmp_yaml, monkeypatch):
        path = tmp_yaml(_MINIMAL_YAML)

        mock_app = MagicMock()
        with patch("muster.__main__.MusterApp") as mock_cls:
            mock_cls.return_value = mock_app
            monkeypatch.setattr(sys, "argv", ["muster", "-f", str(path)])
            main()

        mock_app.run.assert_called_once()
        assert mock_cls.call_args.kwargs["cmd_mode"] == "default"

    def test_main_custom_mode(self, tmp_yaml, monkeypatch):
        path = tmp_yaml(_MINIMAL_YAML)

        mock_app = MagicMock()
        with patch("muster.__main__.MusterApp") as mock_cls:
            mock_cls.return_value = mock_app
            monkeypatch.setattr(sys, "argv", ["muster", "-f", str(path), "-m", "test"])
            main()

        assert mock_cls.call_args.kwargs["cmd_mode"] == "test"

    def test_main_file_not_found(self, tmp_path, monkeypatch, capsys):
        missing = tmp_path / "missing.yaml"
        monkeypatch.setattr(sys, "argv", ["muster", "-f", str(missing)])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "config file not found" in captured.err

    def test_main_resolves_ports(self, tmp_yaml, monkeypatch):
        yaml = """
config:
  groups:
    - id: backend
      label: BACKEND
      color: "#569cd6"
      order: 0
  port_discovery:
    enabled: true
    config_dir: etc
    config_pattern: '*.yaml'
    exclude_pattern: '_(test|prod)\\.yaml$'
    rules:
      - regex: '^\\s*ListenOn:\\s*.*:(\\d+)\\s*$'
services:
  - name: api
    cmd: echo hello
    group: backend
"""
        path = tmp_yaml(yaml)

        mock_app = MagicMock()
        with patch("muster.__main__.MusterApp") as mock_cls:
            mock_cls.return_value = mock_app
            with patch("muster.__main__.resolve_port", return_value=9999):
                monkeypatch.setattr(sys, "argv", ["muster", "-f", str(path)])
                main()

        services = mock_cls.call_args.kwargs["services"]
        assert services[0].port == 9999
