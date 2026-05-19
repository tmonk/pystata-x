"""_engine — Low-level Stata engine wrapper with direct _bist_ C function calls.

Architecture
------------
On ARM64 macOS, ALL _bist_* functions use Stata's proprietary internal calling
convention (NOT the standard ARM64 AAPCS64 ABI).  They read arguments from and
push results to Stata's internal expression stack rather than using registers.

Confirmed by disassembly analysis and empirical testing (2026-05-19):
  - _bist_nobs reads obs count from internal memory (0x39c7000+0xf7c),
    converts to double, and pushes result via _pushdbl.  Ignores w0.
  - _bist_global checks w0 as mode flag: 0=skip/return, 1=execute.
    Reads macro name pointer from internal stack, pushes result as tsmat.
  - _bist_varname checks w0 == 2 for pop-2 mode, reads 1 arg from stack
    otherwise.  Pushes string result as length-prefixed tsmat.
  - _bist_data checks w0 == 2 for alternate pop, always reads 2 args
    from stack (obs, var), pushes double result.
  - Direct CFUNCTYPE(c_int) calls do NOT crash but the w0 return value
    is UNPREDICTABLE leftover register content, not the function's result.

Therefore on ARM64 we MUST use the push+stack+pop pattern for ALL _bist_*:
  1. Push arguments via _pushint / _pushdbl / _pushstr (these DO use std ARM64 ABI).
  2. Call _bist_* via CFUNCTYPE(None) — no register args.
  3. Read result from Stata's internal stack (SP at 0x39b7000+0x108).
     - For doubles/ints: tsmat[0] -> *(double*)data or *(int32*)data
     - For strings: *(char**)(tsmat[0]) -> [uint32 len][char data]
  4. Restore SP to pre-push value (consumes the result from Stata's stack).

Push function signatures (ALL standard ARM64 ABI, confirmed via disasm):
  _pushint(int val)          - val in w0, converts to double internally
  _pushdbl(double *val)      - POINTER to double in x0, NOT the value itself
  _pushstr(char *str, len)   - string ptr in x0, length in x1

_bi_st_* Calling Convention (cracked 2026-05-19):
  The _bi_st_* function family (_bi_st_strlpart, _bi_st_unab, _bi_st_addalias)
  uses the SAME push+stack convention as _bist_*, but with a critical
  difference in argument typing:
    - _pushint() creates tsmats with type=0 at offset +0x34
    - _pushstr() creates tsmats with type=-3 (0xfffd) at offset +0x34
    - _bi_st_* functions REQUIRE type=-3 for their FIRST argument
  
  Rule: The first arg to any _bi_st_* function MUST be pushed via _pushstr().
  Example (_bi_st_strlpart):
    _pushstr(var_name)       # arg1: variable name (type=-3 tsmat)
    _pushint(obs_1based)     # arg2: observation
    _pushint(part)           # arg3: byte count
    CFUNCTYPE(None)(w0=3)    # call with 3 args
    # Result written IN-PLACE into the string tsmat (modifies buffer)

  See docs/bi_st_analysis.md for full tsmat structure and function catalog.

On x86_64 Linux, _bist_* functions use standard SysV ABI (arguments in
rdi/rsi/rdx, return in rax/xmm0), so CFUNCTYPE works directly.
On Windows x86_64, standard Microsoft x64 ABI (rcx/rdx/r8/r9).

Internal stack layout (tsmat):
  After a _bist_* call, *(uint64_t*)SP points to a tsmat structure.
  For numeric results:
    tsmat[0]  ->  double value (8 bytes)
  For string results:
    tsmat[0]  ->  struct { uint32 len; char data[len]; }
    The string is at *(char**)tsmat[0] + 4, length is *(uint32*)*(char**)tsmat[0].

Cell Read Convention (ARM64, confirmed 2026-05-19):
  _bist_data(obs, var) and _bist_sdata(obs, var) both use 1-based
  observation AND variable indexing on ARM64.  The tsmat from _pushint
  stores the int at tsmat[0x28]=1 (data slot ID), and _bist_data uses
  _no_of_vars to count entities from the var tsmat.  Because _pushint
  sets tsmat[0x28]=1, _no_of_vars returns 1, and _bidata_u is called
  with nvars=1.  The actual obs/var indices come from the tsf (tsmat
  structure) data pointer, which in _pushint points to the double value.

  Therefore Python callers must pass (obs+1, var+1) for compatibility
  with the 1-based internal convention.

Symbol Discovery
----------------
1. Ship a pre-computed manifest.json keyed by SHA256 of the binary.
2. At init: hash the loaded library -> look up in manifest -> use addresses.
3. Fallback: parse the binary dynamically via _manifest.discover_symbols().
"""
import ctypes
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Optional

