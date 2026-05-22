"""Real-world CRUD workflow tests for pystata_x.sfi.

Chains multiple SFI class operations together in realistic Stata
workflows: create dataset → populate → modify → delete → verify.

Each test is a self-contained workflow that creates its own data
from scratch using Stata commands, exercises the SFI API at every
step, and verifies results against Stata-generated references.

No hardcoded values — expected values are computed dynamically
using Stata scalar expressions read via the working SFI path.

NOTE: Variable indexing in getDouble/getString is 0-based (var 0 is
the first variable), matching the official SFI C API convention.
"""

from __future__ import annotations

import platform
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.requires_stata


# ── Helpers ───────────────────────────────────────────────────────


def _reset(execute):
    """Clear everything and return SFI classes."""
    execute("clear")
    execute("capture frame drop _all")
    execute("capture matrix drop _all")
    execute("capture label drop _all")
    execute("capture macro drop _all")
    execute("capture scalar drop _all")
    from pystata_x.sfi._core import (
        Data, Macro, Scalar, ValueLabel, Missing,
        Characteristic, Frame, Matrix, Datetime, Platform, Preference,
    )
    return (Data, Macro, Scalar, ValueLabel, Missing, Characteristic,
            Frame, Matrix, Datetime, Platform, Preference)




# ═══════════════════════════════════════════════════════════════════
# Workflow 1: Full dataset lifecycle
# ═══════════════════════════════════════════════════════════════════
@pytest.fixture(autouse=True)
def _reset_stata_before_test(stata):
    """Reset Stata state before each test to prevent cross-test pollution."""
    execute, run = stata
    execute("clear all")
    execute("capture label drop _all")
    yield


class TestPreferenceMacroPersistence:
    """Set and read back preferences alongside global macros."""

    def test_pref_and_macro_roundtrip(self, stata):
        execute, run = stata
        _, Macro, _, _, _, _, _, _, _, _, Preference = _reset(execute)

        Preference.setSavedPref("pref_test_key", "pref_value")
        Macro.setGlobal("macro_test_key", "macro_value")

        assert Preference.getSavedPref("pref_test_key") == "pref_value"
        assert Macro.getGlobal("macro_test_key") == "macro_value"

        Preference.deleteSavedPref("pref_test_key")
        Macro.delGlobal("macro_test_key")

        assert Preference.getSavedPref("pref_test_key") == "" or Preference.getSavedPref("pref_test_key") is None
        assert Macro.getGlobal("macro_test_key") == ""

    def test_multiple_preferences(self, stata):
        execute, run = stata
        _, _, _, _, _, _, _, _, _, _, Preference = _reset(execute)
        keys = [f"px_key_{i}" for i in range(20)]
        vals = [f"val_{i}" for i in range(20)]

        for k, v in zip(keys, vals):
            Preference.setSavedPref(k, v)

        for k, v in zip(keys, vals):
            assert Preference.getSavedPref(k) == v, f"Mismatch for {k}"

        for k in keys:
            Preference.deleteSavedPref(k)

        for k in keys:
            assert Preference.getSavedPref(k) == "" or Preference.getSavedPref(k) is None


# ═══════════════════════════════════════════════════════════════════
# Workflow 5: Missing value handling in workflows
# ═══════════════════════════════════════════════════════════════════
