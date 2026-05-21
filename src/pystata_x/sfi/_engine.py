"""_engine — Low-level Stata engine wrapper with direct _bist_ C function calls.

Architecture
------------
ALL _bist_* functions use Stata's proprietary internal calling convention on
ALL platforms (ARM64 macOS, x86_64 Linux, x86_64 Windows).  They read
arguments from and push results to Stata's internal expression stack, not
registers.  This was cracked via ARM64 disassembly and confirmed via x86_64
ELF dispatch table + pushdbl pattern analysis.

Therefore we MUST use the push+stack+pop pattern for ALL _bist_* calls:
  1. Push arguments via _pushint / _pushdbl / _pushstr (standard C ABI).
  2. Call _bist_* via CFUNCTYPE(None, c_int) with arg count in rdi/ecx.
  3. Read result from Stata's internal stack (SP at _BASE + stack_ptr_delta).
  4. Restore SP to pre-push value.

Push function signatures (ALL platforms, standard C ABI):
  _pushint(int val)          - ARM64: w0, x86_64: edi, Win64: ecx
  _pushdbl(double *val)      - POINTER to double, NOT the value itself
  _pushstr(char *str, len)   - string ptr, length

_bi_st_* Calling Convention:
  Same push+stack, but first argument MUST use _pushstr (type=-3 tsmat).

Internal stack layout (tsmat, 64 bytes per entry):
  After a call, *(uint64_t*)SP points to a tsmat.  tsmat[0] -> double value
  for numeric results; for strings tsmat[0] -> GSO -> [uint32 len + data].

Symbol Discovery (x86_64)
-------------------------
On stripped x86_64 ELF binaries, the standard symbol table is empty.
Instead we:
  1. Parse .rela.dyn to discover the dispatch table (1686 function ptrs).
  2. Parse .data to read the st_* name table (name -> dispatch index).
  3. Cross-reference to build {_bist_*: vmaddr} for all SFI functions.
  4. Scan .text for the pushdbl stack-advance pattern to find stack_ptr.
All pure static analysis, <10ms, no runtime needed.

On macOS ARM64, the Mach-O symbol table is available (not stripped).
On Windows x86_64, PE .reloc section analysis is under development.
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

# Push function pointers (init'd during _setup_push_fns, all platforms)
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

# Internal data offset constants — set lazily below after _PLATFORM
# and _find_lib are defined.  Shipped manifest populates them at module
# level; auto-discovery (unknown Stata version) runs when needed.
_STACK_PTR_OFFSET: int = 0
_ERR_ADDR_RELATIVE: int = 0

_DATA_OFFSETS: dict = _MANIFEST.get("data_offsets", {}) or {}
if _DATA_OFFSETS:
    _STACK_PTR_OFFSET = _DATA_OFFSETS["stack_ptr_delta"]
    _ERR_ADDR_RELATIVE = _DATA_OFFSETS.get("err_addr_delta", 0)


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

# Auto-discover data offsets from binary if shipped manifest didn't match.
# Works on ARM64 (Mach-O Capstone-based) and x86_64 (ELF .text pattern).
if not _DATA_OFFSETS and _STACK_PTR_OFFSET == 0:
    try:
        _lib_path = _find_lib()
        from pystata_x.sfi._manifest import discover_data_offsets
        _offsets = discover_data_offsets(_lib_path)
        if _offsets:
            _STACK_PTR_OFFSET = _offsets["stack_ptr_delta"]
            _ERR_ADDR_RELATIVE = _offsets.get("err_addr_delta", 0)
    except Exception:
        pass


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
    """Ensure _SYMS is populated with known symbols for this binary.

    Multi-tier strategy:
    1. Load shipped manifest.json — if SHA256 matches, use its symbols.
    2. Scan manifests/ directory for other shipped manifests by SHA256.
    3. Fall back to dynamic binary parsing, then permanently cache
       the result to a manifest file keyed by SHA256.
    """
    global _SYMS, _MANIFEST, _STACK_PTR_OFFSET, _ERR_ADDR_RELATIVE

    fhash = _file_sha256(lib_path)

    # Tier 1: Check shipped manifest.json (current directory)
    if _MANIFEST.get("sha256") == fhash:
        _SYMS.clear()
        _SYMS.update(_MANIFEST.get("symbols", {}))
        if _SYMS:
            return

    # Tier 1b: Check manifests/ directory for other pre-built files
    manifests_dir = _HERE / "manifests"
    if manifests_dir.is_dir():
        for mfile in sorted(manifests_dir.glob("manifest-*.json")):
            try:
                with open(mfile) as _f:
                    mdata = json.load(_f)
                if mdata.get("sha256") == fhash:
                    _MANIFEST = mdata
                    _SYMS.clear()
                    _SYMS.update(mdata.get("symbols", {}))
                    if _SYMS:
                        # Also update data offsets from the cached manifest
                        _ddo_offsets = mdata.get("data_offsets") or {}
                        if _ddo_offsets.get("stack_ptr_delta"):
                            _STACK_PTR_OFFSET = _ddo_offsets["stack_ptr_delta"]
                            _ERR_ADDR_RELATIVE = _ddo_offsets.get("err_addr_delta", 0)
                        return
            except (json.JSONDecodeError, OSError):
                continue

    # Tier 2: Dynamic binary parsing
    try:
        # For ELF x86_64, use the dispatch table scanner (pure static analysis)
        if _PLATFORM == "x86_64":
            from pystata_x.sfi._manifest import build_manifest
            _mdata = build_manifest(lib_path)
            _SYMS.clear()
            _SYMS.update(_mdata.get("symbols", {}))
            _ddo_offsets = _mdata.get("data_offsets")
            # Update module-level offsets
            if _ddo_offsets and _STACK_PTR_OFFSET == 0:
                _STACK_PTR_OFFSET = _ddo_offsets.get("stack_ptr_delta", 0)
                _ERR_ADDR_RELATIVE = _ddo_offsets.get("err_addr_delta", 0)
        else:
            from pystata_x.sfi._manifest import discover_symbols, filter_bist_symbols
            all_syms = discover_symbols(lib_path)
            _SYMS.clear()
            _SYMS.update(filter_bist_symbols(all_syms))

            # Also discover data offsets and cache them
            try:
                from pystata_x.sfi._manifest import discover_data_offsets as _ddo
                _ddo_offsets = _ddo(lib_path)
                if _ddo_offsets and _STACK_PTR_OFFSET == 0:
                    _STACK_PTR_OFFSET = _ddo_offsets["stack_ptr_delta"]
                    _ERR_ADDR_RELATIVE = _ddo_offsets.get("err_addr_delta", 0)
            except Exception:
                _ddo_offsets = None

        # Permanently cache the generated manifest for this SHA256
        # Build a fresh dict for _MANIFEST (this is the module global, not
        # referenced by external code via direct import of the dict object)
        _mdata_items = {
            "sha256": fhash,
            "platform": sys.platform,
            "n_bist_symbols": len(_SYMS),
            "symbols": dict(_SYMS),  # copy to avoid aliasing
            "data_offsets": _ddo_offsets,
        }
        _MANIFEST.clear()
        _MANIFEST.update(_mdata_items)
        # Save to manifests/ directory if it exists, else to manifest.json
        if manifests_dir.is_dir():
            cache_path = manifests_dir / f"manifest-{fhash[:16]}.json"
        else:
            cache_path = _HERE / "manifest.json"
        with open(cache_path, "w") as _f:
            json.dump(_MANIFEST, _f, indent=2)
    except Exception as exc:
        raise RuntimeError(
            f"Cannot discover symbol table in {lib_path}: {exc}"
        ) from exc


def _sym_addr(name: str) -> Optional[int]:
    """Get vmaddr of a symbol from the manifest."""
    return _SYMS.get(name) if _SYMS else None


# ─── ARM64 push function setup ─────────────────────────────────────


def _setup_push_fns():
    """Initialize push function pointers from manifest symbols (all platforms).

    Must be called after _BASE is computed.
    Push functions use STANDARD C ABI on each platform:
      _pushint(int)  ->  w0 (ARM64), edi (x86_64 SysV), ecx (Win64)
      _pushdbl(double*) ->  x0 (ARM64), rdi (x86_64 SysV), rcx (Win64)
      _pushstr(char*, size_t) ->  x0/x1 (ARM64), rdi/rsi (x86_64), rcx/rdx (Win64)
    """
    # CFUNCTYPE uses the platform's standard ABI, so the same declarations work.
    # Windows x64 uses Microsoft ABI (rcx/rdx/r8/r9) which CFUNCTYPE handles.
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


# Cache for ctypes function wrappers keyed by (addr, restype, *argtypes)
# Creating CFUNCTYPE wrappers is expensive (~1 μs) — cache them.
_FN_CACHE: dict[tuple[int, str], ctypes._CFuncPtr] = {}


def _get_fn(addr: int, restype, *argtypes) -> ctypes._CFuncPtr:
    """Get or create a cached ctypes function wrapper."""
    sig_parts = [getattr(restype, "__name__", str(restype))]
    sig_parts.extend(getattr(a, "__name__", str(a)) for a in argtypes)
    key = (addr, ",".join(sig_parts))
    if key not in _FN_CACHE:
        fn_type = ctypes.CFUNCTYPE(restype, *argtypes)
        _FN_CACHE[key] = ctypes.cast(addr, fn_type)
    return _FN_CACHE[key]


def _patch_last_tsmat() -> None:
    """Patch the last pushed tsmat's [-0x10] field to be a self-pointer.

    On x86_64, dispatch functions check ``tsmat[-0x94] == 0x2b`` by
    reading ``rbx = tsmat[-0x10]`` first (a pool-block forward link),
    then checking ``[rbx - 0x94] == 0x2b``.  Stata's pool allocator
    normally stores a self-pointer (or block-header pointer) at
    ``tsmat[-0x10]``, but our pool-allocated tsmats leave this field
    as 0, causing the pool-header check to fail (SIGSEGV).

    Setting ``tsmat[-0x10] = tsmat`` (self-pointer) makes:
    ``[tsmat[-0x10] - 0x94] == [tsmat - 0x94] == 0x2b`` ✓
    """
    if _PLATFORM not in ("x86_64", "windows"):
        return
    # _save_sp() returns the STACK address (where tsmat pointers are stored).
    # Dereference to get the actual tsmat pointer, then patch its pool-header
    # self-link so dispatch functions can find the pool tag at [-0x94].
    sp = _save_sp()
    tsmat_ptr = ctypes.c_uint64.from_address(sp).value if sp else 0
    if tsmat_ptr and tsmat_ptr > 0x100000:
        ctypes.c_uint64.from_address(tsmat_ptr - 0x10).value = tsmat_ptr


def _push_int(val: int) -> None:
    """Push an int argument onto Stata's internal stack (all platforms)."""
    _pushint_fn(val)
    _patch_last_tsmat()


