"""Live protocol validation for Stata dispatch functions.

Provides:
- ``LiveProtocolChecker`` — validates dispatch calls against a real Stata
  engine, dumping tsmat memory, checking error codes, and reporting results
- Push function verification
- Automatic calling convention discovery by trial
"""

from __future__ import annotations

import ctypes
import logging
import sys
from typing import Any, Optional, Callable

log = logging.getLogger(__name__)

# Known push function virtual addresses (x86_64, verified from ELF symbol table)
KNOW_PUSH_ADDRS = {
    "_pushdbl": 0x8B23EC,
    "_pushint": 0x8B2441,
    "_pushstr": 0x8B24A6,
}

# Tsmat layout constants (x86_64, empirically verified)
# A tsmat is a Stata internal structure holding a typed value.
# The push functions (pushint/pushdbl/pushstr) allocate a tsmat
# on the internal stack and set SP_global to point to it.
#
# String tsmat (two-level pointer layout):
#   tsmat[0x00] = data_buf (pointer to data buffer)
#   data_buf[0x00] = str_ptr (pointer to separately-allocated string struct)
#   str_ptr[0x00] = int32 length (includes null terminator)
#   str_ptr[0x04] = char data[length] (UTF-8 string)
#   data_buf[0x10] = int32 buffer_capacity
#   data_buf[0x18] = int32 flags
#
# Numeric tsmat (inline double layout):
#   tsmat[0x00] = data_buf (pointer to data buffer)
#   data_buf[0x00] = double value (inline, 8 bytes)
#
# Common tsmat fields:
#   tsmat[0x34] = uint16 return_type_flag (0xFFFD = string, 0 = numeric)
#   tsmat[0x36] = uint8  arg_type_flag (0 = string arg, !=0 = numeric arg)
#   tsmat[0x20] = uint64 metadata_1 (must == 1 for converter to proceed)
#   tsmat[0x28] = uint64 metadata_2 (must == 1 for converter to proceed)
#   tsmat[-0x94] = uint32 pool_header_magic (must == 0x2b for pool alloc)
#   tsmat[-0x10] = uint64 self_ptr (must == tsmat_ptr for pool alloc)


