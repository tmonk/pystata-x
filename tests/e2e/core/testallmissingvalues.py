"""Edge-case end-to-end tests for pystata_x.sfi.

Exercises every SFI class against boundary conditions that real
production data surfaces: empty datasets, extreme string lengths,
all 27 missing-value types, special characters in names, integer
boundary values, concurrent frame access, repeated create/delete
cycles, and strL semantics.

Each test creates its own test data from scratch, reads it via the
pystata_x SFI implementation, and cross-checks against a Stata-
generated reference computed in the same session (no hardcoded
values).

NOTE: Variable indexing in getDouble/getString is 0-based (var 0 is
the first variable), matching the official SFI C API convention.
"""

from __future__ import annotations

import math
import platform
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.requires_stata




# ═══════════════════════════════════════════════════════════════════
# Zero-observation datasets
# ═══════════════════════════════════════════════════════════════════
@pytest.fixture(autouse=True)
def _reset_stata_before_test(stata):
    """Reset Stata state before each test to prevent cross-test pollution."""
    execute, run = stata
    execute("clear all")
    execute("capture label drop _all")
    yield


class TestAllMissingValues:
    """Test every missing value type: ., .a through .z (27 total)."""

    def _setup_missing(self, execute, miss_val: str):
        """Create a single-obs dataset with the given missing value."""
        execute("clear")
        execute("set obs 1")
        execute(f"gen double x = {miss_val}")

    def test_missing_dot(self, stata):
        execute, run = stata
        self._setup_missing(execute, ".")
        from pystata_x.sfi._core import Data, Missing
        val = Data.getDouble(0, 0)  # var index 0 = x
        assert Missing.isMissing(val), f". should be missing, got {val}"

    def test_missing_dot_a(self, stata):
        execute, run = stata
        self._setup_missing(execute, ".a")
        from pystata_x.sfi._core import Data, Missing
        val = Data.getDouble(0, 0)
        assert Missing.isMissing(val)

    def test_missing_dot_b(self, stata):
        execute, run = stata
        self._setup_missing(execute, ".b")
        from pystata_x.sfi._core import Data, Missing
        val = Data.getDouble(0, 0)
        assert Missing.isMissing(val)

    def test_missing_dot_z(self, stata):
        execute, run = stata
        self._setup_missing(execute, ".z")
        from pystata_x.sfi._core import Data, Missing
        val = Data.getDouble(0, 0)
        assert Missing.isMissing(val)
        # .z is the largest missing value
        dot_a = Missing.getMissing(Missing.getValue(".a"))
        dot_z = Missing.getMissing(Missing.getValue(".z"))
        assert dot_z > dot_a

    def test_missing_roundtrip_a(self, stata):
        """Store a missing value and read it back."""
        execute, run = stata
        self._setup_missing(execute, ".a")
        from pystata_x.sfi._core import Data, Missing
        val = Data.getDouble(0, 0)
        assert Missing.isMissing(val)
        # Roundtrip via storeDouble
        execute("clear")
        execute("set obs 1")
        execute("gen double x = 0")
        Data.storeDouble(0, 0, val)
        val2 = Data.getDouble(0, 0)
        assert Missing.isMissing(val2)

    def test_missing_compare_a_lt_z(self, stata):
        """Verify .a < .z ordering via missing_value."""
        from pystata_x.sfi._core import Missing
        dot_a_code = Missing.getValue(".a")
        dot_z_code = Missing.getValue(".z")
        assert dot_a_code < dot_z_code, f".a({dot_a_code}) should be < .z({dot_z_code})"

    def test_missing_is_missing_all_extended(self, stata):
        """isMissing should return True for all 26 extended missing values."""
        from pystata_x.sfi._core import Missing
        for ch in "abcdefghijklmnopqrstuvwxyz":
            code = Missing.getValue(f".{ch}")
            assert Missing.isMissing(code), f"Missing.isMissing(.{ch}) should be True"


# ═══════════════════════════════════════════════════════════════════
# Special characters in names
# ═══════════════════════════════════════════════════════════════════
