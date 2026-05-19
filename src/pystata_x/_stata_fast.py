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

    return _lib


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load(st_path: str, edition: str = "se") -> None:
    """Pre-load libstata (dlopen + dlsym).  Call before :func:`init`
    for minimal init latency (~9 ms vs ~20 ms combined)."""
    global _ctx, _loaded
    if _loaded:
        return
    lib = _load_lib()
    os.environ.setdefault("SYSDIR_STATA", st_path)
    _ctx = lib.stata_load(st_path.encode("utf-8"), edition.encode("utf-8"))
    if not _ctx:
        err = lib.stata_last_error(None) or "unknown error"
        raise RuntimeError(f"stata_load failed: {err}")
    _loaded = True


def init(st_path: str, edition: str = "se", splash: bool = False) -> None:
    """Initialise Stata engine.

    If :func:`load` was called first, only StataSO_Main runs (~9 ms).
    Otherwise loads library first then inits engine (~20 ms total).
    """
    global _ctx, _loaded
    if _ctx is not None:
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


def last_error() -> str:
    """Return the last error message from the C library."""
    lib = _load_lib()
    raw = lib.stata_last_error(_ctx)
    return raw.decode("utf-8", errors="replace") if raw else ""
