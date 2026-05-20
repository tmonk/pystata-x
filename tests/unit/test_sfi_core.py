"""Unit tests for ``pystata_x.sfi._core`` SFI API classes (mocked engine).

Tests Macro, Data, Scalar, Missing, ValueLabel and SFIToolkit with
all _engine.py call_* functions mocked.  Verifies 0-based ↔ 1-based
index conversion, boundary cases, error propagation, and that every
public method routes to the correct engine helper.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch, ANY

import pytest


# ── Fixture: mock all _engine imports used by _core ──────────────


@pytest.fixture(autouse=True)
def _mock_engine():
    """Mock every symbol _core imports from _engine.

    Because _core.py does ``from _engine import call_int, ...``,
    the names are direct module references.  We use ``patch.object``
    on the already-imported _core module to replace each name.
    Also forces ``_IS_X86_64 = False`` so unit tests exercise the
    mocked code paths (display-based fallback tests are e2e-only).
    """
    import pystata_x.sfi._core as core_mod

    mocks = {}
    targets = [
        "call_int", "call_double", "call_string", "call_void",
        "call_store_double", "call_store_string",
        "call_set_scalar", "call_set_strscalar",
        "call_create_valuelabel", "call_vlmodify",
        "read_obs_count", "read_var_count",
    ]
    patchers = []
    for name in targets:
        m = MagicMock()
        mocks[name] = m
        p = patch.object(core_mod, name, m)
        p.start()
        patchers.append(p)

    # Force _IS_X86_64 to False so unit tests use mocked call path
    p_is86 = patch.object(core_mod, "_IS_X86_64", False)
    p_is86.start()
    patchers.append(p_is86)

    yield mocks

    for p in patchers:
        p.stop()


# ── Macro ─────────────────────────────────────────────────────────


class TestMacro:
    def test_get_global(self, _mock_engine):
        _mock_engine["call_string"].return_value = "hello"
        from pystata_x.sfi._core import Macro

        result = Macro.getGlobal("myglob")
        assert result == "hello"
        _mock_engine["call_string"].assert_called_once_with(
            "_bist_global", b"myglob"
        )

    def test_set_global(self, _mock_engine):
        _mock_engine["call_int"].return_value = 0
        from pystata_x.sfi._core import Macro

        Macro.setGlobal("myglob", "myvalue")
        _mock_engine["call_int"].assert_called_once_with(
            "_bist_putglobal", b"myglob", b"myvalue"
        )

    def test_del_global(self, _mock_engine):
        _mock_engine["call_int"].return_value = 0
        from pystata_x.sfi._core import Macro

        Macro.delGlobal("myglob")
        _mock_engine["call_int"].assert_called_once_with(
            "_bist_putglobal", b"myglob", b" "
        )


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
        _mock_engine["call_string"].return_value = "price"
        from pystata_x.sfi._core import Data

        # 0-based input -> 1-based engine call
        result = Data.getVarName(1)
        assert result == "price"
        _mock_engine["call_string"].assert_called_once_with(
            "_bist_varname", 2  # 0-based 1 -> 1-based 2
        )

    def test_get_var_label(self, _mock_engine):
        _mock_engine["call_string"].return_value = "Price Label"
        from pystata_x.sfi._core import Data

        result = Data.getVarLabel(1)
        assert result == "Price Label"
        _mock_engine["call_string"].assert_called_once_with(
            "_bist_varlabel", 2
        )

    def test_get_var_type(self, _mock_engine):
        _mock_engine["call_string"].return_value = "float"
        from pystata_x.sfi._core import Data

        result = Data.getVarType(2)
        assert result == "float"
        _mock_engine["call_string"].assert_called_once_with(
            "_bist_vartype", 3
        )

    def test_get_var_index(self, _mock_engine):
        _mock_engine["call_int"].return_value = 3  # 1-based
        from pystata_x.sfi._core import Data

        result = Data.getVarIndex("mpg")
        assert result == 2  # 0-based
        _mock_engine["call_int"].assert_called_once_with(
            "_bist_varindex", b"mpg"
        )

    def test_get_var_index_none_raises(self, _mock_engine):
        _mock_engine["call_int"].return_value = None
        from pystata_x.sfi._core import Data

        with pytest.raises(ValueError, match="variable"):
            Data.getVarIndex("nonexistent")

    def test_get_var_format(self, _mock_engine):
        _mock_engine["call_string"].return_value = "%8.0g"
        from pystata_x.sfi._core import Data

        result = Data.getVarFormat(2)
        assert result == "%8.0g"
        _mock_engine["call_string"].assert_called_once_with(
            "_bist_varformat", 3
        )

    def test_get_double(self, _mock_engine):
        _mock_engine["call_double"].return_value = 4099.0
        from pystata_x.sfi._core import Data

        result = Data.getDouble(1, 0)  # price[0]
        assert result == 4099.0
        _mock_engine["call_double"].assert_called_once_with(
            "_bist_data", 1, 2  # obs+1=1, var+1=2
        )

    def test_get_string(self, _mock_engine):
        _mock_engine["call_string"].return_value = "AMC Concord"
        from pystata_x.sfi._core import Data

        result = Data.getString(0, 0)
        assert result == "AMC Concord"
        _mock_engine["call_string"].assert_called_once_with(
            "_bist_sdata", 1, 1
        )

    def test_store_double(self, _mock_engine):
        _mock_engine["call_store_double"].return_value = 0
        from pystata_x.sfi._core import Data

        Data.storeDouble(1, 0, 99.5)
        _mock_engine["call_store_double"].assert_called_once_with(
            "_bist_store", 1, 2, 99.5  # obs+1=1, var+1=2
        )

    def test_store_string(self, _mock_engine):
        _mock_engine["call_store_string"].return_value = 0
        from pystata_x.sfi._core import Data

        Data.storeString(0, 0, "hello")
        _mock_engine["call_store_string"].assert_called_once_with(
            "_bist_sstore", 1, 1, b"hello"
        )

    def test_add_obs(self, _mock_engine):
        from pystata_x.sfi._core import Data

        Data.addObs(5)
        _mock_engine["call_void"].assert_called_once_with(
            "_bist_addobs", 5.0
        )

    def test_get_var_value_label(self, _mock_engine):
        _mock_engine["call_string"].return_value = "origin"
        from pystata_x.sfi._core import Data

        result = Data.getVarValueLabel(11)
        assert result == "origin"
        _mock_engine["call_string"].assert_called_once_with(
            "_bist_varvaluelabel", 12
        )


# ── Scalar ────────────────────────────────────────────────────────


class TestScalar:
    def test_get_value(self, _mock_engine):
        _mock_engine["call_double"].return_value = 95.0
        from pystata_x.sfi._core import Scalar

        result = Scalar.getValue("c(level)")
        assert result == 95.0
        _mock_engine["call_double"].assert_called_once_with(
            "_bist_numscalar", b"c(level)"
        )

    def test_set_value(self, _mock_engine):
        _mock_engine["call_set_scalar"].return_value = 0
        from pystata_x.sfi._core import Scalar

        Scalar.setValue("mypi", 3.14)
        _mock_engine["call_set_scalar"].assert_called_once_with(
            "mypi", 3.14
        )

    def test_get_string(self, _mock_engine):
        _mock_engine["call_string"].return_value = "19 May 2026"
        from pystata_x.sfi._core import Scalar

        result = Scalar.getString("c(current_date)")
        assert result == "19 May 2026"
        _mock_engine["call_string"].assert_called_once_with(
            "_bist_strscalar", b"c(current_date)"
        )

    def test_set_string(self, _mock_engine):
        _mock_engine["call_set_strscalar"].return_value = 0
        from pystata_x.sfi._core import Scalar

        Scalar.setString("greeting", "hello world")
        _mock_engine["call_set_strscalar"].assert_called_once_with(
            "greeting", "hello world"
        )


# ── Missing ───────────────────────────────────────────────────────


class TestMissing:
    def test_get_value_returns_nan(self):
        from pystata_x.sfi._core import Missing
        import math

        # getMissing returns the symbol string for a float value
        assert Missing.getMissing(Missing.getValue()) == "."

    def test_is_value_missing_nan(self):
        from pystata_x.sfi._core import Missing
        import math

        assert Missing.isMissing(float("nan"))

    def test_is_value_missing_large(self):
        from pystata_x.sfi._core import Missing

        assert Missing.isMissing(1e308)

    def test_is_value_missing_finite(self):
        from pystata_x.sfi._core import Missing

        assert not Missing.isMissing(42.0)
        assert not Missing.isMissing(0.0)

    def test_is_value_missing_non_nan_large(self):
        """Value near 1e308 but not quite missing should be fine."""
        from pystata_x.sfi._core import Missing

        assert not Missing.isMissing(1e200)


# ── ValueLabel ────────────────────────────────────────────────────


class TestValueLabel:
    def test_exists_true(self, _mock_engine):
        _mock_engine["call_int"].return_value = 1
        from pystata_x.sfi._core import ValueLabel

        assert ValueLabel.exists("origin") is True
        _mock_engine["call_int"].assert_called_once_with(
            "_bist_vlexists", b"origin"
        )

    def test_exists_false(self, _mock_engine):
        _mock_engine["call_int"].return_value = 0
        from pystata_x.sfi._core import ValueLabel

        assert ValueLabel.exists("nonexistent") is False

    def test_exists_none(self, _mock_engine):
        """call_int returning None should not crash."""
        _mock_engine["call_int"].return_value = None
        from pystata_x.sfi._core import ValueLabel

        assert ValueLabel.exists("unknown") is False

    def test_drop(self, _mock_engine):
        _mock_engine["call_int"].return_value = 0
        from pystata_x.sfi._core import ValueLabel

        ValueLabel.drop("origin")
        _mock_engine["call_int"].assert_called_once_with(
            "_bist_vldrop", b"origin"
        )

    def test_create(self, _mock_engine):
        _mock_engine["call_create_valuelabel"].return_value = 0
        from pystata_x.sfi._core import ValueLabel

        ValueLabel.create("myvlab")
        _mock_engine["call_create_valuelabel"].assert_called_once_with(
            "myvlab"
        )

    def test_define(self, _mock_engine):
        _mock_engine["call_vlmodify"].return_value = 0
        from pystata_x.sfi._core import ValueLabel

        ValueLabel.define("myvlab", 1, "Category A")
        _mock_engine["call_vlmodify"].assert_called_once_with(
            "myvlab", 1, "Category A"
        )

    def test_get_value_label(self, _mock_engine):
        # getValueLabel calls getVarValueLabel first (calls call_string),
        # then getLabel (calls call_string with label name + value)
        from pystata_x.sfi._core import ValueLabel

        # Mock Data.getVarValueLabel to return "origin"
        _mock_engine["call_string"].side_effect = ["origin", "Domestic"]

        result = ValueLabel.getValueLabel(11, 0.0)
        assert result == "Domestic"
        # Should have called call_string twice:
        # 1. _bist_varvaluelabel(12) to get label name
        # 2. _bist_vlmap("origin", 0.0) to get label text
        assert _mock_engine["call_string"].call_count == 2
        _mock_engine["call_string"].assert_any_call("_bist_varvaluelabel", 12)
        _mock_engine["call_string"].assert_any_call("_bist_vlmap", b"origin", 0.0)

    def test_get_value_name(self, _mock_engine):
        from pystata_x.sfi._core import ValueLabel

        # getValueName now delegates to Data.getVarValueLabel
        _mock_engine["call_string"].return_value = "origin"

        result = ValueLabel.getValueName(11, 1.0)
        assert result == "origin"
        _mock_engine["call_string"].assert_called_once_with(
            "_bist_varvaluelabel", 12
        )


# ── SFIToolkit ────────────────────────────────────────────────────


class TestSFIToolkit:
    def test_execute_command(self, _mock_engine):
        """executeCommand calls _engine.execute (StataSO_Execute)."""
        import pystata_x.sfi._engine as eng_mod

        with patch.object(eng_mod, "execute") as mock_exec:
            from pystata_x.sfi._core import SFIToolkit
            SFIToolkit.executeCommand("display 1+1")
            mock_exec.assert_called_once_with("display 1+1")


# ── First-var (index 0) edge cases ───────────────────────────────


class TestDataEdgeCases:
    """0-based index 0 maps to 1-based index 1."""

    def test_get_var_name_idx0(self, _mock_engine):
        _mock_engine["call_string"].return_value = "make"
        from pystata_x.sfi._core import Data

        assert Data.getVarName(0) == "make"
        _mock_engine["call_string"].assert_called_with(
            "_bist_varname", 1
        )

    def test_get_double_idx0(self, _mock_engine):
        _mock_engine["call_double"].return_value = 4099.0
        from pystata_x.sfi._core import Data

        assert Data.getDouble(0, 0) == 4099.0
        _mock_engine["call_double"].assert_called_with(
            "_bist_data", 1, 1
        )

    def test_get_string_idx0(self, _mock_engine):
        _mock_engine["call_string"].return_value = "AMC Concord"
        from pystata_x.sfi._core import Data

        assert Data.getString(0, 0) == "AMC Concord"
        _mock_engine["call_string"].assert_called_with(
            "_bist_sdata", 1, 1
        )

    def test_store_double_idx0(self, _mock_engine):
        from pystata_x.sfi._core import Data

        Data.storeDouble(0, 0, 0.0)
        _mock_engine["call_store_double"].assert_called_with(
            "_bist_store", 1, 1, 0.0
        )

    def test_store_string_idx0(self, _mock_engine):
        from pystata_x.sfi._core import Data

        Data.storeString(0, 0, "x")
        _mock_engine["call_store_string"].assert_called_with(
            "_bist_sstore", 1, 1, b"x"
        )

    def test_add_obs_default(self, _mock_engine):
        from pystata_x.sfi._core import Data

        Data.addObs()
        _mock_engine["call_void"].assert_called_with(
            "_bist_addobs", 1.0
        )

    def test_get_var_value_label_origin(self, _mock_engine):
        _mock_engine["call_string"].return_value = "origin"
        from pystata_x.sfi._core import Data

        assert Data.getVarValueLabel(11) == "origin"
        _mock_engine["call_string"].assert_called_with(
            "_bist_varvaluelabel", 12
        )


# ── Error propagation ─────────────────────────────────────────────


class TestErrorPropagation:
    def test_get_var_index_nonexistent(self, _mock_engine):
        _mock_engine["call_int"].return_value = None
        from pystata_x.sfi._core import Data

        with pytest.raises(ValueError, match="variable"):
            Data.getVarIndex("i_dont_exist")

    def test_missing_symbol_doesnt_crash(self, _mock_engine):
        """If engine returns None for unknown symbol, core handles it."""
        for mock_name in [
            "call_int", "call_double", "call_string", "call_void",
        ]:
            _mock_engine[mock_name].return_value = None

        from pystata_x.sfi._core import Macro, Data, Scalar, ValueLabel

        # These should not raise even when engine returns None
        assert Macro.getGlobal("x") is None
        assert Data.getVarName(0) is None
        assert Data.getDouble(0, 0) is None
        # getString converts None → "" to guarantee str return
        assert Data.getString(0, 0) == ""
        assert Scalar.getValue("x") is None
        assert Scalar.getString("x") is None
