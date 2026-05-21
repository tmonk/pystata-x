# x86_64 Discoveries & Design Decisions

> **Status**: 2026-05-21 — Goal "Replace all output-buffer fallbacks" substantially complete.
> - `_x86_display.py` **deleted** — all display-based fallbacks removed
> - **Zero** output-buffer parsing for data access
> - **Zero** pystata-analyzer runtime imports (framework is disassembly-only)
> - `call_string` uses **universal pattern**: no tsmat flag pre-set, auto-detect result type after call

---

## 1. Architecture: How the x86_64 Dispatch Path Actually Works

### Two Globals, Not One

x86_64 has **two separate globals** that were being conflated:

| Name | Address (x86_64 Linux) | Purpose | Set by |
|------|----------------------|---------|--------|
| **SP_global** | `_BASE + 0x500C638` | Reset by SP-resetting function thunks (ignored) | Dispatch functions themselves |
| **ARG_PTR** | `_BASE + 0x500C6A0` | Points to last pushed tsmat | `_pushint`/`_pushdbl`/`_pushstr` |

`_save_sp()` reads from ARG_PTR. Push functions write the tsmat pointer to `[ARG_PTR]` and advance ARG_PTR by 8.

### tsmat Structure (x86_64, Empirically Verified)

```
Offset  Field           Description
------  -----           -----------
[-0x94] pool_header     Always 0x2b for pool-allocated tsmats
[-0x10] self_ptr        Must point back to tsmat (free-list item otherwise)
[0x00]  data_buf        Double value (numeric) or pointer to GSO struct (string)
[0x34]  result_type     0xFFFD = string, 0x0000 = numeric (AFTER call)
[0x36]  arg_type        0 = string arg, non-zero = numeric arg (BEFORE call)
```

### Pool-Header Check

Pool-allocated tsmats always have `0x2b` at `tsmat[-0x94]`. Dispatch functions
that check this do so on the tsmat struct itself (not a separate data buffer).

### The Self-Pointer Patch

Pool-allocated tsmats have a stale **free-list pointer** at `tsmat[-0x10]`
instead of a self-reference. Functions that check `[tsmat[-0x10]]` need
`_patch_last_tsmat()` to restore `tsmat[-0x10] = tsmat`.

---

## 2. call_string Universal Pattern (The Critical Fix)

**Problem**: `call_string()` set `tsmat[0x34] = 0xFFFD` before the dispatch call
on x86_64. This caused SIGSEGV in functions that return numeric results
(e.g., `_bist_dir`, `_bist_varname`) because the dispatch function tried to
format a numeric result as a string, corrupting memory.

**Fix** — Universal pattern (no flag pre-set, auto-detect after call):

```
Before (crashed):               After (safe):
  tsmat[0x34] = 0xFFFD            # Don't set tsmat flag
  fn(args)                        fn(args)
  read_string(sp)                 check tsmat[0x34]:
                                    0xFFFD → read GSO string
                                    0x0000 → read double, str()
```

This is safe for ALL dispatch functions:
- String-return functions set `tsmat[0x34] = 0xFFFD` naturally
- Numeric-return functions leave `tsmat[0x34] = 0x0000`
- No crash for either type

ARM64 still uses the old `tsmat[0x34] = 0xFFFD` pre-set because ARM64 dispatch
functions expect the flag to be set before the call.

---

## 3. Dispatch Function Status (x86_64)

Results from framework's `CrashSafeProtocolTester` (subprocess isolation):

### WORKS (correct data returned)
| Function | Call | Returns |
|----------|------|---------|
| `_bist_nobs` | `call_double()` | 74.0 ✅ |
| `_bist_nvar` | `call_double()` | 12.0 ✅ |
| `_bist_data(obs, var)` | `call_double()` | cell value ✅ |
| `_bist_varlabel(var_idx)` | `call_string()` | 'Label text' ✅ |

### SAFE (echoes input, does NOT crash)
| Function | Behavior |
|----------|----------|
| `_bist_varname` | Echoes numeric input back as string |
| `_bist_numscalar` | Identity function (echoes input) |
| `_bist_strscalar` | Returns GSO pointer as double (garbage) |
| `_bist_macroexpand` | Echoes numeric input |
| `_bist_sdata` | Echoes input (no longer SIGSEGV) |
| `_bist_vlexists` | Returns None |
| `_bist_vlmap` | Echoes input |
| `_bist_dir` | Echoes input |
| `_bist_vlload` | Returns error code |

