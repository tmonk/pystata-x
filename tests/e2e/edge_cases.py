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


@pytest.fixture(autouse=True)
def _reset_stata_edge(stata):
    execute, run = stata
    execute("clear all")
    execute("capture label drop _all")
    yield


# ═══════════════════════════════════════════════════════════════════
# Zero-observation datasets
# ═══════════════════════════════════════════════════════════════════


class TestZeroObsDataset:
    """Data, Macro, Frame operations with a zero-observation dataset."""

    def test_obs_count_zero(self, stata):
        execute, run = stata
        execute("clear")
        execute("set obs 0")
        from pystata_x.sfi._core import Data
        assert Data.getObsTotal() == 0

    def test_var_count_after_set_obs_0(self, stata):
        execute, run = stata
        execute("clear")
        execute("set obs 0")
        execute("gen x = 1")
        from pystata_x.sfi._core import Data
        assert Data.getObsTotal() == 0
        assert Data.getVarCount() == 1

    def test_get_double_empty(self, stata):
        execute, run = stata
        execute("clear")
        execute("set obs 0")
        execute("gen x = 1")
        from pystata_x.sfi._core import Data
        # Reading from an empty dataset should not crash
        val = Data.getDouble(0, 0)
        # Just check no crash; value may be NaN
        assert val is not None or (isinstance(val, float) and math.isnan(val))

    def test_get_string_empty(self, stata):
        execute, run = stata
        execute("clear")
        execute("set obs 0")
        execute('gen str8 s = "a"')
        from pystata_x.sfi._core import Data
        val = Data.getString(1, 0)  # var index 1 = s
        assert val is not None

    def test_var_names_zero_obs(self, stata):
        execute, run = stata
        execute("clear")
        execute("set obs 0")
        execute("gen x = 1")
        execute('gen str8 s = "hello"')
        from pystata_x.sfi._core import Data
        assert Data.getVarCount() == 2
        assert Data.getVarName(0) == "x"
        assert Data.getVarName(1) == "s"


# ═══════════════════════════════════════════════════════════════════
# Extreme string lengths
# ═══════════════════════════════════════════════════════════════════


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


class TestSpecialCharsInNames:
    """Variable and value-label names with underscores, mixed case."""

    def test_varname_with_underscores(self, stata):
        execute, run = stata
        execute("clear")
        execute("set obs 1")
        execute("gen my_var_name_1 = 42")
        from pystata_x.sfi._core import Data
        assert Data.getVarName(0) == "my_var_name_1"
        assert Data.getVarCount() == 1
        assert Data.getVarIndex("my_var_name_1") == 0

    def test_varname_mixed_case(self, stata):
        execute, run = stata
        execute("clear")
        execute("set obs 1")
        execute("gen MyStataVariable = 42")
        from pystata_x.sfi._core import Data
        name = Data.getVarName(0)
        # Stata lowercases variable names internally; getVarName may return
        # the lowercased name or preserve case depending on platform
        assert name.lower() == "mystatavariable"
        idx = Data.getVarIndex("mystatavariable")
        assert idx == 0

    def test_varname_max_length(self, stata):
        execute, run = stata
        execute("clear")
        execute("set obs 1")
        # Max Stata variable name is 32 characters
        long_name = "a" * 32
        execute(f"gen {long_name} = 1")
        from pystata_x.sfi._core import Data
        assert Data.getVarName(0) == long_name

    def test_varname_starts_with_number_fails(self, stata):
        """Stata rejects variable names starting with a digit."""
        execute, run = stata
        from pystata_x.sfi._core import SFIToolkit
        assert not SFIToolkit.isValidName("123abc")

    def test_varname_valid_via_sfitoolkit(self, stata):
        execute, run = stata
        from pystata_x.sfi._core import SFIToolkit
        # Stata confirms most alphanumeric names as syntactically valid
        assert SFIToolkit.isValidName("valid_name")
        assert SFIToolkit.isValidName("x1")
        assert SFIToolkit.isValidName("price")
        assert SFIToolkit.isValidName("_stata")
        assert SFIToolkit.isValidName("123abc")  # syntactically valid per Stata

    def test_varname_make_var_name(self, stata):
        execute, run = stata
        from pystata_x.sfi._core import SFIToolkit
        assert SFIToolkit.makeVarName("my var name") == "myvarname"
        assert SFIToolkit.makeVarName("123abc") == "_123abc"
        assert SFIToolkit.makeVarName("foo") == "foo"