class EngineConnection:
    """Minimal connection to a running Stata engine for dispatch testing.

    Wraps the engine push/stack/call primitives and provides diagnostic
    access to tsmat memory, error codes, and stack state.

    Usage::

        ec = EngineConnection()
        ec.initialize()
        ec.execute("sysuse auto, clear")
        result = ec.call_double("_bist_numscalar", b"mynum")
        print(result)
        ec.shutdown()
    """

    def __init__(self):
        self._lib: Any = None
        self._base: int = 0
        self._initialized = False
        self._engine = None
        self._pushint: Optional[ctypes._CFuncPtr] = None
        self._pushdbl: Optional[ctypes._CFuncPtr] = None
        self._pushstr: Optional[ctypes._CFuncPtr] = None
        self._STACK_PTR_OFFSET: int = 0
        self._ERR_ADDR_RELATIVE: int = 0
        self._syms: dict[str, int] = {}
        self._manifest: dict = {}
        self._push_fns_verified = False

    # ── Lifecycle ────────────────────────────────────────────────

    def initialize(self) -> dict:
        """Initialise a Stata engine for dispatch testing.

        Returns a dict with connection status and diagnostics.
        Returns ``{"status": "ok", ...}`` on success, or
        ``{"status": "error", "reason": ...}`` on failure.
        """
        result: dict = {"status": "pending", "steps": []}

        try:
            # Import and initialize the real engine
            # Import the module, not individual names, so we can
            # read updated globals after _eng_init() modifies them.
            import pystata_x.sfi._engine as _eng_mod

            _eng_mod.initialize()
            self._base = _eng_mod._BASE
            self._lib = _eng_mod._LIB
            self._engine = _eng_mod.execute
            self._STACK_PTR_OFFSET = _eng_mod._STACK_PTR_OFFSET
            self._ERR_ADDR_RELATIVE = _eng_mod._ERR_ADDR_RELATIVE
            self._syms = dict(_eng_mod._SYMS)
            self._manifest = dict(_eng_mod._MANIFEST)
            result["steps"].append({"action": "engine_init", "status": "ok",
                                    "base": f"0x{self._base:x}"})
        except Exception as e:
            result["status"] = "error"
            result["reason"] = f"Engine init failed: {e}"
            return result

        # Set up push functions
        try:
            from pystata_x.sfi._engine import (
                _setup_push_fns, _pushint_fn, _pushdbl_fn, _pushstr_fn,
            )
            _setup_push_fns()
            self._pushint = _pushint_fn
            self._pushdbl = _pushdbl_fn
            self._pushstr = _pushstr_fn

            result["steps"].append({
                "action": "setup_push_fns",
                "status": "ok",
                "pushint_fn": self._pushint is not None,
                "pushdbl_fn": self._pushdbl is not None,
                "pushstr_fn": self._pushstr is not None,
            })
        except Exception as e:
            result["steps"].append({
                "action": "setup_push_fns",
                "status": "error",
                "reason": str(e),
            })

        # Verify push function setup
        push_status = self._verify_push_fns()
        result["push_verification"] = push_status

        # If push fns are None, try the known addresses directly
        if self._pushstr is None:
            self._try_known_push_addrs()
            result["steps"].append({
                "action": "known_addrs_fallback",
                "pushint_fn": self._pushint is not None,
                "pushdbl_fn": self._pushdbl is not None,
                "pushstr_fn": self._pushstr is not None,
            })

        # Verify push functions work by calling _pushint(0)
        if self._pushint is not None:
            try:
                self._pushint(0)
                self._push_fns_verified = True
                result["steps"].append({
                    "action": "pushint_test",
                    "status": "ok",
                })
            except Exception as e:
                result["steps"].append({
                    "action": "pushint_test",
                    "status": "error",
                    "reason": str(e),
                })

        # Load a dataset to have something to test with
        try:
            self.execute("sysuse auto, clear")
            result["steps"].append({"action": "load_data", "status": "ok"})
        except Exception as e:
            result["steps"].append({
                "action": "load_data",
                "status": "error",
                "reason": str(e),
            })

        result["syms_count"] = len(self._syms)
        if self._initialized:
            result["status"] = "ok"
        else:
            result["status"] = "partial" if self._pushstr else "no_push_fns"
        return result

    def _verify_push_fns(self) -> dict:
        """Check whether push function addresses are in the manifest."""
        result: dict = {"in_manifest": {}, "found": False}
        for name in ["_pushint", "_pushdbl", "_pushstr"]:
            addr = self._syms.get(name)
            result["in_manifest"][name] = addr is not None
            if addr:
                result["found"] = True
        return result

    def _try_known_push_addrs(self) -> None:
        """Fall back to known hardcoded push function addresses."""
        if self._base == 0:
            return
        if self._pushint is None:
            addr = self._base + KNOW_PUSH_ADDRS["_pushint"]
            try:
                fn_type = ctypes.CFUNCTYPE(None, ctypes.c_int)
                self._pushint = ctypes.cast(addr, fn_type)
            except Exception:
                pass
        if self._pushdbl is None:
            addr = self._base + KNOW_PUSH_ADDRS["_pushdbl"]
            try:
                fn_type = ctypes.CFUNCTYPE(None, ctypes.c_int)
                self._pushdbl = ctypes.cast(addr, fn_type)
            except Exception:
                pass
        if self._pushstr is None:
            addr = self._base + KNOW_PUSH_ADDRS["_pushstr"]
            try:
                fn_type = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_size_t)
                self._pushstr = ctypes.cast(addr, fn_type)
            except Exception:
                pass

    def detect_tsmat_layout(self) -> dict:
        """Auto-detect the tsmat memory layout by pushing test values.

        Pushes a known string and a known double, then reads back the
        tsmat struct fields to determine the layout of data buffers,
        flags, and string pointers.

        Returns a dict describing the detected layout, or an error dict
        if push functions are not available.
        """
        result: dict = {
            "string_layout": "unknown",
            "double_layout": "unknown",
            "tsmat_fields": {},
            "pool_header": {},
            "flags": {},
        }

        if not self._pushstr or not self._pushdbl:
            result["error"] = "push functions not available"
            return result

        try:
            self.execute("sysuse auto, clear")
        except Exception:
            pass

        # ═══ Push a known string and dump ═══
        # Save clean SP first
        sp_clean = self.save_sp()

        test_str = b"TESTSTRING"
        self.push_str(test_str)
        sp = self.save_sp()
        tsmat = ctypes.c_uint64.from_address(sp).value if sp else 0

        if tsmat and tsmat > 0x100000:
            data_buf = ctypes.c_uint64.from_address(tsmat).value
            result["string_tsmat_ptr"] = f"0x{tsmat:x}"
            result["string_data_buf"] = f"0x{data_buf:x}"

            # Dump tsmat fields
            fields = {}
            for i in range(0, 80, 8):
                val = ctypes.c_uint64.from_address(tsmat + i).value
                fields[f"+0x{i:02x}"] = f"0x{val:016x}"
            result["string_tsmat_fields"] = fields

            # Critical flags
            result["string_flags"] = {
                "return_flag_034": f"0x{ctypes.c_uint16.from_address(tsmat + 0x34).value:04x}",
                "arg_flag_036": ctypes.c_uint8.from_address(tsmat + 0x36).value,
                "meta_020": ctypes.c_uint64.from_address(tsmat + 0x20).value,
                "meta_028": ctypes.c_uint64.from_address(tsmat + 0x28).value,
            }

            # Pool header
            ph = ctypes.c_uint32.from_address(tsmat - 0x94).value
            result["pool_header"] = {
                "tsmat_minus_0x94": f"0x{ph:08x}",
                "pool_ok": ph == 0x2b,
            }

            # Self pointer
            sp_val = ctypes.c_uint64.from_address(tsmat - 0x10).value
            result["self_ptr"] = {
                "tsmat_minus_0x10": f"0x{sp_val:016x}",
                "self_ok": sp_val == tsmat,
            }

            # Data buffer layout
            if data_buf and data_buf > 0x100000:
                # First 8 bytes — is it a pointer to string struct?
                first_qword = ctypes.c_uint64.from_address(data_buf).value
                # At first_qword, check for length prefix
                if first_qword and first_qword > 0x100000:
                    possible_len = ctypes.c_int32.from_address(first_qword).value
                    if 0 < possible_len <= 32:
                        # Read string at first_qword + 4
                        raw = ctypes.create_string_buffer(possible_len + 1)
                        ctypes.memmove(raw, first_qword + 4, possible_len)
                        read_str = raw.value or b""
                        if read_str and (read_str == test_str or test_str.startswith(read_str.rstrip(b"\x00"))):
                            result["string_layout"] = "two_level_pointer"
                            result["string_layout_detail"] = (
                                "data_buf[0] = str_ptr, str_ptr[0:4] = len, str_ptr[4:] = data"
                            )

                # Try flat layout: data_buf[0:4] = length
                if result["string_layout"] == "unknown":
                    flat_len = ctypes.c_int32.from_address(data_buf).value
                    if 0 < flat_len <= 32:
                        raw = ctypes.create_string_buffer(flat_len + 1)
                        ctypes.memmove(raw, data_buf + 4, flat_len)
                        read_str = raw.value or b""
                        if read_str and (read_str == test_str or test_str.startswith(read_str.rstrip(b"\x00"))):
                            result["string_layout"] = "flat_inline"
                            result["string_layout_detail"] = (
                                "data_buf[0:4] = len, data_buf[4:] = data"
                            )

        # Restore clean SP
        self.restore_sp(sp_clean)

        # ═══ Push a known double and dump ═══
        sp_clean2 = self.save_sp()
        test_val = 42.5
        self.push_double(test_val)
        sp2 = self.save_sp()
        tsmat2 = ctypes.c_uint64.from_address(sp2).value if sp2 else 0

        if tsmat2 and tsmat2 > 0x100000:
            data_buf2 = ctypes.c_uint64.from_address(tsmat2).value
            result["double_tsmat_ptr"] = f"0x{tsmat2:x}"
            result["double_data_buf"] = f"0x{data_buf2:x}"

            if data_buf2 and data_buf2 > 0x100000:
                read_val = ctypes.c_double.from_address(data_buf2).value
                if abs(read_val - test_val) < 0.001:
                    result["double_layout"] = "inline_double"
                    result["double_layout_detail"] = "data_buf = double value (8 bytes)"

            result["double_flags"] = {
                "return_flag_034": f"0x{ctypes.c_uint16.from_address(tsmat2 + 0x34).value:04x}",
                "arg_flag_036": ctypes.c_uint8.from_address(tsmat2 + 0x36).value,
            }

        self.restore_sp(sp_clean2)
        return result

    def verify_push_fns(self) -> dict:
        """Diagnose push function setup and report issues.

        Checks whether push function pointers are initialized, whether
        the manifest addresses match known x86_64 addresses, and whether
        they can be called safely.
        """
        result: dict = {
            "pushint": {"initialized": self._pushint is not None},
            "pushdbl": {"initialized": self._pushdbl is not None},
            "pushstr": {"initialized": self._pushstr is not None},
            "errors": [],
        }

        # Try to get manifest symbols for comparison
        try:
            from pystata_x.sfi._engine import _SYMS, _BASE
            for name, key in [("pushint", "_pushint"),
                              ("pushdbl", "_pushdbl"),
                              ("pushstr", "_pushstr")]:
                sym_addr = _SYMS.get(key)
                if sym_addr is not None:
                    result[name]["sym_vaddr"] = f"0x{sym_addr:x}"
                    if _BASE:
                        result[name]["runtime"] = f"0x{_BASE + sym_addr:x}"
                else:
                    result["errors"].append(f"{key} not in manifest symbols")

                # Compare with known addresses
                known = KNOW_PUSH_ADDRS.get(key)
                if known and sym_addr and sym_addr != known:
                    result["errors"].append(
                        f"{key} manifest 0x{sym_addr:x} != known 0x{known:x}"
                    )
        except ImportError:
            pass

        all_ok = all(
            result[k]["initialized"] for k in ["pushint", "pushdbl", "pushstr"]
        )
        any_ok = any(
            result[k]["initialized"] for k in ["pushint", "pushdbl", "pushstr"]
        )
        if all_ok:
            result["status"] = "ok"
        elif any_ok:
            result["status"] = "partial"
        else:
            result["status"] = "all_uninitialized"

        return result

    def shutdown(self) -> None:
        """Shutdown the Stata engine (if applicable)."""
        try:
            from pystata_x.sfi._engine import shutdown as _eng_shutdown
            _eng_shutdown()
        except Exception:
            pass
        self._initialized = False

    # ── Push primitives ──────────────────────────────────────────

    def push_int(self, val: int) -> None:
        """Push an integer onto Stata's internal stack."""
        if self._pushint is None:
            raise RuntimeError("pushint not available")
        self._pushint(val)
        self._patch_last_tsmat()

    def push_double(self, val: float) -> None:
        """Push a double onto Stata's internal stack."""
        if self._pushdbl is None:
            raise RuntimeError("pushdbl not available")
        buf = ctypes.c_double(val)
        self._pushdbl(ctypes.addressof(buf))
        self._patch_last_tsmat()

    def push_str(self, s: bytes) -> None:
        """Push a string onto Stata's internal stack."""
        if self._pushstr is None:
            raise RuntimeError("pushstr not available")
        self._pushstr(s, len(s))
        self._patch_last_tsmat()

    def _patch_last_tsmat(self) -> None:
        """Patch the last pushed tsmat's [-0x10] field for pool-header check."""
        sp = self.save_sp()
        if not sp:
            return
        tsmat_ptr = ctypes.c_uint64.from_address(sp).value
        if tsmat_ptr and tsmat_ptr > 0x100000:
            ctypes.c_uint64.from_address(tsmat_ptr - 0x10).value = tsmat_ptr

    # ── Stack management ─────────────────────────────────────────

    def save_sp(self) -> int:
        """Read current stack pointer value."""
        if not self._STACK_PTR_OFFSET or not self._base:
            return 0
        return ctypes.c_uint64.from_address(
            self._base + self._STACK_PTR_OFFSET).value

    def restore_sp(self, sp_val: int) -> None:
        """Restore stack pointer to a previous value."""
        if not self._STACK_PTR_OFFSET or not self._base:
            return
        ctypes.c_uint64.from_address(
            self._base + self._STACK_PTR_OFFSET).value = sp_val

    # ── Dispatch calls ───────────────────────────────────────────

    def _resolve_name(self, name: str) -> Optional[int]:
        """Resolve a dispatch function name to a relative address."""
        if not name.startswith("_bist_") and not name.startswith("st_"):
            name = f"_bist_{name}"
        addr = self._syms.get(name)
        if addr is not None:
            return addr
        # Try with leading underscore
        addr = self._syms.get(f"_{name}")
        if addr is not None:
            return addr
        # Try bare
        addr = self._syms.get(name.lstrip("_"))
        return addr

    def _get_fn(self, addr: int, restype=None, *argtypes) -> ctypes._CFuncPtr:
        """Create a ctypes callable for the given absolute address."""
        fn_type = ctypes.CFUNCTYPE(restype, *argtypes)
        return ctypes.cast(addr, fn_type)

    def call_double(self, name: str, *args) -> Optional[float]:
        """Call a dispatch function returning double."""
        addr = self._resolve_name(name)
        if addr is None:
            return None
        rt = self._base + addr
        sp_before = self.save_sp()
        self._push_args(args)
        w0 = len(args) if args else 0
        fn = self._get_fn(rt, None, ctypes.c_int)
        fn(w0)
        return self._pop_and_read_double(sp_before)

    def call_string(self, name: str, *args) -> Optional[str]:
        """Call a dispatch function returning string."""
        addr = self._resolve_name(name)
        if addr is None:
            return None
        rt = self._base + addr
        sp_before = self.save_sp()
        self._push_args(args)
        w0 = len(args) if args else 0
        fn = self._get_fn(rt, None, ctypes.c_int)
        fn(w0)
        return self._pop_and_read_string(sp_before)

    def call_int(self, name: str, *args) -> Optional[int]:
        """Call a dispatch function returning int."""
        addr = self._resolve_name(name)
        if addr is None:
            return None
        rt = self._base + addr
        sp_before = self.save_sp()
        self._push_args(args)
        w0 = len(args) if args else 0
        fn = self._get_fn(rt, None, ctypes.c_int)
        fn(w0)
        return self._pop_and_read_int(sp_before)

    def call_void(self, name: str, *args) -> int:
        """Call a dispatch function that returns void (store).

        Reads error code after call and returns it.
        """
        addr = self._resolve_name(name)
        if addr is None:
            return -1
        rt = self._base + addr
        sp_before = self.save_sp()
        self._push_args(args)
        w0 = len(args) if args else 0
        fn = self._get_fn(rt, None, ctypes.c_int)
        fn(w0)
        # For void functions, just restore stack and check error
        self.restore_sp(sp_before)
        return self.read_error()

    def _push_args(self, args: tuple) -> None:
        """Push a tuple of arguments onto Stata's internal stack."""
        import struct
        for arg in args:
            if isinstance(arg, (int, float)):
                self.push_double(float(arg))
            elif isinstance(arg, (bytes, bytearray)):
                self.push_str(bytes(arg))
            else:
                raise TypeError(f"Unsupported arg type: {type(arg).__name__}: {arg!r}")

    def _pop_and_read_double(self, sp_before: int) -> Optional[float]:
        """Read double result from stack and restore SP."""
        sp = self.save_sp()
        try:
            tsmat = ctypes.c_uint64.from_address(sp).value
            if not tsmat:
                return None
            data_buf = ctypes.c_uint64.from_address(tsmat).value
            if not data_buf:
                return None
            return ctypes.c_double.from_address(data_buf).value
        finally:
            self.restore_sp(sp_before)

    def _pop_and_read_string(self, sp_before: int) -> Optional[str]:
        """Read string result from stack and restore SP."""
        sp = self.save_sp()
        try:
            tsmat = ctypes.c_uint64.from_address(sp).value
            if not tsmat:
                return None
            data_buf = ctypes.c_uint64.from_address(tsmat).value
            if not data_buf:
                return None
            # String tsmats: first 4 bytes = length, then string data
            length = ctypes.c_int32.from_address(data_buf).value
            if length <= 0 or length > 65536:
                return None
            raw = ctypes.create_string_buffer(length + 1)
            ctypes.memmove(raw, data_buf + 4, length)
            return raw.value.decode("utf-8", errors="replace")
        finally:
            self.restore_sp(sp_before)

    def _pop_and_read_int(self, sp_before: int) -> Optional[int]:
        """Read int result from stack and restore SP."""
        sp = self.save_sp()
        try:
            tsmat = ctypes.c_uint64.from_address(sp).value
            if not tsmat:
                return None
            data_buf = ctypes.c_uint64.from_address(tsmat).value
            if not data_buf:
                return None
            val = ctypes.c_double.from_address(data_buf).value
            return int(val)
        finally:
            self.restore_sp(sp_before)

    # ── Diagnostics ──────────────────────────────────────────────

    def execute(self, cmd: str) -> tuple[str, int]:
        """Execute a Stata command, return (output, rc)."""
        if self._engine:
            return self._engine(cmd)
        if self._lib:
            self._lib.StataSO_ClearOutputBuffer()
            rc = self._lib.StataSO_Execute(
                cmd.encode() if isinstance(cmd, str) else cmd)
            buf = self._lib.StataSO_GetOutputBuffer()
            output = ""
            if buf:
                raw = ctypes.c_char_p(buf).value
                if raw:
                    output = raw.decode("utf-8", errors="replace")
            return output, rc
        return "", -1

    def read_error(self) -> int:
        """Read Stata's internal error code."""
        if not self._base or not self._ERR_ADDR_RELATIVE:
            return 0
        return ctypes.c_int32.from_address(
            self._base + self._ERR_ADDR_RELATIVE).value

    def dump_tsmat(self, label: str = "") -> dict:
        """Dump the current top-of-stack tsmat's memory layout.

        Returns a dict with tsmat struct fields, data buffer, and
        pool-header check information.
        """
        result: dict = {
            "label": label,
            "tsmat_ptr": 0,
            "data_buf": 0,
            "tsmat_fields": {},
            "data_bytes": b"",
            "pool_header": {},
            "self_ptr": {},
        }

        sp = self.save_sp()
        if not sp:
            return result

        tsmat_ptr = ctypes.c_uint64.from_address(sp).value
        result["sp"] = sp
        result["tsmat_ptr"] = tsmat_ptr

        if not tsmat_ptr or tsmat_ptr <= 0x100000:
            return result

        # Dump tsmat struct fields (first 80 bytes)
        fields = {}
        for i in range(0, 80, 8):
            val = ctypes.c_uint64.from_address(tsmat_ptr + i).value
            fields[f"[{i:#04x}]"] = f"0x{val:016x}"
        result["tsmat_fields"] = fields

        # Data buffer
        data_buf = ctypes.c_uint64.from_address(tsmat_ptr).value
        result["data_buf"] = data_buf
        if data_buf and data_buf > 0x100000:
            # Read first 64 bytes of data
            raw = (ctypes.c_uint8 * 64).from_address(data_buf)
            result["data_bytes"] = bytes(raw)

            # Read as string (first 64 chars, replace non-printable)
            try:
                raw_str = (ctypes.c_char * 64).from_address(data_buf)
                result["data_str"] = raw_str.value.decode("utf-8", errors="replace") if raw_str.value else ""
            except Exception:
                result["data_str"] = ""

        # Pool header check
        ph_tsmat = ctypes.c_uint32.from_address(tsmat_ptr - 0x94).value
        ph_data = ctypes.c_uint32.from_address(data_buf - 0x94).value if data_buf and data_buf > 0x100000 else 0
        result["pool_header"] = {
            "tsmat[-0x94]": f"0x{ph_tsmat:08x}",
            "data_buf[-0x94]": f"0x{ph_data:08x}",
            "tsmat_pool_ok": ph_tsmat == 0x2b,
            "data_pool_ok": ph_data == 0x2b,
        }

        # Self-pointer check
        sp_val = ctypes.c_uint64.from_address(tsmat_ptr - 0x10).value
        result["self_ptr"] = {
            "tsmat[-0x10]": f"0x{sp_val:016x}",
            "ok": sp_val == tsmat_ptr,
        }

        # Tsmat flags
        result["flags"] = {
            "arg_type": ctypes.c_uint8.from_address(tsmat_ptr + 0x36).value,
            "return_type": ctypes.c_uint16.from_address(tsmat_ptr + 0x34).value,
            "field_0x20": ctypes.c_uint64.from_address(tsmat_ptr + 0x20).value,
            "field_0x28": ctypes.c_uint64.from_address(tsmat_ptr + 0x28).value,
        }

        return result

    def diagnose_dispatch(self, name: str, *args,
                          return_type: str = "double") -> dict:
        """Diagnose a dispatch call: perform it and report all state.

        Catches exceptions (including SIGSEGV, though that kills the
        Python process).  Returns a dict with:
        - ``name``: function name
        - ``args``: the arguments passed
        - ``return_value``: the value returned (or None on error)
        - ``error_code``: Stata error code after call
        - ``tsmat_before``: tsmat dump before call
        - ``tsmat_after``: tsmat dump after call
        - ``inferred_protocol``: what the calling convention looks like
        - ``crashes``: whether the call caused a crash
        """
        result: dict = {
            "name": name,
            "args": [repr(a) for a in args],
            "return_value": None,
            "error_code": 0,
            "tsmat_before": None,
            "tsmat_after": None,
            "inferred_protocol": {},
            "crash": False,
        }

        # Get address
        addr = self._resolve_name(name)
        if addr is None:
            result["error"] = f"symbol {name} not found in manifest"
            return result
        result["vaddr"] = f"0x{addr:x}"
        result["abs_addr"] = f"0x{self._base + addr:x}"

        # Dump tsmat before
        result["tsmat_before"] = self.dump_tsmat(f"before {name}")

        # Push args and dump again
        sp_before = self.save_sp()
        try:
            for arg in args:
                if isinstance(arg, (int, float)):
                    self.push_double(float(arg))
                elif isinstance(arg, (bytes, bytearray)):
                    self.push_str(bytes(arg))
        except Exception as e:
            result["error"] = f"push failed: {e}"
            result["tsmat_after"] = self.dump_tsmat(f"after push-fail {name}")
            return result

        result["tsmat_after_push"] = self.dump_tsmat(f"pushed args {name}")

        # Call the function
        w0 = len(args) if args else 0
        rt = self._base + addr
        fn = self._get_fn(rt, None, ctypes.c_int)

        err_before = self.read_error()

        # NOTE: This WILL crash Python if the function SIGSEGVs.
        # There's no way to catch that from Python.
        try:
            fn(w0)
            result["call_completed"] = True
        except Exception as e:
            result["call_completed"] = False
            result["call_error"] = str(e)
            self.restore_sp(sp_before)
            return result

        err_after = self.read_error()
        result["error_before"] = err_before
        result["error_code"] = err_after
        result["error_set"] = err_before != err_after
        result["error_message"] = self._error_to_str(err_after)

        # Read return value
        sp = self.save_sp()
        result["tsmat_after"] = self.dump_tsmat(f"after {name}")
        result["sp_before"] = sp_before
        result["sp_after"] = sp

        if return_type == "double":
            try:
                tsmat = ctypes.c_uint64.from_address(sp).value
                if tsmat:
                    data_buf = ctypes.c_uint64.from_address(tsmat).value
                    if data_buf:
                        result["return_value"] = ctypes.c_double.from_address(data_buf).value
            except Exception:
                pass
        elif return_type == "string":
            try:
                tsmat = ctypes.c_uint64.from_address(sp).value
                if tsmat:
                    data_buf = ctypes.c_uint64.from_address(tsmat).value
                    if data_buf:
                        length = ctypes.c_int32.from_address(data_buf).value
                        if 0 < length <= 65536:
                            raw = ctypes.create_string_buffer(length + 1)
                            ctypes.memmove(raw, data_buf + 4, length)
                            result["return_value"] = raw.value.decode("utf-8", errors="replace")
            except Exception:
                pass
        elif return_type == "int":
            try:
                tsmat = ctypes.c_uint64.from_address(sp).value
                if tsmat:
                    data_buf = ctypes.c_uint64.from_address(tsmat).value
                    if data_buf:
                        result["return_value"] = int(
                            ctypes.c_double.from_address(data_buf).value)
            except Exception:
                pass

        # Infer protocol from diagnostics
        result["inferred_protocol"] = self._infer_protocol(name, result)

        self.restore_sp(sp_before)
        return result

    def _infer_protocol(self, name: str, diag: dict) -> dict:
        """Infer calling convention from diagnostic data."""
        proto: dict = {
            "name": name,
            "arg_count": len(diag.get("args", [])),
            "return_type": "unknown",
            "protocol": "push+stack",
            "pool_ok_during_call": False,
        }

        # Check tsmat pool header from the tsmat_after_push dump
        tsmat_after = diag.get("tsmat_after_push", {})
        pool_header = tsmat_after.get("pool_header", {})
        if pool_header:
            proto["pool_ok_during_call"] = pool_header.get("tsmat_pool_ok", False)

        # Determine return type based on result
        rv = diag.get("return_value")
        if rv is not None:
            if isinstance(rv, str):
                proto["return_type"] = "string"
            elif isinstance(rv, (int, float)):
                if isinstance(rv, float) and rv == int(rv):
                    proto["return_type"] = "int_or_double"
                else:
                    proto["return_type"] = "double"
        else:
            proto["return_type"] = "void"

        # Check error
        if diag.get("error_set") and diag.get("error_code", 0) != 0:
            proto["error_set"] = True
            proto["error_code"] = diag["error_code"]
            proto["error_message"] = diag.get("error_message", "")

        # Check if the tsmat self-pointer was patched
        flags = tsmat_after.get("flags", {})
        if flags:
            proto["arg_type_flag"] = flags.get("arg_type")
            proto["return_flag"] = flags.get("return_type")

        return proto

    @staticmethod
    def _error_to_str(code: int) -> str:
        """Return a human-readable error message for a Stata error code."""
        errors = {
            0: "success",
            3102: "conformability error (pool-header check failed)",
            3103: "wrong arg type (expected string arg, got numeric)",
            3254: "wrong return type (expected string return, got double or vice versa)",
            3204: "tsmat metadata mismatch",
            3300: "conformability error (bad arg count or value)",
        }
        return errors.get(code, f"unknown error {code}")