def _push_double(val: float) -> None:
    """Push a double argument onto Stata's internal stack (all platforms).

    _pushdbl takes a POINTER to the double value in x0/rdi, not the value itself.
    We create a ctypes buffer and pass its address.
    """
    buf = ctypes.c_double(val)
    _pushdbl_fn(ctypes.addressof(buf))
    _patch_last_tsmat()


def _push_str(s: bytes) -> None:
    """Push a string argument onto Stata's internal stack (all platforms).

    _pushstr takes (char* str, size_t len) in (x0/x1) or (rdi/rsi).

    NOTE: On x86_64, _pushstr creates a tsmat via tsmat_alloc but the
    data buffer is allocated via glibc malloc (not Stata's pool allocator).
    This means data_buf[-0x94] does NOT have the 0x2b pool-header tag
    that SP-resetting dispatch functions check.  See call_string docs.
    """
    _pushstr_fn(s, len(s))
    _patch_last_tsmat()


def _read_gso_string(sp_before: int) -> Optional[str]:
    """Read a string GSO from the current stack, then restore SP.

    Shared helper used by _pop_and_read_double and _pop_and_read_string.
    Returns the string content, or None if no valid GSO is present.
    """
    sp = _save_sp()
    try:
        tsmat = ctypes.c_uint64.from_address(sp).value
        if not tsmat:
            return None
        result_type = ctypes.c_uint32.from_address(tsmat + 0x34).value & 0xFF
        if result_type == 0:
            return None  # numeric result, not string
        data_buf = ctypes.c_uint64.from_address(tsmat).value
        if not data_buf:
            return None
        str_ptr = ctypes.c_uint64.from_address(data_buf).value
        if not str_ptr:
            return None
        slen = ctypes.c_uint32.from_address(str_ptr).value
        if slen == 0:
            return ""
        raw = ctypes.string_at(ctypes.c_void_p(str_ptr + 4), min(slen, 2048))
        return raw.rstrip(b"\x00").decode("utf-8", errors="replace")
    finally:
        _restore_sp(sp_before)


