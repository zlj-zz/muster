"""Unit tests for environment dependency checking."""

from __future__ import annotations

from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from muster.core.env import (
    _check_one,
    _compile_pattern,
    check_http,
    check_proc,
    check_tcp,
)
from muster.models import EnvCheck


class TestCheckTcp:
    """TCP connectivity checks."""

    @patch("muster.core.env.socket.create_connection")
    def test_success(self, mock_create):
        mock_create.return_value.__enter__ = MagicMock(return_value=None)
        mock_create.return_value.__exit__ = MagicMock(return_value=False)
        ok, latency = check_tcp("127.0.0.1", 8080)
        assert ok is True
        assert isinstance(latency, int)
        mock_create.assert_called_once_with(("127.0.0.1", 8080), timeout=1.0)

    @patch("muster.core.env.socket.create_connection")
    def test_failure(self, mock_create):
        mock_create.side_effect = OSError("Connection refused")
        ok, latency = check_tcp("127.0.0.1", 8080)
        assert ok is False
        assert latency is None


class TestCheckHttp:
    """HTTP endpoint checks."""

    @patch("muster.core.env.urlopen")
    def test_success(self, mock_urlopen):
        resp = MagicMock()
        resp.getcode.return_value = 200
        mock_urlopen.return_value.__enter__ = MagicMock(return_value=resp)
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)
        ok, latency = check_http("http://127.0.0.1:8080/health")
        assert ok is True
        assert isinstance(latency, int)

    @patch("muster.core.env.urlopen")
    def test_wrong_status(self, mock_urlopen):
        resp = MagicMock()
        resp.getcode.return_value = 500
        mock_urlopen.return_value.__enter__ = MagicMock(return_value=resp)
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)
        ok, latency = check_http("http://127.0.0.1:8080/health", expect_status=200)
        assert ok is False

    @patch("muster.core.env.urlopen")
    def test_custom_method(self, mock_urlopen):
        resp = MagicMock()
        resp.getcode.return_value = 200
        mock_urlopen.return_value.__enter__ = MagicMock(return_value=resp)
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)
        check_http("http://127.0.0.1:8080/health", method="POST")
        req = mock_urlopen.call_args[0][0]
        assert req.get_method() == "POST"

    @patch("muster.core.env.urlopen")
    def test_connection_error(self, mock_urlopen):
        from urllib.error import URLError

        mock_urlopen.side_effect = URLError("Connection refused")
        ok, latency = check_http("http://127.0.0.1:8080/health")
        assert ok is False
        assert latency is None


class TestCheckProc:
    """Process existence checks."""

    @patch("muster.core.env.subprocess.run")
    def test_found(self, mock_run):
        mock_run.return_value.stdout = "python3\nnode\nnginx\n"
        assert check_proc("nginx") is True

    @patch("muster.core.env.subprocess.run")
    def test_not_found(self, mock_run):
        mock_run.return_value.stdout = "python3\nnode\n"
        assert check_proc("nginx") is False

    def test_empty_pattern(self):
        assert check_proc("") is False

    @patch("muster.core.env.subprocess.run")
    def test_regex_match(self, mock_run):
        mock_run.return_value.stdout = "python3.11\npython3.12\n"
        assert check_proc(r"python3\.\d+") is True

    @patch("muster.core.env.subprocess.run")
    def test_subprocess_error_returns_false(self, mock_run):
        mock_run.side_effect = OSError("command not found")
        assert check_proc("nginx") is False


class TestCheckOne:
    """Dispatcher logic in _check_one."""

    @patch("muster.core.env.check_tcp", return_value=(True, 5))
    def test_tcp(self, mock_check_tcp):
        ec = EnvCheck(name="etcd", type="tcp", host="127.0.0.1", port=2379)
        name, ok = _check_one(ec)
        assert ok is True
        assert ec.latency_ms == 5
        assert ec.consecutive_failures == 0
        mock_check_tcp.assert_called_once_with("127.0.0.1", 2379)

    @patch("muster.core.env.check_http", return_value=(True, 10))
    def test_http(self, mock_check_http):
        ec = EnvCheck(name="api", type="http", url="http://127.0.0.1/health")
        name, ok = _check_one(ec)
        assert ok is True
        assert ec.latency_ms == 10
        mock_check_http.assert_called_once_with("http://127.0.0.1/health", None, None)

    @patch("muster.core.env.check_proc", return_value=True)
    def test_proc(self, mock_check_proc):
        ec = EnvCheck(name="nginx", type="proc", pattern="nginx")
        name, ok = _check_one(ec)
        assert ok is True
        assert ec.latency_ms is None  # proc has no latency
        mock_check_proc.assert_called_once_with("nginx")

    def test_unknown_type(self):
        ec = EnvCheck(name="x", type="unknown")
        name, ok = _check_one(ec)
        assert ok is False
        assert ec.consecutive_failures == 1

    @patch("muster.core.env.check_tcp", return_value=(False, None))
    def test_failure_increments_counter(self, mock_check_tcp):
        ec = EnvCheck(name="etcd", type="tcp", host="127.0.0.1", port=2379)
        ec.consecutive_failures = 2
        _check_one(ec)
        assert ec.consecutive_failures == 3


class TestCompilePattern:
    """Regex compilation caching."""

    def test_same_pattern_returns_same_object(self):
        a = _compile_pattern("python")
        b = _compile_pattern("python")
        assert a is b

    def test_different_pattern_returns_different_object(self):
        a = _compile_pattern("python")
        b = _compile_pattern("node")
        assert a is not b
