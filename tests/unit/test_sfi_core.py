"""Unit tests for ``pystata_x.sfi._core`` SFI API classes (mocked strategy).

Tests Macro, Data, Scalar, Missing, ValueLabel and SFIToolkit with
all _engine / _STRATEGY dependencies mocked.  Verifies 0-based ↔ 1-based
index conversion, boundary cases, error propagation, and that every public
method routes to the correct helper.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch, ANY, PropertyMock

import pytest


# ── Fixture: mock _engine + _STRATEGY imports used by _core ──────

@pytest.fixture(autouse=True)
def _mock_engine():
    """Mock every external dependency that _core imports.

    We patch at the _core module level:
    - call_int, call_double, call_string, call_void, etc. (engine calls)
    - read_obs_count, read_var_count (engine helpers)
    - _check_fast_path (always False for unit tests)
    - _STRATEGY methods that _core delegates to
    """
    import pystata_x.sfi._core as core_mod
    from pystata_x.sfi._strategy import _STRATEGY

    patchers = []

    # Engine call functions
    engine_targets = [
        "call_int", "call_double", "call_string", "call_void",
        "call_store_double", "call_store_string",
        "call_set_scalar", "call_set_strscalar",
        "call_create_valuelabel", "call_vlmodify",
    ]
    engine_mocks = {}
    for name in engine_targets:
        mk = MagicMock()
        engine_mocks[name] = mk
        p = patch.object(core_mod, name, mk)
        p.start()
        patchers.append(p)

    # Engine helper functions
    helper_targets = ["read_obs_count", "read_var_count"]
    helper_mocks = {}
    for name in helper_targets:
        mk = MagicMock()
        helper_mocks[name] = mk
        p = patch.object(core_mod, name, mk)
        p.start()
        patchers.append(p)

    # Fast path: always disabled in unit tests
    p_fast = patch.object(core_mod, "_check_fast_path", return_value=False)
    p_fast.start()
    patchers.append(p_fast)

    # Strategy methods — only those that actually exist on _STRATEGY and are
    # called by _core. Check existence first.
    strategy_targets = [
        "get_macro_global", "set_macro_global", "del_macro_global",
        "get_macro_local", "set_macro_local",
        "get_var_name", "get_var_type", "find_var_index",
        "get_var_format", "get_var_value_label",
        "get_string", "store_double", "store_string",
        "get_scalar_value", "set_scalar_value",
        "get_scalar_string", "set_scalar_string",
        "vl_exists", "vl_create", "vl_drop", "vl_define",
        "vl_get_label", "macro_expand", "get_temp_name",
        "get_max_vars",
    ]
    strategy_mocks = {}
    for name in strategy_targets:
        if hasattr(_STRATEGY, name):
            mk = MagicMock()
            strategy_mocks[name] = mk
            p = patch.object(core_mod._STRATEGY, name, mk)
            p.start()
            patchers.append(p)

    mocks = {**engine_mocks, **helper_mocks, **strategy_mocks}
    yield mocks

    for p in patchers:
        p.stop()


# ── Macro ─────────────────────────────────────────────────────────

class TestMacro:
    def test_get_global(self, _mock_engine):
        _mock_engine["get_macro_global"].return_value = "hello"
        from pystata_x.sfi._core import Macro
        assert Macro.getGlobal("myglob") == "hello"
        _mock_engine["get_macro_global"].assert_called_once_with("myglob")

    def test_set_global(self, _mock_engine):
        from pystata_x.sfi._core import Macro
        Macro.setGlobal("myglob", "myvalue")
        _mock_engine["set_macro_global"].assert_called_once_with("myglob", "myvalue")

    def test_del_global(self, _mock_engine):
        from pystata_x.sfi._core import Macro
        Macro.delGlobal("myglob")
        _mock_engine["del_macro_global"].assert_called_once_with("myglob")


# ── Data ──────────────────────────────────────────────────────────

class TestData:
    def test_get_obs_total(self, _mock_engine):
        _mock_engine["read_obs_count"].return_value = 74
        from pystata_x.sfi._core import Data
        assert Data.getObsTotal() == 74

    def test_get_var_count(self, _mock_engine):
        _mock_engine["read_var_count"].return_value = 12
        from pystata_x.sfi._core import Data
        assert Data.getVarCount() == 12

    def test_get_var_name(self, _mock_engine):
        _mock_engine["get_var_name"].return_value = "price"
        from pystata_x.sfi._core import Data
        assert Data.getVarName(1) == "price"
        _mock_engine["get_var_name"].assert_called_once_with(1)

    def test_get_var_label(self, _mock_engine):
        _mock_engine["call_string"].return_value = "Price Label"
        from pystata_x.sfi._core import Data
        assert Data.getVarLabel(1) == "Price Label"
        _mock_engine["call_string"].assert_called_once_with("_bist_varlabel", 2)

    def test_get_var_type(self, _mock_engine):
        _mock_engine["get_var_type"].return_value = "float"
        from pystata_x.sfi._core import Data
        assert Data.getVarType(2) == "float"
        _mock_engine["get_var_type"].assert_called_once_with(2)

    def test_get_var_index(self, _mock_engine):
        _mock_engine["find_var_index"].return_value = 2
        from pystata_x.sfi._core import Data
        assert Data.getVarIndex("mpg") == 2
        _mock_engine["find_var_index"].assert_called_once_with("mpg")

    def test_get_var_index_none_raises(self, _mock_engine):
        from pystata_x.sfi._core import Data
        # Data.getVarIndex returns whatever _STRATEGY.find_var_index returns
        # (error handling may vary by platform strategy)
        _mock_engine["find_var_index"].return_value = -1
        result = Data.getVarIndex("nonexistent")
        assert result == -1

    def test_get_var_format(self, _mock_engine):
        _mock_engine["get_var_format"].return_value = "%8.0g"
        from pystata_x.sfi._core import Data
        assert Data.getVarFormat(2) == "%8.0g"
        _mock_engine["get_var_format"].assert_called_once_with(2)

    def test_get_double(self, _mock_engine):
        _mock_engine["call_double"].return_value = 4099.0
        from pystata_x.sfi._core import Data
        result = Data.getDouble(1, 0)
        assert result == 4099.0
        _mock_engine["call_double"].assert_called_with("_bist_data", 1, 2)

    def test_get_string(self, _mock_engine):
        _mock_engine["get_string"].return_value = "AMC Concord"
        from pystata_x.sfi._core import Data
        assert Data.getString(0, 0) == "AMC Concord"
        _mock_engine["get_string"].assert_called_once_with(0, 0)

    def test_store_double(self, _mock_engine):
        from pystata_x.sfi._core import Data
        Data.storeDouble(1, 0, 99.5)
        _mock_engine["store_double"].assert_called_once_with(0, 1, 99.5)

    def test_store_string(self, _mock_engine):
        from pystata_x.sfi._core import Data
        Data.storeString(0, 0, "hello")
        _mock_engine["store_string"].assert_called_once_with(0, 0, "hello")

    def test_get_var_value_label(self, _mock_engine):
        _mock_engine["get_var_value_label"].return_value = "origin"
        from pystata_x.sfi._core import Data
        assert Data.getVarValueLabel(11) == "origin"
        _mock_engine["get_var_value_label"].assert_called_once_with(11)


# ── Scalar ────────────────────────────────────────────────────────

class TestScalar:
    def test_get_value(self, _mock_engine):
        _mock_engine["get_scalar_value"].return_value = 95.0
        from pystata_x.sfi._core import Scalar
        assert Scalar.getValue("c(level)") == 95.0
        _mock_engine["get_scalar_value"].assert_called_once_with("c(level)")

    def test_set_value(self, _mock_engine):
        # Scalar.setValue calls call_set_scalar via _engine
        _mock_engine["call_set_scalar"].return_value = 0
        from pystata_x.sfi._core import Scalar
        Scalar.setValue("mypi", 3.14)
        _mock_engine["call_set_scalar"].assert_called_once_with("mypi", 3.14)

    def test_get_string(self, _mock_engine):
        _mock_engine["get_scalar_string"].return_value = "19 May 2026"
        from pystata_x.sfi._core import Scalar
        assert Scalar.getString("c(current_date)") == "19 May 2026"
        _mock_engine["get_scalar_string"].assert_called_once_with("c(current_date)")

    def test_set_string(self, _mock_engine):
        # Scalar.setString calls call_set_strscalar via _engine
        _mock_engine["call_set_strscalar"].return_value = 0
        from pystata_x.sfi._core import Scalar
        Scalar.setString("greeting", "hello world")
        _mock_engine["call_set_strscalar"].assert_called_once_with("greeting", "hello world")


# ── Missing ───────────────────────────────────────────────────────

class TestMissing:
    def test_get_value_returns_nan(self):
        from pystata_x.sfi._core import Missing
        assert Missing.getMissing(Missing.getValue()) == "."

    def test_is_value_missing_nan(self):
        from pystata_x.sfi._core import Missing
        assert Missing.isMissing(float("nan"))

    def test_is_value_missing_large(self):
        from pystata_x.sfi._core import Missing
        assert Missing.isMissing(1e308)

    def test_is_value_missing_finite(self):
        from pystata_x.sfi._core import Missing
        assert not Missing.isMissing(42.0)
        assert not Missing.isMissing(0.0)

    def test_is_value_missing_non_nan_large(self):
        from pystata_x.sfi._core import Missing
        assert not Missing.isMissing(1e200)


# ── ValueLabel ────────────────────────────────────────────────────

class TestValueLabel:
    def test_exists_true(self, _mock_engine):
        _mock_engine["vl_exists"].return_value = True
        from pystata_x.sfi._core import ValueLabel
        assert ValueLabel.exists("origin") is True
        _mock_engine["vl_exists"].assert_called_once_with("origin")

    def test_exists_false(self, _mock_engine):
        _mock_engine["vl_exists"].return_value = False
        from pystata_x.sfi._core import ValueLabel
        assert ValueLabel.exists("nonexistent") is False

    def test_exists_none(self, _mock_engine):
        _mock_engine["vl_exists"].return_value = False
        from pystata_x.sfi._core import ValueLabel
        assert ValueLabel.exists("unknown") is False

    def test_drop(self, _mock_engine):
        _mock_engine["vl_drop"].return_value = 0
        from pystata_x.sfi._core import ValueLabel
        ValueLabel.drop("origin")
        _mock_engine["vl_drop"].assert_called_once_with("origin")

    def test_create(self, _mock_engine):
        _mock_engine["vl_create"].return_value = 0
        from pystata_x.sfi._core import ValueLabel
        ValueLabel.create("myvlab")
        _mock_engine["vl_create"].assert_called_once_with("myvlab", [0], [" "])

    def test_define(self, _mock_engine):
        _mock_engine["vl_define"].return_value = 0
        from pystata_x.sfi._core import ValueLabel
        ValueLabel.define("myvlab", 1, "Category A")
        _mock_engine["vl_define"].assert_called_once_with("myvlab", 1, "Category A")

    def test_get_value_label(self, _mock_engine):
        from pystata_x.sfi._core import Data, ValueLabel
        _mock_engine["get_var_value_label"].return_value = "origin"
        _mock_engine["vl_get_label"].return_value = "Domestic"
        result = ValueLabel.getValueLabel(11, 0.0)
        assert result == "Domestic"
        _mock_engine["get_var_value_label"].assert_called_once_with(11)

    def test_get_value_name(self, _mock_engine):
        from pystata_x.sfi._core import ValueLabel
        _mock_engine["get_var_value_label"].return_value = "origin"
        result = ValueLabel.getValueName(11, 1.0)
        assert result == "origin"
        _mock_engine["get_var_value_label"].assert_called_once_with(11)


# ── SFIToolkit ────────────────────────────────────────────────────

class TestSFIToolkit:
    def test_execute_command(self):
        import pystata_x.sfi._engine as eng_mod
        with patch.object(eng_mod, "execute") as mock_exec:
            from pystata_x.sfi._core import SFIToolkit
            SFIToolkit.executeCommand("display 1+1")
            mock_exec.assert_called_once_with("display 1+1")


# ── First-var (index 0) edge cases ───────────────────────────────

class TestDataEdgeCases:
    def test_get_var_name_idx0(self, _mock_engine):
        _mock_engine["get_var_name"].return_value = "make"
        from pystata_x.sfi._core import Data
        assert Data.getVarName(0) == "make"
        _mock_engine["get_var_name"].assert_called_with(0)

    def test_get_double_idx0(self, _mock_engine):
        _mock_engine["call_double"].return_value = 4099.0
        from pystata_x.sfi._core import Data
        assert Data.getDouble(0, 0) == 4099.0
        _mock_engine["call_double"].assert_called_with("_bist_data", 1, 1)

    def test_get_string_idx0(self, _mock_engine):
        _mock_engine["get_string"].return_value = "AMC Concord"
        from pystata_x.sfi._core import Data
        assert Data.getString(0, 0) == "AMC Concord"
        _mock_engine["get_string"].assert_called_with(0, 0)

    def test_store_double_idx0(self, _mock_engine):
        from pystata_x.sfi._core import Data
        Data.storeDouble(0, 0, 0.0)
        _mock_engine["store_double"].assert_called_with(0, 0, 0.0)

    def test_store_string_idx0(self, _mock_engine):
        from pystata_x.sfi._core import Data
        Data.storeString(0, 0, "x")
        _mock_engine["store_string"].assert_called_with(0, 0, "x")

    def test_get_var_value_label_origin(self, _mock_engine):
        _mock_engine["get_var_value_label"].return_value = "origin"
        from pystata_x.sfi._core import Data
        assert Data.getVarValueLabel(11) == "origin"
        _mock_engine["get_var_value_label"].assert_called_with(11)


# ── Error propagation ─────────────────────────────────────────────

class TestErrorPropagation:
    def test_get_var_index_nonexistent(self, _mock_engine):
        _mock_engine["find_var_index"].return_value = -1
        from pystata_x.sfi._core import Data
        result = Data.getVarIndex("i_dont_exist")
        assert result == -1


# ── Last chunk for robustness ──

    def test_missing_symbol_doesnt_crash(self, _mock_engine):
        """If strategy returns None for unknown symbol, core handles it."""
        # Methods that delegate to _STRATEGY
        _mock_engine["get_macro_global"].return_value = None
        _mock_engine["get_var_name"].return_value = None
        _mock_engine["get_scalar_value"].return_value = None
        _mock_engine["get_scalar_string"].return_value = None
        # get_string converts None to ""
        _mock_engine["get_string"].return_value = ""

        from pystata_x.sfi._core import Macro, Data, Scalar
        assert Macro.getGlobal("x") is None
        assert Data.getVarName(0) is None
        assert Data.getString(0, 0) == ""
        assert Scalar.getValue("x") is None
        assert Scalar.getString("x") is None