_LIB: Optional[ctypes.CDLL] = None
_BASE: int = 0
_INITIALIZED: bool = False

# Push function pointers (ARM64 only, init'd during _arm64_setup)
_pushint_fn: Optional[ctypes._CFuncPtr] = None
_pushdbl_fn: Optional[ctypes._CFuncPtr] = None
_pushstr_fn: Optional[ctypes._CFuncPtr] = None

# Load manifest (pre-computed symbol table, keyed by file hash)
_MANIFEST: dict = {}
_HERE = Path(__file__).parent
_manifest_path = _HERE / "manifest.json"
if _manifest_path.exists():
    with open(_manifest_path) as _f:
        _MANIFEST = json.load(_f)
_SYMS: dict = _MANIFEST.get("symbols", {})

# Stata internal stack pointer offset
# _pushdbl at 0x56bb5c does: adrp x8, 0x39b7000; add x8, x8, #0x108
_STACK_PTR_OFFSET: int = 0x39b7000 + 0x108


# ─── Public helpers ────────────────────────────────────────────────


def _find_lib() -> str:
    """Locate libstata-se.  Override via STATA_LIB_PATH env var."""
    if "STATA_LIB_PATH" in os.environ:
        p = os.environ["STATA_LIB_PATH"]
        if os.path.exists(p):
            return p
    if sys.platform == "darwin":
        candidates = [
            "/Applications/StataNow/StataSE.app/Contents/MacOS/libstata-se.dylib",
            "/Applications/Stata/StataSE.app/Contents/MacOS/libstata-se.dylib",
        ]
    elif sys.platform in ("linux", "linux2"):
        candidates = ["/usr/local/stata19/libstata-se.so"]
    elif sys.platform == "win32":
        candidates = ["C:\\Program Files\\StataNow\\libstata-se.dll"]
    else:
        candidates = []
    for p in candidates:
        if os.path.exists(p):
            return p
    raise FileNotFoundError(f"libstata not found. Set STATA_LIB_PATH")


def _check_platform() -> str:
    """Return platform key: 'arm64', 'x86_64', or 'windows'."""
    if sys.platform == "darwin":
        return "arm64"  # macOS on Apple Silicon
    elif sys.platform in ("linux", "linux2"):
        return "x86_64"
    elif sys.platform == "win32":
        return "windows"
    return sys.platform


_PLATFORM: str = _check_platform()


def _file_sha256(path: str) -> str:
    """Compute SHA256 of a file."""
    h = hashlib.sha256()
    with open(path, "rb", buffering=1048576) as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _ensure_symbols(lib_path: str) -> None:
    """Ensure _SYMS is populated.  Tries manifest by hash, then dynamic parsing."""
    global _SYMS, _MANIFEST
    if _SYMS:
        return

    # Try manifest by hash
    fhash = _file_sha256(lib_path)
    if _MANIFEST.get("sha256") == fhash:
        _SYMS = _MANIFEST.get("symbols", {})
        if _SYMS:
            return

    # Fallback: dynamic binary parsing (works with hash mismatch too)
    try:
        from pystata_x.sfi._manifest import discover_symbols, filter_bist_symbols

        all_syms = discover_symbols(lib_path)
        _SYMS = filter_bist_symbols(all_syms)
    except Exception as exc:
        raise RuntimeError(
            f"Cannot discover symbol table in {lib_path}: {exc}"
        ) from exc


