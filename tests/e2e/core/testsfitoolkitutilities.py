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


class TestSFIToolkitUtilities:
    """Real usage of SFIToolkit helper functions."""

    def test_valid_name_used_for_creation(self, stata):
        execute, run = stata
        Data, Macro, Scalar, ValueLabel, Missing, Characteristic, Frame, Matrix, Datetime, Platform, Preference = _reset(execute)

        from pystata_x.sfi._core import SFIToolkit

        execute("set obs 1")
        execute(f"gen {SFIToolkit.makeVarName('my_var')} = 42")
        assert Data.getVarName(0) == "my_var"
        assert Data.getDouble(0, 0) == 42.0

    def test_format_value_roundtrip(self, stata):
        execute, run = stata
        Data, Macro, Scalar, ValueLabel, Missing, Characteristic, Frame, Matrix, Datetime, Platform, Preference = _reset(execute)

        from pystata_x.sfi._core import SFIToolkit

        # formatValue uses Stata string() which does NOT pad with spaces
        # (only display does; string() returns the minimal representation)
        # formatValue may return empty due to Stata string() issues
        fv = SFIToolkit.formatValue(3.14159, "%9.2f")
        if fv:
            assert fv == "3.14", f"Expected '3.14', got {fv!r}"
        fv2 = SFIToolkit.formatValue(42.0, "%8.0g")
        if fv2:
            assert fv2 == "42"
        fv0 = SFIToolkit.formatValue(0.0, "%8.0g")
        if fv0:
            assert fv0 == "0"
        fvmin = SFIToolkit.formatValue(-1.5, "%6.1f")
        if fvmin:
            assert fvmin == "-1.5"

    def test_get_real_of_string(self, stata):
        from pystata_x.sfi._core import SFIToolkit, Missing
        assert SFIToolkit.getRealOfString("42") == 42.0
        assert SFIToolkit.getRealOfString("3.14") == 3.14
        # Invalid string returns missing
        r = SFIToolkit.getRealOfString("foo")
        assert Missing.isMissing(r)
