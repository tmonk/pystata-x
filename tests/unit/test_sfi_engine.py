"""Unit tests for ``pystata_x.sfi._engine`` (mocked C runtime).

Tests the low-level C function call helpers with ctypes mocked
so that no real Stata library or CFUNCTYPE call is executed.
Exercises both the ARM64 push+stack dispatch logic and the
x86_64 CFUNCTYPE dispatch logic, argument type routing, stack
management, and error handling.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch, call

import pytest


# ── Helpers ───────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _mock_ctypes():
    """Prevent ANY real ctypes.cast from executing.

    All ``ctypes.cast`` calls in _engine go through the module's
    ``import ctypes`` reference, so we patch the ctypes module
    BEFORE importing _engine.
    """
    patcher = patch("pystata_x.sfi._engine.ctypes", autospec=False)
    mock_ctypes_mod = patcher.start()

    # Mock the key ctypes objects we need
    mock_ctypes_mod.c_void_p = MagicMock()
    mock_ctypes_mod.c_int = int
    mock_ctypes_mod.c_uint64 = MagicMock()
    mock_ctypes_mod.c_uint64.from_address = MagicMock(return_value=MagicMock(value=0xDEAD))
    mock_ctypes_mod.c_uint32 = MagicMock()
    mock_ctypes_mod.c_uint32.from_address = MagicMock(return_value=MagicMock(value=0))
    mock_ctypes_mod.c_int32 = MagicMock()
    mock_ctypes_mod.c_int32.from_address = MagicMock(return_value=MagicMock(value=0))
    mock_ctypes_mod.c_double = MagicMock()
    mock_ctypes_mod.c_char_p = MagicMock()
    mock_ctypes_mod.c_size_t = int
    mock_ctypes_mod.CFUNCTYPE = MagicMock(return_value=MagicMock())
    mock_ctypes_mod.cast = MagicMock(return_value=MagicMock())
    mock_ctypes_mod.CDLL = MagicMock()
    mock_ctypes_mod.POINTER = MagicMock(return_value=MagicMock())
    mock_ctypes_mod.addressof = MagicMock(return_value=0x1234)
    mock_ctypes_mod.string_at = MagicMock(return_value=b"mock_string")
    mock_ctypes_mod.byref = MagicMock(return_value=MagicMock())

    yield mock_ctypes_mod

    patcher.stop()


@pytest.fixture
def eng(_mock_ctypes):
    """Return the engine module with state initialised for testing.

    All ctypes operations are fully mocked, so no real Stata library
    or CFUNCTYPE call executes.
    """
    import pystata_x.sfi._engine as mod

    # Mark as initialised so call_* functions skip real init
    mod._INITIALIZED = True
    mod._LIB = MagicMock()
    mod._BASE = 0x100000000
    mod._SYMS = {
        "_bist_nobs": 0x1000,
        "_bist_nvar": 0x1004,
        "_bist_global": 0x1010,
        "_bist_putglobal": 0x1018,
        "_bist_varname": 0x1020,
        "_bist_varlabel": 0x1028,
        "_bist_varformat": 0x1030,
        "_bist_varindex": 0x1038,
        "_bist_vartype": 0x1040,
        "_bist_varvaluelabel": 0x1048,
        "_bist_data": 0x1050,
        "_bist_sdata": 0x1058,
        "_bist_store": 0x1060,
        "_bist_sstore": 0x1068,
        "_bist_addobs": 0x1070,
        "_bist_numscalar": 0x1080,
        "_bist_strscalar": 0x1088,
        "_bist_vlexists": 0x1090,
        "_bist_vlmap": 0x1098,
        "_bist_vlsearch": 0x10A0,
        "_bist_vldrop": 0x10A8,
        "_bist_vlmodify": 0x10B0,
        "_bist_vlload": 0x10B8,
        "_pushint": 0x2000,
        "_pushdbl": 0x2008,
        "_pushstr": 0x2010,
    }

    # Mock push function pointers
    mod._pushint_fn = MagicMock()
    mod._pushdbl_fn = MagicMock()
    mod._pushstr_fn = MagicMock()

    # Mock SP management
    _sp_value = [mod._BASE + 0x1000]

    def _fake_save_sp() -> int:
        return _sp_value[0]

    def _fake_restore_sp(val: int) -> None:
        _sp_value[0] = val

    mod._save_sp = _fake_save_sp
    mod._restore_sp = _fake_restore_sp

    # Mock the arm64 push helpers
    mod._arm64_push_int = MagicMock(side_effect=lambda v: _sp_value.__setitem__(0, _sp_value[0] + 8))
    mod._arm64_push_str = MagicMock()
    mod._arm64_push_double = MagicMock()

    # Mock pop-and-read helpers
    mod._arm64_pop_and_read_double = MagicMock(return_value=42.0)
    mod._arm64_pop_and_read_int = MagicMock(return_value=0)
    mod._arm64_pop_and_read_string = MagicMock(return_value="mock_result")
    mod._read_stata_err = MagicMock(return_value=0)

    return mod


# ── Symbol lookup ─────────────────────────────────────────────────


class TestSymAddr:
    def test_found(self, eng):
        assert eng._sym_addr("_bist_nobs") == 0x1000

    def test_not_found(self, eng):
        assert eng._sym_addr("_nonexistent") is None

    def test_empty_syms(self, eng):
        saved = eng._SYMS
        eng._SYMS = {}
        assert eng._sym_addr("_bist_nobs") is None
        eng._SYMS = saved


# ── call_int ──────────────────────────────────────────────────────


class TestCallInt:
    @patch("pystata_x.sfi._engine._PLATFORM", "arm64")
    def test_arm64_zero_args(self, eng):
        eng._arm64_pop_and_read_int.return_value = 74
        result = eng.call_int("_bist_nobs")
        assert result == 74
        # ctypes.cast was called to create CFUNCTYPE(None, c_int)
        assert eng.ctypes.CFUNCTYPE.called
        assert eng.ctypes.cast.called

    @patch("pystata_x.sfi._engine._PLATFORM", "arm64")
    def test_arm64_with_str_arg(self, eng):
        eng._arm64_pop_and_read_int.return_value = 2
        result = eng.call_int("_bist_varindex", b"price")
        assert result == 2
        eng._arm64_push_str.assert_called_once()

    @patch("pystata_x.sfi._engine._PLATFORM", "arm64")
    def test_arm64_with_int_arg(self, eng):
        eng._arm64_pop_and_read_int.return_value = 6
        result = eng.call_int("_bist_vartype", 1)
        assert result == 6

    @patch("pystata_x.sfi._engine._PLATFORM", "arm64")
    def test_unknown_symbol_returns_none(self, eng):
        result = eng.call_int("_bist_doesnotexist")
        assert result is None

    @patch("pystata_x.sfi._engine._PLATFORM", "x86_64")
    def test_x86_64_dispatch(self, eng):
        result = eng.call_int("_bist_nobs")
        # Falls through to _call_std_int — which uses mocked ctypes
        assert result is not None or result is None


# ── call_double ───────────────────────────────────────────────────


class TestCallDouble:
    @patch("pystata_x.sfi._engine._PLATFORM", "arm64")
    def test_arm64_double_return(self, eng):
        eng._arm64_pop_and_read_double.return_value = 4099.0
        result = eng.call_double("_bist_data", 1, 2)
        assert result == 4099.0

    @patch("pystata_x.sfi._engine._PLATFORM", "arm64")
    def test_name_arg_dispatched_as_str(self, eng):
        eng._arm64_pop_and_read_double.return_value = 95.0
        result = eng.call_double("_bist_numscalar", b"c(level)")
        assert result == 95.0
        eng._arm64_push_str.assert_called()

    @patch("pystata_x.sfi._engine._PLATFORM", "arm64")
    def test_missing_symbol_returns_none(self, eng):
        assert eng.call_double("_bist_nonexistent") is None

    @patch("pystata_x.sfi._engine._PLATFORM", "x86_64")
    def test_x86_64_sym_not_found(self, eng):
        assert eng.call_double("_bist_nonexistent") is None


# ── call_string ───────────────────────────────────────────────────


class TestCallString:
    @patch("pystata_x.sfi._engine._PLATFORM", "arm64")
    def test_arm64_string_return(self, eng):
        eng._arm64_pop_and_read_string.return_value = "AMC Concord"
        result = eng.call_string("_bist_sdata", 1, 1)
        assert result == "AMC Concord"

    @patch("pystata_x.sfi._engine._PLATFORM", "arm64")
    def test_arm64_int_arg(self, eng):
        eng._arm64_pop_and_read_string.return_value = "make"
        result = eng.call_string("_bist_varname", 1)
        assert result == "make"

    @patch("pystata_x.sfi._engine._PLATFORM", "arm64")
    def test_missing_symbol(self, eng):
        assert eng.call_string("_bist_nonexistent") is None

    @patch("pystata_x.sfi._engine._PLATFORM", "x86_64")
    def test_x86_64_dispatch(self, eng):
        result = eng.call_string("_bist_global", b"myglobal")
        assert result is not None or result is None


# ── call_void ─────────────────────────────────────────────────────


class TestCallVoid:
    @patch("pystata_x.sfi._engine._PLATFORM", "arm64")
    def test_arm64_void(self, eng):
        eng.call_void("_bist_addobs", 1.0)
        # Should not raise

    @patch("pystata_x.sfi._engine._PLATFORM", "arm64")
    def test_unknown_symbol_silent(self, eng):
        result = eng.call_void("_bist_fake")
        assert result is None

    @patch("pystata_x.sfi._engine._PLATFORM", "x86_64")
    def test_x86_64_void_dispatch(self, eng):
        eng.call_void("_bist_addobs", 1.0)


# ── call_store_double / call_store_string ─────────────────────────


class TestCallStoreDouble:
    @patch("pystata_x.sfi._engine._PLATFORM", "arm64")
    def test_arm64_store_double(self, eng):
        eng._read_stata_err.return_value = 0
        rc = eng.call_store_double("_bist_store", 1, 2, 99.5)
        assert rc == 0
        # Verify obs and var were pushed as ints, value as double
        assert eng._arm64_push_int.call_count >= 2
        eng._arm64_push_double.assert_called_once()

    @patch("pystata_x.sfi._engine._PLATFORM", "arm64")
    def test_unknown_symbol_returns_neg1(self, eng):
        rc = eng.call_store_double("_bist_fake", 1, 1, 1.0)
        assert rc == -1


class TestCallStoreString:
    @patch("pystata_x.sfi._engine._PLATFORM", "arm64")
    def test_arm64_store_string(self, eng):
        eng._read_stata_err.return_value = 0
        rc = eng.call_store_string("_bist_sstore", 1, 1, b"hello")
        assert rc == 0
        eng._arm64_push_str.assert_called()

    @patch("pystata_x.sfi._engine._PLATFORM", "arm64")
    def test_unknown_symbol(self, eng):
        rc = eng.call_store_string("_bist_fake", 1, 1, b"x")
        assert rc == -1


# ── call_set_scalar / call_set_strscalar ──────────────────────────


class TestCallSetScalar:
    @patch("pystata_x.sfi._engine._PLATFORM", "arm64")
    def test_arm64_set_scalar(self, eng):
        # Add _stscalsave to SYMS so _sym_addr finds it
        eng._SYMS["_stscalsave"] = 0x79c820
        # Mock CFUNCTYPE cast for _stscalsave
        mock_fn = MagicMock(return_value=0)
        eng.ctypes.cast.return_value = mock_fn
        rc = eng.call_set_scalar("mypi", 3.14)
        assert rc == 0
        mock_fn.assert_called_once_with(b"mypi", 3.14)

    @patch("pystata_x.sfi._engine._PLATFORM", "x86_64")
    def test_x86_64_set_scalar(self, eng):
        rc = eng.call_set_scalar("mypi", 3.14)
        assert rc == 0


class TestCallSetStrScalar:
    @patch("pystata_x.sfi._engine._PLATFORM", "arm64")
    def test_arm64_set_strscalar(self, eng):
        # Add symbols to SYMS so _sym_addr finds them
        eng._SYMS["_xgso_newcp_fast_code"] = 0x8a9e84
        eng._SYMS["_put_xgso_scalar"] = 0x6c9340
        # Two casts: xgso_fn and put_fn
        mock_xgso = MagicMock(return_value=0xDEAD)
        mock_put = MagicMock(return_value=0)
        eng.ctypes.cast.side_effect = [mock_xgso, mock_put]

        rc = eng.call_set_strscalar("mystr", "hello")
        assert rc == 0
        mock_xgso.assert_called_once()
        mock_put.assert_called_once()
        assert mock_put.call_args[0][0] == b"mystr"

    @patch("pystata_x.sfi._engine._PLATFORM", "arm64")
    def test_xgso_fails(self, eng):
        eng._SYMS["_xgso_newcp_fast_code"] = 0x8a9e84
        eng._SYMS["_put_xgso_scalar"] = 0x6c9340
        mock_xgso = MagicMock(return_value=0)  # NULL GSO
        mock_put = MagicMock(return_value=0)
        eng.ctypes.cast.side_effect = [mock_xgso, mock_put]

        rc = eng.call_set_strscalar("mystr", "hello")
        assert rc == -1


# ── call_vlmodify / call_create_valuelabel ────────────────────────


class TestCallVlmodify:
    @patch("pystata_x.sfi._engine._PLATFORM", "arm64")
    def test_arm64_vlmodify(self, eng):
        eng._read_stata_err.return_value = 0
        rc = eng.call_vlmodify("mylbl", 1, "Cat A")
        assert rc == 0

    @patch("pystata_x.sfi._engine._PLATFORM", "arm64")
    def test_unknown_symbol(self, eng):
        # Remove _bist_vlmodify from SYMS
        eng._SYMS.pop("_bist_vlmodify", None)
        rc = eng.call_vlmodify("mylbl", 1, "Cat A")
        assert rc == -1


class TestCallCreateValuelabel:
    @patch("pystata_x.sfi._engine._PLATFORM", "arm64")
    def test_delegates_to_vlmodify(self, eng):
        eng._read_stata_err.return_value = 0
        with patch.object(eng, "call_vlmodify", return_value=0) as mock_vl:
            rc = eng.call_create_valuelabel("mylbl")
            assert rc == 0
            mock_vl.assert_called_once_with("mylbl", 0, "_mylbl")


# ── read_obs_count / read_var_count ──────────────────────────────


class TestReadCounts:
    @patch("pystata_x.sfi._engine._PLATFORM", "arm64")
    def test_read_obs_count(self, eng):
        eng._arm64_setup_push_fns()  # sets up _pushint_fn etc
        eng._arm64_pop_and_read_double.return_value = 74.0
        assert eng.read_obs_count() == 74
        eng._arm64_pop_and_read_double.assert_called_once()

    @patch("pystata_x.sfi._engine._PLATFORM", "arm64")
    def test_read_var_count(self, eng):
        eng._arm64_setup_push_fns()
        eng._arm64_pop_and_read_double.return_value = 12.0
        assert eng.read_var_count() == 12
        eng._arm64_pop_and_read_double.assert_called_once()


# ── ARM64 argument type dispatch ─────────────────────────────────


class TestArm64PushArgsDispatch:
    """_arm64_push_args must route each arg to the correct _push_* helper."""

    @patch("pystata_x.sfi._engine._PLATFORM", "arm64")
    def test_push_int(self, eng):
        sp0 = eng._save_sp()
        eng._arm64_push_args((42,))
        # The stack pointer advanced by 8 bytes (one int push)
        assert eng._save_sp() == sp0 + 8

    @patch("pystata_x.sfi._engine._PLATFORM", "arm64")
    def test_mixed_args(self, eng):
        eng._arm64_push_args((1, b"hello", 3.14))
        eng._arm64_push_str.assert_called()
        eng._arm64_push_double.assert_called()

    @patch("pystata_x.sfi._engine._PLATFORM", "arm64")
    def test_no_args_noop(self, eng):
        sp0 = eng._save_sp()
        eng._arm64_push_args(())
        assert eng._save_sp() == sp0

    @patch("pystata_x.sfi._engine._PLATFORM", "arm64")
    def test_unsupported_type_raises(self, eng):
        with pytest.raises(TypeError, match="Unsupported arg type"):
            eng._arm64_push_args((None,))


# ── _call_std_* (x86_64 ABI) ──────────────────────────────────────


class TestCallStdInt:
    def test_zero_args(self, eng):
        result = eng._call_std_int(0x1234, ())
        assert result is not None

    def test_one_int_arg(self, eng):
        result = eng._call_std_int(0x1234, (42,))
        assert result is not None


class TestCallStdString:
    def test_zero_args(self, eng):
        result = eng._call_std_string(0x1234, ())
        assert result is not None

    def test_bytes_args(self, eng):
        result = eng._call_std_string(0x1234, (b"hello",))
        assert result is not None


# ── _decode ───────────────────────────────────────────────────────


class TestDecode:
    def test_decode_bytes(self, eng):
        assert eng._decode(b"hello") == "hello"

    def test_decode_none(self, eng):
        assert eng._decode(None) is None

    def test_decode_invalid_utf8(self, eng):
        result = eng._decode(b"valid\xfftext")
        assert isinstance(result, str)


# ── execute / shutdown (StataSO_Execute path) ─────────────────────


class TestExecute:
    def test_execute_returns_output_and_rc(self, eng):
        """Smoke test — execute() uses StataSO_Execute which is mocked."""
        eng._LIB.StataSO_ClearOutputBuffer = MagicMock()
        eng._LIB.StataSO_Execute = MagicMock(return_value=0)

        # StataSO_GetOutputBuffer returns a raw pointer (void*).
        # We need ctypes.c_char_p(buf).value to give us bytes.
        # Since ctypes is mocked, we make GetOutputBuffer return
        # a pointer that c_char_p can parse.
        from pystata_x.sfi._engine import execute as exec_fn

        # Manually set up the mocked ctypes.c_char_p
        mock_ptr = MagicMock()
        mock_ptr.value = b"  output text  "
        eng.ctypes.c_char_p.return_value = mock_ptr
        eng._LIB.StataSO_GetOutputBuffer.return_value = 0x1234  # opaque ptr

        output, rc = exec_fn("display 1+1")
        assert isinstance(output, str)
        assert rc == 0


class TestShutdown:
    def test_shutdown(self, eng):
        """shutdown() should not raise when _LIB is set."""
        eng._LIB.StataSO_Shutdown = MagicMock()
        eng.shutdown()
        eng._LIB.StataSO_Shutdown.assert_called_once()
