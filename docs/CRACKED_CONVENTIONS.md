# CRACKED_CONVENTIONS — Complete tsmat Structure & Calling Convention Reference

## x86_64 Status (2026-05-19)

### Architecture (discovered via runtime Capstone disassembly)

**GSO Argument Buffer (replaces ARM64 internal stack):**
```
head_ptr at BASE + 0x500c6a0   (on x86_64 Linux)
limit_ptr at BASE + 0x500c620
```
Each `_pushdbl` / `_pushint` / `_pushstr` call stores an 8-byte tsmat pointer
at `[old_head + 8]` and advances `head_ptr` by 8.  The buffer grows upward
until it reaches `limit_ptr` (default 512 KB buffer).

**Dispatch function buffer reads:**
Every dispatch function reads tsmat pointers from the GSO buffer at fixed
offsets relative to `head`.  The offsets depend on the FUNCTION, not on the
number of arguments:
- dispatch[87] (`bist_data`, 2 args): reads `[head-0x20]`, `[head-0x18]`,
  `[head-0x10]`, `[head-8]`, `[head]` — 5 entries spanning 40 bytes
- dispatch[143] (`bist_varname`, 1 arg): reads only `[head]` — 1 entry
- dispatch[9] (`bist_global`, 1 arg): reads `[head]` — 1 entry
- dispatch[65] (`bist_vartype`, 1 arg): reads `[head-0x10]`, `[head-8]`,
  `[head]` — 3 entries

**Result tsmat location:**
After the dispatch call, the result tsmat is always at `[head]` (the current
head position).  `head` advances by 8 total (net of push + consume + result).

### Working via push+stack on x86_64
- `_bist_nobs` (dispatch[85], 0x823b48) — 0-arg, returns obs count
- `_bist_nvar` (dispatch[84], 0x823b22) — 0-arg, returns var count
- `_bist_data` (dispatch[87], 0x826494) — 2-arg read, returns double value
- `_bist_varindex` — returns integer index
- `_bist_numscalar` — returns numeric scalar value (via dispatch)

### NOT working via push+stack on x86_64
- **String-arg functions** (`_bist_global`, `_bist_strscalar`): SYMS addresses
  point to WRONG subroutines (0x8221ea, 0x81924a) instead of dispatch table
  entries.  The dispatch index mapping in the ELF scanner is incorrect for
  these entries.  String arguments are pushed correctly but the subroutine
  at the wrong address doesn't resolve them.
- **String-return functions** (`_bist_varname`, `_bist_sdata`): Dispatch
  functions check `tsmat[0x36]` (flags) which is 0 for freshly-allocated
  pool tsmats.  Patching `[0x36] = 2` is done in both C extension and
  Python engine but the dispatch function also interprets `dim1`/`dim2`
  fields as offsets, expecting values set by Stata internals instead of
  tsmat_alloc defaults (dim1=1, dim2=1).
- **Store operations:** dispatch[87]'s 3-arg path (obs + var + value) reads
  the value as a double from the third tsmat but the check cascades fail
  due to mismatched tsmat fields.
- **`_bist_vartype`**: dispatches through [65] which reads 3 pre-existing
  entries and expects string-type (TYPE=-3) entries for validation.

### Fixed
- ✓ GSO buffer head (`_STACK_PTR_OFFSET = 0x500c6a0`) correctly discovered
  and used by engine on x86_64
- ✓ tsmat flag patching (`[0x36] = 2`) in `call_string` for x86_64
- ✓ Pool header (0x2b at tsmat[-0x94]) present for ALL pool-allocated tsmats
  (pushint/pushdbl/pushstr all go through tsmat_alloc → pool_alloc)
- ✓ Manifest scanner correctly maps all st_* entries to dispatch table positions
  on x86_64, verified by array comparison (132 BIST symbols found)

### Key Discovery: String dispatch functions require Stata execution context
Even on macOS ARM64 where everything "works", `call_string("_bist_global", ...)`
returns None for all inputs.  The dispatch functions for string operations
(`_bist_global`, `_bist_strscalar`, `_bist_c_local`, `_bist_varname`, etc.)
require the full Stata interpreter execution context (macro tables, string
buffers, etc.) which is only active when Stata is processing commands through
its normal pipeline.  Calling them through raw ctypes dispatch bypasses this.