### BYPASSED (not in dispatch table)
| Function | Replacement |
|----------|-------------|
| `_bist_putglobal` | `execute("global name = value")` for writes |
| `_bist_global` | Not found — `execute()` for writes |
| `_stscalsave` | `execute("scalar name = value")` for writes |
| `_xgso_newcp_fast_code` | Not in dispatch table |

---

## 4. Data Access Strategies

### Strategy 1: Direct Dispatch (Works)
For `nobs`, `nvar`, `data`, `varlabel`:
```python
call_double("_bist_nobs")
call_double("_bist_nvar")
call_double("_bist_data", obs + 1, var + 1)
call_string("_bist_varlabel", float(var_idx))
```

### Strategy 2: Memory Read (Variable Metadata)
For `varname`, `vartype`:
```python
_read_var_name_x86(varno)   # Stride 129 in heap
_read_var_type_x86(varno)   # Stride 2, type codes decoded
```
These read directly from Stata's internal variable tables at known heap offsets.

### Strategy 3: Hybrid Execute-set + C-read (Scalars)
For numeric scalar reads:
```python
execute(f"quietly replace {TEMP_VAR} = scalar({name}) in 1")
call_double("_bist_data", 1, TEMP_VAR_INDEX)
```
`execute()` sets the var (write — permitted), `call_double` reads via C dispatch (safe).

### Strategy 4: Execute Write-Only (Store Operations)
For `storeDouble`, `storeString`, `setValue`:
```python
execute(f"quietly replace {varname} = {val} in {obs + 1}")
execute(f"scalar {name} = {value}")
```
These are write-only operations. No output buffer is read.

### Forbidden: Output Buffer Parsing
```python
# FORBIDDEN — never do this:
out, rc = execute(f"display scalar({name})")
val = float(out.strip())
```

---

## 5. Scalar Reader Implementation

### Numeric Scalars (Working)
Uses temp variable hybrid approach:
```python
# In _engine.py:
_temp_var = None  # Created on first use
execute("capture drop __px_scl")
execute("generate double __px_scl = 0")
_temp_var = int(call_double("_bist_nvar"))  # Last var index

def _read_scalar_x86(name):
    execute(f"quietly replace __px_scl = scalar({name}) in 1")
    return call_double("_bist_data", 1, _temp_var)
```

### String Scalars (Not Working)
String dispatch functions echo input on x86_64. `_read_string_scalar_x86()`
returns `""` as a known limitation. String scalar reads need direct memory
access to the GSO pointer in the scalar hash table entry.

---

## 6. Value Label Operations

All value label dispatch functions echo input on x86_64:
- `_bist_vlmap(name, value)` → `str(value)` (echo)
- `_bist_vlexists(name)` → None
- `_bist_dir(7)` → "7.0"
- `_bist_vlload(name)` → error code

**Current behavior**: Functions return echo data (wrong but safe — no crash).
No output-buffer parsing is used. Value label reads need the framework to
discover the hash table storage location in memory.

---

## 7. Framework Scope

`pystata-analyzer` is for **disassembly and protocol analysis only**.
It must NOT be imported at runtime by `pystata-x`.

Correct usage:
- **Development time**: Use framework to analyze binary, discover calling
  conventions, find memory offsets, test dispatch functions
- **Runtime**: Use the discovered patterns directly in `pystata_x` code
  (no framework imports)

The `_analyzer.py` bridge module is the ONLY allowed import from
pystata-analyzer, and only for binary analysis commands, not runtime data access.

---

## 8. Test Status

| Suite | Count | Status |
|-------|-------|--------|
| Unit tests (mocked) | 116 | ✅ All pass |
| E2E full_cycle | 11 | ✅ All pass |
| E2E SFI core (nobs, nvar, data, scalar num, varlabel) | ~50 | ✅ Pass |
| E2E SFI value labels | 5 | ❌ Echo data (wrong values, no crash) |
| E2E SFI scalar string | 1 | ❌ Returns "" |
| Framework internal | ~36 | ✅ |

---

## 9. Known Limitations (x86_64)

### Missing Direct Memory Readers
These need framework extension to discover storage locations:
- **String scalar storage** — GSO pointer not at same offset as numeric value
- **Value label hash table** — storage not yet located
- **Macro hash table** — global/local macro storage not found
- **c() value table** — system constant storage location unknown
- **Format string table** — per-variable format pointers not yet found

### Dispatch Functions That Echo
These are identity stubs on x86_64 (the real scalar/value-label lookup happens
in the expression evaluator, not dispatch):
- `_bist_numscalar`, `_bist_strscalar`
- `_bist_macroexpand`
- `_bist_vlmap`, `_bist_vlexists`, `_bist_vlload`, `_bist_dir`
- `_bist_varname`, `_bist_vartype`, `_bist_varformat`
