"""Pytest configuration for pystata-x.

Auto-applies ``fast`` and ``slow`` markers based on test directory,
and skips ``requires_stata`` tests when Stata is not available.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _is_stata_available() -> bool:
    """Quick check if Stata is available on this system."""
    if os.environ.get("STATA_AGENT_MOCK") == "1":
        return False
    for path in [
        "/usr/local/bin/stata-se",
        "/usr/local/bin/stata-mp",
        "/usr/local/bin/stata-ic",
        "/usr/local/bin/stata",
        "/Applications/StataNow/stata-se",
        "/Applications/StataNow/stata-mp",
        "/Applications/StataNow/stata-ic",
        "/Applications/StataNow/stata",
        "/Applications/StataNow/StataSE.app/Contents/MacOS/StataSE",
        "/Applications/StataNow/StataSE.app/Contents/MacOS/stata-se",
        "/Applications/StataNow/StataMP.app/Contents/MacOS/StataMP",
        "/Applications/StataNow/StataMP.app/Contents/MacOS/stata-mp",
        "/Applications/StataNow/StataIC.app/Contents/MacOS/StataIC",
        "/Applications/StataNow/StataIC.app/Contents/MacOS/stata-ic",
        "/Applications/Stata/StataSE.app/Contents/MacOS/StataSE",
        "/Applications/Stata/StataSE.app/Contents/MacOS/stata-se",
        "/Applications/Stata/StataMP.app/Contents/MacOS/StataMP",
        "/Applications/Stata/StataMP.app/Contents/MacOS/stata-mp",
        "/Applications/Stata/StataIC.app/Contents/MacOS/StataIC",
        "/Applications/Stata/StataIC.app/Contents/MacOS/stata-ic",
    ]:
        if os.path.exists(path) and os.access(path, os.X_OK):
            return True
    return False


def pytest_collection_modifyitems(config, items):
    """Apply markers based on file path and handle Stata availability."""
    tests_root = Path(__file__).resolve().parent
    stata_available = _is_stata_available()

    for item in items:
        fspath = Path(item.fspath).resolve()

        # Unit tests are fast
        if _in_dir(fspath, tests_root / "unit"):
            item.add_marker(pytest.mark.fast)

        # Integration tests that don't require Stata are fast
        if _in_dir(fspath, tests_root / "integration"):
            if "requires_stata" not in item.keywords:
                item.add_marker(pytest.mark.fast)

        # Top-level test files: mark as fast unless already slow or requires_stata
        if fspath.parent == tests_root:
            if "slow" not in item.keywords and "requires_stata" not in item.keywords:
                item.add_marker(pytest.mark.fast)

        # Auto-skip requires_stata tests when Stata is unavailable
        if "requires_stata" in item.keywords and not stata_available:
            item.add_marker(pytest.mark.skip(
                reason="requires Stata license — run with Stata installed and without STATA_AGENT_MOCK=1"
            ))


def _in_dir(path: Path, dirpath: Path) -> bool:
    """Return True if *path* is inside (or equal to) *dirpath*."""
    try:
        path.resolve().relative_to(dirpath.resolve())
        return True
    except ValueError:
        return False