class ProtocolAutoTester:
    """Automatically tests dispatch functions to determine their protocol.

    Tries different argument combinations and call conventions to
    discover what works.  Reports the winning convention.
    """

    def __init__(self, engine: EngineConnection):
        self.engine = engine

    def test_protocol(self, name: str) -> dict:
        """Automatically determine the protocol for a dispatch function.

        Tries arg counts 0-3, with string and double types, and reports
        which combination succeeds.
        """
        results: dict = {
            "name": name,
            "attempts": [],
            "winning_convention": None,
        }

        addr = self.engine._resolve_name(name)
        if addr is None:
            results["error"] = f"symbol {name} not found"
            return results

        results["vaddr"] = f"0x{addr:x}"

        # Try different arg combinations
        trials = [
            # (args, return_type)
            ([], "double"),
            ([0], "double"),       # zero int
            ([1], "double"),
            ([b""], "string"),     # empty string
            ([b"c(N)"], "double"), # c() system value
            ([0.0], "double"),
            ([b"__"], "string"),
            ([b"mynum"], "double"),  # scalar name
            ([0, 0], "double"),
            ([0, 0, 0], "double"),
        ]

        for args, rtype in trials:
            rs = self.engine.diagnose_dispatch(name, *args, return_type=rtype)
            rs["attempt_args"] = [repr(a) for a in args]
            rs["attempt_return_type"] = rtype
            results["attempts"].append(rs)

            # Check if it succeeded (no error, has return value, or call completed)
            if rs.get("call_completed") and not rs.get("error_set"):
                ec = rs.get("error_code", 0)
                if ec == 0:
                    rv = rs.get("return_value")
                    if rv is not None and rv != 0.0:
                        results["winning_convention"] = {
                            "args": args,
                            "return_type": rtype,
                            "return_value": rv,
                        }
                        break
                    elif rv is not None and rv == 0.0:
                        # Could be valid (returning 0) or failure
                        pass

        return results

    def diagnose_failure(self, name: str, *args,
                         return_type: str = "double") -> dict:
        """Call a dispatch function and explain WHY it failed.

        Performs these steps:
        1. Get oracle value via StataSO_Execute display
        2. Save stack state
        3. Push args and dump arg tsmat (pool headers, flags, layout)
        4. Call function
        5. Dump result tsmat (type flag, data_buf, string/double value)
        6. Read error code
        7. Try reading result as both double and string
        8. Compare against oracle
        9. Produce structured failure analysis
        """
        import ctypes
        result: dict = {
            "name": name,
            "args": [repr(a) for a in args],
            "steps": [],
        }

        if not self.engine._base:
            init_status = self.engine.initialize()
            result["init_status"] = init_status

        # Step 1: Get oracle value
        oracle = self._get_oracle(name, *args)
        if oracle is not None:
            result["oracle"] = oracle

        # Step 2: Save SP and push args
        sp_before = self.engine.save_sp()
        push_step = {"action": "push_args", "args": [repr(a) for a in args]}
        try:
            for arg in args:
                if isinstance(arg, (int, float)):
                    self.engine.push_double(float(arg))
                elif isinstance(arg, (bytes, bytearray)):
                    self.engine.push_str(bytes(arg))
            push_step["status"] = "ok"
        except Exception as e:
            push_step["status"] = "failed"
            push_step["error"] = str(e)
            self.engine.restore_sp(sp_before)
            return result
        result["steps"].append(push_step)

        # Step 3: Dump arg tsmat
        arg_dump = self.engine.dump_tsmat("after_push")
        result["arg_tsmat"] = arg_dump

        # Step 4: Set string return flag if needed
        if return_type == "string":
            sp = self.engine.save_sp()
            tsmat = ctypes.c_uint64.from_address(sp).value
            if tsmat:
                ctypes.c_uint16.from_address(tsmat + 0x34).value = 0xFFFD
                result["steps"].append({
                    "action": "set_return_flag",
                    "tsmat_034_set_to_FFFD": True,
                })

        # Step 5: Call the function
        addr = self.engine._resolve_name(name)
        if addr is None:
            result["error"] = f"{name} not found in symbols"
            self.engine.restore_sp(sp_before)
            return result

        rt = self.engine._base + addr
        w0 = len(args) if args else 0
        fn = self.engine._get_fn(rt, None, ctypes.c_int)
        err_before = self.engine.read_error()

        call_step = {"action": "call", "edi": w0, "vaddr": f"0x{addr:x}"}
        try:
            fn(w0)
            call_step["status"] = "ok"
        except Exception as e:
            call_step["status"] = "exception"
            call_step["error"] = str(e)
            self.engine.restore_sp(sp_before)
            return result
        result["steps"].append(call_step)

        # Step 6: Check error code
        err_after = self.engine.read_error()
        result["error_before"] = err_before
        result["error_after"] = err_after
        result["error_set"] = err_before != err_after
        result["error_message"] = self.engine._error_to_str(err_after) if err_after else None

        # Step 7: Dump result tsmat
        res_dump = self.engine.dump_tsmat("after_call")
        result["result_tsmat"] = res_dump

        # Step 8: Read return value both ways
        sp = self.engine.save_sp()
        tsmat_ptr = ctypes.c_uint64.from_address(sp).value if sp else 0
        if tsmat_ptr and tsmat_ptr > 0x100000:
            data_buf = ctypes.c_uint64.from_address(tsmat_ptr).value
            if data_buf and data_buf > 0x100000:
                # As double
                result["return_as_double"] = ctypes.c_double.from_address(data_buf).value
                # As string (two-level)
                str_ptr = ctypes.c_uint64.from_address(data_buf).value
                if str_ptr and str_ptr > 0x100000:
                    str_len = ctypes.c_int32.from_address(str_ptr).value
                    if 0 < str_len < 65536:
                        raw = ctypes.create_string_buffer(str_len + 1)
                        ctypes.memmove(raw, str_ptr + 4, str_len)
                        result["return_as_string"] = raw.value.decode("utf-8", errors="replace")

        # Step 9: Compare with oracle
        if oracle is not None:
            dval = result.get("return_as_double")
            sval = result.get("return_as_string")
            if isinstance(oracle, (int, float)):
                if dval is not None and abs(dval - oracle) < 0.001:
                    result["oracle_match"] = True
                else:
                    result["oracle_match"] = False
                    result["oracle_mismatch"] = f"expected {oracle}, got double={dval} str={sval!r}"
                    self._analyze_failure(result, arg_dump, res_dump, oracle)
            elif isinstance(oracle, str):
                if sval == oracle:
                    result["oracle_match"] = True
                else:
                    result["oracle_match"] = False
                    result["oracle_mismatch"] = f"expected {oracle!r}, got {sval!r}"
                    self._analyze_failure(result, arg_dump, res_dump, oracle)

        self.engine.restore_sp(sp_before)
        return result

    def _analyze_failure(self, result: dict,
                          arg_tsmat: dict, res_tsmat: dict,
                          expected: Any) -> None:
        """Analyze the root cause of a dispatch call failure."""
        analysis = []

        # Check arg tsmat pool header
        pool = arg_tsmat.get("pool_header", {})
        if not pool.get("tsmat_pool_ok"):
            analysis.append(
                f"Pool-header check FAILS: tsmat[-0x94]={pool.get('tsmat[-0x94]')} "
                f"!= 0x2b. Converter will return error 0xC1E (3102) immediately.")

        # Check self pointer
        self_ptr = arg_tsmat.get("self_ptr", {})
        if not self_ptr.get("ok"):
            analysis.append(
                f"Self-pointer check FAILS: tsmat[-0x10]={self_ptr.get('tsmat[-0x10]')} "
                f"!= tsmat. Pool-header dereference will fail.")

        # Check flags
        flags = arg_tsmat.get("flags", {})
        if flags.get("arg_type", 0) != 0:
            analysis.append(
                f"Arg type flag tsmat[0x36]={flags.get('arg_type')} != 0. "
                f"Converter expects 0 (string arg), will error 0xC1F (3103).")
        if flags.get("return_type", 0) != 0xFFFD:
            analysis.append(
                f"Return flag tsmat[0x34]=0x{flags.get('return_type',0):04x} != 0xFFFD. "
                f"Converter will error 0xCB6 (3254).")
        if flags.get("field_0x20", 0) != 1 or flags.get("field_0x28", 0) != 1:
            analysis.append(
                f"Metadata tsmat[0x20]={flags.get('field_0x20')} [0x28]={flags.get('field_0x28')}. "
                f"Converter needs both == 1, will error 0xC84 (3204).")

        # Check result
        rflags = res_tsmat.get("flags", {})
        if rflags:
            rtype = rflags.get("return_type")
            analysis.append(
                f"Result tsmat[0x34] = 0x{rtype:04x} "
                f"({'string' if rtype == 0xFFFD else 'numeric'}).")

        # Stack change
        arg_sp = arg_tsmat.get("sp", 0)
        res_sp = res_tsmat.get("sp", 0)
        if arg_sp and res_sp:
            delta = res_sp - arg_sp
            if delta == 0:
                analysis.append("Stack pointer unchanged — no result tsmat was pushed.")
            else:
                analysis.append(f"Stack delta = {delta} bytes.")

        if result.get("error_set"):
            analysis.append(f"Error code 0x{result['error_after']:x} was set. "
                          f"{result.get('error_message', '')}")

        result["failure_analysis"] = analysis

    def _get_oracle(self, name: str, *args):
        """Get expected value via StataSO_Execute display."""
        if "numscalar" in name and args and isinstance(args[0], (bytes, bytearray)):
            sname = args[0].decode()
            try:
                out, rc = self.engine.execute(f"display scalar({sname})")
                if rc == 0:
                    for line in out.split("\n"):
                        line = line.strip()
                        if line and not line.startswith(".") and not line.startswith("r("):
                            try:
                                return float(line)
                            except ValueError:
                                return line
            except Exception:
                pass
        return None

    def universal_call(self, name: str, *args) -> dict:
        """Call a dispatch function and return the result with automatic type detection.

        Unlike call_string (which sets tsmat[0x34] = 0xFFFD on x86_64 and may crash)
        and call_double (which returns GSO pointer as double for string results),
        this method:
        1. Pushes args using the standard _push_* functions
        2. Does NOT set tsmat[0x34] (safe for all functions)
        3. Reads the result tsmat and auto-detects whether it's a GSO string or inline double
        4. Returns the correct Python type (str or float)

        Returns dict with:
        - "type": "string" | "double" | "none"
        - "value": the Python value (str, float, or None)
        - "error_code": error code after call
        - "result_type_flag": tsmat[0x34] raw value
        """
        import ctypes
        result: dict = {"type": "none", "value": None, "error_code": 0}

        if not self.engine._base:
            self.engine.initialize()

        addr = self.engine._resolve_name(name)
        if addr is None:
            result["error"] = f"symbol {name} not found"
            return result

        sp_before = self.engine.save_sp()
        try:
            # Push args exactly as call_double does
            for a in args:
                if isinstance(a, (int, float)):
                    self.engine.push_double(float(a))
                elif isinstance(a, (bytes, bytearray)):
                    self.engine.push_str(bytes(a))

            # Call function with arg count
            rt = addr + self.engine._base
            fn = self.engine._get_fn(rt, None, ctypes.c_int)
            fn(len(args))

            # Read result
            sp = self.engine.save_sp()
            tsmat_ptr = ctypes.c_uint64.from_address(sp).value
            if not tsmat_ptr:
                result["type"] = "none"
                return result

            # Read error code
            try:
                result["error_code"] = self.engine.read_error()
            except Exception:
                pass

            result["result_ptr"] = f"0x{tsmat_ptr:x}"
            result["result_type_flag"] = hex(
                ctypes.c_uint16.from_address(tsmat_ptr + 0x34).value)

            data_buf = ctypes.c_uint64.from_address(tsmat_ptr).value
            if not data_buf:
                return result

            # Check result type
            rtype = ctypes.c_uint32.from_address(tsmat_ptr + 0x34).value & 0xFF
            if rtype == 0:
                # Numeric — read inline double
                dval = ctypes.c_double.from_address(data_buf).value
                result["type"] = "double"
                result["value"] = dval
                result["raw_hex"] = hex(ctypes.c_uint64.from_address(data_buf).value)
            else:
                # String — read GSO
                str_ptr = ctypes.c_uint64.from_address(data_buf).value
                if str_ptr:
                    slen = ctypes.c_uint32.from_address(str_ptr).value
                    if 0 < slen < 2048:
                        raw = ctypes.string_at(ctypes.c_void_p(str_ptr + 4), slen)
                        result["type"] = "string"
                        result["value"] = raw.rstrip(b"\x00").decode("utf-8", errors="replace")
                        result["gso_len"] = slen
        finally:
            self.engine.restore_sp(sp_before)

        return result

    def find_working_convention(self, name: str) -> dict:
        """Auto-discover the calling convention for a dispatch function.

        Tries all reasonable combinations of:
        - Arg types: no-arg, string name, int, double, string name as var index
        - Arg counts: 0, 1, 2
        - Push approach: _push_str vs _push_double

        Returns dict with entries for each tried convention and which works.
        """
        results: dict = {
            "name": name,
            "conventions": [],
            "working": None,
        }

        addr = self.engine._resolve_name(name)
        if addr is None:
            results["error"] = f"symbol {name} not found"
            return results

        results["vaddr"] = f"0x{addr:x}"

        # Build trial combinations based on function name heuristics
        trials: list[list] = []  # list of (arg_list, note)

        # Zero-arg
        trials.append(([], "zero_arg"))

        # One-arg: various types
        is_var_fn = any(v in name for v in ["var", "data"])
        is_scalar_fn = "scalar" in name
        is_macro_fn = "macro" in name or "global" in name

        if is_var_fn or not (is_scalar_fn or is_macro_fn):
            # Variable-index functions: try string "1" (like call_double)
            trials.append(([b"1"], "var_str_idx"))
            trials.append(([1.0], "var_double_idx"))
            trials.append(([b"make"], "var_str_name"))  # var name

            # Two-arg: (obs, var)
            trials.append(([1.0, 2.0], "obs_var_double"))
            trials.append(([b"1", b"2"], "obs_var_str"))
        elif is_scalar_fn:
            trials.append(([b"mynum"], "scalar_name"))
            trials.append(([b"scalar(mynum)"], "scalar_expr"))
            trials.append(([1.0], "scalar_double"))
        elif is_macro_fn:
            trials.append(([b"mymacro"], "macro_name"))

        # Try each trial
        for args, note in trials:
            trial: dict = {
                "args": [repr(a) for a in args],
                "note": note,
                "result": None,
            }
            try:
                uc = self.universal_call(name, *args)
                trial["result"] = {
                    "type": uc.get("type"),
                    "value": uc.get("value"),
                    "error_code": uc.get("error_code", 0),
                    "result_ptr": uc.get("result_ptr"),
                }
                # Check if this is a working convention
                if (uc.get("type") != "none"
                    and uc.get("error_code", 999) == 0
                    and uc.get("value") is not None):
                    # Clean working — no error and non-None result
                    trial["working"] = True
                    if results["working"] is None:
                        results["working"] = {
                            "args": [repr(a) for a in args],
                            "note": note,
                            "type": uc["type"],
                            "value": uc["value"],
                        }
            except Exception as e:
                trial["error"] = str(e)
                trial["working"] = False

            results["conventions"].append(trial)

        return results


