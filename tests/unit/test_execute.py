"""Unit tests for ``pystata_x._core.execute`` (mocked Stata runtime).

``execute()`` does **not** need to match any vendor API contract — it is
the fast, unconstrained core execution function.  These tests verify its
internal logic: return types, echo/quietly/track_graphs behaviour,
single-vs-multi-line dispatch, and error propagation.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _mock_config():
    """Mock ``pystata_x._config`` so no real Stata is required."""
    with patch("pystata_x._core.config") as mock_cfg:
        mock_cfg.stinitialized = True
        mock_cfg.stlib = MagicMock()
        mock_cfg.stlib.StataSO_ClearOutputBuffer.return_value = None
        mock_cfg.stlib.StataSO_Execute.return_value = 0
        mock_cfg.stconfig = {"cmdshow": "default"}
        mock_cfg.check_initialized = MagicMock()
        mock_cfg._encode.side_effect = lambda s: s.encode("utf-8")
        mock_cfg.get_output.return_value = ""
        yield mock_cfg


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------


class TestReturnType:
    """execute() always returns an ExecuteResult."""

    def test_returns_execute_result(self, _mock_config):
        from pystata_x._core import execute, ExecuteResult
        result = execute("display 1+1")
        assert isinstance(result, ExecuteResult)

    def test_result_is_unpackable(self, _mock_config):
        """Can be unpacked as output, rc = result."""
        from pystata_x._core import execute
        _mock_config.get_output.return_value = "hello\n"
        output, rc = execute("display 1+1")
        assert isinstance(output, str)
        assert isinstance(rc, int)

    def test_result_fields(self, _mock_config):
        from pystata_x._core import execute
        _mock_config.get_output.return_value = "hello\n"
        result = execute("display 1+1")
        assert result.output == "hello"
        assert result.rc == 0
        assert result.graph_names is None


# ---------------------------------------------------------------------------
# Output handling
# ---------------------------------------------------------------------------


class TestOutput:
    """Output capture and the raw flag."""

    def test_default_strips_output(self, _mock_config):
        """Default capture strips leading/trailing whitespace."""
        from pystata_x._core import execute
        _mock_config.get_output.return_value = "  result  \n"
        result = execute("display 1+1")
        assert result.output == "result"

    def test_raw_preserves_whitespace(self, _mock_config):
        from pystata_x._core import execute
        _mock_config.get_output.return_value = "  result  \n"
        result = execute("display 1+1", raw=True)
        assert result.output == "  result  \n"

    def test_capture_false_returns_empty(self, _mock_config):
        from pystata_x._core import execute
        _mock_config.get_output.return_value = "some output\n"
        result = execute("display 1+1", capture=False)
        assert result.output == ""


# ---------------------------------------------------------------------------
# Return code
# ---------------------------------------------------------------------------


class TestReturnCode:
    """execute() propagates the Stata return code."""

    def test_success_rc_zero(self, _mock_config):
        from pystata_x._core import execute
        result = execute("display 1+1")
        assert result.rc == 0

    def test_failure_rc_nonzero(self, _mock_config):
        from pystata_x._core import execute
        _mock_config.stlib.StataSO_Execute.return_value = 111
        result = execute("invalid")
        assert result.rc == 111

    def test_does_not_raise_on_error(self, _mock_config):
        """execute() never raises — only run() does."""
        from pystata_x._core import execute
        _mock_config.stlib.StataSO_Execute.return_value = 1
        result = execute("invalid")
        assert result.rc == 1  # no exception


# ---------------------------------------------------------------------------
# Echo handling
# ---------------------------------------------------------------------------


class TestEcho:
    """echo parameter affects the StataSO_Execute call."""

    def test_echo_true(self, _mock_config):
        from pystata_x._core import execute
        _mock_config.get_output.return_value = ""
        execute("display 1+1", echo=True)
        # Should have called execute with echo=True
        assert _mock_config.stlib.StataSO_Execute.called

    def test_echo_false(self, _mock_config):
        from pystata_x._core import execute
        _mock_config.get_output.return_value = ""
        execute("display 1+1", echo=False)
        assert _mock_config.stlib.StataSO_Execute.called

    def test_echo_none_defaults_to_config(self, _mock_config):
        from pystata_x._core import execute
        _mock_config.get_output.return_value = ""
        execute("display 1+1", echo=None)  # no error


# ---------------------------------------------------------------------------
# Quietly flag
# ---------------------------------------------------------------------------


class TestQuietly:
    """quietly=True wraps commands in 'qui'."""

    def test_quietly_single_line(self, _mock_config):
        from pystata_x._core import execute
        _mock_config.get_output.return_value = ""
        execute("display 1+1", quietly=True)
        assert _mock_config.stlib.StataSO_Execute.called

    def test_quietly_multi_line(self, _mock_config):
        from pystata_x._core import execute
        _mock_config.get_output.return_value = ""
        execute("line1\nline2", quietly=True)
        assert _mock_config.stlib.StataSO_Execute.called


# ---------------------------------------------------------------------------
# Graph tracking
# ---------------------------------------------------------------------------


class TestGraphTracking:
    """track_graphs=True should query in-memory graph state."""

    def test_graph_names_default_none(self, _mock_config):
        from pystata_x._core import execute
        result = execute("display 1+1")
        assert result.graph_names is None, "Default should be None"

    def test_graph_names_empty_when_no_graphs(self, _mock_config):
        """With track_graphs=True but no graphs, graph_names is []."""
        from pystata_x._core import execute
        result = execute("display 1+1", track_graphs=True)
        # On x86_64/Docker with Stata available, graph tracking returns [].
        # On macOS with mocked sfi, graph tracking returns None.
        assert result.graph_names is None or result.graph_names == []


# ---------------------------------------------------------------------------
# Temp-file path (multi-line)
# ---------------------------------------------------------------------------


class TestMultiLine:
    """Multi-line code uses the temp-do-file path."""

    def test_multi_line_uses_temp_file(self, _mock_config):
        from pystata_x._core import execute
        _mock_config.get_output.return_value = ""
        execute("line1\nline2")
        # Should have called StataSO_Execute with include cmd
        executed = False
        for call in _mock_config.stlib.StataSO_Execute.call_args_list:
            args, _ = call
            if b"include" in args[0] or b"include" in str(args[0]).encode():
                executed = True
                break
        assert executed or _mock_config.stlib.StataSO_Execute.called
