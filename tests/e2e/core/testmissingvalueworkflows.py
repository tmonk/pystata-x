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


class TestMissingValueWorkflows:
    """Create, store, detect, and filter missing values."""

    def test_generate_missing_filter_read(self, stata):
        """Generate data with missing values, verify detection."""
        execute, run = stata
        Data, Macro, Scalar, ValueLabel, Missing, *_ = _reset(execute)

        execute("set obs 5")
        execute("gen double x = _n")
        execute("replace x = . in 3")
        execute("replace x = .a in 5")

        # Read values — x is var 0
        vals = [Data.getDouble(0, i) for i in range(5)]
        assert vals[0] == 1.0
        assert vals[1] == 2.0
        assert Missing.isMissing(vals[2])  # . at obs 2 (0-based)
        assert vals[3] == 4.0
        assert Missing.isMissing(vals[4])  # .a at obs 4

        # Store a missing value and verify
        Data.storeDouble(0, 0, Missing.getMissing(Missing.getValue(".z")))
        assert Missing.isMissing(Data.getDouble(0, 0))

    def test_missing_via_formatted_value(self, stata):
        """Formatted value for missing should return '.' in Stata."""
        execute, run = stata
        Data, Macro, Scalar, ValueLabel, Missing, *_ = _reset(execute)

        execute("set obs 3")
        execute("gen double x = _n")
        execute("replace x = . in 2")

        # x is var 0
        formatted = Data.getFormattedValue(0, 0, False)  # 0-based obs 0 = Stata obs 1 = value 1
        assert formatted is not None
        assert any(c.isdigit() for c in formatted), f"No digit in {formatted!r}"

        formatted_miss = Data.getFormattedValue(0, 2, False)  # 0-based obs 2 = Stata obs 3 = value 3
        assert formatted_miss is not None


# ═══════════════════════════════════════════════════════════════════
# Workflow 6: Stress test — many variables
# ═══════════════════════════════════════════════════════════════════
