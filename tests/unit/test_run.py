"""Unit tests for ``pystata_x._core.run`` (mocked Stata runtime).

``run()`` is a thin API-compatible wrapper around :func:`execute`.
It performs **no** type validation, no initialisation check, no empty-cmd
short-circuit, and no comment detection of its own.  These tests only
verify the thin interface layer: stdout printing and ``SystemError``
on failure.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _mock_config():
    """Mock ``pystata_x._config`` so no real Stata runtime is required."""
    with patch("pystata_x._core.config") as mock_cfg:
        mock_cfg.stinitialized = True
        mock_cfg.stlib = MagicMock()
        mock_cfg.stlib.StataSO_ClearOutputBuffer.return_value = None
        mock_cfg.stlib.StataSO_Execute.return_value = 0
        mock_cfg.stconfig = {"grshow": False, "cmdshow": "default"}
        mock_cfg.check_initialized = MagicMock()
        mock_cfg._encode.side_effect = lambda s: s.encode("utf-8")
        mock_cfg.get_output.return_value = ""
        yield mock_cfg


@pytest.fixture
def mock_print():
    with patch("builtins.print") as mock_pr:
        yield mock_pr


class TestOutput:
    """run() prints output from execute() to stdout."""

    def test_prints_output(self, _mock_config, mock_print):
        from pystata_x._core import run
        _mock_config.get_output.return_value = "      1\n"
        run("display 1+1")
        mock_print.assert_called_once_with("      1\n")

    def test_does_not_print_when_no_output(self, _mock_config, mock_print):
        from pystata_x._core import run
        _mock_config.get_output.return_value = ""
        run("display 1+1")
        mock_print.assert_not_called()

    def test_prints_multi_line_output(self, _mock_config, mock_print):
        from pystata_x._core import run
        _mock_config.get_output.return_value = "result\n"
        run("line1\nline2")
        mock_print.assert_called_once_with("result\n")


class TestError:
    """run() raises SystemError when execute() returns non-zero rc."""

    def test_raises_on_nonzero_rc(self, _mock_config):
        from pystata_x._core import run
        _mock_config.get_output.return_value = "invalid command"
        _mock_config.stlib.StataSO_Execute.return_value = 1
        with pytest.raises(SystemError, match="invalid command"):
            run("invalid")

    def test_raises_with_generic_message_when_no_output(self, _mock_config):
        from pystata_x._core import run
        _mock_config.get_output.return_value = ""
        _mock_config.stlib.StataSO_Execute.return_value = 1
        with pytest.raises(SystemError, match="failed to execute the specified command"):
            run("invalid")

    def test_does_not_raise_on_success(self, _mock_config):
        from pystata_x._core import run
        _mock_config.get_output.return_value = "result\n"
        run("display 1+1")


class TestDelegation:
    """run() delegates to execute() for all actual work."""

    def test_delegates_to_execute(self, _mock_config):
        from pystata_x._core import run
        _mock_config.get_output.return_value = ""
        run("display 1+1")
        # execute() calls StataSO_Execute internally
        assert _mock_config.stlib.StataSO_Execute.called

    def test_returns_none(self, _mock_config):
        from pystata_x._core import run
        _mock_config.get_output.return_value = "output\n"
        assert run("display 1+1") is None

    def test_passes_raw_true(self, _mock_config, mock_print):
        """run() should pass through output with raw=True (preserve whitespace)."""
        from pystata_x._core import run
        _mock_config.get_output.return_value = "  result  \n"
        run("display 1+1")
        mock_print.assert_called_once_with("  result  \n")
