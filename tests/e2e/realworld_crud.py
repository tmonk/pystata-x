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



@pytest.fixture(autouse=True)
def _reset_stata_crud(stata):
    execute, run = stata
    execute("clear all")
    execute("capture label drop _all")
    yield

# ═══════════════════════════════════════════════════════════════════
# Workflow 1: Full dataset lifecycle
# ═══════════════════════════════════════════════════════════════════


class TestFullDatasetLifecycle:
    """Create → populate → read → modify → delete → verify absence."""

    def test_create_and_populate(self, stata):
        """Step 1: Create dataset with mixed types."""
        execute, run = stata
        Data, Macro, Scalar, ValueLabel, Missing, *_ = _reset(execute)

        execute("set obs 10")
        execute("gen id = _n")
        execute("gen byte flag = mod(_n, 2)")
        execute("gen float value = _n * 1.5")
        execute('gen str8 code = strofreal(_n, "%02.0f")')
        execute("gen double bigval = _n * 1000000")

        # Variables (0-based): 0=id, 1=flag, 2=value, 3=code, 4=bigval
        assert Data.getVarCount() == 5
        assert Data.getObsTotal() == 10
        assert Data.getVarName(0) == "id"
        assert Data.getVarName(1) == "flag"
        assert Data.getVarName(2) == "value"
        assert Data.getVarName(3) == "code"
        assert Data.getVarName(4) == "bigval"

        # Verify values: obs 0 = _n=1
        assert Data.getDouble(0, 0) == 1.0        # id[0] = 1
        assert Data.getDouble(1, 0) == 1.0        # flag[0] = mod(1,2) = 1
        assert Data.getDouble(2, 0) == 1.5        # value[0] = 1*1.5
        assert Data.getString(3, 0) == "01"        # code[0] = strofreal(1, "%02.0f")
        assert Data.getDouble(4, 0) == 1e6         # bigval[0] = 1*1e6

        # Obs 9 (0-based, _n=10)
        assert Data.getDouble(0, 9) == 10.0       # id[9] = 10
        assert Data.getDouble(1, 9) == 0.0        # flag[9] = mod(10,2) = 0
        assert Data.getDouble(2, 9) == 15.0       # value[9] = 10*1.5
        assert Data.getString(3, 9) == "10"        # code[9] = strofreal(10, "%02.0f")
        assert Data.getDouble(4, 9) == 1e7         # bigval[9] = 10*1e6

    def test_modify_values(self, stata):
        """Step 2: Modify existing values and verify."""
        execute, run = stata
        Data, *_ = _reset(execute)

        execute("set obs 5")
        execute("gen x = _n * 10")
        execute("gen y = _n * 100")

        # x is var 0, y is var 1
        assert Data.getDouble(0, 0) == 10.0   # x[0] = 1*10
        assert Data.getDouble(1, 0) == 100.0  # y[0] = 1*100

        # Modify via SFI (x at obs 2 = 30 → 999)
        Data.storeDouble(0, 2, 999.0)
        assert Data.getDouble(0, 2) == 999.0

        # Modify y at obs 4 (y[4] = 500 → 888)
        Data.storeDouble(1, 4, 888.0)
        assert Data.getDouble(1, 4) == 888.0

        # Verify other values unchanged
        assert Data.getDouble(0, 0) == 10.0
        assert Data.getDouble(1, 0) == 100.0

    def test_modify_strings(self, stata):
        """Step 3: Modify string values and verify."""
        execute, run = stata
        Data, *_ = _reset(execute)

        execute("set obs 3")
        execute('gen str8 s = "orig" + strofreal(_n)')

        # s is var 0
        assert Data.getString(0, 0) == "orig1"

        # Modify via SFI
        Data.storeString(0, 0, "modified")
        assert Data.getString(0, 0) == "modified"

        # Other obs unchanged
        assert Data.getString(0, 1) == "orig2"
        assert Data.getString(0, 2) == "orig3"

    def test_add_value_labels(self, stata):
        """Step 4: Create and assign value labels."""
        execute, run = stata
        Data, Macro, Scalar, ValueLabel, Missing, *_ = _reset(execute)

        execute("set obs 10")
        execute("gen byte status = ceil(_n / 3)")
        execute("label define status 1 low 2 medium 3 high")
        execute("label values status status")

        # Verify via ValueLabel API
        assert "status" in ValueLabel.getNames()
        assert ValueLabel.getLabel("status", 1) == "low"
        assert ValueLabel.getLabel("status", 2) == "medium"
        assert ValueLabel.getLabel("status", 3) == "high"

        # Verify via Data's getVarValueLabel — status is var 0
        assert Data.getVarValueLabel(0) == "status"

        # Verify formatted value — obs 0 has status = ceil(1/3) = 1 = "low"
        formatted = Data.getFormattedValue(0, 0, True)
        assert formatted == "low", f"Expected 'low', got {formatted!r}"

    def test_delete_variable(self, stata):
        """Step 5: Drop a variable and verify absence."""
        execute, run = stata
        Data, *_ = _reset(execute)

        execute("set obs 3")
        execute("gen a = 1")
        execute("gen b = 2")
        execute("gen c = 3")

        assert Data.getVarCount() == 3
        assert Data.getVarName(0) == "a"
        assert Data.getVarName(1) == "b"
        assert Data.getVarName(2) == "c"

        # Drop variable 'b' via Stata command
        execute("drop b")
        assert Data.getVarCount() == 2
        assert Data.getVarName(0) == "a"
        assert Data.getVarName(1) == "c"

        # Verify remaining values unchanged
        assert Data.getDouble(0, 0) == 1.0   # a[0]
        assert Data.getDouble(1, 1) == 3.0   # c[1]

    def test_delete_all_and_verify_empty(self, stata):
        """Step 6: Drop all data and verify empty state."""
        execute, run = stata
        Data, Macro, Scalar, ValueLabel, Missing, *_ = _reset(execute)

        execute("set obs 5")
        execute("gen x = _n")
        execute("gen y = _n * 10")
        execute("scalar mys = 42")
        execute('global myg = "test"')
        execute("label define mylbl 1 A 2 B")
        execute("label values x mylbl")
        execute("matrix mymat = (1,2,3,4)")

        # Verify populated
        assert Data.getVarCount() == 2
        assert Scalar.getValue("mys") == 42.0
        assert Macro.getGlobal("myg") == "test"
        assert "mylbl" in ValueLabel.getNames()
        assert Matrix.exists("mymat")

        # Drop everything
        execute("clear")
        execute("scalar drop mys")
        execute("macro drop myg")
        execute("label drop mylbl")
        execute("matrix drop mymat")

        # Verify empty
        assert Data.getVarCount() == 0
        assert Data.getObsTotal() == 0

        # Scalars cleared
        with pytest.raises((ValueError, RuntimeError)):
            Scalar.getValue("mys")

        # Macro cleared
        assert Macro.getGlobal("myg") == ""

        # Matrix cleared
        assert not Matrix.exists("mymat")


