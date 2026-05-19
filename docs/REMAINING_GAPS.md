# Remaining API Gaps — Updated Analysis

## Status (2026-05-19)

**Current parity**: 203/203 methods covered across 18 classes.
- Working (via _bist_*/_bi_st_*): ~160 methods
- NotImplementedError with explanation (dead ends): ~43 methods
- Pure Python (no Stata calls needed): Platform, Datetime, some Data helpers

The _bi_st_* family calling convention has been **cracked**, enabling StrLConnector
read operations that were previously blocked.

## Key Discovery: _bi_st_* Calling Convention

The `_bi_st_*` functions use the **same push+stack convention** as `_bist_*`, but
with a critical difference in argument typing:

| Push function | tsmat type at +0x34 | Used for |
|---|---|---|
| `_pushint(val)` | `0` | Numeric/integer arguments |
| `_pushstr(s, len)` | `-3` (0xfffd) | String arguments — **required by _bi_st_*** |

**Rule**: The first argument to a `_bi_st_*` function MUST be created by `_pushstr`
(which produces a tsmat with type=-3 at offset +0x34). `_bist_*` functions accept
both type=0 and type=-3 tsmats interchangeably. `_bi_st_*` functions check the
type field and return err=3254 if it's wrong.

### Cracked Functions

| Function | Convention | Status |
|---|---|---|
| `_bi_st_strlpart(var_name, obs, part)` | pushstr(var_name), pushint(obs+1), pushint(part), w0=3 | **WORKS** — reads strL data in-place |
| `_bi_st_unab(var_name)` | pushstr(var_name), pushint(obs?), w0=1 or 2 | **WORKS** — err=0, state preserved |
| `_bi_st_addalias(var_name)` | pushstr(var_name), w0=1 | **WORKS** — err=0 |
| `_bi_st_strlpartid` | Same as strlpart at different address | Not tested |

All other `_bi_st_*` functions (putmatrixcolstripe, putmatrixrowstripe, vl_from_frame, etc.)
remain unproven but are expected to follow the same pattern (first arg via pushstr).

### tsmat Structure (complete)

```
Offset  Field
+0x00   tsmat[0] = data pointer
          For int: pointer to double value (8 bytes)
          For string: pointer to GSO (General String Object)
+0x08   tsmat[1] = 0 (secondary data)
+0x10   tsmat[2] = 0x8 (struct header size, 8 qwords)
+0x18   tsmat[3] = 0x1 (flags)
+0x20   tsmat[4] = 0x1 (data slot ID for int; or other metadata)
+0x28   tsmat[5] = 0x1
+0x30   tsmat[6] = type info high bits (0x100fffd00000000 for string, 0x100000000000000 for int)
+0x34   TYPE FIELD (signed 16-bit): 0=int, -3(0xfffd)=string
+0x38   tsmat[7] = 0x0
```

GSO structure (for string tsmats):
```
GSO[0] = pointer to string struct → [uint32 len] [char data[len+1]]
                                    len includes null terminator
                                    data is null-terminated
GSO[1] = 0
GSO[2..4] = metadata
```

## Gap Categorization (updated)

### 1. StrL Operations (17 methods) — PARTIALLY IMPLEMENTED

| Method | Status | Notes |
|---|---|---|
| StrLConnector.__init__ | ✅ Working | Var + obs constructor |
| StrLConnector.close/reset | ✅ Working | Pure Python |
| StrLConnector.getPosition/setPosition | ✅ Working | Pure Python |
| StrLConnector.getSize | ✅ Working | Uses _bi_st_strlpart with part=65535 |
| StrLConnector.readBytes(N) | ✅ Working | Uses _bi_st_strlpart with position tracking |
| StrLConnector.isBinary | ❌ NotImplementedError | Only _stpy_isstrlbinary exists (segfaults) |
| StrLConnector.writeBytes/storeBytes | ❌ NotImplementedError | Only _stpy_writebytes exists (segfaults) |
| Data.connect(name) | ✅ Working | Creates StrLConnector |
| Data.readBytes(sc, len) | ✅ Working | Delegates to sc.readBytes |
| Data.writeBytes/storeBytes | ❌ NotImplementedError | Stub |
| Data.addVarStrL(name) | ❌ NotImplementedError | _stpy_addvarstrl segfaults; use `gen strL` via SFIToolkit |
| Data.allocateStrL(sc, size) | ❌ NotImplementedError | _stpy_allocatestrl segfaults |
| Frame.addVarStrL/allocateStrL/readBytes/writeBytes/storeBytes | Same as Data | Implemented as stubs |

