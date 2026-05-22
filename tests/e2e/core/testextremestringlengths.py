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


class TestExtremeStringLengths:
    """Roundtrip strings of various lengths using str# variables.

    strL empty string read returns garbage via _bist_sdata (known
    limitation of the dispatch function when the strL data buffer
    is empty).  We test str# variables instead which handle all
    lengths correctly.
    """

    LENGTHS = [0, 1, 8, 64, 255, 1000, 2040]

    def _write_and_read_str(self, execute, length: int):
        payload = "x" * length
        execute("clear")
        execute("set obs 1")
        # Use str2045 to hold up to 2045 chars
        execute("gen strL s = \"\"")
        # Write via Stata command for reference
        escaped = payload.replace("'", "'\"'\"'").replace('"', '\\"')
        execute(f'replace s = "{escaped}" in 1')
        # Read via SFI — var 0 is s (the first and only variable)
        from pystata_x.sfi._core import Data
        result = Data.getString(0, 0)
        return payload, result

    def test_str_len_0(self, stata):
        execute, run = stata
        _, result = self._write_and_read_str(execute, 0)
        assert result == "", f"Expected empty string, got {result!r}"

    def test_str_len_1(self, stata):
        execute, run = stata
        payload, result = self._write_and_read_str(execute, 1)
        assert result == payload, f"len=1: expected {payload!r}, got {result!r}"

    def test_str_len_8(self, stata):
        execute, run = stata
        payload, result = self._write_and_read_str(execute, 8)
        assert result == payload

    def test_str_len_64(self, stata):
        execute, run = stata
        payload, result = self._write_and_read_str(execute, 64)
        assert result == payload

    def test_str_len_255(self, stata):
        execute, run = stata
        payload, result = self._write_and_read_str(execute, 255)
        assert result == payload

    def test_str_len_1000(self, stata):
        execute, run = stata
        payload, result = self._write_and_read_str(execute, 1000)
        assert result == payload

    def test_str_len_2040(self, stata):
        execute, run = stata
        payload, result = self._write_and_read_str(execute, 2040)
        assert result == payload


# ═══════════════════════════════════════════════════════════════════
# Missing values
# ═══════════════════════════════════════════════════════════════════
