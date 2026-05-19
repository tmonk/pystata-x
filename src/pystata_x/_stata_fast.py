"""Minimal Python ctypes bindings for libstata_fast.

Wraps the C shared library into Python functions with zero code overhead
in the hot path.  Exposes ``init()`` and ``execute()`` matching the shape
of ``pystata_x._config.init()`` and ``_core.execute()`` but much faster
because all buffer management happens in C in a single ctypes call.
"""

# SPDX-FileCopyrightText: 2025 Thomas Monk <t.d.monk@lse.ac.uk>
# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import ctypes
import os
import platform
import sys
import tempfile
from ctypes import c_char_p, c_int, c_size_t, c_void_p, POINTER
from pathlib import Path

# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

_lib: ctypes.CDLL | None = None   # The loaded libstata_fast shared library
_ctx: ctypes.c_void_p | None = None  # Opaque C context handle
_loaded: bool = False              # True after stata_load completes
_engine_running: bool = False      # True after StataSO_Main (init engine) finishes
_bist_configured: bool = False     # True after setup_bist() succeeds

# BIST function slot IDs (must match C header)
# Double-returning
BIST_NOBS       = 0   # _bist_nobs (0 int args)
BIST_NVAR       = 1   # _bist_nvar (0 int args)
BIST_DATA       = 2   # _bist_data (2 int args: obs, var)
BIST_NUMSCALAR  = 3   # _bist_numscalar (1 str arg: name)
# String-returning
BIST_VARNAME    = 4   # _bist_varname (1 int arg: varno)
BIST_VARTYPE    = 5   # _bist_vartype (1 int arg: varno)
BIST_VARLABEL   = 6   # _bist_varlabel (1 int arg: varno)
BIST_VARFMT     = 7   # _bist_varformat (1 int arg: varno)
BIST_SDATA      = 8   # _bist_sdata (2 int args: obs, var)
BIST_GLOBAL     = 9   # _bist_global (1 str arg: name)
BIST_STRSCALAR  = 10  # _bist_strscalar (1 str arg: name)
# Store operations
BIST_STORE      = 11  # _bist_store (3 pushes: obs, var, double)
BIST_SSTORE     = 12  # _bist_sstore (3 pushes: obs, var, str)
# ValueLabel
BIST_VLMODIFY   = 13  # _bist_vlmodify_u
BIST_VLLOAD     = 14  # _bist_vlload
# Push helper functions
BIST_PUSHINT    = 30
BIST_PUSHDBL    = 31
BIST_PUSHSTR    = 32
# Other internal helpers
BIST_STSCALSAVE = 40
BIST_XGSO_NEWCP = 41
BIST_PUT_XGSO   = 42

# ---------------------------------------------------------------------------
# Load the C library
# ---------------------------------------------------------------------------

def _find_lib() -> str:
    """Locate libstata_fast.{dylib,so,dll} relative to this source file."""
    src_dir = Path(__file__).resolve().parent.parent.parent  # repo root
    stata_fast_dir = src_dir / "src" / "stata-fast"
    system = platform.system()
    if system == "Darwin":
        lib_name = "libstata_fast.dylib"
        build_dir = stata_fast_dir / "build"
    elif system == "Windows":
        lib_name = "stata_fast.dll"  # CMake produces no lib prefix on Windows
        build_dir = stata_fast_dir / "build"
    else:
        lib_name = "libstata_fast.so"
        build_dir = stata_fast_dir / "build"
    # Check direct source dir first, then CMake build dir, then build/Release (Windows)
    for d in [stata_fast_dir, build_dir, build_dir / "Release"]:
        candidate = d / lib_name
        if candidate.is_file():
            return str(candidate.resolve())
    # Fall back to PATH / LD_LIBRARY_PATH / DYLD_LIBRARY_PATH
    return lib_name


