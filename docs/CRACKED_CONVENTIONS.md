# CRACKED_CONVENTIONS — Complete tsmat Structure & Calling Convention Reference

> **IMPORTANT**: This document covers the ARCHITECTURAL understanding of the calling
> convention. For detailed x86_64-specific discoveries (ARG_PTR vs SP_global,
> display-based fallback, variable metadata memory reading, pool-header catalog),
> see [X86_64_DISCOVERIES.md](X86_64_DISCOVERIES.md).

## Key Discovery (2026-05-21): Two Globals, Not One

The highest-impact discovery was that x86_64 has **two separate globals** that
were conflated for weeks:

| Name | Address (x86_64 Linux) | Purpose |
|------|----------------------|---------|
| **SP_global** | `_BASE + 0x500C638` | Reset by SP-resetting function thunks; **they reset this, we ignore it** |
| **ARG_PTR** | `_BASE + 0x500C6A0` | Points to last pushed tsmat; **this is what push functions update and dispatch functions read** |

`_save_sp()` reads from ARG_PTR. `_push_int()`/`_push_dbl()`/`_push_str()` write
to `[ARG_PTR]` and advance ARG_PTR by 8. The `_STACK_PTR_OFFSET` in the manifest
(`0x500C6A0`) equals ARG_PTR, NOT SP_global.

The existing push+stack protocol is already correct for ALL dispatch functions.
No changes needed to the push+stack code path after this understanding.

## Key Discovery: Pool-Allocated tsmat Data is Embedded

There is **no separate data buffer**. The tsmat struct holds the value directly:
- `tsmat[0]` = pointer to double value (numeric) or GSO pointer (string)
- `tsmat[-0x94]` = 0x2b pool-header tag (always set by pool allocator)
- `tsmat[-0x10]` = **stale free-list pointer** (not a self-reference)

**Fix** (`_patch_last_tsmat()`): After every push, set `tsmat[-0x10] = tsmat`
so that dispatch functions' `[tsmat[-0x10] - 0x94]` check reads `tsmat[-0x94]`
which has the 0x2b tag.

## Key Discovery: String Sentinel Protocol

String-returning functions need **NO separate sentinel push**. `_push_str` creates
a tsmat with `[0x34] = 0xFFFD` which acts as both argument AND sentinel.
`call_string()` sets `tsmat[0x34] = 0xFFFD` on the last pushed tsmat.

## Older discoveries below remain correct in their architecture but may need
## x86_64-specific corrections. See X86_64_DISCOVERIES.md for current status.

[291 more lines in file. Use offset=21 to continue.]

### Platform-specific type checking
On x86_64, the dispatch table functions were compiled with additional
run-time type checks that are absent from the ARM64 builds.

**tsmat[-0x94] check**: Some functions check the byte at `tsmat_ptr - 148`
for value 0x2b (the pool header tag).  Pool-allocated tsmats always have
0x2b at this offset.  These functions work with push+stack tsmats.

**data_ptr[-0x94] check**: OBSOLETE understanding. The data is EMBEDDED
in the tsmat pool allocation, not at a separate location. See
X86_64_DISCOVERIES.md for corrected understanding.

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
