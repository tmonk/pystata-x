# _bi_st_* Reverse Engineering — Final Report

## What Was Done

**Success Criteria Achieved:**

1. ✅ **radare2 installed** — v6.1.4 via `brew install radare2`
2. ✅ **Side-by-side disassembly comparison** — `_bi_st_strlpart` vs `_bist_data` compared, key differences documented in `docs/bi_st_analysis.md`
3. ✅ **lldb infrastructure** — breakpoint capture scripts built and tested
4. ✅ **C test harness** — `scripts/test_bi_st_harness.c` compiled to `.dylib`, loaded from Python to prove calling convention works without ctypes FFI
5. ✅ **Calling convention cracked** — `_bi_st_strlpart` callable with (string, int, int) args, err=0, state preserved
6. ✅ **Working Python probe** — `scripts/test_strlpart3.py` demonstrates correct calling convention
7. ✅ **Remaining gaps documented** — `docs/bi_st_analysis.md` and `docs/REMAINING_GAPS.md` updated
8. ✅ **All unit tests pass** — no regressions

## Key Findings

### The Calling Convention

`_bi_st_*` functions use the **same push+stack convention** as `_bist_*`, but with critical differences:

| Aspect | `_bist_*` | `_bi_st_*` |
|--------|-----------|------------|
| Arg reading | SP[0], SP[-1] (2 args) | Varies: strlpart reads SP[-2], SP[-1], SP[0] (3 args) |
| tsmat type | type=0 at +0x34 | type=-3 (0xfffd) for string-like args |
| Error on wrong type | err=0xc82 (3202) | err=0xcb6 (3254) |
| Result | Pushed to stack | May modify tsmat in-place |

### Cracked Functions

**`_bi_st_strlpart`**: 
- Needs 3 args: (string_name, int_obs, int_part)
- String arg MUST be pushed via `_pushstr` (creates type=-3 tsmat)
- Int args via `_pushint` (type=0 tsmat)
- Returns: err=0, SP decreases by 16 (consumes 2 ints, leaves string)
- State preserved after call
- **Does NOT push a result to the stack** — result may be in tsmat modification

**`_bi_st_unab`** (variable name unabbreviation):
- Needs 1 string arg via `_pushstr`
- Returns: err=0, no result pushed
- State preserved

### tsmat Structure (confirmed by hex dump)

```
Offset  Field
+0x00   next pointer (link to previous tsmat)
+0x08   data pointer (NULL for pushint/pushstr-created tsmats)
+0x10   length/flag (0x8 for ints)
+0x18   flag (0x1)
+0x20   value/type field 1 (0x1 for ints)
+0x28   value/type field 2 (0x1 for ints)
+0x30   type info high bits
+0x34   TYPE FIELD (signed 16-bit):
        0 = _pushint-created tsmat
        -3 (0xfffd) = _pushstr-created tsmat
+0x38   reserved
-0x94   0x2b magic value (function entry check)
```

### Unresolved

- `_bi_st_strlpart` doesn't push a result to the stack; the part data must be extracted differently (maybe through tsmat data pointer modification, or the function writes to a buffer)
- `_bi_st_putmatrixcolstripe` crashes — may need a Matrix handle arg
- `_bi_st_vl_from_frame` crashes — may need Frame context set up
- Some `_bi_st_*` functions may genuinely be internal helpers that don't produce user-facing output

## Deliverables

| File | Purpose |
|------|---------|
| `scripts/test_bi_st_harness.c` | C shared library for calling _bi_st_* from C (proves convention) |
| `scripts/test_bi_st_harness.dylib` | Compiled shared library |
| `scripts/test_strlpart3.py` | Python probe for _bi_st_strlpart with correct arg types |
| `scripts/test_unab2.py` | Python probe for _bi_st_unab |
| `scripts/test_c_harness.py` | Test harness loading C library from Python |
| `scripts/examine_tsmat.py` | Tsmat structure hex dump tool |
| `docs/bi_st_analysis.md` | Detailed analysis of disassembly findings |
| `docs/REMAINING_GAPS.md` | Updated gap analysis |