def _load_lib() -> ctypes.CDLL:
    """Load and configure libstata_fast ctypes bindings (idempotent)."""
    global _lib
    if _lib is not None:
        return _lib

    lib_path = _find_lib()
    try:
        _lib = ctypes.cdll.LoadLibrary(lib_path)
    except OSError as exc:
        raise OSError(
            f"Cannot load libstata_fast from {lib_path}\n"
            f"  Build it: cd src/stata-fast && make\n"
            f"  Original error: {exc}"
        ) from exc

    # ------ configure function signatures ------

    # int stata_execute(ctx, command, echo, &output, &out_len, &retcode)
    _lib.stata_execute.argtypes = [
        c_void_p,       # ctx
        c_char_p,       # command
        c_int,          # echo
        POINTER(c_char_p),  # &output (out)
        POINTER(c_size_t),  # &out_len (out)
        POINTER(c_int),     # &retcode (out)
    ]
    _lib.stata_execute.restype = c_int

    # char* stata_get_output(ctx)
    _lib.stata_get_output.argtypes = [c_void_p]
    _lib.stata_get_output.restype = c_char_p

    # void stata_clear_output(ctx)
    _lib.stata_clear_output.argtypes = [c_void_p]
    _lib.stata_clear_output.restype = None

    # int stata_set_break(ctx)
    _lib.stata_set_break.argtypes = [c_void_p]
    _lib.stata_set_break.restype = c_int

    # void stata_free(ptr)
    _lib.stata_free.argtypes = [c_char_p]
    _lib.stata_free.restype = None

    # const char* stata_last_error(ctx)
    _lib.stata_last_error.argtypes = [c_void_p]
    _lib.stata_last_error.restype = c_char_p

    # Combined init for backward compat
    _lib.stata_init.argtypes = [c_char_p, c_char_p, c_int]
    _lib.stata_init.restype = c_void_p

    # Separate load (dlopen only, no engine)
    _lib.stata_load.argtypes = [c_char_p, c_char_p]
    _lib.stata_load.restype = c_void_p

    # Init engine only (no dlopen)
    _lib.stata_init_engine.argtypes = [c_void_p, c_int]
    _lib.stata_init_engine.restype = c_int

    # --- Fast _bist_* call path bindings ---

    # bist_ctx_t* stata_bist_ctx_new(base, stack_off, err_off)
    _lib.stata_bist_ctx_new.argtypes = [ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64]
    _lib.stata_bist_ctx_new.restype = c_void_p

    # void stata_bist_ctx_free(ctx)
    _lib.stata_bist_ctx_free.argtypes = [c_void_p]
    _lib.stata_bist_ctx_free.restype = None

    # void stata_bist_configure(ctx, base_addr, stack_ptr_off, err_addr_off)
    _lib.stata_bist_configure.argtypes = [c_void_p, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64]
    _lib.stata_bist_configure.restype = None

    # int stata_bist_set_fn(ctx, slot_id, fn_addr)
    _lib.stata_bist_set_fn.argtypes = [c_void_p, c_int, c_void_p]
    _lib.stata_bist_set_fn.restype = c_int

    # double stata_bist_call_d0(ctx, slot_id) — 0 int args, returns double
    _lib.stata_bist_call_d0.argtypes = [c_void_p, c_int]
    _lib.stata_bist_call_d0.restype = ctypes.c_double

    # double stata_bist_call_d1i(ctx, slot_id, arg1)
    _lib.stata_bist_call_d1i.argtypes = [c_void_p, c_int, ctypes.c_int64]
    _lib.stata_bist_call_d1i.restype = ctypes.c_double

    # double stata_bist_call_d2i(ctx, slot_id, arg1, arg2)
    _lib.stata_bist_call_d2i.argtypes = [c_void_p, c_int, ctypes.c_int64, ctypes.c_int64]
    _lib.stata_bist_call_d2i.restype = ctypes.c_double

    # double stata_bist_call_d1s(ctx, slot_id, str_arg)
    _lib.stata_bist_call_d1s.argtypes = [c_void_p, c_int, c_char_p]
    _lib.stata_bist_call_d1s.restype = ctypes.c_double

    # char* stata_bist_call_s0(ctx, slot_id) — 0 int args, returns string
    _lib.stata_bist_call_s0.argtypes = [c_void_p, c_int]
    _lib.stata_bist_call_s0.restype = c_char_p

    # char* stata_bist_call_s1i(ctx, slot_id, arg1)
    _lib.stata_bist_call_s1i.argtypes = [c_void_p, c_int, ctypes.c_int64]
    _lib.stata_bist_call_s1i.restype = c_char_p

    # char* stata_bist_call_s2i(ctx, slot_id, arg1, arg2)
    _lib.stata_bist_call_s2i.argtypes = [c_void_p, c_int, ctypes.c_int64, ctypes.c_int64]
    _lib.stata_bist_call_s2i.restype = c_char_p

    # char* stata_bist_call_s1s(ctx, slot_id, str_arg)
    _lib.stata_bist_call_s1s.argtypes = [c_void_p, c_int, c_char_p]
    _lib.stata_bist_call_s1s.restype = c_char_p

    # int stata_bist_store_double(ctx, slot_id, obs, var, val)
    _lib.stata_bist_store_double.argtypes = [
        c_void_p, c_int, ctypes.c_int64, ctypes.c_int64, ctypes.c_double]
    _lib.stata_bist_store_double.restype = c_int

    # int stata_bist_store_string(ctx, slot_id, obs, var, val)
    _lib.stata_bist_store_string.argtypes = [
        c_void_p, c_int, ctypes.c_int64, ctypes.c_int64, c_char_p]
    _lib.stata_bist_store_string.restype = c_int

    # Convenience wrappers (use internal slot IDs)
    _lib.stata_bist_get_nobs.argtypes = [c_void_p]
    _lib.stata_bist_get_nobs.restype = ctypes.c_double
    _lib.stata_bist_get_nvar.argtypes = [c_void_p]
    _lib.stata_bist_get_nvar.restype = ctypes.c_double
    _lib.stata_bist_get_vartype.argtypes = [c_void_p, c_int]
    _lib.stata_bist_get_vartype.restype = c_char_p
    _lib.stata_bist_get_varname.argtypes = [c_void_p, c_int]
    _lib.stata_bist_get_varname.restype = c_char_p
    _lib.stata_bist_get_varlabel.argtypes = [c_void_p, c_int]
    _lib.stata_bist_get_varlabel.restype = c_char_p
    _lib.stata_bist_get_varfmt.argtypes = [c_void_p, c_int]
    _lib.stata_bist_get_varfmt.restype = c_char_p
    _lib.stata_bist_get_double.argtypes = [c_void_p, c_int, c_int]
    _lib.stata_bist_get_double.restype = ctypes.c_double
    _lib.stata_bist_get_string.argtypes = [c_void_p, c_int, c_int]
    _lib.stata_bist_get_string.restype = c_char_p
    _lib.stata_bist_get_macro.argtypes = [c_void_p, c_char_p]
    _lib.stata_bist_get_macro.restype = c_char_p
    _lib.stata_bist_get_scalar.argtypes = [c_void_p, c_char_p]
    _lib.stata_bist_get_scalar.restype = ctypes.c_double
    _lib.stata_bist_get_scalar_str.argtypes = [c_void_p, c_char_p]
    _lib.stata_bist_get_scalar_str.restype = c_char_p
    _lib.stata_bist_store.argtypes = [c_void_p, c_int, c_int, ctypes.c_double]
    _lib.stata_bist_store.restype = c_int
    _lib.stata_bist_sstore.argtypes = [c_void_p, c_int, c_int, c_char_p]
    _lib.stata_bist_sstore.restype = c_int

    return _lib


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load(st_path: str, edition: str = "se") -> None:
    """Pre-load libstata (dlopen + dlsym).  Call before :func:`init`
    for minimal init latency (~9 ms vs ~20 ms combined)."""
    global _ctx, _loaded, _engine_running
    if _loaded:
        return
    lib = _load_lib()
    os.environ.setdefault("SYSDIR_STATA", st_path)
    _ctx = lib.stata_load(st_path.encode("utf-8"), edition.encode("utf-8"))
    if not _ctx:
        err = lib.stata_last_error(None) or "unknown error"
        raise RuntimeError(f"stata_load failed: {err}")
    _loaded = True
    _engine_running = False  # Engine not yet started


