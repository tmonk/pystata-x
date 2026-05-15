"""Unit tests for ``pystata_x._core.run`` (mocked Stata runtime).

These tests mock ``pystata_x._config`` so no real Stata is needed.
They verify that ``run()`` matches the original StataCorp ``pystata.stata.run()``
API contract exactly — parameter validation, output to stdout, ``SystemError``
on failure, comment handling, empty-cmd short-circuit, and the ``check_initialized``
gate.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_config():
    """Mock ``pystata_x._config`` so no real Stata runtime is required.

    Sets up:
    - ``stinitialized = True`` (tests that need uninitialised override it)
    - ``stlib`` as a ``MagicMock``
    - ``stconfig`` with sensible defaults
    - ``check_initialized()`` as a no-op
    - ``_encode()`` as a simple str→bytes converter
    - ``get_output()`` returning an empty string
    """
    with patch("pystata_x._core.config") as mock_cfg:
        # Shared state
        mock_cfg.stinitialized = True
        mock_cfg.stlib = MagicMock()
        mock_cfg.stlib.StataSO_ClearOutputBuffer.return_value = None
        mock_cfg.stlib.StataSO_Execute.return_value = 0

        # Config dict
        mock_cfg.stconfig = {
            "grshow": False,
            "cmdshow": "default",
        }

        # Helpers
        mock_cfg.check_initialized = MagicMock()
        mock_cfg._encode.side_effect = lambda s: s.encode("utf-8")
        mock_cfg.get_output.return_value = ""

        yield mock_cfg


@pytest.fixture
def mock_print():
    """Capture ``print`` calls for output verification."""
    with patch("builtins.print") as mock_pr:
        yield mock_pr


# ---------------------------------------------------------------------------
# Tests: check_initialized gate
# ---------------------------------------------------------------------------


class TestInitializedGate:
    """run() must call check_initialized() first and raise on failure."""

    def test_raises_when_not_initialized(self, _mock_config):
        """If stinitialized is False, check_initialized raises SystemError."""
        _mock_config.stinitialized = False
        _mock_config.check_initialized.side_effect = SystemError(
            "Stata not initialised"
        )
        from pystata_x._core import run

        with pytest.raises(SystemError, match="Stata not initialised"):
            run("display 1+1")

    def test_calls_check_initialized(self, _mock_config):
        """check_initialized() is always called before anything else."""
        _mock_config.stinitialized = False
        _mock_config.check_initialized.side_effect = SystemError("x")
        from pystata_x._core import run

        with pytest.raises(SystemError):
            run("display 1+1")
        _mock_config.check_initialized.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: empty cmd
# ---------------------------------------------------------------------------


class TestEmptyCmd:
    """Empty/whitespace-only cmd must return immediately."""

    def test_empty_string_returns_none(self, _mock_config, mock_print):
        from pystata_x._core import run
        assert run("") is None
        mock_print.assert_not_called()

    def test_only_newlines_returns_none(self, _mock_config, mock_print):
        from pystata_x._core import run
        assert run("\n\n") is None
        mock_print.assert_not_called()

    def test_does_not_execute_for_empty_cmd(self, _mock_config):
        """No StataSO calls should happen for empty cmd."""
        from pystata_x._core import run
        run("")
        # Buffer clear, check_initialized still happen but execute should not
        _mock_config.stlib.StataSO_Execute.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: type validation
# ---------------------------------------------------------------------------


class TestTypeValidation:
    """echo and inline must be True, False, or None — else TypeError."""

    def test_echo_non_bool_raises_typeerror(self, _mock_config):
        from pystata_x._core import run
        with pytest.raises(TypeError, match="echo must be a boolean value"):
            run("display 1+1", echo="yes")

    def test_echo_int_raises_typeerror(self, _mock_config):
        from pystata_x._core import run
        with pytest.raises(TypeError, match="echo must be a boolean value"):
            run("display 1+1", echo=1)

    def test_echo_none_is_valid(self, _mock_config):
        from pystata_x._core import run
        _mock_config.stlib.StataSO_Execute.return_value = 0
        _mock_config.get_output.return_value = ""
        run("display 1+1", echo=None)  # no TypeError

    def test_inline_non_bool_raises_typeerror(self, _mock_config):
        from pystata_x._core import run
        with pytest.raises(TypeError, match="inline must be a boolean value"):
            run("display 1+1", inline="yes")

    def test_inline_int_raises_typeerror(self, _mock_config):
        from pystata_x._core import run
        with pytest.raises(TypeError, match="inline must be a boolean value"):
            run("display 1+1", inline=1)

    def test_inline_none_is_valid(self, _mock_config):
        from pystata_x._core import run
        _mock_config.stlib.StataSO_Execute.return_value = 0
        _mock_config.get_output.return_value = ""
        run("display 1+1", inline=None)  # no TypeError


# ---------------------------------------------------------------------------
# Tests: normal execution
# ---------------------------------------------------------------------------


class TestExecution:
    """run() behaviour for single-line commands."""

    def test_prints_output_to_stdout(self, _mock_config, mock_print):
        from pystata_x._core import run
        _mock_config.get_output.return_value = "      1\n"
        run("display 1+1")
        # run() passes raw=True to execute(), preserving leading whitespace
        mock_print.assert_called_once_with("      1\n")

    def test_raises_systemerror_on_nonzero_rc(self, _mock_config, mock_print):
        from pystata_x._core import run
        _mock_config.get_output.return_value = "invalid command"
        _mock_config.stlib.StataSO_Execute.return_value = 1
        with pytest.raises(SystemError, match="invalid command"):
            run("invalid")

    def test_raises_systemerror_with_generic_message_when_no_output(self, _mock_config):
        from pystata_x._core import run
        _mock_config.get_output.return_value = ""
        _mock_config.stlib.StataSO_Execute.return_value = 1
        with pytest.raises(SystemError, match="failed to execute the specified command"):
            run("invalid")

    def test_successful_run_does_not_raise(self, _mock_config):
        from pystata_x._core import run
        _mock_config.get_output.return_value = "      1\n"
        run("display 1+1")  # no exception


# ---------------------------------------------------------------------------
# Tests: echo default resolution
# ---------------------------------------------------------------------------


class TestEchoDefault:
    """echo=None must use config.stconfig['cmdshow'] as default."""

    def test_echo_default_default_becomes_false(self, _mock_config):
        """cmdshow='default' → echo=False."""
        _mock_config.stconfig["cmdshow"] = "default"
        from pystata_x._core import run
        _mock_config.get_output.return_value = ""
        run("display 1+1")  # should resolve without error

    def test_echo_default_on_becomes_true(self, _mock_config):
        """cmdshow='on' → echo=True."""
        _mock_config.stconfig["cmdshow"] = "on"
        from pystata_x._core import run
        _mock_config.get_output.return_value = ""
        run("display 1+1")  # should resolve without error

    def test_echo_default_off_becomes_false(self, _mock_config):
        """cmdshow='off' → echo=False."""
        _mock_config.stconfig["cmdshow"] = "off"
        from pystata_x._core import run
        _mock_config.get_output.return_value = ""
        run("display 1+1")  # should resolve without error


# ---------------------------------------------------------------------------
# Tests: comment handling
# ---------------------------------------------------------------------------


class TestCommentHandling:
    """Single-line comments must be detected and handled as in vendor."""

    def test_single_line_comment_double_slash(self, _mock_config, mock_print):
        """// comment → print empty string."""
        from pystata_x._core import run
        run("// this is a comment")
        mock_print.assert_called_once_with("")

    def test_block_comment_detected(self, _mock_config, mock_print):
        """/* ... */ as full line → print empty string."""
        from pystata_x._core import run
        run("/* comment */")
        mock_print.assert_called_once_with("")

    def test_comment_does_not_call_stata_execute(self, _mock_config):
        """Comments should not call StataSO_Execute at all."""
        from pystata_x._core import run
        run("// just a comment")
        # Comment path should not trigger Stata execution
        # (check_initialized and clear buffer may still happen)
        _mock_config.stlib.StataSO_Execute.assert_not_called()

    def test_block_comment_does_not_call_stata_execute(self, _mock_config):
        from pystata_x._core import run
        run("/* block */")
        _mock_config.stlib.StataSO_Execute.assert_not_called()

    def test_non_comment_executes_normally(self, _mock_config):
        """Regular commands are not treated as comments."""
        from pystata_x._core import run
        _mock_config.get_output.return_value = "result\n"
        run("display 1+1")
        assert _mock_config.stlib.StataSO_Execute.called

    def test_comment_with_echo_true_prints_line(self, _mock_config, mock_print):
        """Comment with echo=True prints '. <line>' when not quiet."""
        from pystata_x._core import run
        run("// a comment", echo=True)
        mock_print.assert_called_once_with(". // a comment")

    def test_comment_with_echo_true_and_quietly_prints_empty(self, _mock_config, mock_print):
        """Comment with echo=True and quietly=True prints empty string."""
        from pystata_x._core import run
        run("// a comment", echo=True, quietly=True)
        mock_print.assert_called_once_with("")