def _sym_addr(name: str) -> Optional[int]:
    """Get vmaddr of a symbol from the manifest."""
    return _SYMS.get(name) if _SYMS else None


# ─── ARM64 push function setup ─────────────────────────────────────


def _arm64_setup_push_fns():
    """Initialize ARM64 push function pointers from manifest symbols.

    Must be called after _BASE is computed.
    Push functions use STANDARD ARM64 ABI (confirmed via disassembly):
      _pushint(int)  ->  w0 = value
      _pushdbl(double*) ->  x0 = pointer to double
      _pushstr(char*, size_t) ->  x0 = string ptr, x1 = length
    """
    global _pushint_fn, _pushdbl_fn, _pushstr_fn
    if _pushint_fn is not None:
        return
    pushint_vm = _sym_addr("_pushint")
    pushdbl_vm = _sym_addr("_pushdbl")
    pushstr_vm = _sym_addr("_pushstr")
    if pushint_vm is not None:
        _pushint_fn = ctypes.cast(
            _BASE + pushint_vm,
            ctypes.CFUNCTYPE(None, ctypes.c_int),
        )
    if pushdbl_vm is not None:
        _pushdbl_fn = ctypes.cast(
            _BASE + pushdbl_vm,
            ctypes.CFUNCTYPE(None, ctypes.c_void_p),
        )
    if pushstr_vm is not None:
        _pushstr_fn = ctypes.cast(
            _BASE + pushstr_vm,
            ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_size_t),
        )


# ─── ARM64 internal stack helpers ──────────────────────────────────


def _stack_ptr_addr() -> int:
    """Return the runtime address of Stata's internal stack pointer storage."""
    return _BASE + _STACK_PTR_OFFSET


def _save_sp() -> int:
    """Read current Stata stack pointer value."""
    return ctypes.c_uint64.from_address(_stack_ptr_addr()).value


def _restore_sp(sp_val: int) -> None:
    """Restore Stata stack pointer to a previous value."""
    ctypes.c_uint64.from_address(_stack_ptr_addr()).value = sp_val


def _arm64_push_int(val: int) -> None:
    """Push an int argument onto Stata's internal stack (ARM64)."""
    _pushint_fn(val)


def _arm64_push_double(val: float) -> None:
    """Push a double argument onto Stata's internal stack (ARM64).

    _pushdbl takes a POINTER to the double value in x0, not the value itself.
    We create a ctypes buffer and pass its address.
    """
    buf = ctypes.c_double(val)
    _pushdbl_fn(ctypes.addressof(buf))


def _arm64_push_str(s: bytes) -> None:
    """Push a string argument onto Stata's internal stack (ARM64).

    _pushstr takes (char* str, size_t len) in x0, x1.
    """
    _pushstr_fn(s, len(s))


def _arm64_pop_and_read_double(sp_before: int) -> Optional[float]:
    """After an ARM64 _bist_* call, read the double result from
    Stata's internal stack and restore SP."""
    sp = _save_sp()
    try:
        tsmat = ctypes.c_uint64.from_address(sp).value
        if not tsmat:
            return None
        data_buf = ctypes.c_uint64.from_address(tsmat).value
        if not data_buf:
            return None
        return ctypes.c_double.from_address(data_buf).value
    finally:
        _restore_sp(sp_before)


def _arm64_pop_and_read_int(sp_before: int) -> Optional[int]:
    """After an ARM64 _bist_* call, read the int result from
    Stata's internal stack and restore SP.

    NOTE: _bist_* functions push int results as DOUBLE values
    (via _pushint which does scvtf to convert int to double,
    then calls _m_mktsmatsto).  tsmat[0] points to a double.
    We read the double and cast to int."""
    sp = _save_sp()
    try:
        tsmat = ctypes.c_uint64.from_address(sp).value
        if not tsmat:
            return None
        data_buf = ctypes.c_uint64.from_address(tsmat).value
        if not data_buf:
            return None
        return int(ctypes.c_double.from_address(data_buf).value)
    finally:
        _restore_sp(sp_before)