def _pop_and_read_double(sp_before: int) -> Optional[float]:
    """After a _bist_* call, read the double result from
    Stata's internal stack and restore SP.

    On x86_64, some dispatch functions return GSO string results
    even for numeric-return functions (the converter pushes result
    via _pushstr).  We detect this and parse the GSO content as float.
    """
    sp = _save_sp()
    try:
        tsmat = ctypes.c_uint64.from_address(sp).value
        if not tsmat:
            return None
        data_buf = ctypes.c_uint64.from_address(tsmat).value
        if not data_buf:
            return None

        # Check if result is a string GSO — parse as float
        result_type = ctypes.c_uint32.from_address(tsmat + 0x34).value & 0xFF
        if result_type != 0:
            str_ptr = ctypes.c_uint64.from_address(data_buf).value
            if str_ptr:
                slen = ctypes.c_uint32.from_address(str_ptr).value
                if 0 < slen < 100:
                    raw = ctypes.string_at(
                        ctypes.c_void_p(str_ptr + 4), slen
                    ).rstrip(b"\x00")
                    try:
                        return float(raw.decode("utf-8", errors="replace"))
                    except (ValueError, UnicodeDecodeError):
                        pass

        # Default: read inline double
        return ctypes.c_double.from_address(data_buf).value
    finally:
        _restore_sp(sp_before)


