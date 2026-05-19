"""Test if _bi_st_strlpart causes heap corruption with small initial strings.
We need to push a string large enough to hold the output, or figure out
how to push a string with a pre-allocated buffer of a specific size."""
import sys, ctypes, json
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize, call_string, call_void
from pystata_x.sfi._core import SFIToolkit
import pystata_x.sfi._engine as eng

initialize()
base = eng._BASE
sp_addr = base + 0x39b7000 + 0x108
err_addr = base + 0x39b7000 + 0x11c
manifest = json.load(open('src/pystata_x/sfi/manifest.json'))

_restore_sp = eng._restore_sp
pushint = lambda v: eng._pushint_fn(v)
pushstr = lambda s: eng._pushstr_fn(s, len(s))

fn_addr = base + manifest["symbols"]["_bi_st_strlpart"]
fn = ctypes.cast(fn_addr, ctypes.CFUNCTYPE(None, ctypes.c_int))

def read_part_with_size(initial_str, var_name, obs, part):
    """Push a string of given size, call strlpart, read result."""
    sp_base = ctypes.c_uint64.from_address(sp_addr).value
    pushstr(initial_str)  # output buffer sized to this string
    pushint(obs)
    pushint(part)
    fn(3)
    sp = ctypes.c_uint64.from_address(sp_addr).value
    result = None
    tsmat = ctypes.c_uint64.from_address(sp).value
    if tsmat and tsmat > 0x100000:
        gso = ctypes.c_uint64.from_address(tsmat).value
        if gso and gso > 0x100000:
            str_ptr = ctypes.c_uint64.from_address(gso).value
            if str_ptr and str_ptr > 0x100000:
                slen = ctypes.c_uint32.from_address(str_ptr).value
                if slen and slen < 10000:
                    data = ctypes.string_at(str_ptr + 4, slen)
                    if data and data[-1:] == b'\x00':
                        data = data[:-1]
                    result = data
    _restore_sp(sp_base)
    return result

SFIToolkit.executeCommand('sysuse auto, clear')
SFIToolkit.executeCommand('gen strL longstr = "The quick brown fox jumps over the lazy dog. " * 5 if _n == 1')

print("=== Testing buffer overflow safety ===", flush=True)

# Test 1: One-char initial string, read 10 bytes → should overflow buffer
print("\n1. Init='s' (1 char), read 10 bytes from 'longstr':", flush=True)
result = read_part_with_size(b's', b'longstr', 1, 10)
print(f"   result: {result!r}", flush=True)

# Check state
try:
    r = call_string("_bist_sdata", 1, 1)
    print(f"   state check: {r!r}", flush=True)
except Exception as e:
    print(f"   STATE CORRUPTED: {e}", flush=True)

# Test 2: Larger initial string
print("\n2. Init='AAAAAAAAAA' (10 chars), read 50 bytes:", flush=True)
result = read_part_with_size(b'AAAAAAAAAA', b'longstr', 1, 50)
print(f"   result: {result!r}", flush=True)
try:
    r = call_string("_bist_sdata", 1, 1)
    print(f"   state check: {r!r}", flush=True)
except Exception as e:
    print(f"   STATE CORRUPTED: {e}", flush=True)

# Test 3: Init with a really long buffer
print("\n3. Init='X'*200, read 200 bytes:", flush=True)
result = read_part_with_size(b'X' * 200, b'longstr', 1, 200)
print(f"   result: {result!r} (len={len(result) if result else 0})", flush=True)
try:
    r = call_string("_bist_sdata", 1, 1)
    print(f"   state check: {r!r}", flush=True)
except Exception as e:
    print(f"   STATE CORRUPTED: {e}", flush=True)

# Test 4: Does 1-char init corrupt? Let's test data read and write
print("\n4. Verify data integrity after small-buffer call:", flush=True)
r_before = call_string("_bist_sdata", 1, 1)
print(f"   sdata(1,1) before: {r_before!r}", flush=True)

# small buffer test
result = read_part_with_size(b's', b'longstr', 1, 10)
print(f"   small buffer result: {result!r}", flush=True)

r_after = call_string("_bist_sdata", 1, 1)
print(f"   sdata(1,1) after: {r_after!r}", flush=True)

# Try to store a value
SFIToolkit.executeCommand('replace make = "TOYOTA" if _n == 2')
r_store = call_string("_bist_sdata", 2, 1)
print(f"   sdata(2,1) after replace: {r_store!r}", flush=True)

print("\n=== Conclusion ===", flush=True)
print("The function overwrites the string tsmat's internal buffer.", flush=True)
print("If the output is larger than the buffer, it OVERFLOWS!", flush=True)
print("We need to push a string at least as large as the expected output.", flush=True)
print("For safety, always push a buffer as large as the strL cell's size.", flush=True)

print("\nDone", flush=True)