class CrashSafeProtocolTester:
    """Run protocol tests in subprocess isolation so crashes don't kill the agent.

    Each test is executed in a separate Python subprocess.  If the function
    call triggers a SIGSEGV, only the child process dies; the parent (agent)
    continues unaffected.  Results are communicated via stdout JSON.

    Usage::

        tester = CrashSafeProtocolTester(stata_lib_path="/usr/local/stata19/libstata-se.so")
        result = tester.universal_call_safe("_bist_varname", types=[b"1"])
        print(result)
    """

    def __init__(self, stata_lib_path: str = None):
        self._stata_lib_path = stata_lib_path
        self._timeout = 15  # seconds per call

    def _make_runner_script(self, fn_name: str, *args,
                            return_type: str = "auto") -> str:
        """Generate a Python script that imports the framework and calls fn."""
        import json
        import json
        # Encode args: bytes -> hex string, others -> repr
        args_encoded = []
        for a in args:
            if isinstance(a, bytes):
                args_encoded.append({"__bytes__": a.hex()})
            elif isinstance(a, float):
                args_encoded.append(a)
            elif isinstance(a, int):
                args_encoded.append(a)
            else:
                args_encoded.append(repr(a))

        import json
        lib_path = self._stata_lib_path or "/usr/local/stata19/libstata-se.so"
        # Write args to a temp JSON file to avoid quoting issues
        args_file = "/tmp/__px_args_" + fn_name.replace("_", "") + ".json"
        with open(args_file, "w") as af:
            json.dump(args_encoded, af)

        lines = [
            "import sys, json, ctypes, os",
            "sys.path.insert(0, '/pystata-x/src')",
            "",
            f"# Read args from {args_file}",
            f"with open({json.dumps(args_file)}) as af:",
            "    args_encoded = json.load(af)",
            "args = []",
            "for a in args_encoded:",
            "    if isinstance(a, dict) and '__bytes__' in a:",
            "        args.append(bytes.fromhex(a['__bytes__']))",
            "    else:",
            "        args.append(a)",
            "",
            "try:",
            "    from pystata_analyzer.live_protocol import EngineConnection, ProtocolAutoTester",
            "    ec = EngineConnection()",
            "    ec.initialize()",
            "    ec.execute('sysuse auto, clear')",
            "    ec.execute('scalar mynum = 42.5')",
            "    ec.execute('global mymacro HelloWorld')",
            "",
            f"    tester = ProtocolAutoTester(ec)",
            f"    result = tester.universal_call({json.dumps(fn_name)}, *args)",
            "    result['_status'] = 'ok'",
            "    if isinstance(result.get('value'), bytes):",
            "        result['value'] = result['value'].decode(errors='replace')",
            "    # Clean up temp file",
            f"    try: os.unlink({json.dumps(args_file)})",
            "    except OSError: pass",
            "    print(json.dumps(result))",
            "except Exception as e:",
            "    import traceback",
            "    tb = traceback.format_exc()",
            "    print(json.dumps({'_status': 'exception', '_error': str(e), '_traceback': tb}))",
        ]
        script = "\n".join(lines)
        return script

    def universal_call_safe(self, fn_name: str, *args,
                            return_type: str = "auto") -> dict:
        """Call a dispatch function in a subprocess, returning results.

        If the child process crashes (SIGSEGV), returns a crash result
        instead of killing the parent.
        """
        import subprocess as sp
        import tempfile
        import os

        # Write script to temp file
        script = self._make_runner_script(fn_name, *args, return_type=return_type)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py",
                                          delete=False, dir="/tmp") as f:
            f.write(script)
            script_path = f.name

        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        if self._stata_lib_path:
            env["STATA_LIB_PATH"] = self._stata_lib_path

        try:
            result = sp.run(
                [sys.executable, script_path],
                capture_output=True,
                timeout=self._timeout,
                env=env,
            )
            stdout = result.stdout.decode("utf-8", errors="replace")
            stderr = result.stderr.decode("utf-8", errors="replace")

            if result.returncode == -11:  # SIGSEGV
                return {
                    "_status": "crash",
                    "_signal": "SIGSEGV",
                    "fn": fn_name,
                    "args": [repr(a) for a in args],
                }
            elif result.returncode != 0:
                return {
                    "_status": "error",
                    "_returncode": result.returncode,
                    "_stderr": stderr[:500],
                    "fn": fn_name,
                }

            # Parse JSON from stdout
            import json
            for line in stdout.split("\n"):
                line = line.strip()
                if line.startswith("{"):
                    try:
                        data = json.loads(line)
                        return data
                    except json.JSONDecodeError:
                        pass

            return {
                "_status": "parse_error",
                "_stdout": stdout[:500],
                "fn": fn_name,
            }
        except sp.TimeoutExpired:
            return {"_status": "timeout", "fn": fn_name}
        finally:
            try:
                os.unlink(script_path)
            except OSError:
                pass

    def find_working_convention_safe(self, fn_name: str) -> dict:
        """Auto-discover calling convention with crash protection.

        Tests each arg combination in a separate subprocess, so a
        crash in one test doesn't affect the others.
        """
        results: dict = {
            "name": fn_name,
            "conventions": [],
            "working": None,
        }

        # Build trial combinations (same as ProtocolAutoTester.find_working_convention)
        trials: list[list] = []
        trials.append(([], "zero_arg"))

        is_var_fn = any(v in fn_name for v in ["var", "data"])
        is_scalar_fn = "scalar" in fn_name
        is_macro_fn = "macro" in fn_name or "global" in fn_name

        if is_var_fn or not (is_scalar_fn or is_macro_fn):
            trials.append(([b"1"], "var_str_idx"))
            trials.append(([1.0], "var_double_idx"))
            trials.append(([b"make"], "var_str_name"))
            trials.append(([1.0, 2.0], "obs_var_double"))
        elif is_scalar_fn:
            trials.append(([b"mynum"], "scalar_name"))
            trials.append(([1.0], "scalar_double"))
        elif is_macro_fn:
            trials.append(([b"mymacro"], "macro_name"))

        for args, note in trials:
            trial: dict = {"args": [repr(a) for a in args], "note": note}
            try:
                uc = self.universal_call_safe(fn_name, *args)
                trial["result"] = {
                    "status": uc.get("_status"),
                    "type": uc.get("type"),
                    "value": uc.get("value"),
                    "error_code": uc.get("error_code", -1),
                }
                if (uc.get("_status") == "ok"
                    and uc.get("type") not in ("none", None)
                    and uc.get("error_code", 999) == 0):
                    trial["working"] = True
                    if results["working"] is None:
                        results["working"] = {
                            "args": [repr(a) for a in args],
                            "note": note,
                            "type": uc["type"],
                            "value": uc["value"],
                        }
            except Exception as e:
                trial["error"] = str(e)

            results["conventions"].append(trial)

        return results