def _arm64_pop_and_read_string(sp_before: int) -> Optional[str]:
    """After an ARM64 _bist_* call, read the string result from
    Stata's internal stack and restore SP.

    String format (confirmed empirically):
      *(char**)tsmat[0] points to a struct:
        +0: uint32 length (includes null terminator)
        +4: char data[length]
    """
    sp = _save_sp()
    try:
        tsmat = ctypes.c_uint64.from_address(sp).value
        if not tsmat:
            return None
        data_buf = ctypes.c_uint64.from_address(tsmat).value
        if not data_buf:
            return None
        str_ptr = ctypes.c_uint64.from_address(data_buf).value
        if not str_ptr:
            return None
        slen = ctypes.c_uint32.from_address(str_ptr).value
        if slen == 0:
            return ""
        raw = ctypes.string_at(ctypes.c_void_p(str_ptr + 4), slen)
        # Remove trailing null bytes
        return raw.rstrip(b"\x00").decode("utf-8", errors="replace")
    finally:
        _restore_sp(sp_before)


# ─── Initialization ────────────────────────────────────────────────


def initialize():
    """Load libstata, init engine, populate symbols, init ARM64 push fns.

    If the _config module has already initialised Stata, this reuses the
    existing library handle.  Otherwise loads and initialises the library
    itself (without -pyexec, suitable for standalone use).

    The engine is initialised WITHOUT the -pyexec flag, because we access
    Stata data through direct _bist_* C function calls, not through Stata's
    embedded Python.  This avoids Python-version compatibility issues
    (ast.FrameError was removed in Python 3.14) and startup overhead.
    """
    global _LIB, _BASE, _INITIALIZED

    if _INITIALIZED:
        return

    lib_path = _find_lib()

    # Check if Stata already loaded by _config module
    already_inited = False
    try:
        from pystata_x import _config as _pxc

        if _pxc.stinitialized and _pxc.stlib is not None:
            _LIB = _pxc.stlib
            already_inited = True
    except (ImportError, AttributeError):
        pass

    if _LIB is None:
        _LIB = ctypes.CDLL(lib_path)

    # Ensure symbol table is populated
    _ensure_symbols(lib_path)

    # Compute base address: _BASE = st_main - st_main_vmaddr
    main_vmaddr = _sym_addr("_StataSO_Main")
    if main_vmaddr is None:
        raise RuntimeError("_StataSO_Main not found in symbol table")
    st_main = ctypes.cast(_LIB.StataSO_Main, ctypes.c_void_p).value
    _BASE = st_main - main_vmaddr

    # Init engine if needed (no -pyexec!)
    if not already_inited:
        _LIB.StataSO_Main.restype = ctypes.c_int
        _LIB.StataSO_Main.argtypes = [
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_char_p),
        ]
        av = (ctypes.c_char_p * 2)(b"", None)
        ret = _LIB.StataSO_Main(1, av)
        if ret not in (0, 1):
            raise RuntimeError(f"StataSO_Main returned {ret}")

    # Set up output buffer and execute (needed for wrappers, not for _bist_*)
    _LIB.StataSO_SetOutputBufferSz.restype = None
    _LIB.StataSO_SetOutputBufferSz.argtypes = [ctypes.c_size_t]
    _LIB.StataSO_SetOutputBufferSz(65536)
    _LIB.StataSO_Execute.restype = ctypes.c_int
    _LIB.StataSO_Execute.argtypes = [ctypes.c_char_p]

    # Set up ARM64 push function pointers
    if _PLATFORM == "arm64":
        _arm64_setup_push_fns()
        # Warm up: push a dummy int so _bist_* functions that check
        # the internal stack have a valid entry to dereference.
        if _pushint_fn is not None:
            _pushint_fn(0)

    _INITIALIZED = True


# ─── Function callers ──────────────────────────────────────────────


