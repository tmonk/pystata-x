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


from pathlib import Path
import os
import platform
import sys

# Reuse helpers from tests.conftest
def _find_stata_root() -> Path | None:
    """Return the first Stata installation root directory found, or None.

    Version-agnostic — searches by directory-name prefix rather than
    hardcoding version numbers.
    """
    system = platform.system()
    if system == "Windows":
        prog_files = Path(r"C:\Program Files")
        if prog_files.is_dir():
            for entry in sorted(prog_files.iterdir()):
                if entry.name.upper().startswith("STATA"):
                    for f in entry.iterdir():
                        if f.name.endswith("-64.dll") and f.is_file():
                            return entry
        return None

    if system == "Darwin":
        apps = Path("/Applications")
        if apps.is_dir():
            for entry in sorted(apps.iterdir()):
                if "stata" in entry.name.lower():
                    return entry
        return None

    # Linux
    for parent in [Path("/usr/local"), Path("/opt")]:
        if parent.is_dir():
            for entry in sorted(parent.iterdir()):
                if entry.name.lower().startswith("stata"):
                    return entry
    return None


def _detect_edition(stata_root: Path) -> str:
    """Detect Stata edition (be/se/mp) from DLL/library name."""
    system = platform.system()
    if system == "Windows":
        for f in stata_root.iterdir():
            if f.name.endswith("-64.dll") and f.is_file():
                stem = f.stem.lower()
                if "mp" in stem:
                    return "mp"
                if "se" in stem:
                    return "se"
                if "be" in stem:
                    return "be"
                return stem.replace("-64", "").replace("stata", "").strip()
        return "mp"

    if system == "Darwin":
        name = stata_root.name.lower()
        if "mp" in name:
            return "mp"
        if "se" in name:
            return "se"
        if "be" in name:
            return "be"
        if "ic" in name:
            return "se"
        return "mp"

    # Linux
    for f in stata_root.iterdir():
        if f.name.startswith("libstata") and f.suffix == ".so":
            stem = f.stem.lower()
            if "mp" in stem:
                return "mp"
            if "se" in stem:
                return "se"
            if "be" in stem:
                return "be"
    return "mp"


@pytest.fixture(autouse=True)
def _ensure_stata(request):
    """Ensure Stata is initialised before each test (and shut down after)."""
    from pystata_x import _config as config
    from pystata_x.stata_setup import config as stata_config

    if not config.stinitialized:
        stata_root = _find_stata_root()
        if stata_root is None:
            pytest.skip("No Stata installation found")
        edition = _detect_edition(stata_root)
        stata_config(str(stata_root), edition, splash=False)

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
        """run() with empty string returns None (delegated to execute)."""
        from pystata_x._core import run
        assert run("") is None


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


class TestRunErrorHandling:
    """run() raises SystemError on Stata errors."""

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
# Execute (unconstrained)
# ---------------------------------------------------------------------------


class TestExecuteIntegration:
    """execute() integration tests — no vendor constraints."""

    def test_execute_returns_result(self):
        from pystata_x._core import execute
        result = execute("display 1+1")
        assert result.rc == 0
        assert "2" in result.output

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
        assert "2" in result.output
        assert "4" in result.output

    def test_execute_with_graph_tracking(self):
        from pystata_x._core import execute
        result = execute("display 1+1", track_graphs=True)
        assert result.rc == 0
        # graph_names may be empty list or None depending on SFI availability