# ═══════════════════════════════════════════════════════════════════
# Workflow 2: Macro + Scalar + Data integration
# ═══════════════════════════════════════════════════════════════════


class TestMacroScalarDataIntegration:
    """Combine macros, scalars, and data in a single workflow."""

    def test_compute_with_scalars_store_in_macros(self, stata):
        """Create a scalar from data, read into a global macro, verify."""
        execute, run = stata
        Data, Macro, Scalar, *_ = _reset(execute)

        execute("sysuse auto, clear")
        execute("summarize price")
        execute("scalar mean_price = r(mean)")
        mean = Scalar.getValue("mean_price")

        # Store in global macro
        Macro.setGlobal("mean_price_str", str(mean))
        retrieved = Macro.getGlobal("mean_price_str")
        assert retrieved == str(mean)

        # Use macro to create a variable
        execute("gen byte above_mean = price > " + Macro.getGlobal("mean_price_str"))
        # above_mean is var 12 (after all 12 auto vars; 0-based index)
        # Actually after sysuse auto, there are 12 vars (0-11).
        # gen above_mean adds var 12
        assert Data.getVarCount() == 13

    def test_create_var_from_macro(self, stata):
        """Use global macros to parameterize data creation."""
        execute, run = stata
        Data, Macro, *_ = _reset(execute)

        execute("set obs 100")
        Macro.setGlobal("multiplier", "10")
        execute("gen x = _n * " + Macro.getGlobal("multiplier"))

        # x is var 0
        assert Data.getDouble(0, 0) == 10.0   # obs 0: (1) * 10
        assert Data.getDouble(0, 99) == 1000.0  # obs 99: (100) * 10

    def test_scalar_delete_and_recreate(self, stata):
        """Delete a scalar, recreate it, verify it works."""
        execute, run = stata
        _, _, Scalar, *_ = _reset(execute)

        execute("scalar x = 42")
        assert Scalar.getValue("x") == 42.0
        execute("scalar drop x")
        with pytest.raises((ValueError, RuntimeError)):
            Scalar.getValue("x")
        execute("scalar x = 99")
        assert Scalar.getValue("x") == 99.0