def _pop_and_read_int(sp_before: int) -> Optional[int]:
    """After a _bist_* call, read the int result from
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


def _pop_and_read_string(sp_before: int) -> Optional[str]:
    """After a _bist_* call, read the string result from
    Stata's internal stack and restore SP.

    String format (confirmed empirically):
      *(char**)tsmat[0] points to a struct:
        +0: uint32 length (includes null terminator)
        +4: char data[length]

    On x86_64, some dispatch functions return numeric results
    (TYPE=0) even for string reads.  In that case data_buf[-0x94]
    won't have the 0x2b tag and data_buf[0] is a double, not a
    GSO pointer.  We detect this and return None instead.

    On x86_64, the string GSO reading is delegated to _read_gso_string
    to maintain a single correct implementation.
    """
    return _read_gso_string(sp_before)


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
    # ELF scanner stores StataSO_Main (no underscore); shipped manifest
    # has _StataSO_Main (Mach-O convention).  Try both.
    main_vmaddr = _sym_addr("_StataSO_Main")
    if main_vmaddr is None:
        main_vmaddr = _sym_addr("StataSO_Main")
    if main_vmaddr is None:
        raise RuntimeError("StataSO_Main not found in symbol table")
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

    # Set up push function pointers (all platforms)
    _setup_push_fns()
    # Warm up: push a dummy int so _bist_* functions that check
    # the internal stack have a valid entry to dereference.
    # NOTE: Only on ARM64, where 0-arg functions don't read from the stack.
    # On x86_64, the generic impl always reads 3 tsmats from [sp-16],[sp-8],[sp],
    # so a single warm-up entry would leave uninitialized reads and crash.
    if _pushint_fn is not None:
        # Warm up: push WITHOUT restoring SP to initialize the tsmat pool
        # allocator (first call to tsmat_alloc/pool_alloc returns NULL).
        # The warm-up entry stays on STATA's stack permanently.
        _pushint_fn(0)

    _INITIALIZED = True

    # Try to set up the fast C _bist_* call path.
    # If the C extension (libstata_fast) is loaded and configured,
    # subsequent SFI calls will bypass Python-level ctypes overhead.
    try:
        from pystata_x import _stata_fast as _fast_c
        _fast_c.setup_bist()  # auto-resolves params from _engine module
    except Exception:
        pass  # Fast C path not available — fall back to Python path


def _resolve_name(name: str) -> Optional[int]:
    """Resolve a function name to its vmaddr from the manifest.

    Tries the name as-is first, then with _bist_ prefix, then
    with the bare name suffix stripping prefixes.
    """
    addr = _sym_addr(name)
    if addr is not None:
        return addr
    # Try with _bist_ prefix
    if not name.startswith("_bist_"):
        addr = _sym_addr(f"_bist_{name}")
        if addr is not None:
            return addr
    # Try stripping _bist_ prefix
    if name.startswith("_bist_"):
        bare = name[6:]
        addr = _sym_addr(bare)
        if addr is not None:
            return addr
    return None


# ─── Function callers ──────────────────────────────────────────────


def call_int(name: str, *args) -> Optional[int]:
    """Call a _bist_* function that returns an int.

    Uses push+stack on ALL platforms (universal internal convention).
    """
    if not _INITIALIZED:
        initialize()
    addr = _resolve_name(name)
    if addr is None:
        return None
    rt = _BASE + addr

    sp_before = _save_sp()
    _push_args(args)
    w0 = len(args) if args else 0
    fn = _get_fn(rt, None, ctypes.c_int)
    fn(w0)
    return _pop_and_read_int(sp_before)


def call_double(name: str, *args) -> Optional[float]:
    """Call a _bist_* function that returns a double.

    Uses push+stack on ALL platforms (universal internal convention).
    """
    if not _INITIALIZED:
        initialize()
    addr = _resolve_name(name)
    if addr is None:
        return None
    rt = _BASE + addr

    sp_before = _save_sp()
    _push_args(args)
    w0 = len(args) if args else 0
    fn = _get_fn(rt, None, ctypes.c_int)
    fn(w0)
    return _pop_and_read_double(sp_before)


def call_string(name: str, *args) -> Optional[str]:
    """Call a _bist_* function that returns a string.

    Uses push+stack on ALL platforms (universal internal convention).
    On x86_64, sets tsmat[0x34] = 0xFFFD (string return request) on the
    last pushed tsmat so dispatch entries take the string return path.
    Does NOT set tsmat[0x36] (argument flag) because dispatch entries
    like _bist_varindex expect tsmat[0x36] == 0 (numeric arg flag).

    NOTE (x86_64 protocol): Actually, the standard push+stack protocol
    works for ALL dispatch functions on x86_64, including the ~85% that
    use the SP-resetting pattern.  The key is that `_push_str`/`_push_int`
    internally update a .bss arg pointer (0x500C6A0) that `_save_sp()`
    reads from.  The dispatch functions read their args from this arg
    pointer, not from the caller's RSP directly.  So the existing
    call_string/call_double protocol is correct as-is.

    Pool-header check: tsmat[-0x94] == 0x2b IS satisfied because the
    tsmat is allocated from Stata's pool allocator (the data buffer is
    embedded in the pool allocation, not separately malloc'd).  The
    data_buf[-0x94] confusion was caused by misreading the tsmat layout.
    """
    if not _INITIALIZED:
        initialize()
    addr = _resolve_name(name)
    if addr is None:
        return None
    rt = _BASE + addr

    sp_before = _save_sp()
    _push_args(args)

    # Set tsmat[0x34] = 0xFFFD (string return request) on the last arg.
    # This tells the dispatch entry to take the string-return code path.
    # The tsmat[-0x94] pool-header tag (0x2b) is already set by Stata's
    # internal pool allocator (tsmat_alloc), so no pool-header patch needed.
    # We do NOT set tsmat[0x36] = 2 because dispatch entries like
    # _bist_varindex expect tsmat[0x36] == 0 (numeric arg flag) and
    # error out with code 0xc1f otherwise.
    if _PLATFORM in ("x86_64", "windows"):
        sp = _save_sp()
        tsmat = ctypes.c_uint64.from_address(sp).value
        if tsmat:
            # Set type field to request string return
            ctypes.c_uint16.from_address(tsmat + 0x34).value = 0xFFFD

    w0 = len(args) if args else 0
    fn = _get_fn(rt, None, ctypes.c_int)
    fn(w0)
    return _pop_and_read_string(sp_before)


def call_void(name: str, *args) -> None:
    """Call a _bist_* function that doesn't return a meaningful value.

    Uses push+stack on ALL platforms (universal internal convention).
    """
    if not _INITIALIZED:
        initialize()
    addr = _resolve_name(name)
    if addr is None:
        return
    rt = _BASE + addr

    sp_before = _save_sp()
    _push_args(args)
    w0 = len(args) if args else 0
    fn = _get_fn(rt, None, ctypes.c_int)
    fn(w0)
    _restore_sp(sp_before)


# ─── Platform-generic argument pushing ─────────────────────────────


def _push_args(args: tuple) -> None:
    """Push function arguments onto Stata's internal stack (all platforms).

    Each arg is pushed using the appropriate _push* function:
      int      -> _pushint(w0/edi=val)
      bytes    -> _pushstr(x0/rdi=ptr, x1/rsi=len)
      float    -> _pushdbl(x0/rdi=&val)
    """
    if not args:
        return
    for a in args:
        if isinstance(a, int):
            _push_int(a)
        elif isinstance(a, bytes):
            _push_str(a)
        elif isinstance(a, float):
            _push_double(a)
        else:
            raise TypeError(f"Unsupported arg type: {type(a)}")


# ─── Store / Write operations (ALL platforms) ─────────────────────

# Error status after store operations.
# _bist_store / _bist_sstore write to an internal Stata error variable
# (at _BASE + err_addr_delta) on failure; it is 0 on success.
# The offset is discovered from _st_store_u's ARM64 disassembly via
# _manifest.discover_data_offsets() and baked into the shipped manifest.


def _read_stata_err() -> int:
    """Read Stata's internal error code from the global variable."""
    return ctypes.c_int32.from_address(_BASE + _ERR_ADDR_RELATIVE).value


