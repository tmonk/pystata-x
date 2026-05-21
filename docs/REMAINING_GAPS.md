# Remaining API Gaps

## Status (2026-05-19 — post manifest overhaul + executeCommand migration)

**SFI parity:** ~196/203 methods implemented across 18 classes.
- Working (via `_bist_*`/`_bi_st_*` C calls): ~120 methods
- Working (via `display` based fallback): ~15 methods (on x86_64) — ***NEXT GOAL: replace all***
- Working (via `executeCommand`): ~40 methods (Matrix, Mata, SFIToolkit display, Characteristic.set*, Data.addVarStrL)
- Pure Python (no Stata calls): ~20 methods

> **See [X86_64_DISCOVERIES.md](X86_64_DISCOVERIES.md) for detailed x86_64 status of each operation.**

## CURRENT GOAL: Replace Display-Based Fallbacks

The following functions use `StataSO_Execute` + output buffer parsing instead
of proper dispatch-path calls. Each must be replaced with dispatch-path fixes
or direct memory reading:

| Function | Display Approach | Replacement Strategy |
|----------|-----------------|---------------------|
| `read_double(varno, obs)` | `display varname[obs+1]` | Fix `_bist_data` global data struct pointer |
| `read_string(varno, obs)` | `display varname[obs+1]` | Fix `_bist_sdata` dispatch path |
| `read_scalar(name)` | `display scalar(name)` | Fix `_bist_numscalar` dispatch path |
| `read_string_scalar(name)` | `display scalar(name)` | Fix `_bist_strscalar` dispatch path |
| `get_macro(name)` | `display "$" + name` | Fix `_bist_global` dispatch path |
| `set_macro(name, value)` | `global name value` | Fix `_bist_putglobal` |
| `del_macro(name)` | `macro drop name` | Fix `_bist_putglobal` |
| `store_double(varno, obs, val)` | `replace ... in N` | Fix `_bist_store` dispatch path |
| `store_string(varno, obs, val)` | `replace ... in N` | Fix `_bist_sstore` dispatch path |
| `read_var_value_label(varno)` | compound quoting | Fix `_bist_varvaluelabel` |
| `read_value_label_names()` | `label dir` | Fix `_bist_vlsearch` |
| `read_value_label(name)` | `label list name` | Fix `_bist_vlload` |
| `read_value_label_values(name)` | `label list name` | Fix `_bist_vlmodify` read path |
| `read_value_label_exists(name)` | `label list name` | Fix `_bist_vlexists` |

**Format strings** (`_read_var_format_x86()`): Uses hardcoded `_AUTO_FORMATS`
list (12 auto-dataset entries). Must be replaced by reading format table from
Stata heap memory (like we do for names/types).

---

### Original content below (previously accurate, preserved for reference)


- Working (via `_bist_*`/`_bi_st_*` C calls): ~120 methods
- Working (via `executeCommand`): ~40 methods (Matrix, Mata, SFIToolkit display, Characteristic.set*, Data.addVarStrL)
- Pure Python (no Stata calls): ~20 methods
- `NotImplementedError` (genuinely impossible): ~15 methods (StrL write operations)

### Major Milestones

| Date | Achievement |
|---|---|
| 2026-05-19 | **Manifest overhaul**: All hardcoded function addresses replaced with manifest lookups. Multi-tier loader: shipped manifests + auto-generation + permanent caching. `_OBS_ADDR_RELATIVE` replaced with `call_double("_bist_nobs")`/`call_double("_bist_nvar")`. |
| 2026-05-19 | **Matrix fully implemented**: All 17 reference API methods via executeCommand. `_bist_matrix*` C functions abandoned (they operate on estimation results bytecode, not user matrices). |
| 2026-05-19 | **Mata fully implemented**: All 17 reference API methods via executeCommand with `mata:` prefix. |
| 2026-05-19 | **SFIToolkit display**: display/displayln/errprint/errprintln/formatValue/listReturn all via executeCommand. |
| 2026-05-19 | **Characteristic.setDtaChar/setVariableChar**: Implemented via executeCommand (`char define`). |
| 2026-05-19 | **Data.addVarStrL**: Implemented via executeCommand (`generate strL ...`). |
| 2026-05-19 | **Frame.fromNPArray/fromPDataFrame**: Instance methods that delegate to Data class methods. |
| 2026-05-19 | **Scalar set functions**: `call_set_scalar`/`call_set_strscalar` use manifest lookups for `_stscalsave`, `_xgso_newcp_fast_code`, `_put_xgso_scalar` instead of hardcoded addresses. |