def init(st_path: str, edition: str = "se", splash: bool = False) -> None:
    """Initialise Stata engine.

    If :func:`load` was called first, only StataSO_Main runs (~9 ms).
    Otherwise loads library first then inits engine (~20 ms total).
    """
    global _ctx, _loaded, _engine_running
    if _engine_running:
        return

    lib = _load_lib()
    os.environ.setdefault("SYSDIR_STATA", st_path)

    system = platform.system()
    if system == "Darwin":
        if not os.path.isdir(st_path):
            raise OSError(f"Stata root not found: {st_path}")
    elif system == "Windows":
        # Accept both forward and backslash paths
        norm_path = os.path.normpath(st_path)
        if not os.path.isdir(norm_path):
            raise OSError(f"Stata root not found: {norm_path}")
    # Linux: don't check here (path may be a library-symlink dir, not a dir)

    if _loaded:
        # Library already loaded — only init engine
        rc = lib.stata_init_engine(_ctx, 1 if splash else 0)
        if rc != 0:
            err = lib.stata_last_error(_ctx) or f"stata_init_engine failed rc={rc}"
            raise RuntimeError(err)
    else:
        # Combined load + init
        _ctx = lib.stata_init(
            st_path.encode("utf-8"),
            edition.encode("utf-8"),
            1 if splash else 0,
        )
        if not _ctx:
            err = lib.stata_last_error(None) or "unknown error"
            raise RuntimeError(f"stata_init failed: {err}")
        _loaded = True
    _engine_running = True