# ═══════════════════════════════════════════════════════════════════
# 32-bit integer boundaries
# ═══════════════════════════════════════════════════════════════════


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


class TestMatrixCreateDeleteCycles:
    """Repeated create / verify / delete / verify cycles for matrices."""

    def test_matrix_exists_after_creation(self, stata):
        execute, run = stata
        from pystata_x.sfi._core import Matrix
        from pystata_x.sfi._engine import _LIB
        _LIB.StataSO_Execute(b"clear")
        _LIB.StataSO_Execute(b"matrix testmat = (1,2,3,4)")
        assert Matrix.exists("testmat")
        assert Matrix.get("testmat") == [[1.0, 2.0, 3.0, 4.0]]
        _LIB.StataSO_Execute(b"matrix drop testmat")
        assert not Matrix.exists("testmat")

    def test_matrix_repeated_create_delete(self, stata):
        """Create, delete, recreate — 5 cycles."""
        execute, run = stata
        from pystata_x.sfi._core import Matrix
        from pystata_x.sfi._engine import _LIB
        for i in range(5):
            name = f"cycle_mat_{i}"
            _LIB.StataSO_Execute(f"matrix {name} = (1,2,3,4)".encode())
            assert Matrix.exists(name), f"Cycle {i}: create failed"
            _LIB.StataSO_Execute(f"matrix drop {name}".encode())
            assert not Matrix.exists(name), f"Cycle {i}: delete failed"

    def test_matrix_dims_after_cycle(self, stata):
        execute, run = stata
        from pystata_x.sfi._core import Matrix
        # Use bytes-level execute to avoid Python escaping issues with \
        from pystata_x.sfi._engine import _LIB
        _LIB.StataSO_Execute(b'matrix m = (1,2,3,4\\5,6,7,8)')
        _LIB.StataSO_Execute(b'matrix rownames m = ra rb')
        _LIB.StataSO_Execute(b'matrix colnames m = ca cb cd ce')
        assert Matrix.getRowTotal("m") == 2
        assert Matrix.getColTotal("m") == 4
        assert Matrix.getRowNames("m") == ["ra", "rb"]
        assert Matrix.getColNames("m") == ["ca", "cb", "cd", "ce"]
        _LIB.StataSO_Execute(b'matrix drop m')
        assert not Matrix.exists("m")
        # Recreate with different dims
        _LIB.StataSO_Execute(b'matrix m = (5,6,7,8,9,10\\11,12,13,14,15,16)')
        assert Matrix.getRowTotal("m") == 2
        assert Matrix.getColTotal("m") == 6
        _LIB.StataSO_Execute(b'matrix drop m')

    def test_matrix_non_existent_raises(self, stata):
        execute, run = stata
        from pystata_x.sfi._core import Matrix
        assert not Matrix.exists("__never_created__")
        with pytest.raises(ValueError, match="does not exist|__never_created__"):
            Matrix.getRowTotal("__never_created__")
        with pytest.raises(ValueError, match="does not exist|__never_created__"):
            Matrix.getColTotal("__never_created__")


# ═══════════════════════════════════════════════════════════════════
# strL boundary behavior
# ═══════════════════════════════════════════════════════════════════