def call_int(name: str, *args) -> Optional[int]:
    """Call a _bist_* function that returns an int (error code or index).

    On ARM64: push args to internal stack, call function, read from stack.
    On x86_64: direct CFUNCTYPE (standard SysV/Microsoft ABI).
    """
    if not _INITIALIZED:
        initialize()
    addr = _sym_addr(name)
    if addr is None:
        return None
    rt = _BASE + addr

    if _PLATFORM == "arm64":
        sp_before = _save_sp()
        _arm64_push_args(args)
        # Pass arg count as w0 (mode flag for _bist_* functions)
        w0 = len(args) if args else 0
        fn = ctypes.cast(rt, ctypes.CFUNCTYPE(None, ctypes.c_int))
        fn(w0)
        return _arm64_pop_and_read_int(sp_before)
    else:
        return _call_std_int(rt, args)


def call_double(name: str, *args) -> Optional[float]:
    """Call a _bist_* function that returns a double.

    On ARM64: push args to internal stack, call function, read from stack.
    On x86_64: direct CFUNCTYPE (standard SysV/Microsoft ABI).
    """
    if not _INITIALIZED:
        initialize()
    addr = _sym_addr(name)
    if addr is None:
        return None
    rt = _BASE + addr

    if _PLATFORM == "arm64":
        sp_before = _save_sp()
        _arm64_push_args(args)
        w0 = len(args) if args else 0
        fn = ctypes.cast(rt, ctypes.CFUNCTYPE(None, ctypes.c_int))
        fn(w0)
        return _arm64_pop_and_read_double(sp_before)
    else:
        return _call_std_double(rt, args)


def call_string(name: str, *args) -> Optional[str]:
    """Call a _bist_* function that returns a string.

    On ARM64: push args to internal stack, call function, read from stack.
    On x86_64: direct CFUNCTYPE (standard SysV/Microsoft ABI).
    """
    if not _INITIALIZED:
        initialize()
    addr = _sym_addr(name)
    if addr is None:
        return None
    rt = _BASE + addr

    if _PLATFORM == "arm64":
        sp_before = _save_sp()
        _arm64_push_args(args)
        w0 = len(args) if args else 0
        fn = ctypes.cast(rt, ctypes.CFUNCTYPE(None, ctypes.c_int))
        fn(w0)
        return _arm64_pop_and_read_string(sp_before)
    else:
        return _call_std_string(rt, args)


def call_void(name: str, *args) -> None:
    """Call a _bist_* function that doesn't return a meaningful value.
    On ARM64: push args to internal stack, call function.
    On x86_64: direct CFUNCTYPE (standard SysV/Microsoft ABI).
    """
    if not _INITIALIZED:
        initialize()
    addr = _sym_addr(name)
    if addr is None:
        return
    rt = _BASE + addr

    if _PLATFORM == "arm64":
        sp_before = _save_sp()
        _arm64_push_args(args)
        w0 = len(args) if args else 0
        fn = ctypes.cast(rt, ctypes.CFUNCTYPE(None, ctypes.c_int))
        fn(w0)
        _restore_sp(sp_before)
    else:
        _call_std_void(rt, args)


# ─── ARM64 argument pushing ────────────────────────────────────────


def _arm64_push_args(args: tuple) -> None:
    """Push function arguments onto Stata's internal stack.

    Each arg is pushed using the appropriate _push* function:
      int      -> _pushint(w0=val)
      bytes    -> _pushstr(x0=ptr, x1=len)
      float    -> _pushdbl(x0=&val)
    """
    if not args:
        return
    for a in args:
        if isinstance(a, int):
            _arm64_push_int(a)
        elif isinstance(a, bytes):
            _arm64_push_str(a)
        elif isinstance(a, float):
            _arm64_push_double(a)
        else:
            raise TypeError(f"Unsupported arg type: {type(a)}")


# ─── Standard ABI callers (x86_64 / Windows) ──────────────────────


def _cast_fn(rt, restype, *argtypes):
    """Cast a raw address to a CFUNCTYPE with given return and arg types."""
    return ctypes.cast(rt, ctypes.CFUNCTYPE(restype, *argtypes))


