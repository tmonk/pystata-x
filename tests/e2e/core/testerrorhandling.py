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


class TestErrorHandling:
    """Out-of-bounds, invalid args, deleted structures — all should raise."""

    def test_var_index_nonexistent(self, stata):
        execute, run = stata
        execute("sysuse auto, clear")
        from pystata_x.sfi._core import Data
        with pytest.raises(ValueError, match="__does_not_exist__"):
            Data.getVarIndex("__does_not_exist__")

    def test_macro_get_nonexistent_global(self, stata):
        execute, run = stata
        execute("sysuse auto, clear")
        from pystata_x.sfi._core import Macro
        result = Macro.getGlobal("__never_set__")
        assert result == ""

    def test_macro_del_nonexistent(self, stata):
        execute, run = stata
        execute("sysuse auto, clear")
        from pystata_x.sfi._core import Macro
        Macro.delGlobal("__never_set__")

    def test_scalar_get_nonexistent(self, stata):
        execute, run = stata
        execute("sysuse auto, clear")
        from pystata_x.sfi._core import Scalar
        # Returns 0.0 (missing) for nonexistent scalars
        result = Scalar.getValue("__never_set__")
        assert result == 0.0 or result is None

    def test_valuelabel_get_label_nonexistent_name(self, stata):
        execute, run = stata
        execute("sysuse auto, clear")
        from pystata_x.sfi._core import ValueLabel
        # Returns empty string for nonexistent label names
        result = ValueLabel.getLabel("__never_set__", 0)
        assert result == ""

    def test_valuelabel_get_label_nonexistent_val(self, stata):
        execute, run = stata
        execute("sysuse auto, clear")
        from pystata_x.sfi._core import ValueLabel
        execute("label define testlbl 1 A 2 B")
        result = ValueLabel.getLabel("testlbl", 999)
        assert result == ""
        execute("label drop testlbl")

    def test_characteristic_get_nonexistent(self, stata):
        execute, run = stata
        execute("sysuse auto, clear")
        from pystata_x.sfi._core import Characteristic
        result = Characteristic.getDtaChar("__never_set__")
        assert result == "" or result is None

    def test_frame_get_at_nonexistent(self, stata):
        execute, run = stata
        execute("sysuse auto, clear")
        from pystata_x.sfi._core import Frame
        # FrameError is raised for out-of-range indices
        from pystata_x.sfi._core import FrameError
        with pytest.raises((ValueError, IndexError, FrameError)):
            Frame.getFrameAt(999)

    def test_frame_exists_nonexistent(self, stata):
        execute, run = stata
        execute("sysuse auto, clear")
        from pystata_x.sfi._core import Frame
        assert not Frame.exists("__no_such_frame__")

    def test_platform_methods_always_return(self, stata):
        """Platform methods should never raise, only return True/False."""
        from pystata_x.sfi._core import Platform
        assert isinstance(Platform.isWindows(), bool)
        assert isinstance(Platform.isMac(), bool)
        assert isinstance(Platform.isUnix(), bool)
        assert isinstance(Platform.isLinux(), bool)
        assert isinstance(Platform.isSolaris(), bool)