def setup_bist(
    base_addr: int | None = None,
    stack_ptr_off: int | None = None,
    err_addr_off: int | None = None,
    syms: dict | None = None,
) -> bool:
    """Configure the C-level fast _bist_* call path.

    Must be called after the Stata engine is initialised (via either
    :func:`init()` in this module or the standard ``config()`` flow).

    Parameters
    ----------
    base_addr : int, optional
        Runtime base address of libstata.  If None, read from
        ``_engine._BASE`` at call time.
    stack_ptr_off : int, optional
        Stack pointer offset.  If None, read from
        ``_engine._STACK_PTR_OFFSET``.
    err_addr_off : int, optional
        Error address offset.  If None, read from
        ``_engine._ERR_ADDR_RELATIVE``.
    syms : dict, optional
        Manifest symbol table.  If None, read from
        ``_engine._SYMS``.

    Returns
    -------
    bool
        True if configuration succeeded and fast path is available.
    """
    global _ctx, _loaded, _bist_configured
    _bist_configured = False

    # Resolve parameters from engine module if not provided
    if base_addr is None or stack_ptr_off is None or err_addr_off is None or syms is None:
        try:
            from pystata_x.sfi import _engine as _eng
            if base_addr is None:
                base_addr = _eng._BASE
            if stack_ptr_off is None:
                stack_ptr_off = _eng._STACK_PTR_OFFSET
            if err_addr_off is None:
                err_addr_off = _eng._ERR_ADDR_RELATIVE
            if syms is None:
                syms = _eng._SYMS
        except ImportError:
            return False

    # Load C extension if not already loaded
    lib = _load_lib()

    # Create a bist-only C context if we don't have a full stata_ctx.
    # This happens when called from _engine.initialize() after the
    # standard config() flow (which doesn't use _stata_fast).
    if _ctx is None:
        _ctx = lib.stata_bist_ctx_new(base_addr, stack_ptr_off, err_addr_off)
        if not _ctx:
            return False
        _loaded = True

    # Configure base/offsets
    lib.stata_bist_configure(_ctx, base_addr, stack_ptr_off, err_addr_off)

    # Slot ID -> symbol name mapping
    # Only symbols that exist in the shipped manifest are included.
    # Incorrect names cause silent NULL pointers and wrong results.
    slot_map = {
        # Double-returning
        BIST_NOBS: "_bist_nobs",
        BIST_NVAR: "_bist_nvar",
        BIST_DATA: "_bist_data",
        BIST_NUMSCALAR: "_bist_numscalar",
        # String-returning
        BIST_VARNAME: "_bist_varname",
        BIST_VARTYPE: "_bist_vartype",
        BIST_VARLABEL: "_bist_varlabel",
        BIST_VARFMT: "_bist_varformat",
        BIST_SDATA: "_bist_sdata",
        BIST_GLOBAL: "_bist_global",
        BIST_STRSCALAR: "_bist_strscalar",
        # Store operations
        BIST_STORE: "_bist_store",
        BIST_SSTORE: "_bist_sstore",
        # ValueLabel
        BIST_VLLOAD: "_bist_vlload",
        # Push helper functions (always present)
        BIST_PUSHINT: "_pushint",
        BIST_PUSHDBL: "_pushdbl",
        BIST_PUSHSTR: "_pushstr",
        # Internal helpers (may be absent; fallback handles it)
        BIST_STSCALSAVE: "_stscalsave",
        BIST_XGSO_NEWCP: "_xgso_newcp_fast_code",
        BIST_PUT_XGSO: "_put_xgso_scalar",
    }

    # Register each function address
    for slot_id, sym_name in slot_map.items():
        vmaddr = syms.get(sym_name)
        if vmaddr is None:
            continue
        fn_addr = base_addr + vmaddr
        rc = lib.stata_bist_set_fn(_ctx, slot_id, ctypes.c_void_p(fn_addr))
        if rc != 0:
            return False

    _bist_configured = True
    return True