def _call_std_int(rt: int, args: tuple) -> Optional[int]:
    """Call _bist_* via standard ABI (int return in rax)."""
    if len(args) == 0:
        return _cast_fn(rt, ctypes.c_int)()
    elif len(args) == 1:
        if isinstance(args[0], int):
            return _cast_fn(rt, ctypes.c_int, ctypes.c_int)(args[0])
        elif isinstance(args[0], bytes):
            return _cast_fn(rt, ctypes.c_int, ctypes.c_char_p)(args[0])
    elif len(args) == 2:
        if isinstance(args[0], bytes) and isinstance(args[1], bytes):
            return _cast_fn(rt, ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p)(
                args[0], args[1]
            )
    raise TypeError(f"Unsupported args for call_int: {args}")


def _call_std_double(rt: int, args: tuple) -> Optional[float]:
    """Call _bist_* via standard ABI (double return in xmm0)."""
    if len(args) == 0:
        return _cast_fn(rt, ctypes.c_double)()
    elif len(args) == 1:
        if isinstance(args[0], bytes):
            return _cast_fn(rt, ctypes.c_double, ctypes.c_char_p)(args[0])
        elif isinstance(args[0], int):
            return _cast_fn(rt, ctypes.c_double, ctypes.c_int)(args[0])
    elif len(args) == 2:
        if isinstance(args[0], int) and isinstance(args[1], int):
            return _cast_fn(rt, ctypes.c_double, ctypes.c_int, ctypes.c_int)(
                args[0], args[1]
            )
    raise TypeError(f"Unsupported args for call_double: {args}")


def _call_std_string(rt: int, args: tuple) -> Optional[str]:
    """Call _bist_* via standard ABI (char* return in rax)."""
    if len(args) == 0:
        return _decode(_cast_fn(rt, ctypes.c_char_p)())
    elif len(args) == 1:
        if isinstance(args[0], bytes):
            return _decode(_cast_fn(rt, ctypes.c_char_p, ctypes.c_char_p)(args[0]))
        elif isinstance(args[0], int):
            return _decode(_cast_fn(rt, ctypes.c_char_p, ctypes.c_int)(args[0]))
    elif len(args) == 2:
        if isinstance(args[0], int) and isinstance(args[1], int):
            return _decode(
                _cast_fn(rt, ctypes.c_char_p, ctypes.c_int, ctypes.c_int)(
                    args[0], args[1]
                )
            )
    raise TypeError(f"Unsupported args for call_string: {args}")


def _call_std_void(rt: int, args: tuple) -> None:
    """Call _bist_* via standard ABI (void return)."""
    if len(args) == 0:
        ctypes.cast(rt, ctypes.CFUNCTYPE(None))()
    elif len(args) == 1:
        if isinstance(args[0], bytes):
            ctypes.cast(rt, ctypes.CFUNCTYPE(None, ctypes.c_char_p))(args[0])
        elif isinstance(args[0], int):
            ctypes.cast(rt, ctypes.CFUNCTYPE(None, ctypes.c_int))(args[0])
        elif isinstance(args[0], float):
            ctypes.cast(rt, ctypes.CFUNCTYPE(None, ctypes.c_double))(args[0])
    elif len(args) == 2:
        ctypes.cast(rt, ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_char_p))(
            args[0], args[1]
        )


def _decode(b: Optional[bytes]) -> Optional[str]:
    if b is None:
        return None
    return b.decode("utf-8", errors="replace")


# ─── Store / Write operations (ARM64 only) ─────────────────────────

# Error code location used by _bist_store, _bist_sstore, etc.
# _st_store_u writes to 0x39b7000 + 0x11c on error; on success it's 0.
_ERR_ADDR_RELATIVE: int = 0x39b7000 + 0x11c


def _read_stata_err() -> int:
    """Read Stata's internal error code from the global variable."""
    return ctypes.c_int32.from_address(_BASE + _ERR_ADDR_RELATIVE).value


