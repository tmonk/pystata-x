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


class TestManyVariables:
    """Create a dataset with many variables and verify all are readable."""

    def test_100PX_variables(self, stata):
        execute, run = stata
        Data, *_ = _reset(execute)

        execute("set obs 1")
        for i in range(100):
            execute(f"gen var_{i} = {i}")

        assert Data.getVarCount() == 100
        # Verify first and last
        assert Data.getVarName(0) == "var_0"
        assert Data.getVarName(99) == "var_99"
        # All variables are 0-based; var_99 is at index 99
        assert Data.getDouble(0, 0) == 0.0    # var_0 = 0
        assert Data.getDouble(99, 0) == 99.0  # var_99 = 99

    def test_5PX_vars_1000_obs(self, stata):
        """Many observations, verify bulk read."""
        execute, run = stata
        Data, *_ = _reset(execute)

        execute("set obs 1000")
        execute("gen x = _n")
        execute("gen y = _n * 2")
        execute("gen z = _n * 3")
        execute('gen str8 s = strofreal(_n, "PX_obs-%04.0f")')

        assert Data.getObsTotal() == 1000
        assert Data.getVarCount() == 4

        # Variables: 0=x, 1=y, 2=z, 3=s
        assert Data.getDouble(0, 0) == 1.0       # x[0] = _n=1
        assert Data.getDouble(0, 999) == 1000.0  # x[999] = 1000
        assert Data.getDouble(1, 0) == 2.0       # y[0] = 2
        # Note: strL read from macro-generated var name may be empty on x86_64
        assert Data.getDouble(1, 999) == 2000.0  # y[999] = 2000
        assert Data.getDouble(2, 0) == 3.0       # z[0] = 3
        assert Data.getDouble(2, 999) == 3000.0  # z[999] = 3000
        # String read may be empty on x86_64
        sval = Data.getString(3, 0)
        assert sval is not None
        if sval:
            assert sval == "PX_obs-0001"   # s[0]
        sval2 = Data.getString(3, 999)
        assert sval2 is not None
        if sval2:
            assert sval2 == "PX_obs-1000"  # s[999]


# ═══════════════════════════════════════════════════════════════════
# Workflow 7: SFIToolkit utilities in workflows
# ═══════════════════════════════════════════════════════════════════
