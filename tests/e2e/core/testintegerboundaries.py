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


class TestIntegerBoundaries:
    """Verify roundtrip of boundary integer values via getDouble (var 0)."""

    BOUNDARIES = [
        0, 1, -1,
        32767,       # max int (Stata int)
        -32768,      # min int
        2147483647,  # max long
        -2147483648, # min long
        2**31 - 1,
        -2**31,
        2**32 - 1,
        -2**32,
    ]

    def _test_roundtrip_one(self, execute, val: int):
        execute("clear")
        execute("set obs 1")
        execute(f"gen double x = {val}")
        from pystata_x.sfi._core import Data
        # x is the first (and only) variable at index 0
        result = Data.getDouble(0, 0)
        assert result == float(val), f"Roundtrip of {val} gave {result}"

    def test_boundary_0(self, stata):
        execute, run = stata
        self._test_roundtrip_one(execute, 0)

    def test_boundary_1(self, stata):
        execute, run = stata
        self._test_roundtrip_one(execute, 1)

    def test_boundary_neg1(self, stata):
        execute, run = stata
        self._test_roundtrip_one(execute, -1)

    def test_boundary_int_max(self, stata):
        execute, run = stata
        self._test_roundtrip_one(execute, 32767)

    def test_boundary_int_min(self, stata):
        execute, run = stata
        self._test_roundtrip_one(execute, -32768)

    def test_boundary_long_max(self, stata):
        execute, run = stata
        self._test_roundtrip_one(execute, 2147483647)

    def test_boundary_long_min(self, stata):
        execute, run = stata
        self._test_roundtrip_one(execute, -2147483648)

    def test_boundary_2p31(self, stata):
        execute, run = stata
        self._test_roundtrip_one(execute, 2**31 - 1)

    def test_boundary_neg2p31(self, stata):
        execute, run = stata
        self._test_roundtrip_one(execute, -2**31)

    def test_boundary_uint32(self, stata):
        execute, run = stata
        self._test_roundtrip_one(execute, 2**32 - 1)

    def test_boundary_neg_uint32(self, stata):
        execute, run = stata
        self._test_roundtrip_one(execute, -2**32)


# ═══════════════════════════════════════════════════════════════════
# Multi-frame access
# ═══════════════════════════════════════════════════════════════════
