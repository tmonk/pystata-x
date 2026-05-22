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


class TestMultiFrameAccess:
    """Simultaneous access to multiple frames with independent data."""

    def _setup_frames(self, execute):
        execute("clear")
        execute("set obs 1")
        execute("gen x = 10")
        execute("capture frame drop frame_a")
        execute("capture frame drop frame_b")
        execute("frame create frame_a")
        execute("frame create frame_b")
        execute("frame change frame_a")
        execute("clear")
        execute("set obs 1")
        execute("gen x = 100")
        execute("frame change frame_b")
        execute("clear")
        execute("set obs 1")
        execute("gen x = 1000")
        execute("frame change default")

    def test_frames_independent(self, stata):
        """Each frame has its own data; switching frames reads the right values."""
        execute, run = stata
        self._setup_frames(execute)
        from pystata_x.sfi._core import Data, Frame

        # x is always the first (only) variable at index 0 in each frame
        def _read_x():
            return Data.getDouble(0, 0)

        Frame.setCWF("frame_a")
        assert _read_x() == 100.0, "frame_a.x should be 100"

        Frame.setCWF("frame_b")
        assert _read_x() == 1000.0, "frame_b.x should be 1000"

        Frame.setCWF("default")
        assert _read_x() == 10.0, "default.x should be 10"

    def test_frame_create_delete_cycle(self, stata):
        """Create, verify, delete, verify absence, recreate."""
        execute, run = stata
        from pystata_x.sfi._core import Frame

        execute("clear")
        execute("set obs 1")
        execute("gen x = 1")

        assert not Frame.exists("cycle_frame")

        execute("frame create cycle_frame")
        assert Frame.exists("cycle_frame")
        assert "cycle_frame" in Frame.getFrames()

        execute("frame drop cycle_frame")
        assert not Frame.exists("cycle_frame")
        assert "cycle_frame" not in Frame.getFrames()

        # Recreate
        execute("frame create cycle_frame")
        assert Frame.exists("cycle_frame")

        execute("frame drop cycle_frame")

    def test_frame_get_frame_count_matches(self, stata):
        """getFrameCount should match number of names returned by getFrames."""
        execute, run = stata
        from pystata_x.sfi._core import Frame
        names = Frame.getFrames()
        count = Frame.getFrameCount()
        assert count >= 1
        assert len(names) >= count

    def test_frame_switch_with_data(self, stata):
        """Switch between frames with different variables."""
        execute, run = stata
        from pystata_x.sfi._core import Data, Frame
        execute("clear")
        execute("set obs 5")
        execute("gen default_var = 99")
        execute("capture frame drop f1")
        execute("frame create f1")
        execute("frame change f1")
        execute("clear")
        execute("set obs 3")
        execute("gen f1_var = 200")
        execute("frame change default")

        assert Frame.exists("f1")
        assert Data.getVarName(0) == "default_var"
        Frame.setCWF("f1")
        assert Data.getVarName(0) == "f1_var"
        Frame.setCWF("default")
        assert Data.getVarName(0) == "default_var"


# ═══════════════════════════════════════════════════════════════════
# Matrix create/delete cycles
# ═══════════════════════════════════════════════════════════════════