def _ensure_ctx():
    if _ctx is None:
        raise RuntimeError("Stata not initialised. Call init() first.")
    return _ctx


# Temp do-file for multi-line commands (same approach as _core.py)
_STATA_TEMP_DO = os.path.join(
    tempfile.gettempdir(), "_pystata_x_fast_temp.do"
)
_STATA_TEMP_FD: int | None = None


def _ensure_temp_fd() -> int:
    global _STATA_TEMP_FD
    if _STATA_TEMP_FD is None:
        _STATA_TEMP_FD = os.open(
            _STATA_TEMP_DO,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644
        )
    return _STATA_TEMP_FD


def _write_temp_do(code: str) -> None:
    """Overwrite temp do-file with *code*, reusing fd."""
    fd = _ensure_temp_fd()
    bdata = code.encode("utf-8")
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, bdata)


def execute(
    command: str,
    echo: bool = False,
    capture: bool = True,
) -> tuple[str, int]:
    """Execute a Stata command via libstata_fast — one ctypes call.

    Parameters
    ----------
    command : str
        Stata command.  Multi-line commands are automatically written
        to a temp do-file and ``include``-d (same approach as _core.py).
    echo : bool
        If True, echo the command in output.
    capture : bool
        If False, skip reading the output buffer.

    Returns
    -------
    tuple[str, int]
        ``(output_string, return_code)`` — both from the single C call.
        Output is stripped (leading/trailing whitespace removed).
    """
    ctx = _ensure_ctx()
    lib = _load_lib()

    # Handle multi-line: write to temp do-file and include
    if "\n" in command:
        _write_temp_do(command)
        # Ensure showcommand matches echo setting
        if echo:
            lib.stata_execute(ctx, b"set showcommand on", 0, None, None, None)
        else:
            lib.stata_execute(ctx, b"set showcommand off", 0, None, None, None)
        include_cmd = f'include "{_STATA_TEMP_DO}"'
        cmd_bytes = include_cmd.encode("utf-8")
    else:
        cmd_bytes = command.encode("utf-8")

    # Prepare output pointers
    out_ptr = c_char_p()
    out_len = c_size_t()
    rc = c_int()

    err = lib.stata_execute(
        ctx,
        cmd_bytes,
        1 if echo else 0,
        ctypes.byref(out_ptr) if capture else None,
        ctypes.byref(out_len) if capture else None,
        ctypes.byref(rc),
    )
    if err != 0:
        raise RuntimeError(f"stata_execute failed (err={err})")

    output = ""
    if capture and out_ptr.value:
        try:
            output = out_ptr.value.decode("utf-8", errors="replace").strip()
        finally:
            lib.stata_free(out_ptr)

    return output, rc.value


def get_output() -> str:
    """Drain and return the current Stata output buffer."""
    ctx = _ensure_ctx()
    lib = _load_lib()
    raw = lib.stata_get_output(ctx)
    if not raw:
        return ""
    result = raw.decode("utf-8", errors="replace")
    lib.stata_free(raw)
    return result


def clear_output() -> None:
    """Clear the Stata output buffer."""
    ctx = _ensure_ctx()
    lib = _load_lib()
    lib.stata_clear_output(ctx)


def set_break() -> None:
    """Interrupt any running Stata command."""
    ctx = _ensure_ctx()
    lib = _load_lib()
    lib.stata_set_break(ctx)