# ---------------------------------------------------------------------------
# Tests: multi-line
# ---------------------------------------------------------------------------


class TestMultiLine:
    """run() with multi-line commands."""

    def test_multi_line_executes(self, _mock_config):
        from pystata_x._core import run
        _mock_config.get_output.return_value = ""
        run("line1\nline2")
        assert _mock_config.stlib.StataSO_Execute.called

    def test_multi_line_prints_output(self, _mock_config, mock_print):
        from pystata_x._core import run
        _mock_config.get_output.return_value = "result\n"
        run("line1\nline2")
        # raw=True preserves trailing newline from buffer
        mock_print.assert_called_once_with("result\n")

    def test_multi_line_raises_on_error(self, _mock_config):
        from pystata_x._core import run
        _mock_config.get_output.return_value = "error message"
        _mock_config.stlib.StataSO_Execute.return_value = 1
        with pytest.raises(SystemError, match="error message"):
            run("line1\nline2")

    def test_multi_line_inline_enables_graphs(self, _mock_config):
        """inline=True should call qui _gr_list on/off."""
        from pystata_x._core import run
        _mock_config.get_output.return_value = ""
        run("line1\nline2", inline=True)
        on_call = None
        off_call = None
        for call in _mock_config.stlib.StataSO_Execute.call_args_list:
            args, _ = call
            if "qui _gr_list on" in str(args[0]):
                on_call = call
            if "qui _gr_list off" in str(args[0]):
                off_call = call
        assert on_call is not None, "Expected 'qui _gr_list on' call"
        assert off_call is not None, "Expected 'qui _gr_list off' call"