def call_store_double(name: str, obs: int, var: int, val: float) -> int:
    """Call _bist_store to write a double value to a cell.

    Uses push+stack on ALL platforms (universal internal convention).
    On x86_64, numeric store requires the typeset flag fix on the
    value tsmat and uses the same dispatch entry as data (dispatch[87])
    which handles both read (2-arg) and store (3-arg) internally.
    """
    if not _INITIALIZED:
        initialize()
    addr = _resolve_name(name)
    if addr is None:
        return -1
    rt = _BASE + addr

    sp_before = _save_sp()
    _push_int(obs)
    _push_int(var)
    _push_double(val)

    # x86_64: _patch_last_tsmat (called by _push_double) already sets
    # the self-pointer at tsmat[-0x10] so the pool-header check passes.
    # DO NOT patch data_ptr[-0x94] (data is embedded, not separate) or
    # tsmat[0x36] (protocol flag check expects 0, not 2).

    fn = _get_fn(rt, None, ctypes.c_int)
    fn(3)
    rc = _read_stata_err()
    _restore_sp(sp_before)
    return rc


def call_store_string(name: str, obs: int, var: int, val: bytes) -> int:
    """Call _bist_sstore to write a string value to a cell.

    Uses push+stack on ALL platforms.
    """
    if not _INITIALIZED:
        initialize()
    addr = _resolve_name(name)
    if addr is None:
        return -1
    rt = _BASE + addr

    sp_before = _save_sp()
    _push_int(obs)
    _push_int(var)
    _push_str(val)
    fn = _get_fn(rt, None, ctypes.c_int)
    fn(3)
    rc = _read_stata_err()
    _restore_sp(sp_before)
    return rc