def shutdown() -> None:
    """Shut down the Stata engine.

    Note: this typically terminates the current process (StataSO_Shutdown
    may call exit()).  After calling this, no further Stata operations
    are possible.
    """
    global _ctx
    if _ctx is None:
        return
    # We don't have a separate shutdown in libstata_fast (the C library
    # calls StataSO_Shutdown which often calls exit()).  Instead, just
    # clear the context so subsequent calls raise RuntimeError.
    _ctx = None


# ---------------------------------------------------------------------------
# Fast _bist_* path — Python convenience wrappers
# ---------------------------------------------------------------------------
# These call into the C extension directly, bypassing the Python ctypes
# CFUNCTYPE and ARM64 push/stack cycle.  Each function is a single
# ctypes call into C where the push/stack cycle runs at native speed.
#
# They require _ctx to be set and _bist_configured to be True.
# The SFI classes in _core.py use these when available, falling back to
# the Python _engine.call_* path otherwise.


def _ensure_bist():
    """Ensure the fast bist path is available. Raises RuntimeError if not."""
    if _ctx is None:
        raise RuntimeError("Stata not initialised. Call init() first.")
    if not _bist_configured:
        raise RuntimeError("Bist fast path not configured. Call setup_bist() first.")
    return _ctx


def get_nobs() -> float:
    ctx = _ensure_bist()
    return _lib.stata_bist_get_nobs(ctx)


def get_nvar() -> float:
    ctx = _ensure_bist()
    return _lib.stata_bist_get_nvar(ctx)


def get_vartype(varno: int) -> str:
    ctx = _ensure_bist()
    raw = _lib.stata_bist_get_vartype(ctx, varno)
    if raw is None:
        return ""
    return raw.decode("utf-8", errors="replace")


def get_varname(varno: int) -> str:
    ctx = _ensure_bist()
    raw = _lib.stata_bist_get_varname(ctx, varno)
    if raw is None:
        return ""
    return raw.decode("utf-8", errors="replace")


def get_varlabel(varno: int) -> str:
    ctx = _ensure_bist()
    raw = _lib.stata_bist_get_varlabel(ctx, varno)
    if raw is None:
        return ""
    return raw.decode("utf-8", errors="replace")


def get_varfmt(varno: int) -> str:
    ctx = _ensure_bist()
    raw = _lib.stata_bist_get_varfmt(ctx, varno)
    if raw is None:
        return ""
    return raw.decode("utf-8", errors="replace")


def get_double(obs: int, var: int) -> float:
    ctx = _ensure_bist()
    return _lib.stata_bist_get_double(ctx, obs, var)


def get_string(obs: int, var: int) -> str:
    ctx = _ensure_bist()
    raw = _lib.stata_bist_get_string(ctx, obs, var)
    if raw is None:
        return ""
    return raw.decode("utf-8", errors="replace")


def get_macro(name: str) -> str:
    ctx = _ensure_bist()
    raw = _lib.stata_bist_get_macro(ctx, name.encode("utf-8"))
    if raw is None:
        return ""
    return raw.decode("utf-8", errors="replace")


def get_scalar(name: str) -> float:
    ctx = _ensure_bist()
    return _lib.stata_bist_get_scalar(ctx, name.encode("utf-8"))


def get_scalar_str(name: str) -> str:
    ctx = _ensure_bist()
    raw = _lib.stata_bist_get_scalar_str(ctx, name.encode("utf-8"))
    if raw is None:
        return ""
    return raw.decode("utf-8", errors="replace")


def store(obs: int, var: int, val: float) -> int:
    """Store a double value at (obs, var). Returns error code (0=OK)."""
    ctx = _ensure_bist()
    return _lib.stata_bist_store(ctx, obs, var, val)


def sstore(obs: int, var: int, val: str) -> int:
    """Store a string value at (obs, var). Returns error code (0=OK)."""
    ctx = _ensure_bist()
    return _lib.stata_bist_sstore(ctx, obs, var, val.encode("utf-8"))


def last_error() -> str:
    """Return the last error message from the C library."""
    lib = _load_lib()
    raw = lib.stata_last_error(_ctx)
    return raw.decode("utf-8", errors="replace") if raw else ""