def call_store_double(name: str, obs: int, var: int, val: float) -> int:
    """Call _bist_store to write a double value to a cell.

    On ARM64: push 3 args (obs, var, double*) via _pushint/_pushdbl, then
    call fn(3).  Return code is in the global error variable.

    On x86_64: direct CFUNCTYPE with (int, int, c_double).
    """
    if not _INITIALIZED:
        initialize()
    addr = _sym_addr(name)
    if addr is None:
        return -1
    rt = _BASE + addr

    if _PLATFORM == "arm64":
        sp_before = _save_sp()
        _arm64_push_int(obs)
        _arm64_push_int(var)
        # _pushdbl takes a double* — create a buffer and push its address
        _arm64_push_double(val)
        fn = ctypes.cast(rt, ctypes.CFUNCTYPE(None, ctypes.c_int))
        fn(3)
        rc = _read_stata_err()
        _restore_sp(sp_before)
        return rc
    else:
        fn = ctypes.cast(
            rt, ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_double)
        )
        return fn(obs, var, val)


def call_store_string(name: str, obs: int, var: int, val: bytes) -> int:
    """Call _bist_sstore to write a string value to a cell.

    On ARM64: push 3 args (obs, var, char*) via _pushint/_pushstr, then
    call fn(3).  Return code is in the global error variable.

    On x86_64: direct CFUNCTYPE with (int, int, c_char_p).
    """
    if not _INITIALIZED:
        initialize()
    addr = _sym_addr(name)
    if addr is None:
        return -1
    rt = _BASE + addr

    if _PLATFORM == "arm64":
        sp_before = _save_sp()
        _arm64_push_int(obs)
        _arm64_push_int(var)
        _arm64_push_str(val)
        fn = ctypes.cast(rt, ctypes.CFUNCTYPE(None, ctypes.c_int))
        fn(3)
        rc = _read_stata_err()
        _restore_sp(sp_before)
        return rc
    else:
        fn = ctypes.cast(
            rt, ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_char_p)
        )
        return fn(obs, var, val)


def _arm64_push_double_ptr(addr: int) -> None:
    """Push a double value via pointer onto Stata's internal stack (ARM64).

    _pushdbl takes a POINTER to the double value in x0.
    We already have the address from a ctypes buffer.
    """
    _pushdbl_fn(addr)


# ─── Scalar set operations (pure C calls, no StataSO_Execute) ──────
#
# Numeric scalar set: _stscalsave(name, d0=value) — standard ARM64 ABI
#   from disasm at 0x79c820: saves d0 on stack, calls _sclrsv(name, &val)
#
# String scalar set: _xgso_newcp_fast_code(type, len, src) + _put_xgso_scalar(name, gso)
#   from disasm at 0x8a9e84 / 0x6c9340
#   type=0x82 creates a GSO for scalar storage
#
# Both confirmed working empirically (2026-05-19).


def call_set_scalar(name: str, value: float) -> int:
    """Set a numeric scalar via _stscalsave(name, d0=value).

    Uses standard ARM64 ABI (no internal stack needed).
    """
    if not _INITIALIZED:
        initialize()
    addr = _BASE + 0x79c820  # _stscalsave
    if _PLATFORM == "arm64":
        fn = ctypes.cast(
            addr,
            ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_char_p, ctypes.c_double),
        )
        return fn(name.encode(), value)
    else:
        # TODO: x86_64 stub — use StataSO_Execute as fallback
        execute(f"scalar {name} = {value}")
        return 0


def call_set_strscalar(name: str, value: str) -> int:
    """Set a string scalar via _xgso_newcp_fast_code + _put_xgso_scalar.

    Uses standard ARM64 ABI (no internal stack needed).
    """
    if not _INITIALIZED:
        initialize()
    if _PLATFORM == "arm64":
        val_bytes = value.encode()
        xgso_fn = ctypes.cast(
            _BASE + 0x8a9e84,  # _xgso_newcp_fast_code
            ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_char_p),
        )
        put_fn = ctypes.cast(
            _BASE + 0x6c9340,  # _put_xgso_scalar
            ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p),
        )
        gso = xgso_fn(0x82, len(val_bytes) + 1, val_bytes)
        if not gso:
            return -1
        return put_fn(name.encode(), gso)
    else:
        # TODO: x86_64 stub — use StataSO_Execute as fallback
        execute(f'scalar {name} = "{value}"')
        return 0


