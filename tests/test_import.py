"""Smoke tests: verify the package can be imported and has the expected API."""

from __future__ import annotations

import pytest


class TestPackageImport:
    """Basic import and version checks."""

    def test_import_pystata_x(self):
        """The top-level package can be imported."""
        import pystata_x

    def test_version(self):
        """The package exposes a __version__ string."""
        import pystata_x
        assert hasattr(pystata_x, "__version__")
        assert isinstance(pystata_x.__version__, str)
        assert pystata_x.__version__ == "0.1.0"

    def test_version_consistency(self):
        """The version in pyproject.toml matches the package version."""
        import tomllib
        from pathlib import Path
        import pystata_x

        root = Path(__file__).resolve().parent.parent
        pyproject = tomllib.loads(
            (root / "pyproject.toml").read_text(encoding="utf-8")
        )
        assert pyproject["project"]["version"] == pystata_x.__version__

    def test_exposes_core_api(self):
        """The package exposes the expected public API."""
        import pystata_x
        assert hasattr(pystata_x, "run")
        assert hasattr(pystata_x, "execute")
        assert hasattr(pystata_x, "get_output")
        assert hasattr(pystata_x, "config")
        assert hasattr(pystata_x, "ExecuteResult")

    def test_exposes_config_module(self):
        """The config module is accessible."""
        from pystata_x import _config
        assert hasattr(_config, "init")
        assert hasattr(_config, "shutdown")
        assert hasattr(_config, "status")
        assert hasattr(_config, "check_initialized")
        assert hasattr(_config, "get_output")


class TestStataRequiring:
    """Tests that require a running Stata instance.

    These are skipped by default in CI (no Stata available).
    Run with: pytest -v -m requires_stata
    """

    pytestmark = pytest.mark.requires_stata

    def test_run_basic(self):
        """A simple Stata command can be executed."""
        from pystata_x._core import run
        run("display 1+1")


class TestSmokeBuild:
    """Verify the package builds correctly (slow marker)."""

    pytestmark = pytest.mark.slow

    def test_build(self, tmp_path):
        """Build an sdist and wheel, verify they exist."""
        import subprocess
        import sys
        from pathlib import Path

        result = subprocess.run(
            [sys.executable, "-m", "build", "--outdir", str(tmp_path)],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )
        assert result.returncode == 0, f"Build failed:\n{result.stderr}"

        artifacts = list(tmp_path.iterdir())
        names = [p.name for p in artifacts]

        # Expect at least one sdist (.tar.gz) and one wheel (.whl)
        sdists = [n for n in names if n.endswith(".tar.gz")]
        wheels = [n for n in names if n.endswith(".whl")]

        assert len(sdists) >= 1, f"No sdist found in {names}"
        assert len(wheels) >= 1, f"No wheel found in {names}"