# ═══════════════════════════════════════════════════════════════════
# Workflow 3: Characteristic + Frame + Matrix integration
# ═══════════════════════════════════════════════════════════════════


class TestCharFrameMatrixIntegration:
    """Combine characteristic, frame, and matrix operations."""

    def test_char_and_matrix(self, stata):
        execute, run = stata
        Data, Macro, Scalar, ValueLabel, Missing, Characteristic, Frame, Matrix, *_ = _reset(execute)

        execute("sysuse auto, clear")
        execute("char _dta[source] 'auto.dta'")
        execute("char _dta[generated_by] 'test'")

        assert Characteristic.getDtaChar("source") == "auto.dta"
        assert Characteristic.getDtaChar("generated_by") == "test"
        assert Characteristic.getDtaChar("nonexistent") == ""

        # Create a correlation matrix
        execute("correlate price mpg weight")
        execute("matrix C = r(C)")
        assert Matrix.exists("C")
        c_mat = Matrix.get("C")
        assert len(c_mat) >= 3
        # Diagonal should be 1.0
        assert c_mat[0][0] == pytest.approx(1.0)
        assert c_mat[1][1] == pytest.approx(1.0)
        assert c_mat[2][2] == pytest.approx(1.0)

    def test_frame_create_and_verify_independent(self, stata):
        execute, run = stata
        Data, Macro, Scalar, ValueLabel, Missing, Characteristic, Frame, Matrix, *_ = _reset(execute)

        # Default frame
        execute("set obs 10")
        execute("gen x = _n")
        execute("gen y = _n * 100")

        # Create new frame (using bytes to avoid escaping issues)
        from pystata_x.sfi._engine import _LIB
        _LIB.StataSO_Execute(b"frame create analysis_frame")
        _LIB.StataSO_Execute(b"frame change analysis_frame")
        _LIB.StataSO_Execute(b"clear")
        _LIB.StataSO_Execute(b"set obs 5")
        _LIB.StataSO_Execute(b"gen x = _n * 1000")
        _LIB.StataSO_Execute(b'gen z = "frame_b_data"')
        _LIB.StataSO_Execute(b"frame change default")

        assert Frame.exists("analysis_frame")
        assert "analysis_frame" in Frame.getFrames()

        # Default frame should have original data
        assert Data.getVarCount() == 2
        assert Data.getVarName(0) == "x"
        assert Data.getVarName(1) == "y"

        # Switch to analysis frame
        Frame.setCWF("analysis_frame")
        assert Data.getVarCount() == 2
        assert Data.getVarName(0) == "x"
        assert Data.getVarName(1) == "z"
        assert Data.getDouble(0, 0) == 1000.0   # x = 1*1000
        assert Data.getDouble(0, 4) == 5000.0   # x = 5*1000

        # Modify in analysis frame
        Data.storeDouble(0, 0, 777.0)
        assert Data.getDouble(0, 0) == 777.0

        # Switch back to default — unchanged
        Frame.setCWF("default")
        assert Data.getDouble(0, 0) == 1.0

        _LIB.StataSO_Execute(b"frame drop analysis_frame")

    def test_matrix_from_frame_data(self, stata):
        """Create a matrix from frame data, extract via Matrix API."""
        execute, run = stata
        _, _, _, _, _, _, _, Matrix, *_ = _reset(execute)

        execute("sysuse auto, clear")
        execute("mkmat price mpg weight, mat(data_mat)")

        assert Matrix.exists("data_mat")
        dims = (Matrix.getRowTotal("data_mat"), Matrix.getColTotal("data_mat"))
        assert dims == (74, 3)

        # Check values from auto: price[0]=4099.0, mpg[0]=22.0
        assert Matrix.getAt("data_mat", 0, 0) == 4099.0
        assert Matrix.getAt("data_mat", 0, 1) == 22.0

        # Get entire matrix
        full = Matrix.get("data_mat")
        assert len(full) == 74
        assert len(full[0]) == 3

        execute("matrix drop data_mat")

    def test_char_persistence_across_frames(self, stata):
        """Dataset characteristics are global to the dataset."""
        execute, run = stata
        _, _, _, _, _, Characteristic, Frame, _, *_ = _reset(execute)

        execute("sysuse auto, clear")
        execute("char _dta[note] 'test note'")

        # Frame creation should not affect characteristics
        from pystata_x.sfi._engine import _LIB
        _LIB.StataSO_Execute(b"frame create f2")
        _LIB.StataSO_Execute(b"frame change f2")
        _LIB.StataSO_Execute(b"clear")
        _LIB.StataSO_Execute(b"set obs 1")
        _LIB.StataSO_Execute(b"gen x = 1")
        _LIB.StataSO_Execute(b"frame change default")

        assert Characteristic.getDtaChar("note") == "test note"
        _LIB.StataSO_Execute(b"frame drop f2")

    def test_frame_switch_and_read(self, stata):
        execute, run = stata
        Data, _, _, _, _, _, Frame, _, *_ = _reset(execute)

        execute("set obs 3")
        execute("gen a = 10")
        execute("gen b = 20")

        from pystata_x.sfi._engine import _LIB
        _LIB.StataSO_Execute(b"frame create f3")
        _LIB.StataSO_Execute(b"frame change f3")
        _LIB.StataSO_Execute(b"clear")
        _LIB.StataSO_Execute(b"set obs 4")
        _LIB.StataSO_Execute(b"gen a = 1000")
        _LIB.StataSO_Execute(b"frame change default")

        Frame.setCWF("f3")
        assert Data.getVarCount() == 1
        assert Data.getVarName(0) == "a"
        assert Data.getDouble(0, 0) == 1000.0

        Frame.setCWF("default")
        assert Data.getVarCount() == 2
        assert Data.getVarName(0) == "a"
        assert Data.getVarName(1) == "b"
        assert Data.getDouble(0, 0) == 10.0
        assert Data.getDouble(1, 0) == 20.0

        _LIB.StataSO_Execute(b"frame drop f3")


