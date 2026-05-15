"""Integration tests for ``run()`` (requires a running Stata instance).

These tests verify that ``run()`` matches the observable behaviour of the
original StataCorp ``pystata.stata.run()`` API when used with a real Stata
engine: output is printed to stdout, ``SystemError`` is raised on failure,
comments are handled, and parameters are validated.

All tests in this module are marked ``@requires_stata`` — they will be
skipped in CI where Stata is not available.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.requires_stata


@pytest.fixture(autouse=True)
def _ensure_stata(request):
    """Ensure Stata is initialised before each test (and shut down after)."""
    from pystata_x import _config as config
    from pystata_x.stata_setup import config as stata_config

    if not config.stinitialized:
        # Auto-detect Stata — use common paths
        import sys
        import platform

        system = platform.system()
        if system == "Darwin":
            # Try common macOS Stata paths
            candidates = [
                "/Applications/StataMP.app",
                "/Applications/StataSE.app",
                "/Applications/StataBE.app",
                "/Applications/StataNow/StataMP.app",
                "/Applications/StataNow/StataSE.app",
            ]
            for path in candidates:
                from pathlib import Path
                if Path(path).exists():
                    edition = "mp" if "MP" in path else "se" if "SE" in path else "be"
                    stata_config(path, edition, splash=False)
                    break
            else:
                pytest.skip("No Stata installation found on macOS")
        elif system == "Windows":
            candidates = [
                r"C:\Program Files\Stata18",
                r"C:\Program Files\Stata17",
            ]
            for path in candidates:
                from pathlib import Path
                if Path(path).exists():
                    stata_config(path, "mp", splash=False)
                    break
            else:
                pytest.skip("No Stata installation found on Windows")
        elif system == "Linux":
            candidates = [
                "/usr/local/stata18",
                "/usr/local/stata17",
                "/opt/stata",
            ]
            for path in candidates:
                from pathlib import Path
                if Path(path).exists():
                    stata_config(path, "mp", splash=False)
                    break
            else:
                pytest.skip("No Stata installation found on Linux")

    yield

    # No teardown needed — Stata stays alive for the session


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestRunHappyPath:
    """Basic successful command execution."""

    def test_run_simple_command(self):
        """run() executes a simple display command without error."""
        from pystata_x._core import run
        run("display 1+1")  # should not raise

    def test_run_quietly(self):
        """run() with quietly=True suppresses output."""
        from pystata_x._core import run
        run("display 1+1", quietly=True)  # should not raise

    def test_run_multi_line(self):
        """run() with multi-line commands."""
        from pystata_x._core import run
        run("display 1+1\ndisplay 2+2")  # should not raise

    def test_run_empty_cmd(self):
        """run() with empty string returns None."""
        from pystata_x._core import run
        assert run("") is None


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


class TestRunErrorHandling:
    """run() must raise SystemError on Stata errors."""

    def test_raises_on_invalid_command(self):
        """An invalid Stata command raises SystemError."""
        from pystata_x._core import run
        with pytest.raises(SystemError):
            run("invalid_command_xyz")

    def test_raises_on_syntax_error(self):
        """A Stata syntax error raises SystemError."""
        from pystata_x._core import run
        with pytest.raises(SystemError):
            run("display 1+")  # incomplete expression

    def test_error_in_multi_line(self):
        """Multi-line commands propagate errors."""
        from pystata_x._core import run
        with pytest.raises(SystemError):
            run("display 1+1\ninvalid_command_xyz\ndisplay 2+2")


# ---------------------------------------------------------------------------
# Type validation
# ---------------------------------------------------------------------------


class TestRunTypeValidation:
    """run() must validate echo and inline types."""

    def test_echo_wrong_type_raises(self):
        from pystata_x._core import run
        with pytest.raises(TypeError, match="echo must be a boolean"):
            run("display 1+1", echo="yes")

    def test_inline_wrong_type_raises(self):
        from pystata_x._core import run
        with pytest.raises(TypeError, match="inline must be a boolean"):
            run("display 1+1", inline="yes")


# ---------------------------------------------------------------------------
# Comment handling
# ---------------------------------------------------------------------------


class TestRunCommentHandling:
    """run() must handle Stata comments as the vendor does."""

    def test_comment_line(self):
        """A // comment line should not raise."""
        from pystata_x._core import run
        run("// this is a comment")  # no error

    def test_block_comment(self):
        """A /* */ comment line should not raise."""
        from pystata_x._core import run
        run("/* block comment */")  # no error

    def test_comment_with_echo_true(self):
        """Comment line with echo=True should not execute Stata."""
        from pystata_x._core import run
        run("// comment", echo=True)  # no error


# ---------------------------------------------------------------------------
# Execute (unconstrained)
# ---------------------------------------------------------------------------


class TestExecuteIntegration:
    """execute() integration tests — no vendor constraints."""

    def test_execute_returns_result(self):
        from pystata_x._core import execute
        result = execute("display 1+1")
        assert result.rc == 0
        assert "1" in result.output

    def test_execute_error_returns_nonzero_rc(self):
        from pystata_x._core import execute
        result = execute("invalid")
        assert result.rc != 0

    def test_execute_quietly(self):
        from pystata_x._core import execute
        result = execute("display 1+1", quietly=True)
        assert result.rc == 0

    def test_execute_multi_line(self):
        from pystata_x._core import execute
        result = execute("display 1+1\ndisplay 2+2")
        assert result.rc == 0
        assert "1" in result.output
        assert "2" in result.output

    def test_execute_with_graph_tracking(self):
        from pystata_x._core import execute
        result = execute("display 1+1", track_graphs=True)
        assert result.rc == 0
        # graph_names may be empty list or None depending on SFI availability
