"""End-to-end tests for pystata-x (requires a running Stata instance).

Exercises the full lifecycle: library discovery, Stata initialisation,
command execution (run + execute), graph tracking, error recovery,
and shutdown.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.requires_stata


@pytest.fixture(scope="module")
def _init_stata():
    """Initialise Stata once per module."""
    from pystata_x.stata_setup import config as stata_config
    from pystata_x import _config as cfg
    import platform
    from pathlib import Path

    if cfg.stinitialized:
        yield
        return

    system = platform.system()
    if system == "Darwin":
        candidates = [
            "/Applications/StataMP.app",
            "/Applications/StataSE.app",
            "/Applications/StataBE.app",
            "/Applications/StataNow/StataMP.app",
            "/Applications/StataNow/StataSE.app",
        ]
    elif system == "Windows":
        candidates = [
            r"C:\Program Files\Stata18",
            r"C:\Program Files\Stata17",
        ]
    elif system == "Linux":
        candidates = [
            "/usr/local/stata18",
            "/usr/local/stata17",
            "/opt/stata",
        ]
    else:
        pytest.skip(f"Unsupported platform: {system}")

    for path in candidates:
        if Path(path).exists():
            edition = "mp" if "MP" in path else "se" if "SE" in path else "be"
            stata_config(path, edition, splash=False)
            break
    else:
        pytest.skip("No Stata installation found")

    yield


# ---------------------------------------------------------------------------
# Full lifecycle
# ---------------------------------------------------------------------------


class TestFullLifecycle:
    """Complete Stata lifecycle: init → execute → shutdown."""

    def test_init_and_run(self, _init_stata):
        """After init, run() executes Stata commands."""
        from pystata_x._core import run
        run("display 1+1")

    def test_init_and_execute(self, _init_stata):
        """After init, execute() returns expected results."""
        from pystata_x._core import execute
        result = execute("display 2+2")
        assert result.rc == 0
        assert "4" in result.output

    def test_consecutive_commands(self, _init_stata):
        """Multiple consecutive calls work correctly."""
        from pystata_x._core import run, execute

        run("clear all")
        run("set obs 100")

        result = execute("display _N")
        assert result.rc == 0
        assert "100" in result.output

    def test_mixed_run_and_execute(self, _init_stata):
        """Interleaved run() and execute() calls."""
        from pystata_x._core import run, execute

        run("clear all")
        run("set obs 50")
        run("gen x = _n")

        result = execute("summarize x")
        assert result.rc == 0
        assert "50" in result.output  # N=50 in summary

    def test_error_recovery(self, _init_stata):
        """After an error, Stata can still execute commands."""
        from pystata_x._core import run, execute

        # Error command
        with pytest.raises(SystemError):
            run("invalid_command_xyz")

        # Subsequent command should still work
        result = execute("display 3+3")
        assert result.rc == 0
        assert "6" in result.output

    def test_sysuse_auto(self, _init_stata):
        """Load the auto dataset and verify."""
        from pystata_x._core import run, execute

        run("sysuse auto, clear")
        result = execute("describe")
        assert result.rc == 0
        assert "74" in result.output  # 74 observations


# ---------------------------------------------------------------------------
# Graph tracking (e2e)
# ---------------------------------------------------------------------------


class TestGraphTracking:
    """track_graphs parameter end-to-end."""

    def test_track_graphs_with_no_graphs(self, _init_stata):
        from pystata_x._core import execute
        result = execute("display 1+1", track_graphs=True)
        assert result.rc == 0
        # graph_names may be empty or None depending on SFI
        if result.graph_names is not None:
            assert isinstance(result.graph_names, list)

    def test_track_graphs_after_graph(self, _init_stata):
        from pystata_x._core import execute, run as core_run
        core_run("sysuse auto, clear")
        result = execute("histogram mpg", quietly=True, track_graphs=True)
        assert result.rc == 0
        core_run("graph drop _all")


# ---------------------------------------------------------------------------
# Config module
# ---------------------------------------------------------------------------


class TestConfigModule:
    """Config module API end-to-end."""

    def test_check_initialized_after_init(self, _init_stata):
        from pystata_x._config import check_initialized
        check_initialized()  # should not raise

    def test_status_after_init(self, _init_stata, capsys):
        from pystata_x._config import status
        status()
        captured = capsys.readouterr()
        assert "Stata" in captured.out

    def test_is_stata_initialized(self, _init_stata):
        from pystata_x._config import is_stata_initialized
        assert is_stata_initialized() is True



