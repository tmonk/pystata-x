# Remaining API Gaps (x86_64)

**Status**: 2026-05-21 — Display-based fallback replacement complete
- `_x86_display.py` deleted ✅
- Zero output-buffer parsing for data access ✅
- Zero pystata-analyzer runtime imports ✅

---

## Currently Working (via dispatch or memory)

| Class | Method | Strategy |
|-------|--------|----------|
| Data | `getVarCount()` | `call_double("_bist_nvar")` |
| Data | `getObsTotal()` | `call_double("_bist_nobs")` |
| Data | `getDouble(varno, obs)` | `call_double("_bist_data", obs+1, var+1)` |
| Data | `getVarLabel(varno)` | `call_string("_bist_varlabel", float(varno+1))` |
| Data | `getVarName(varno)` | `_read_var_name_x86(varno)` — direct memory |
| Data | `getVarType(varno)` | `_read_var_type_x86(varno)` — direct memory |
| Data | `getMaxVars()` | Fallback 32767 |
| Data | `storeDouble()` | `execute("replace ...")` — write only |
| Data | `storeString()` | `execute("replace ...")` — write only |
| Scalar | `getValue(name)` | Hybrid temp-var: `execute("replace")` + `call_double("_bist_data")` |
| Scalar | `setValue(name)` | `execute("scalar name = value")` — write only |
| Scalar | `setString(name)` | `execute('scalar name = "value"')` — write only |

---

## Current Gaps (need direct memory readers)

### 1. String Scalar Reads (`Scalar.getString()`)
- **Problem**: `_bist_strscalar` echoes input (identity function on x86_64)
- **Returns**: `""` (empty string)
- **Need**: Locate string scalar GSO pointer in the scalar hash table entry

### 2. Value Label Functions (`ValueLabel.*`)
- **Problem**: All `_bist_vl*` dispatch functions echo input or return None
- **Returns**: Echo data instead of real labels (wrong values, no crash)
- **Affected**: `getNames()`, `getLabel()`, `getLabels()`, `getValues()`,
  `exists()`, `getValueLabel()`, `getVarValueLabel()`
- **Need**: Locate value label hash table in Stata memory

### 3. Format String Reads (`Data.getVarFormat()`)
- **Problem**: `_bist_varformat` crashes on x86_64
- **Current**: Returns hardcoded format strings for auto dataset only
- **Need**: Locate per-variable format string pointers in Stata heap

### 4. Macro Reads (`Macro.getGlobal()`, `Macro.getLocal()`)
- **Problem**: `_bist_global`/`_bist_macroexpand` echo input
- **Current**: `execute()` for writes only (reads return echo data)
- **Need**: Locate macro hash table in Stata memory

### 5. `getMaxVars()` — No Dispatch Entry
- **Problem**: No `_bist_k` or `_stpy_getmaxvars` in x86_64 dispatch table
- **Current**: Returns 32767 (Stata SE/MP default)
- **Need**: Locate `c(maxvar)` value in Stata's .bss or runtime memory

### 6. `getFormattedValue()` — Format String Dependency
- **Problem**: Depends on format string read (gap #3 above)
- **Current**: Returns `str(call_double(...))` — unformatted

---

## Strategy for Fixing Each Gap

### General Approach
1. **Use the framework** (`pystata-analyzer`) to analyze the binary:
   - Disassemble the relevant `_bist_*` function to find its .bss/heap references
   - Use `StataBinary.analyze_dispatch_fn()` to find memory offset patterns
   - Use `CrashSafeProtocolTester` to verify dispatch behavior
2. **Add a direct memory reader** to `_engine.py`:
   - Read from the discovered heap/.bss offset
   - Use `ctypes` for raw memory access
   - Cache results for performance
3. **Update `_core.py`** to use the new reader

### Specific Strategies

| Gap | Analysis Target | Expected Offset Source |
|-----|----------------|----------------------|
| String scalar | `_bist_strscalar` dispatch code | GSO pointer in scalar entry |
| Value labels | `_bist_vlmap` / `_bist_vlload` code | Value label hash table |
| Format strings | `_bist_varformat` crash analysis | Per-var pointer table near name table |
| Macros | `_bist_macroexpand` / `_bist_global` code | Macro hash table in .bss |
| c(maxvar) | Expression evaluator code (0x81d3xx) | .bss global near nvar |

---

## Never-Will-Work Operations

These require Stata's embedded Python (`_stpy_*` functions), which is NOT
available from external Python:

| Operation | Reason |
|-----------|--------|
| `StrLConnector.writeBytes()` | No Stata command for byte-level strL buffer writes |
| `Data.writeBytes()` | Delegates to StrLConnector |
| `Data.allocateStrL()` | Requires `_stpy_allocatestrl` |
| `StrLConnector.isBinary` | Requires `_stpy_isstrlbinary` |
| `Data.storeBytes()` | Delegates to StrLConnector.storeBytes |

---

## Design Decisions

### Framework Scope
`pystata-analyzer` is **disassembly/analysis only** — NOT a runtime dependency.
Runtime code in `pystata-x` must be self-contained (only stdlib + ctypes).

### Output Buffer Parsing
`execute()` output is NOT parsed for data access. `execute()` is used only for
write/set operations where output is discarded. The `GetOutputBuffer` function
is called ONLY by the infrastructure layer (`_engine.py`'s `execute()`) — never
by data-access code.

### Hybrid Execute-Set / C-Read
The sole permitted pattern for combining Stata commands with C dispatch:
```python
execute("replace __tmp = scalar(name) in 1")  # write (permitted)
val = call_double("_bist_data", 1, tmp_idx)   # read via C dispatch
```

### Test Strategy
- **Unit tests**: Mock dispatch functions, test `_core.py` logic
- **E2e tests**: Real Stata engine, verify against oracle values
- **Crash-safe tests**: Subprocess isolation via `CrashSafeProtocolTester`
- Value label tests produce echo data (known, documented gaps)