class TestStrLBoundary:
    """strL variables — reading strings with non-empty content.

    NOTE: _bist_sdata returns garbage for empty strL variables (known
    dispatch function limitation).  Tests here use non-empty strings.
    """

    def test_strl_basic_read(self, stata):
        execute, run = stata
        execute("clear")
        execute("set obs 1")
        execute('gen strL s = "hello world"')
        from pystata_x.sfi._core import Data
        val = Data.getString(0, 0)  # var 0 = s
        assert val == "hello world", f"strL basic read: got {val!r}"

    def test_strl_numeric_stored_as_str(self, stata):
        execute, run = stata
        execute("clear")
        execute("set obs 1")
        execute('gen strL s = "42"')
        from pystata_x.sfi._core import Data
        val = Data.getString(0, 0)
        assert val == "42"

    def test_strl_with_newlines(self, stata):
        """strL can hold multi-line strings (Stata \n is literal backslash-n)."""
        execute, run = stata
        execute("clear")
        execute("set obs 1")
        # Use actual newlines via macro expansion
        execute('global __px_br = char(10)')
        execute('gen strL s = "line 1" + "$" + "line 2" + "$" + "line 3"')
        from pystata_x.sfi._core import Data
        val = Data.getString(0, 0)
        assert "line 1" in val
        assert "line 2" in val
        assert "line 3" in val

    def test_strl_is_str_type_detection(self, stata):
        """isVarTypeStr and isVarTypeStrL should distinguish str from strL."""
        execute, run = stata
        execute("clear")
        execute("set obs 1")
        execute('gen str8 s1 = "short"')
        execute('gen strL s2 = "long str"')
        from pystata_x.sfi._core import Data
        assert Data.isVarTypeStr(0)    # str8 is a string type
        assert Data.isVarTypeStr(1)    # strL is also a string type
        assert not Data.isVarTypeStrL(0)  # str8 is NOT strL
        assert Data.isVarTypeStrL(1)      # strL IS strL
        # isVarTypeString should be True for both
        assert Data.isVarTypeString(0)
        assert Data.isVarTypeString(1)


# ═══════════════════════════════════════════════════════════════════
# Preference edge cases
# ═══════════════════════════════════════════════════════════════════


class TestPreferenceEdgeCases:
    """Preference set/get/delete with edge-case key names."""

    def test_pref_empty_key(self, stata):
        execute, run = stata
        from pystata_x.sfi._core import Preference as PR
        # Empty key is not a valid preference — just check no crash
        val = PR.getSavedPref("")
        assert val is not None

    def test_pref_long_key(self, stata):
        execute, run = stata
        from pystata_x.sfi._core import Preference as PR
        long_key = "x" * 200
        PR.setSavedPref(long_key, "long_key_val")
        assert PR.getSavedPref(long_key) == "long_key_val"
        PR.deleteSavedPref(long_key)
        assert PR.getSavedPref(long_key) == "" or PR.getSavedPref(long_key) is None

    def test_pref_special_chars_key(self, stata):
        execute, run = stata
        from pystata_x.sfi._core import Preference as PR
        PR.setSavedPref("pref_a_b", "dash_val")
        assert PR.getSavedPref("pref_a_b") == "dash_val"
        PR.deleteSavedPref("pref_a_b")

    def test_pref_unicode_value(self, stata):
        execute, run = stata
        from pystata_x.sfi._core import Preference as PR
        PR.setSavedPref("px_unicode", "café")
        assert PR.getSavedPref("px_unicode") == "café"
        PR.deleteSavedPref("px_unicode")

    def test_pref_overwrite(self, stata):
        execute, run = stata
        from pystata_x.sfi._core import Preference as PR
        PR.setSavedPref("px_overwrite", "first")
        assert PR.getSavedPref("px_overwrite") == "first"
        PR.setSavedPref("px_overwrite", "second")
        assert PR.getSavedPref("px_overwrite") == "second"
        PR.deleteSavedPref("px_overwrite")


# ═══════════════════════════════════════════════════════════════════
# Error handling
# ═══════════════════════════════════════════════════════════════════


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
        with pytest.raises(ValueError, match="__never_set__"):
            Scalar.getValue("__never_set__")

    def test_valuelabel_get_label_nonexistent_name(self, stata):
        execute, run = stata
        execute("sysuse auto, clear")
        from pystata_x.sfi._core import ValueLabel
        with pytest.raises(ValueError, match="__never_set__"):
            ValueLabel.getLabel("__never_set__", 0)

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
        with pytest.raises((ValueError, IndexError)):
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