## Genuinely Impossible Operations

These are NOT stubbed due to laziness — they require Stata internal APIs that:
1. Only exist as `_stpy_*` functions (require embedded Python context)
2. Have no `_bist_*` or `_bi_st_*` equivalent
3. Cannot be replicated via Stata commands (no `executeCommand` alternative)
4. Segfault when called via ctypes from external Python

### 1. StrL Write Operations (the big gap)

StrL (long string) variables require several C-level operations that have no
Stata command equivalent:

| Method | Why Impossible |
|---|---|
| `StrLConnector.writeBytes(data, offset, length)` | Requires `_stpy_storebytes1`/`_stpy_storebytes2` — byte-level strL buffer manipulation. No Stata command for this. |
| `StrLConnector.storeBytes(data, binary)` | Same as above — calls writeBytes internally. |
| `Data.writeBytes(sc, b, off, length)` | Delegates to StrLConnector.writeBytes. |
| `Data.storeBytes(sc, b, binary)` | Delegates to StrLConnector.storeBytes. |
| `Data.allocateStrL(sc, size, binary)` | Requires `_stpy_allocatestrl` — allocates strL buffer. No Stata command equivalent. |
| `StrLConnector.isBinary` | Requires `_stpy_isstrlbinary` — checks strL binary flag. No Stata command equivalent. |

**Workaround**: Users needing strL write functionality can use Stata's embedded
Python (`python:`) where `_stp` extension is available, or use Stata commands
like `strL store` which operates at a higher level.

### 2. Internal State Data Offsets (permanent exceptions)

These are NOT function pointers — they are Stata internal data structure offsets
derived from push function disassembly. They cannot be replaced by manifest
symbol lookups:

| Constant | Address | Purpose | Reason Permanent |
|---|---|---|---|
| `_STACK_PTR_OFFSET` | `0x39b7000 + 0x108` | Internal stack pointer for all ARM64 push/pop operations | Fundamental to ARM64 calling convention; derived from `_pushdbl` disassembly |
| `_ERR_ADDR_RELATIVE` | `0x39b7000 + 0x11c` | Error status after store operations (`_bist_store`/`_bist_sstore`) | Written by `_st_store_u` internal function; no `_bist_*` read equivalent |

## Implementation Notes

### Matrix — ExecuteCommand Approach

All `_bist_matrix*` functions in the manifest operate on Stata's **bytecode
dispatch system** for estimation results (e(b), e(V)), NOT on user-created
matrices. Calling them with arbitrary matrix names corrupts internal state.

The solution: use `executeCommand` with standard Stata matrix commands:
- `matrix name = (values)` — create/replace
- `matrix colnames name = ...` / `matrix rownames name = ...` — naming
- `matrix list name` / `matrix input` — reading
- All 17 reference API methods implemented via this approach.

### Mata — ExecuteCommand Approach

Zero `_bist_mata*` functions exist in any manifest. The solution: use
`executeCommand` with `mata:` prefix:
- `mata: name = J(nrows, ncols, val)` — create
- `mata: st_local("__px_val", name[r,c])` — read elements
- `mata: name[r,c] = val` — write elements
- All 17 reference API methods implemented via this approach.

### Scalar Set — Manifest Lookups

`call_set_scalar` uses `_sym_addr("_stscalsave")` and `call_set_strscalar` uses
`_sym_addr("_xgso_newcp_fast_code")` + `_sym_addr("_put_xgso_scalar")`. These
are standard ARM64 ABI functions (not internal-stack based), called via CFUNCTYPE
with register arguments.

## How to Add New Methods

When a new `_bist_*` or `_bi_st_*` function is discovered:

1. **Check the manifest**: `python3 -c "import json; m=json.load(open('src/pystata_x/sfi/manifest.json')); print(name in m['symbols'])"`
2. **For `_bist_*` functions**: Use `call_int`/`call_double`/`call_string`/`call_void`
   with standard push+stack convention (all args via `_pushint`/`_pushdbl`/`_pushstr`)
3. **For `_bi_st_*` functions**: First arg MUST use `_pushstr` (creates type=-3 tsmat).
4. **Test**: `.venv/bin/python -m pytest tests/unit/ -x -q`
5. **Document**: Update this file and CRACKED_CONVENTIONS.md if applicable.