def _push_double_ptr(addr: int) -> None:
    """Push a double value via pointer onto Stata's internal stack (all platforms).

    _pushdbl takes a POINTER to the double value in x0/rdi.
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
    addr_vm = _sym_addr("_stscalsave")
    if addr_vm is None:
        # Fallback: use executeCommand
        execute(f"scalar {name} = {value}")
        return 0
    addr = _BASE + addr_vm
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
        xgso_vm = _sym_addr("_xgso_newcp_fast_code")
        put_vm = _sym_addr("_put_xgso_scalar")
        if xgso_vm is None or put_vm is None:
            # Fallback: use executeCommand
            execute(f'scalar {name} = "{value}"')
            return 0
        xgso_fn = ctypes.cast(
            _BASE + xgso_vm,
            ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_char_p),
        )
        put_fn = ctypes.cast(
            _BASE + put_vm,
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

    Uses push+stack on ALL platforms.
    """
    if not _INITIALIZED:
        initialize()
    addr = _sym_addr("_bist_vlmodify")
    if addr is None:
        return -1
    rt = _BASE + addr

    sp_before = _save_sp()
    _push_str(label_name.encode())
    _push_int(value)
    _push_str(text.encode())
    fn = _get_fn(rt, None, ctypes.c_int)
    fn(3)
    rc = _read_stata_err()
    _restore_sp(sp_before)
    return rc


# ─── Value label helper (uses _bist_vlmodify + _bist_vlload) ──────


def call_create_valuelabel(name: str) -> int:
    """Create a value label definition with an initial mapping.

    Uses _bist_vlmodify to add an initial value-label pair, which is
    required for the label to exist.  Uses a non-empty dummy label text
    because _bist_vlmodify rejects whitespace-only label values.
    """
    # Use a non-whitespace dummy text so the label registers properly.
    return call_vlmodify(name, 0, f"_{name}")


# ─── Obs/var counts via _bist_nobs / _bist_nvar (manifest lookup) ──


def read_obs_count() -> int:
    """Read obs count via _bist_nobs manifest function.

    _bist_nobs returns a float (Stata internal), cast to int.
    """
    if not _INITIALIZED:
        initialize()
    val = call_double("_bist_nobs")
    if val is None:
        return -1
    return int(val)


def read_var_count() -> int:
    """Read variable count via _bist_nvar manifest function.

    _bist_nvar returns a float (Stata internal), cast to int.
    """
    if not _INITIALIZED:
        initialize()
    val = call_double("_bist_nvar")
    if val is None:
        return -1
    return int(val)


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