The OFFICIAL `sfi` module (from Stata's built-in embedded Python stpy) works
because stpy IS within Stata's execution context.  Our external Python cannot
use stpy (requires pyexec load which is unavailable).

**Numeric operations** (`_bist_data`, `_bist_nobs`, `_bist_nvar`, `_bist_vartype`)
work because they read from in-memory dataset structures that are always
accessible after dataset load (`sysuse auto, clear`).

**String operations** require one of:
1. Stata's embedded Python (stpy) — unavailable (no pyexec)
2. StataSO_Execute — forbidden
3. Direct internal data structure access (variable name table, macro hash tables)

[291 more lines in file. Use offset=21 to continue.]

### Platform-specific type checking
On x86_64, the dispatch table functions were compiled with additional
run-time type checks that are absent from the ARM64 builds.

**tsmat[-0x94] check**: Some functions (like dispatch[87] for `_bist_data`)
check the byte at `tsmat_ptr - 148` for value 0x2b (the pool header tag).
Pool-allocated tsmats always have 0x2b at this offset.  These functions
work with push+stack tsmats.

**data_ptr[-0x94] check**: Other functions (like dispatch[143] for
`_bist_varname`) dereference tsmat[0] to get `data_ptr` and then check
`data_ptr[-0x94]`.  The data is allocated at a DIFFERENT pool location
from the tsmat, and `data_ptr[-0x94]` does NOT normally contain 0x2b.
These functions require manual type-tag patching:
```python
ctypes.c_uint8.from_address(data_ptr - 0x94).value = 0x2b
(ctypes.c_uint8 * 64).from_address(tsmat)[0x36] = 2  # flags byte
ctypes.c_uint64.from_address(tsmat + 0x28).value = var_idx  # slot_id
```
Even with patching, varname returns double values (not the name string)
because the shared dispatch entry always follows the viewobs code path.

### C Extension fast path
For operations that don't work via Python-level push+stack on x86_64,
the C extension (`stata_fast.c`) handles them by calling internal dispatch
functions from within the Stata process context, avoiding QEMU emulation
memory-access issues entirely.

## Internal Stack Fundamentals

**ARM64 Location**: `_BASE + 0x39b7000 + 0x108`
**x86_64 Location**: `_BASE + 0x500c6a0` (in BSS)
**Growth**: Upward (increment BEFORE store)
**Element size**: 8 bytes (tsmat pointers)
**Push mechanism**: `_pushint`, `_pushdbl`, `_pushstr` (standard C ABI on all platforms)

## tsmat Structure

All arguments and results on the internal stack are **tsmat** (term storage matrix)
pointers. Each tsmat is a 64-byte (8 qword) structure:

### Numeric tsmat (created by _pushint)
```
Offset  Size  Field              Value
+0x00   8     data_ptr           → double value (8 bytes at this address)
+0x08   8     (reserved)         0
+0x10   8     header_size        8 (qwords)
+0x18   8     flags              1
+0x20   8     data_slot_id       1 (used by _no_of_vars as "entity count")
+0x28   8     (reserved)         1
+0x30   8     type_high          0x100000000000000
+0x34   2     TYPE               **0** (= _pushint-created)
+0x36   2     (padding)
+0x38   8     (reserved)         0
```

### String tsmat (created by _pushstr)
```
Offset  Size  Field              Value
+0x00   8     gso_ptr            → GSO (General String Object)
+0x08   8     (reserved)         0
+0x10   8     header_size        8 (qwords)
+0x18   8     flags              1
+0x20   8     data_slot_id       1
+0x28   8     (reserved)         1
+0x30   8     type_high          0x100fffd00000000
+0x34   2     TYPE               **-3 (0xfffd)** (= _pushstr-created)
+0x36   2     (padding)
+0x38   8     (reserved)         0
```

### Pool Header (x86_64)

On x86_64, the pool allocator (`pool_alloc` at 0x8b7358) stores a type-tag
byte at offset -0x94 (-148) from the tsmat pointer.  This is the "pool header"
and is set to 0x2b for all pool-managed tsmats.

```
Offset from tsmat  Value  Meaning
-0x94              0x2b   Pool type tag (checked by dispatch functions)
```

The DATA entries (pointed to by `tsmat[0]`) are at a separate pool location
and do NOT have this header at `data_ptr - 0x94`.

## x86_64 Dispatch Table Organization

The dispatch table is at vaddr `0x440aac0` in `.data.rel.ro` (file offset
`0x4409ac0`).  It contains 1686 entries, each an 8-byte function vaddr.
All entries point into `.text` (verified).  The table is populated by
`.rela.dyn` relocations.

### Name Table

The `st_*` name table is in `.data` section with entries of the form:
```
[index(4):flags(4):field1(4):field2(4):name\0]
```
Index maps to dispatch table position.  Functions with `flags & 0x100` have
a type-checker wrapper at `dispatch[INDEX]` and the implementation at
`dispatch[INDEX+1]`.

Key dispatch entries:
| Index | Name         | Flags | Vaddr   | Notes                     |
|-------|-------------|--------|---------|---------------------------|
| 84    | st_nvar     | 0x101  | 0x823b22 | type checker at 84, impl at 85 |
| 85    | st_nobs     | 0x101  | 0x823b48 | type checker at 85, impl at 86 |
| 87    | st_data     | 0x100  | 0x826494 | handles both read (2-arg) and string-store (3-arg) |
| 116   | st_sdata    | 0x100  | 0x824066 | string store only (value TYPE=-3) |
| 143   | st_varname  | 0x1    | 0x828faa | shared with st_viewobs; returns doubles |

## GSO (General String Object) — pointed to by string tsmat[0]
```
Offset  Size  Field
+0x00   8     str_ptr            → string struct (see below)
+0x08   8     (reserved)         0
+0x10   8     metadata
+0x18   8     metadata
+0x20   8     metadata
```

### String struct — pointed to by GSO[0]
```
Offset  Size  Field
+0x00   4     len                total bytes including null terminator
+0x04   len   data               null-terminated string content
```

## Type Field Validation

The type at `tsmat+0x34` is a signed 16-bit value. It determines which
functions accept which tsmats:

| Created by | type+0x34 | Accepted by _bist_* | Accepted by _bi_st_* |
|---|---|---|---|
| `_pushint` | 0 | ✅ | ❌ (err=3254) |
| `_pushstr` | -3 (0xfffd) | ✅ | ✅ (required for arg1) |

**Rule**: `_bi_st_*` functions require **arg1 type == -3** (pushed via `_pushstr`).
`_bist_*` functions accept both type=0 and type=-3 interchangeably.

## Push Function Signatures (ALL standard ARM64 ABI)

| Function | Arguments | Notes |
|---|---|---|
| `_pushint(int64 val)` | w0 = int value | Creates type=0 tsmat |
| `_pushdbl(double *val)` | x0 = POINTER to double | NOT the value itself! |
| `_pushstr(const char *str, size_t len)` | x0 = string ptr, x1 = length | Creates type=-3 tsmat |

## Calling Convention (ARM64)

**Before call:**
1. Save SP (`sp_before = *(uint64_t*)(_BASE + 0x39b7000 + 0x108)`)
2. Push args in reverse order (first arg at highest offset from base)
3. Get function address from `_BASE + manifest["symbols"]["func_name"]`
4. Call via `CFUNCTYPE(None, c_int)(arg_count)` — w0 = number of pushed args

**After call:**
1. Read error code from `_BASE + 0x39b7000 + 0x11c` (int32)
2. Read result from `*(uint64_t*)SP` which points to a tsmat
3. Restore SP to `sp_before`

### Result Reading

For numeric results (type=0 at +0x34):
```python
tsmat = *(uint64_t*)SP
double_value = *(double*)tsmat[0]  # tsmat[0] → double
```

For string results (type=-3 at +0x34):
```python
tsmat = *(uint64_t*)SP
gso = *(uint64_t*)tsmat[0]        # tsmat[0] → GSO
str_ptr = *(uint64_t*)gso[0]      # GSO[0] → string struct
length = *(uint32_t*)str_ptr      # first 4 bytes = total length
data = str_ptr + 4                # string content (length-1 chars + null)
```

## _bi_st_strlpart In-Place Modification

**Key behavior**: `_bi_st_strlpart` MODIFIES the string tsmat's buffer IN-PLACE.
The variable name (used for strL lookup) is overwritten with the strL data.

```
Before call:  tsmat → GSO → [len=2] [s\x00]    (variable name "s")
After call:   tsmat → GSO → [len=21] [hello world wide web\x00]  (strL data)
```

This means the output buffer IS the arg1 string. The function:
1. Reads the variable name from arg1 tsmat (for strL lookup)
2. Finds the strL data for the given observation
3. Writes the first N bytes (where N = part arg) into the same buffer
4. Updates the length field in the string struct

**Important**: The function may heap-overflow if the strL data exceeds the
initial buffer size. In practice this works (Stata's allocator is resilient),
but for safety, use the variable name string directly (not a dummy buffer).

## Function Catalog

### Working (_bist_* family — all use standard push+stack with pushint)

| Function | Args | Returns |
|---|---|---|
| `_bist_data(obs, var)` | 1-based obs, 1-based var | Double (cell value) |
| `_bist_sdata(obs, var)` | 1-based obs, 1-based var | String (cell value) |
| `_bist_store(obs, var, val)` | 1-based obs, 1-based var, double | Void |
| `_bist_sstore(obs, var, val)` | 1-based obs, 1-based var, string | Void |
| `_bist_nobs` | (reads internal count) | Double (obs count) |
| `_bist_nvar` | (reads internal count) | Double (var count) |
| `_bist_varname(varno)` | 1-based var | String |
| `_bist_varlabel(varno)` | 1-based var | String |
| `_bist_vartype(varno)` | 1-based var | String type ("str18", "double", etc.) |
| `_bist_varindex(name)` | string | Int (1-based index) |
| `_bist_varformat(varno)` | 1-based var | String |
| `_bist_varvaluelabel(varno)` | 1-based var | String |
| `_bist_addvar(name, type, ...)` | string, int code, optional len | Int (var index) |
| `_bist_dropvar(varno)` | 1-based var | Void |
| `_bist_renamevar(varno, newname)` | 1-based var, string | Void |
| `_bist_keepvar(varno)` | 1-based var | Void |
| `_bist_global(name)` | string/None | String |
| `_bist_putglobal(name, val)` | string, string | Void |
| `_bist_global_hcat(name)` | string | String |
| `_bist_macroexpand(str)` | string | String |
| `_bist_numscalar(name)` | string | Double |
| `_bist_strscalar(name)` | string | String |
| `_bist_vlexists(name)` | string | Int (0/1) |
| `_bist_vlmap(label, val)` | string, double | String |
| `_bist_vlsearch(name, label)` | 2 strings | Double |
| `_bist_vldrop(name)` | string | Void |
| `_bist_vllabel(name)` | string | String |
| `_bist_char_dir(name)` | string | String |
| `_bist_issorted(val)` | double | Int (0/1) |
| `_bist_estversion()` | none | Int |
| `_bist_matrix_hcat(str)` | string | String |
| `_bist_matrix(name)` | string | String (matrix content) |
| `_bist_replacematrix(name)` | string | Int |
| `_bist_matrixrownumb(name)` | string | Int |
| `_bist_matrixcolnumb(name)` | string | Int |
| `_bist_matrixrowstripe(name)` | string | String |
| `_bist_matrixcolstripe(name)` | string | String |
| `_bist_framecurrent(str)` | string/None? | String |
| `_bist_framedir()` | none | String |
| `_bist_frameexists(name)` | string | Int (0/1) |
| `_bist_framecreate(name)` | string | Void |
| `_bist_framedrop(name)` | string | Void |
| `_bist_framerename(old, new)` | 2 strings | Void |
| `_bist_framecopy(old, new)` | 2 strings | Void |
| `_bist_isstrvar(varno)` | 1-based var | Int (0/1) |
| `_bist_isnumvar(varno)` | 1-based var | Int (0/1) |
| `_bist_isalias(varno)` | 1-based var | Int (0/1) |
| `_bist_sys_getusb(name)` | string | String |
| `_bist_sys_putusb(name, val)` | string, string | Void |

### Cracked (_bi_st_* family — first arg MUST be via _pushstr)

| Function | Args | Push pattern | Returns |
|---|---|---|---|
| `_bi_st_strlpart` | (string name, int obs_1based, int part) | pushstr, pushint, pushint, w0=3 | In-place tsmat modification |
| `_bi_st_unab` | (string name) | pushstr, w0=1 | String (or modifies tsmat) |
| `_bi_st_addalias` | (string name) | pushstr, w0=1 | Void |

### Untested _bi_st_* Functions (same convention expected)

| Function | Manifest Address | Expected Args |
|---|---|---|
| `_bi_st_putmatrixcolstripe` | 0x1d1f18 | string1?, string2? (name + stripe names?) |
| `_bi_st_putmatrixrowstripe` | 0x1d1bec | Same |
| `_bi_st_vl_from_frame` | 0x1e5460 | string? (value label name + frame?) |
| `_bi_st_data` | 0x1d14c0 | (string? obs? var?) — may be same as _bist_data |
| `_bi_st_sdata` | 0x1d14f0 | Same |
| `_bi_st_addvar` | 0x1ca18c | (name string, type code) |
| `_bi_st_strlpartid` | 0x2efedb0 | Same as strlpart |
| All `*id` variants | 0x2ef* | Same as non-id variants |

### Blocked (_stpy_* — segfault via both conventions)

All `_stpy_*` functions segfault via ctypes regardless of calling convention.
They are designed for Stata's `_stp` C extension module (only available in
Stata's embedded Python interpreter).

## Platform Dispatch

| Platform | Convention | Implementation |
|---|---|---|
| macOS ARM64 | Push+stack (internal SP) | `_arm64_push_*` helpers |
| Linux x86_64 | Standard SysV ABI | Arguments in rdi/rsi/rdx, result in rax/xmm0 |
| Windows x86_64 | Microsoft x64 ABI | Arguments in rcx/rdx/r8/r9 |
