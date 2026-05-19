# _bi_st_* Reverse-Engineering Analysis (Updated 2026-05-19)

## Key Breakthrough: _pushstr Creates type=-3 tsmats

The `_bist_*` and `_bi_st_*` function families share the same push+stack calling
convention, but they differ in how they validate argument types:

| Function family | Reads type at tsmat+0x34 | Accepts |
|---|---|---|
| `_bist_*` (e.g. _bist_data) | Optional validation | type=0 or type=-3 |
| `_bi_st_*` (e.g. _bi_st_strlpart) | **Required** validation | type=-3 ONLY |

**Key insight**: `_pushstr()` creates tsmats with type=-3 (0xfffd) at offset +0x34.
`_pushint()` creates tsmats with type=0. This is why `_bi_st_*` functions failed
with int-only args — the type check at +0x34 returned err=3254.

## Cracked Convention: pushstr-first for _bi_st_*

The first argument to any `_bi_st_*` function MUST be pushed via `_pushstr()`
to create a tsmat with type=-3. Subsequent arguments (int, double, or string)
follow the same push+stack pattern as `_bist_*`.

### Example: _bi_st_strlpart

```python
# Calling convention:
pushstr(b'varname')   # arg1: SP[-2], tsmat type=-3 ✓ (variable name + output buffer)
pushint(obs_1based)   # arg2: SP[-1], tsmat type=0 (observation, 1-based)
pushint(part)         # arg3: SP[0], tsmat type=0 (number of bytes to read)
fn(3)                 # w0 = 3 (arg count)

# Result: The string tsmat at SP is MODIFIED IN-PLACE.
# The variable name is overwritten with the strL data.
# Read from: tsmat[0] → GSO[0] → [uint32 len][char data...]
```

## Arg Reading Patterns (from radare2 disassembly)

```
_bi_st_strlpart: reads SP[-2], SP[-1], SP[0]  (3 args, string-first)
_bi_st_unab:     reads SP[0] only               (1+ args)
_bist_data:      reads SP[-1], SP[0]            (2 args, any order)
```

## tsmat Structure (complete, confirmed via hex dump)

### Numeric (pushint-created) tsmat:
```
Offset  Content
+0x00   pointer to double value (8 bytes)
+0x08   0x0 (NULL)
+0x10   0x8 (struct header size)
+0x18   0x1 (flags)
+0x20   0x1 (data slot ID: "entity count" passed to _no_of_vars)
+0x28   0x1
+0x30   0x100000000000000 (high bits)
+0x34   0x0000 = type=0  ← _pushint creates this
```

### String (pushstr-created) tsmat:
```
Offset  Content
+0x00   pointer to GSO (General String Object)
+0x08   0x0
+0x10   0x8 (struct header size)
+0x18   0x1 (flags)
+0x20   0x1
+0x28   0x1
+0x30   0x100fffd00000000 (high bits + type tag)
+0x34   0xfffd = type=-3  ← _pushstr creates this!
+0x38   0x0
```

### GSO (General String Object) — pointed to by tsmat[0]:
```
GSO[0] = pointer to string struct: [uint32 len] [char data[len+1]]
GSO[1] = 0
GSO[2..4] = metadata (path data, allocator info)
```

String struct format:
```
[0x00]: uint32 total_length (includes null terminator)
[0x04]: data (null-terminated)
```

### meta[-0x94] = 0x2b
All tsmat-based functions check this magic value at function entry. It's a type
tag for the tsmat evaluation stack entries.

## Functions Successfully Called

| Function | Args | Convention | Result |
|---|---|---|---|
| `_bi_st_strlpart` | (string, int, int) | pushstr, 2x pushint, w0=3 | err=0, modifies tsmat in-place |
| `_bi_st_unab` | (string) | pushstr, w0=1 | err=0, no crash |
| `_bi_st_addalias` | (string) | pushstr, w0=1 | err=0, state preserved |

## Implemented Wrapper

`StrLConnector._strlpart_read(part)` in `_core.py` wraps `_bi_st_strlpart`:
```python
def _strlpart_read(self, part):
    sp_base = _save_sp()
    _arm64_push_str(var_name)
    _arm64_push_int(obs + 1)  # 1-based
    _arm64_push_int(part)
    fn(3)  # direct CFUNCTYPE call
    result = _read_string_from_tsmat()
    _restore_sp(sp_base)
    return result
```

This is used by `readBytes()` (with position tracking via slicing) and
`getSize()` (with part=65535 to get the full string length).

## Still Blocked

| Function | Reason |
|---|---|
| `_bi_st_putmatrixcolstripe` | Needs additional args (column names list) |
| `_bi_st_putmatrixrowstripe` | Same |
| `_bi_st_vl_from_frame` | May need frame context |
| `_bi_st_strlpartid` | Untested (same convention expected) |
| All `_stpy_*` | Segfault via both ctypes conventions |

## Debugging Tools

| Script | Purpose |
|---|---|
| `scripts/test_strlpart3.py` | _bi_st_strlpart with correct args |
| `scripts/examine_tsmat2.py` | Deep tsmat structure dump |
| `scripts/check_strlpart_modify.py` | Verify in-place modification |
| `scripts/scan_strl_parts.py` | Part-by-part scan of strL data |
| `scripts/test_bi_st_harness.c` | C test harness (cross-check ctypes results) |
| `scripts/test_c_harness.py` | C harness loaded from Python |