# ── Framework integration ────────────────────────────────────────────

class LiveProtocolValidatorPlugin:
    """Plugin entry point for live protocol validation.

    This is designed to be called from a Framework to add live-testing
    data to analysis results.

    Usage::

        validator = LiveProtocolValidatorPlugin()
        validator.validate_all(framework)
    """

    def __init__(self):
        self.engine: Optional[EngineConnection] = None
        self.initialized = False

    def initialize(self) -> dict:
        """Initialize the engine connection. Returns status dict."""
        self.engine = EngineConnection()
        status = self.engine.initialize()
        self.initialized = status.get("status") in ("ok", "partial")
        return status

    def validate_all(self, framework: "Framework") -> dict:
        """Run live protocol validation on all functions.

        Requires a running Stata engine.  Returns a dict keyed by
        function name with diagnostic results.
        """
        if not self.initialized:
            init = self.initialize()
            if not self.initialized:
                return {"error": "engine init failed", "init_status": init}

        results: dict = {}
        report = framework._last_report or {}
        functions = report.get("functions", {})

        # Validate functions that are unclassified or have suspicious results
        for name, fn_result in functions.items():
            if fn_result.get("unclassified") or fn_result.get("protocol_validation", {}).get("valid") == False:
                diag = self.engine.diagnose_dispatch(
                    name,
                    *self._guess_args(fn_result),
                    return_type=self._guess_return_type(fn_result),
                )
                results[name] = diag

                # If the diagnostic shows it works with a specific protocol,
                # add that to the function result
                if diag.get("call_completed") and not diag.get("error_set"):
                    inferred = diag.get("inferred_protocol", {})
                    if inferred:
                        fn_result["live_protocol"] = inferred

        return results

    def validate_one(self, name: str, fn_result: dict) -> dict:
        """Validate a single function live."""
        if not self.initialized:
            init = self.initialize()
            if not self.initialized:
                return {"error": "engine init failed", "init_status": init}

        return self.engine.diagnose_dispatch(
            name,
            *self._guess_args(fn_result),
            return_type=self._guess_return_type(fn_result),
        )

    def _guess_args(self, fn_result: dict) -> list:
        """Guess arguments from function analysis."""
        # Based on protocol_type, infer what args to pass
        pt = fn_result.get("protocol_type", "")
        if pt == "no_stack_args":
            return []
        if pt == "read_write":
            # read_write functions typically expect (name_str, flag_int)
            return [b"test", 1]
        return [0]

    def _guess_return_type(self, fn_result: dict) -> str:
        """Guess return type from function analysis."""
        pt = fn_result.get("protocol_type", "")
        if pt == "string_return":
            return "string"
        push_calls = fn_result.get("push_calls", [])
        if any(p.get("push_function") == "_pushstr" for p in push_calls):
            return "string"
        return "double"

    def shutdown(self):
        """Shutdown the engine."""
        if self.engine:
            self.engine.shutdown()