### 2. Matrix Operations (12 methods) — PARTIALLY IMPLEMENTED

| Method | Status | Notes |
|---|---|---|
| Matrix.getNames | ✅ Working | Uses _bist_matrix_hcat |
| Matrix.exists | ✅ Working | Checks name against getNames |
| Matrix.get | 🟡 Partial | Uses _bist_matrix (may need estimation results) |
| Matrix.getRowNames/getColNames | 🟡 Partial | Uses _bist_matrixrowstripe/colstripe |
| Matrix.getRowCount/getColCount | ❌ Broken | _bist_matrixrownumb/colnumb return 0 |
| Matrix.set | ❌ Broken | _bist_replacematrix needs data |
| Matrix.drop | ✅ Working | Uses _bist_matrix |
| Matrix.create/fromNPArray/etc. | ❌ NotImplementedError | Only _stpy_* exist |

All `_bist_matrix*` functions operate on Stata's **estimation results** system
(e(b), e(V)), not arbitrary user matrices created via `matrix define`. This is
a fundamental limitation.

`_bi_st_putmatrixcolstripe`/`_bi_st_putmatrixrowstripe` exist in manifest but
have not been successfully called (may need string-tsmat convention and
additional args).

### 3. Mata Operations (14 methods) — ALL BLOCKED

**Verdict**: TRULY IMPOSSIBLE. Zero `_bist_mata*` or `_bi_st_mata*` functions
exist in the manifest. All Mata operations require the `_stp` C extension which
is only available in Stata's embedded Python.

### 4. SFIToolkit Display/Eprint (8 methods) — INTENTIONALLY NOT IMPLEMENTED

User declined `executeCommand` wrapping for display/errprint/formatValue/listReturn.
Only `_stpy_*` functions exist which segfault via ctypes.

### 5. Characteristic.set* (2 methods) — ALL BLOCKED

`setDtaChar`/`setVariableChar`: only `_stpy_set*` exists (segfaults).

### 6. Frame.fromNPArray/fromPDataFrame (2 methods) — PARTIALLY IMPLEMENTED

Frame data access via shared `_bist_data` family works. fromNPArray/fromPDataFrame
are pure Python and can be implemented (not yet done).

## Summary Table

| Category | Total | Working | Stubbed | Notes |
|---|---|---|---|---|
| Data | 47 | 44 | 3 | addVarStrL, allocateStrL, writeBytes, storeBytes stubbed |
| Frame | 40 | 35 | 5 | Same gaps as Data plus fromNPArray/fromPDataFrame |
| Macro | 7 | 6 | 1 | delLocal stubbed |
| ValueLabel | 11 | 11 | 0 | All working |
| Missing | 6 | 6 | 0 | All working |
| SFIToolkit | 12 | 4 | 8 | display/errprint/formatValue/listReturn stubbed |
| SFIError | 3 | 3 | 0 | Simple exception classes |
| Platform | 7 | 7 | 0 | Pure Python |
| Characteristic | 4 | 2 | 2 | set* stubbed |
| Preference | 3 | 3 | 0 | All working |
| Datetime | 4 | 4 | 0 | Pure Python |
| Matrix | 12 | 5 | 7 | getRowCount/ColCount return wrong values |
| Mata | 14 | 0 | 14 | No _bist_mata* exist |
| StrLConnector | 10 | 7 | 3 | isBinary/write/storeBytes stubbed |
| Total | 180+ | ~150 | ~37 | (+ pure Python helpers) |

## How to Add New Methods

When a new `_bist_*` or `_bi_st_*` function is discovered:

1. **Check the manifest**: `grep "func_name" manifest.json`
2. **For `_bist_*` functions**: Use `call_int`/`call_double`/`call_string`/`call_void`
   with standard push+stack convention (all args via `_pushint`)
3. **For `_bi_st_*` functions**: First arg MUST use `_pushstr` (creates type=-3 tsmat).
   Use the engine's `_arm64_push_str` helper and call via direct CFUNCTYPE if
   the built-in `call_*` wrappers don't support mixed arg types.
4. **Test**: `python3 -m pytest tests/unit/ -x -q`
5. **Document**: Update this file and add to bi_st_analysis.md if it's a _bi_st_*