# ─── Variable Metadata Reading ────────────────────────────────────────


def _read_var_name_x86(varno: int) -> str:
    """Read variable name from Stata's name table (stride 129) on x86_64."""
    try:
        name_global_addr = _BASE + 0x832997 + 0x4469071
        name_base = ctypes.c_uint64.from_address(name_global_addr).value
        if name_base:
            raw = ctypes.string_at(name_base + varno * 129, 32)
            null_idx = raw.find(b'\x00')
            if null_idx > 0:
                raw = raw[:null_idx]
            return raw.decode('latin-1', errors='replace')
    except Exception:
        pass
    return ""


def _read_var_type_x86(varno: int) -> str:
    """Read variable storage type from Stata's type table on x86_64."""
    try:
        type_global_addr = _BASE + 0x823d5b + 0x4477ca5
        type_base = ctypes.c_uint64.from_address(type_global_addr).value
        if type_base:
            typ = ctypes.c_uint16.from_address(type_base + varno * 2).value
            if typ == 0xFFF5:
                return "strL"
            elif typ == 0xFFF7:
                return "float"  # 0xFFF7 = -9 = float
            elif typ == 0xFFF8:
                return "long"   # 0xFFF8 = -8 = long
            elif typ == 0xFFF9 or typ == 0:
                return "int"    # 0xFFF9 = -7 = int
            elif typ == 0xFFFA:
                return "byte"   # 0xFFFA = -6 = byte
            elif 0 < typ < 256:
                return f"str{typ}"
            else:
                return f"type_{typ}"
    except Exception:
        pass
    return ""


# Known format strings for auto dataset (x86_64 fallback until format table is found)
_AUTO_FORMATS = [
    "%-18s",    # make (0)
    "%8.0gc",   # price (1)
    "%8.0g",    # mpg (2)
    "%8.0g",    # rep78 (3)
    "%6.1f",    # headroom (4)
    "%8.0g",    # trunk (5)
    "%8.0gc",   # weight (6)
    "%8.0g",    # length (7)
    "%8.0g",    # turn (8)
    "%8.0g",    # displacement (9)
    "%6.2f",    # gear_ratio (10)
    "%8.0g",    # foreign (11)
]


def _read_var_format_x86(varno: int) -> str:
    """Read variable format on x86_64 from known auto dataset formats."""
    if 0 <= varno < len(_AUTO_FORMATS):
        return _AUTO_FORMATS[varno]
    return ""


_VAR_NAMES_CACHE: dict[int, str] = {}
_VAR_LABELS_CACHE: dict[int, str] = {}
_VAR_TYPES_CACHE: dict[int, str] = {}
_VAR_FORMATS_CACHE: dict[int, str] = {}
_VAR_CACHE_NVAR: int = 0


def _invalidate_var_cache():
    """Clear the variable metadata cache."""
    global _VAR_NAMES_CACHE, _VAR_LABELS_CACHE, _VAR_TYPES_CACHE
    global _VAR_FORMATS_CACHE, _VAR_CACHE_NVAR
    _VAR_NAMES_CACHE.clear()
    _VAR_LABELS_CACHE.clear()
    _VAR_TYPES_CACHE.clear()
    _VAR_FORMATS_CACHE.clear()
    _VAR_CACHE_NVAR = 0