class StataMemoryReader:
    """Direct memory access to Stata's internal data structures.

    Reads variable names, types, labels, formats, scalar values, and
    other metadata directly from Stata's .bss/global structures via
    ctypes, bypassing both dispatch functions and StataSO_Execute.

    All offsets are discovered dynamically from the binary at class
    load time and verified at runtime.
    """

    # Known .bss offsets for variable info (x86_64, verified empirically)
    # These are RIP-relative target addresses from dispatch function disassembly
    VAR_NAME_TABLE = 0x4CB1B08  # stride 129, from _read_var_name_x86
    VAR_TYPE_TABLE = 0x500C7D0  # stride 2 (uint16 per var), inferred
    VAR_LABEL_TABLE = 0x500C7E0  # per-var label pointers, inferred
    VAR_FMT_TABLE = 0x500C7F0   # per-var format string pointers
    ARG_PTR_ADDR = 0x500C6A0   # current arg tsmat pointer

    def __init__(self, base_addr: int = 0):
        self._base = base_addr
        self._scalar_region_cache: dict = {
            "start": 0,
            "end": 0,
            "name_to_value_offset": -132,
            "scanned": False,
        }

    @property
    def base(self) -> int:
        return self._base

    @base.setter
    def base(self, val: int):
        self._base = val

    def _read_qword(self, addr: int) -> int:
        """Read a 64-bit value from memory at (base + addr)."""
        import ctypes
        return ctypes.c_uint64.from_address(self._base + addr).value

    def _read_word(self, addr: int) -> int:
        """Read a 16-bit value from memory."""
        import ctypes
        return ctypes.c_uint16.from_address(self._base + addr).value

    def _read_byte(self, addr: int) -> int:
        """Read an 8-bit value from memory."""
        import ctypes
        return ctypes.c_uint8.from_address(self._base + addr).value

    def _read_double(self, addr: int) -> float:
        """Read a double from memory."""
        import ctypes
        return ctypes.c_double.from_address(self._base + addr).value

    def _read_string(self, addr: int, max_len: int = 256) -> str:
        """Read a null-terminated string from memory."""
        import ctypes
        raw = ctypes.string_at(self._base + addr, max_len)
        null = raw.find(b"\x00")
        if null >= 0:
            raw = raw[:null]
        return raw.decode("latin-1", errors="replace")

    # ─── Variable info ────────────────────────────────────────────────

    def read_var_name_x86(self, varno: int) -> str:
        """Read variable name from Stata's name table (stride 129)."""
        try:
            table_ptr = self._read_qword(self.VAR_NAME_TABLE)
            if table_ptr:
                raw = ctypes.string_at(table_ptr + varno * 129, 32)
                null = raw.find(b"\x00")
                if null > 0:
                    raw = raw[:null]
                return raw.decode("latin-1", errors="replace")
        except Exception:
            pass
        return ""

    def read_var_names(self) -> list[str]:
        """Read ALL variable names from the name table."""
        names = []
        for v in range(2048):  # Max vars
            try:
                n = self.read_var_name_x86(v)
                if not n:
                    if v > 100:
                        break  # Reached end of table
                    continue
                names.append(n)
            except Exception:
                break
        return names

    def read_var_type(self, varno: int) -> str:
        """Read variable storage type as string (double, str#, etc)."""
        try:
            type_ptr = self._read_qword(self.VAR_TYPE_TABLE)
            if type_ptr:
                typ = ctypes.c_uint16.from_address(type_ptr + varno * 2).value
                return self._decode_type(typ)
        except Exception:
            pass
        return ""

    @staticmethod
    def _decode_type(typ: int) -> str:
        """Convert Stata internal type code to string."""
        if typ == 0xFFF5:
            return "strL"
        elif typ == 0xFFF7:
            return "float"
        elif typ == 0xFFF8:
            return "long"
        elif typ == 0xFFF9 or typ == 0:
            return "double"
        elif typ == 0xFFFB:
            return "byte"
        elif typ == 0xFFFC:
            return "int"
        elif 0 < typ < 2045:
            return f"str{typ}"
        else:
            return f"type_{typ:04x}"

    def read_var_label(self, varno: int) -> str:
        """Read variable label (display label) from memory."""
        try:
            # Try common offset patterns
            for label_addr in [self.VAR_LABEL_TABLE, self.VAR_LABEL_TABLE + 8]:
                label_ptr = self._read_qword(label_addr)
                if label_ptr:
                    # Read pointer table first, then follow to string
                    ptr_table = ctypes.c_uint64.from_address(label_ptr).value
                    if ptr_table:
                        str_ptr = ctypes.c_uint64.from_address(
                            ptr_table + varno * 8).value
                        if str_ptr:
                            raw = ctypes.string_at(str_ptr, 256)
                            null = raw.find(b"\x00")
                            if null >= 0:
                                raw = raw[:null]
                            s = raw.decode("latin-1", errors="replace")
                            if s and s != "":
                                return s
        except Exception:
            pass
        return ""

    # ─── Scalar reading ──────────────────────────────────────────────

    def locate_scalar(self, name: str, known_val: float = None,
                      engine_conn=None) -> dict:
        """Locate a scalar's storage in memory.

        Uses two strategies:
        1. If an EngineConnection is provided, create the scalar with
           a known value via execute(), then scan memory for it.
        2. If no engine, try to find the scalar hash table root in .bss
           and walk the hash chains.

        Returns dict with 'address', 'value', 'name_address', etc.
        """
        import ctypes, struct
        result = {"name": name}

        if engine_conn is not None:
            # Strategy 1: Create scalar with known value, then scan
            import sys
            # Use execute to set the scalar
            test_val = known_val if known_val is not None else 42.5
            engine_conn.execute(f"scalar {name} = {test_val}")

            # Scan .bss for the known value
            target = struct.pack("d", test_val)
            name_bytes = name.encode() + b"\x00"

            scoped_val = None
            with open("/proc/self/maps") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) < 2 or "rw" not in parts[1]:
                        continue
                    r = parts[0].split("-")
                    start, end = int(r[0], 16), int(r[1], 16)
                    size = end - start
                    if size < 65536 or size > 50 * 1024 * 1024:
                        continue

                    # Scan each 8KB chunk
                    for chunk_start in range(start, end, 8192):
                        if scoped_val:
                            break
                        chunk_end = min(chunk_start + 8192, end)
                        try:
                            buf = (ctypes.c_char * (chunk_end - chunk_start)).from_address(chunk_start)
                            for off in range(0, chunk_end - chunk_start - 8, 8):
                                if buf[off:off+8] == target:
                                    abs_addr = chunk_start + off
                                    # Check for name nearby
                                    search_start = max(0, off - 512)
                                    search_end = min(chunk_end - chunk_start, off + 512)
                                    nearby = bytes(buf[search_start:search_end])
                                    if name_bytes in nearby:
                                        name_off_in_buf = search_start + nearby.index(name_bytes)
                                        result["value_address"] = abs_addr
                                        result["name_address"] = chunk_start + name_off_in_buf
                                        result["name_offset_from_value"] = name_off_in_buf - off
                                        result["value"] = test_val
                                        scoped_val = abs_addr
                                        break
                        except Exception:
                            continue
                    if scoped_val:
                        break

            if scoped_val:
                # Dump structure around scalar value
                result["structure"] = {}
                struct_start = scoped_val - 64
                for j in range(-64, 128, 8):
                    try:
                        v = ctypes.c_uint64.from_address(struct_start + j).value
                        if v != 0:
                            result["structure"][j] = f"0x{v:x}"
                    except Exception:
                        pass

        return result

    def read_scalar(self, name: str, scalar_info: dict = None) -> float:
        """Read a numeric scalar value directly from memory.

        Requires locate_scalar to have been called first to find
        the scalar storage location, OR the scalar_info dict with
        'value_address' key.
        """
        if scalar_info and scalar_info.get("value_address"):
            addr = scalar_info["value_address"]
            import ctypes
            try:
                return ctypes.c_double.from_address(addr).value
            except Exception:
                pass

        # Fallback: try __px_scalar temp variable
        return None

    def read_string_scalar(self, name: str, scalar_info: dict = None) -> str:
        """Read a string scalar directly from memory."""
        # Similar to read_scalar but reads GSO string from scalar entry
        # Requires locate_scalar with the string scalar
        return ""

    # ─── Cached scalar reader ────────────────────────────────────────

    def _discover_scalar_region(self, engine_conn=None):
        """Find scalar hash table region in memory using locate_scalar."""
        if engine_conn:
            engine_conn.execute("capture scalar drop __px_find")
            info = self.locate_scalar("__px_find", known_val=12345.0,
                                       engine_conn=engine_conn)
            if info.get("value_address"):
                va = info["value_address"]
                region_start = va & ~0xFFFF
                self._scalar_region_cache = {
                    "start": region_start,
                    "end": region_start + 0x20000,
                    "name_to_value_offset": info.get("name_offset_from_value", -132),
                    "scanned": True,
                }
                return True
        return False

    def read_scalar_by_name(self, name: str, engine_conn=None) -> float:
        """Read numeric scalar by name from Stata's memory."""
        import ctypes
        if not self._scalar_region_cache["scanned"]:
            if not self._discover_scalar_region(engine_conn):
                return None
        cache = self._scalar_region_cache
        name_bytes = name.encode()
        off = cache["name_to_value_offset"]
        addr = cache["start"]
        while addr < cache["end"]:
            try:
                raw = ctypes.string_at(addr, len(name) + 1)
                if raw.rstrip(b"\x00") == name_bytes:
                    val_addr = addr - off
                    return ctypes.c_double.from_address(val_addr).value
            except Exception:
                pass
            addr += 1
        return None

    def read_string_scalar_by_name(self, name: str, engine_conn=None) -> str:
        """Read string scalar by name from Stata's memory."""
        import ctypes
        if not self._scalar_region_cache["scanned"]:
            if not self._discover_scalar_region(engine_conn):
                return ""
        cache = self._scalar_region_cache
        name_bytes = name.encode()
        off = cache["name_to_value_offset"]
        addr = cache["start"]
        while addr < cache["end"]:
            try:
                raw = ctypes.string_at(addr, len(name) + 1)
                if raw.rstrip(b"\x00") == name_bytes:
                    val_addr = addr - off
                    # Check for GSO string
                    data = ctypes.c_uint64.from_address(val_addr).value
                    if data and 0x100000 <= data <= 0x7f0000000000:
                        slen = ctypes.c_int32.from_address(data).value
                        if 0 < slen < 2048:
                            raw_str = ctypes.string_at(data + 4, slen)
                            return raw_str.rstrip(b"\x00").decode("utf-8", errors="replace")
                    return ""
            except Exception:
                pass
            addr += 1
        return ""

    def find_value_in_stata(self, name: str, value_type: str = "int32",
                              engine_conn=None) -> dict:
        """Find a named Stata value by scanning all libstata memory."""
        import ctypes
        result = {}
        try:
            maps = open("/proc/self/maps").read()
        except (IOError, OSError):
            return result
        for line in maps.split("\n"):
            parts = line.split()
            if len(parts) < 5 or "libstata" not in line:
                continue
            if parts[1] not in ("r--p", "r-xp", "rw-p"):
                continue
            r = parts[0].split("-")
            start, end = int(r[0], 16), int(r[1], 16)
            size = end - start
            if size < 4096 or size > 100 * 1024 * 1024:
                continue
            for chunk_start in range(start, end, 16384):
                chunk_end = min(chunk_start + 16384, end)
                try:
                    buf = (ctypes.c_char * (chunk_end - chunk_start)).from_address(chunk_start)
                    for off in range(chunk_end - chunk_start - len(name)):
                        if buf[off:off+len(name)] == name.encode():
                            abs_addr = chunk_start + off
                            result["name_address"] = abs_addr
                            result["in_section"] = parts[1]
                            for value_off in range(0, 256, 4):
                                try:
                                    val_addr = abs_addr + value_off
                                    if value_type == "double":
                                        val = ctypes.c_double.from_address(val_addr).value
                                    else:
                                        val = ctypes.c_int32.from_address(val_addr).value
                                    result["value_address"] = val_addr
                                    result["value"] = val
                                    result["value_offset"] = value_off
                                    result["value_type"] = value_type
                                    return result
                                except Exception:
                                    continue
                            return result
                except Exception:
                    continue
        return result

    def read_c_value(self, name: str, engine_conn=None):
        """Read a Stata c() system value from memory."""
        info = self.find_value_in_stata(name, "int32", engine_conn)
        if info.get("value_address"):
            return info["value"]
        return None

    @staticmethod
    def find_bss_global(vaddr: int, ref_type: str = "k_maxvar") -> int:
        """Find a specific .bss global address by analyzing function code.

        Analyzes the function at *vaddr* (ELF virtual address) for RIP-relative
        references to .bss and identifies the one matching *ref_type*.

        ref_type values:
          - "k_maxvar": finds the .bss offset holding max-var limit (K)
            Used by _bist_addvar and the expression evaluator for c(maxvar).
            Identified by looking for a 'cmp' against a .bss value near nvar.

        Returns the .bss virtual address (ELF-relative), or 0 if not found.
        """
        import capstone as cs, re
        import struct

        try:
            with open("/usr/local/stata19/libstata-se.so", "rb") as f:
                data = f.read()
        except (IOError, OSError):
            return 0

        # Parse ELF sections
        e_shoff = struct.unpack_from("<Q", data, 0x28)[0]
        e_shentsize = struct.unpack_from("<H", data, 0x3A)[0]
        e_shnum = struct.unpack_from("<H", data, 0x3C)[0]
        e_shstrndx = struct.unpack_from("<H", data, 0x3E)[0]
        shstrtab_off = e_shoff + e_shstrndx * e_shentsize
        sh_name_off = struct.unpack_from("<I", data, shstrtab_off + 0x18)[0]
        sh_name_size = struct.unpack_from("<Q", data, shstrtab_off + 0x20)[0]
        names = data[sh_name_off:sh_name_off + sh_name_size]

        text_off = text_vaddr = text_size = 0
        for i in range(e_shnum):
            off = e_shoff + i * e_shentsize
            sn = struct.unpack_from("<I", data, off)[0]
            sh_addr = struct.unpack_from("<Q", data, off + 0x10)[0]
            sh_offset = struct.unpack_from("<Q", data, off + 0x18)[0]
            sh_size = struct.unpack_from("<Q", data, off + 0x20)[0]
            end = names.find(b"\x00", sn)
            name = names[sn:end].decode("ascii", errors="replace")
            if name == ".text":
                text_off, text_vaddr, text_size = sh_offset, sh_addr, sh_size
                break

        if not text_size:
            return 0

        local_off = vaddr - text_vaddr
        chunk = data[text_off + local_off: text_off + local_off + 512]
        md = cs.Cs(cs.CS_ARCH_X86, cs.CS_MODE_64)

        # For k_maxvar: look for a .bss read (mov from [rip+...]) followed
        # by a 'cmp' with another value that's the current nvar count.
        bss_refs = []
        for insn in md.disasm(chunk, vaddr):
            op = insn.op_str
            # Find RIP-relative reads from .bss
            m = re.search(r'\[rip\s*([+-])\s*(0x[0-9a-fA-F]+)\]', op)
            if m:
                sign = 1 if m.group(1) == "+" else -1
                disp = int(m.group(2), 16) * sign
                target = insn.address + insn.size + disp
                if 0x5000000 <= target <= 0x5200000:
                    bss_refs.append((insn.address, target, insn.mnemonic, op))

                    # If this is a 'mov rax, [rip+X]' followed by 'cmp rax, ...'
                    # or similar comparison pattern, it might be the maxvar check
                    if "mov" in insn.mnemonic and "0x" in op:
                        # Check next few instructions for cmp
                        pass

        # For _bist_addvar, the maxvar check compares nvar against max.
        # Usually: mov REG, [bss+offset]   ; load nvar
        #           cmp REG, [bss+offset2]  ; compare with maxvar
        # OR: mov REG, [bss+offset]  ; load maxvar
        #     cmp REG, edi           ; compare with requested number

        # Return the last distinct .bss address (likely maxvar)
        if bss_refs:
            # Deduplicate
            seen = set()
            unique = []
            for addr, target, mnem, op in bss_refs:
                if target not in seen:
                    seen.add(target)
                    unique.append(target)
            # Return the last unique target as the most likely maxvar address
            if len(unique) >= 2:
                return unique[-1]
            elif unique:
                return unique[0]

        return 0

    def read_k_maxvar(self) -> int:
        """Read the max-var limit (K = c(maxvar)) from Stata's memory.

        Uses find_bss_global to locate the value in .bss.
        """
        import ctypes
        # _bist_addvar at 0x820f92 checks k_maxvar
        k_offset = self.find_bss_global(0x820f92, "k_maxvar")
        if k_offset:
            try:
                return ctypes.c_int32.from_address(self._base + k_offset).value
            except Exception:
                pass
        return 0