def call_vlmodify(label_name: str, value: int, text: str) -> int:
    """Add/modify a value-label mapping via _bist_vlmodify.

    _bist_vlmodify reads 3 entries from the internal stack:
      *(SP-16) = label name (string tsmat)
      *(SP-8)  = value (numeric tsmat, e.g. 0, 1)
      *(SP)    = label text (string tsmat)

    On x86_64: direct CFUNCTYPE with (char*, int, char*).
    """
    if not _INITIALIZED:
        initialize()
    addr = _sym_addr("_bist_vlmodify")
    if addr is None:
        return -1
    rt = _BASE + addr

    if _PLATFORM == "arm64":
        sp_before = _save_sp()
        _arm64_push_str(label_name.encode())
        _arm64_push_int(value)
        _arm64_push_str(text.encode())
        fn = ctypes.cast(rt, ctypes.CFUNCTYPE(None, ctypes.c_int))
        fn(3)
        rc = _read_stata_err()
        _restore_sp(sp_before)
        return rc
    else:
        fn = ctypes.cast(
            rt,
            ctypes.CFUNCTYPE(
                ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p
            ),
        )
        return fn(label_name.encode(), value, text.encode())


# ─── Value label helper (uses _bist_vlmodify + _bist_vlload) ──────


def call_create_valuelabel(name: str) -> int:
    """Create a value label definition with an initial mapping.

    Uses _bist_vlmodify to add an initial value-label pair, which is
    required for the label to exist.  Uses a non-empty dummy label text
    because _bist_vlmodify rejects whitespace-only label values.
    """
    # Use a non-whitespace dummy text so the label registers properly.
    return call_vlmodify(name, 0, f"_{name}")


# ─── Direct memory reads (platform-independent obs/var counts) ─────

# From _bist_nobs disassembly:
#   adrp x8, 0x39c7000   -> x8 = _BASE + 0x39c7000
#   add  x8, x8, #0xf7c  -> x8 = _BASE + 0x39c7000 + 0xf7c
#   ldr  s0, [x8]         -> load int32 (obs count)
_OBS_ADDR_RELATIVE: int = 0x39c7000 + 0xf7c


def read_obs_count() -> int:
    """Read obs count directly from Stata's internal memory."""
    if not _INITIALIZED:
        initialize()
    addr = _BASE + _OBS_ADDR_RELATIVE
    return ctypes.c_int32.from_address(addr).value


def read_var_count() -> int:
    """Read variable count directly from Stata's internal memory."""
    if not _INITIALIZED:
        initialize()
    addr = _BASE + _OBS_ADDR_RELATIVE - 4
    return ctypes.c_int32.from_address(addr).value


# ─── Engine commands (via StataSO_Execute) ─────────────────────────
# Note: only for non-SFI Stata commands.  SFI data access uses _bist_* only.


def execute(command: str) -> tuple[str, int]:
    """Execute a Stata command, return (output, return_code)."""
    if not _INITIALIZED:
        initialize()
    if not _LIB:
        raise RuntimeError("Engine not initialized")
    _LIB.StataSO_ClearOutputBuffer.restype = None
    _LIB.StataSO_ClearOutputBuffer()
    cmd = command.encode() if isinstance(command, str) else command
    rc = _LIB.StataSO_Execute(cmd)
    _LIB.StataSO_GetOutputBuffer.restype = ctypes.c_void_p
    buf = _LIB.StataSO_GetOutputBuffer()
    output = ""
    if buf:
        raw = ctypes.c_char_p(buf).value
        if raw:
            output = raw.decode("utf-8", errors="replace")
    return output, rc


def shutdown():
    """Shutdown Stata engine."""
    global _INITIALIZED
    if _LIB:
        try:
            _LIB.StataSO_Shutdown.restype = ctypes.c_int
            _LIB.StataSO_Shutdown()
        except Exception:
            pass
    _INITIALIZED = False