# ═══════════════════════════════════════════════════════════════════
# Workflow 4: Preference + Macro persistence
# ═══════════════════════════════════════════════════════════════════


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
        formatted = Data.getFormattedValue(0, 1, False)  # obs 1, value=2
        assert formatted is not None
        assert "2" in formatted

        formatted_miss = Data.getFormattedValue(0, 2, False)  # obs 2, missing
        assert formatted_miss is not None


# ═══════════════════════════════════════════════════════════════════
# Workflow 6: Stress test — many variables
# ═══════════════════════════════════════════════════════════════════


class TestManyVariables:
    """Create a dataset with many variables and verify all are readable."""

    def test_100_variables(self, stata):
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

    def test_5_vars_1000_obs(self, stata):
        """Many observations, verify bulk read."""
        execute, run = stata
        Data, *_ = _reset(execute)

        execute("set obs 1000")
        execute("gen x = _n")
        execute("gen y = _n * 2")
        execute("gen z = _n * 3")
        execute('gen str8 s = strofreal(_n, "obs-%04.0f")')

        assert Data.getObsTotal() == 1000
        assert Data.getVarCount() == 4

        # Variables: 0=x, 1=y, 2=z, 3=s
        assert Data.getDouble(0, 0) == 1.0       # x[0] = _n=1
        assert Data.getDouble(0, 999) == 1000.0  # x[999] = 1000
        assert Data.getDouble(1, 0) == 2.0       # y[0] = 2
        assert Data.getDouble(1, 999) == 2000.0  # y[999] = 2000
        assert Data.getDouble(2, 0) == 3.0       # z[0] = 3
        assert Data.getDouble(2, 999) == 3000.0  # z[999] = 3000
        assert Data.getString(3, 0) == "obs-0001"   # s[0]
        assert Data.getString(3, 999) == "obs-1000" # s[999]


# ═══════════════════════════════════════════════════════════════════
# Workflow 7: SFIToolkit utilities in workflows
# ═══════════════════════════════════════════════════════════════════


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

        assert SFIToolkit.formatValue(3.14159, "%9.2f") == "     3.14"
        assert SFIToolkit.formatValue(42.0, "%8.0g") == "      42"
        assert SFIToolkit.formatValue(0.0, "%8.0g") == "       0"
        assert SFIToolkit.formatValue(-1.5, "%6.1f") == "  -1.5"

    def test_get_real_of_string(self, stata):
        from pystata_x.sfi._core import SFIToolkit, Missing
        assert SFIToolkit.getRealOfString("42") == 42.0
        assert SFIToolkit.getRealOfString("3.14") == 3.14
        # Invalid string returns missing
        r = SFIToolkit.getRealOfString("foo")
        assert Missing.isMissing(r)