# ---------------------------------------------------------------------------
# Tests: inline default resolution
# ---------------------------------------------------------------------------


class TestInlineDefault:
    """inline=None must use config.stconfig['grshow']."""

    def test_inline_default_false(self, _mock_config):
        """grshow=False → inline=False (graph commands not sent)."""
        _mock_config.stconfig["grshow"] = False
        from pystata_x._core import run
        _mock_config.get_output.return_value = ""
        run("display 1+1")
        # No _gr_list calls expected
        has_gr = any(
            "qui _gr_list" in str(c.args[0])
            for c in _mock_config.stlib.StataSO_Execute.call_args_list
        )
        assert not has_gr

    def test_inline_default_true(self, _mock_config):
        """grshow=True → inline=True."""
        _mock_config.stconfig["grshow"] = True
        from pystata_x._core import run
        _mock_config.get_output.return_value = ""
        run("line1\nline2")  # multi-line for inline to have effect
        found = any(
            "qui _gr_list on" in str(c.args[0])
            for c in _mock_config.stlib.StataSO_Execute.call_args_list
        )
        assert found


# ---------------------------------------------------------------------------
# Tests: buffer clear
# ---------------------------------------------------------------------------


class TestBufferClear:
    """run() must clear Stata output buffer at start (vendor behaviour).

    Note: ``execute()`` also clears the buffer internally, so a double
    clear is expected when ``run()`` calls ``execute()``.  We verify the
    vendor-required clear happens via ``run()``.
    """

    def test_clears_output_buffer_at_least_once(self, _mock_config):
        from pystata_x._core import run
        _mock_config.get_output.return_value = ""
        run("display 1+1")
        # At least one clear from run() (execute() may add another)
        assert _mock_config.stlib.StataSO_ClearOutputBuffer.called


# ---------------------------------------------------------------------------
# Tests: _is_comment_line helper (matches vendor logic exactly)
# ---------------------------------------------------------------------------


class TestIsCommentLine:
    """Internal comment-detection helper must match vendor logic."""

    def test_double_slash(self):
        from pystata_x._core import _is_comment_line
        assert _is_comment_line("// comment")
        assert _is_comment_line("//")
        assert _is_comment_line("//  with spaces  ")

    def test_block_comment_simple(self):
        from pystata_x._core import _is_comment_line
        # Vendor logic: /* ... */ — ends with /, last * before / has
        # only whitespace between * and /
        assert _is_comment_line("/* comment */")

    def test_block_comment_empty(self):
        from pystata_x._core import _is_comment_line
        assert _is_comment_line("/**/")

    def test_block_comment_multiline_string_detected_by_helper(self):
        """A multi-line comment string is detected by the helper (in actual
        ``run()`` flow this would be multi-line and never reach the helper)."""
        from pystata_x._core import _is_comment_line
        # The helper uses the vendor's logic: starts with /*, ends with /
        # and last * is properly closed. In run() this would be multi-line.
        assert _is_comment_line("/*\ncomment\n*/")  # vendor logic matches this

    def test_regular_code_not_comment(self):
        from pystata_x._core import _is_comment_line
        assert not _is_comment_line("display 1+1")
        assert not _is_comment_line("gen x = 1")
        assert not _is_comment_line("")
        assert not _is_comment_line("x/*not a comment*/y")  # inline block not detected