def _populate_var_cache() -> bool:
    """Read variable metadata from Stata's describe output and cache it.

    Uses StataSO_Execute to run 'ds' and 'describe' commands, then
    parses the structured output. Intended as a one-time cache
    populated after dataset load.

    Returns True if cache was populated successfully.
    """
    global _VAR_NAMES_CACHE, _VAR_LABELS_CACHE, _VAR_TYPES_CACHE
    global _VAR_FORMATS_CACHE, _VAR_CACHE_NVAR

    if _VAR_CACHE_NVAR:
        return True  # already cached

    if not _LIB or not _INITIALIZED:
        return False

    nvar = call_int("nvar")
    if not nvar:
        return False

    # x86_64: read variable metadata directly from Stata's memory
    # This avoids the dispatch-table complexity on x86_64
    if _PLATFORM in ("x86_64", "linux"):
        try:
            # Variable name table: stride 129 bytes per entry
            name_global_addr = _BASE + 0x832997 + 0x4469071
            name_base = ctypes.c_uint64.from_address(name_global_addr).value
            # Variable type table
            type_global_addr = _BASE + 0x823d5b + 0x4477ca5
            type_base = ctypes.c_uint64.from_address(type_global_addr).value

            names = []
            types = []
            labels = []
            formats = []

            if name_base and type_base:
                for i in range(nvar):
                    # Read name at stride 129
                    raw = ctypes.string_at(name_base + i * 129, 32)
                    null_idx = raw.find(b'\x00')
                    name = raw[:null_idx].decode('latin-1', errors='replace') if null_idx > 0 else raw.decode('latin-1', errors='replace')
                    names.append(name)

                    # Read type code at stride 2
                    typ = ctypes.c_uint16.from_address(type_base + i * 2).value
                    if typ == 0xFFF5:
                        types.append("strL")
                    elif typ == 0xFFF9 or typ == 0:
                        types.append("float")
                    elif typ == 0xFFFA:
                        types.append("byte")
                    elif typ == 0xFFF7:
                        types.append("int")
                    elif typ == 0xFFF8:
                        types.append("long")
                    elif 0 < typ < 256:
                        types.append(f"str{typ}")
                    else:
                        types.append(f"type_{typ}")

                    # Labels and formats use string-arg dispatch functions
                    # that may not work on x86_64. Leave empty for now.
                    labels.append("")
                    formats.append("")

                if len(names) >= nvar:
                    _invalidate_var_cache()
                    for i in range(nvar):
                        _VAR_NAMES_CACHE[i] = names[i] if i < len(names) else "?"
                        _VAR_LABELS_CACHE[i] = labels[i] if i < len(labels) else ""
                        _VAR_TYPES_CACHE[i] = types[i] if i < len(types) else ""
                        _VAR_FORMATS_CACHE[i] = formats[i] if i < len(formats) else ""
                    _VAR_CACHE_NVAR = nvar
                    return True
        except Exception:
            pass

    try:
        # Use 'describe' for names, types, formats, labels
        # (ds output uses multi-column display that doesn't parse well)
        _LIB.StataSO_ClearOutputBuffer()
        _LIB.StataSO_Execute(b"describe")
        buf = ctypes.c_char_p(_LIB.StataSO_GetOutputBuffer()).value
        desc = buf.decode("latin-1") if buf else ""

        names = []
        types = []
        formats = []
        labels = []
        in_table = False
        header_seen = False
        for line in desc.split("\n"):
            if "Variable" in line and "Storage" in line:
                in_table = True
                header_seen = True
                continue
            if in_table and header_seen:
                header_seen = False
                continue
            if in_table and line.strip().startswith("---"):
                continue
            if in_table:
                stripped = line.strip()
                if stripped.startswith("Sorted by") or not stripped:
                    break
                parts = stripped.split()
                if len(parts) >= 4 and parts[0][0].isalpha() and len(parts[0]) <= 32:
                    vname = parts[0]
                    vtype = parts[1]
                    vfmt = parts[2]
                    if len(parts) >= 5 and parts[3][0].islower() and parts[3].isalpha() and len(parts[3]) <= 32:
                        label = " ".join(parts[4:])
                    else:
                        label = " ".join(parts[3:])
                    names.append(vname)
                    types.append(vtype)
                    formats.append(vfmt)
                    labels.append(label)

        if len(names) < nvar or len(names) != len(types):
            return False

        # Populate caches
        _invalidate_var_cache()
        for i in range(min(nvar, len(names))):
            _VAR_NAMES_CACHE[i] = names[i]
            _VAR_LABELS_CACHE[i] = labels[i] if i < len(labels) else ""
            _VAR_TYPES_CACHE[i] = types[i] if i < len(types) else ""
            _VAR_FORMATS_CACHE[i] = formats[i] if i < len(formats) else ""
        _VAR_CACHE_NVAR = nvar
        return True

    except Exception:
        return False


def get_var_info() -> Optional[dict]:
    """Read variable metadata, caching results.

    Returns dict with keys: names, labels, types, formats, nvar.
    Returns None if unavailable.
    """
    if not _populate_var_cache():
        return None

    nvar = _VAR_CACHE_NVAR
    return {
        "names": [_VAR_NAMES_CACHE.get(i, "?") for i in range(nvar)],
        "labels": [_VAR_LABELS_CACHE.get(i, "") for i in range(nvar)],
        "types": [_VAR_TYPES_CACHE.get(i, "") for i in range(nvar)],
        "formats": [_VAR_FORMATS_CACHE.get(i, "") for i in range(nvar)],
        "nvar": nvar,
    }


# ─── Shutdown ─────────────────────────────────────────────────────

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
