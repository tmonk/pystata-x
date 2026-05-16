"""Pytest configuration for pystata-x.

Auto-applies ``fast`` and ``slow`` markers based on test directory,
and skips ``requires_stata`` tests when Stata is not available.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _find_stata_root() -> Path | None:
    """Return the first Stata installation root directory found, or None.

    Version-agnostic: searches ``C:\\Program Files\\Stata*`` (Windows),
    ``/Applications/Stata*`` (macOS), and ``/usr/local/stata*`` (Linux)
    for the presence of a Stata shared library (DLL/SO) or executable.
    """
    if os.name == "nt":
        prog_files = Path(r"C:\Program Files")
        if prog_files.is_dir():
            for entry in sorted(prog_files.iterdir()):
                if entry.name.upper().startswith("STATA"):
                    # Look for a Stata DLL marker inside
                    for f in entry.iterdir():
                        if f.name.endswith("-64.dll") and f.is_file():
                            return entry
        return None

    if sys.platform == "darwin":
        apps = Path("/Applications")
        if apps.is_dir():
            for entry in sorted(apps.iterdir()):
                name = entry.name.lower()
                if "stata" in name and (entry.suffix == ".app" or entry.is_dir()):
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
    # Windows: check for *-64.dll files
    if os.name == "nt":
        for f in stata_root.iterdir():
            if f.name.endswith("-64.dll") and f.is_file():
                stem = f.stem.lower()  # e.g. "se-64" -> "se"
                if "mp" in stem:
                    return "mp"
                if "se" in stem:
                    return "se"
                if "be" in stem:
                    return "be"
                return stem.replace("-64", "").replace("stata", "").strip()
        return "mp"  # fallback

    # macOS: examine .app bundle name
    if sys.platform == "darwin":
        name = stata_root.name.lower()
        if "mp" in name:
            return "mp"
        if "se" in name:
            return "se"
        if "be" in name:
            return "be"
        if "ic" in name:
            return "se"  # StataIC -> SE-compatible
        return "mp"  # fallback

    # Linux: check for libstata-{edition}.so
    for f in stata_root.iterdir():
        if f.name.startswith("libstata") and f.suffix == ".so":
            stem = f.stem.lower()
            if "mp" in stem:
                return "mp"
            if "se" in stem:
                return "se"
            if "be" in stem:
                return "be"
    return "mp"  # fallback


def _is_stata_available() -> bool:
    """Quick check if Stata is available on this system."""
    if os.environ.get("STATA_AGENT_MOCK") == "1":
        return False
    return _find_stata_root() is not None


def pytest_collection_modifyitems(config, items):
    """Apply markers based on file path and handle Stata availability."""
    tests_root = Path(__file__).resolve().parent
    stata_available = _is_stata_available()

    for item in items:
        fspath = Path(item.fspath).resolve()

        # Optional tests (require additional dependencies)
        if _in_dir(fspath, tests_root / "optional"):
            item.add_marker(pytest.mark.optional)

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
