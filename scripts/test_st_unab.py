"""Test _bi_st_unab with various arg types.
Based on disassembly: it reads only SP[0] for 2-arg calls.
"""
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

SFIToolkit.executeCommand('sysuse auto, clear')
SFIToolkit.executeCommand('sysuse auto, clear')  # twice for clean state

_pushstr = eng._pushstr_fn
_pushint = eng._pushint_fn
_restore_sp = eng._restore_sp

# Try _bi_st_unab directly via call_string (engine wrapper)
print("=== Testing with engine wrapper ===", flush=True)
for args, desc in [
    ((b'make price',), "call_string(str)"),
    ((b'make',), "call_string('make')"),
    ((1,), "call_string(int=1)"),
]:
    err_before = ctypes.c_int32.from_address(err_addr).value
    try:
        r = call_string("_bi_st_unab", *args)
        err_after = ctypes.c_int32.from_address(err_addr).value
        print(f"  {desc:25s}: {r!r}  err={err_before}->{err_after}", flush=True)
    except Exception as e:
        print(f"  {desc:25s}: ERR {e}", flush=True)

# Try _bi_st_macroexpand  
print("\n=== Testing _bi_st_macroexpand ===", flush=True)
for args, desc in [
    ((b'make',), "string"),
    ((1,), "int"),
]:
    try:
        r = call_string("_bi_st_macroexpand", *args)
        print(f"  {desc:10s}: {r!r}", flush=True)
    except Exception as e:
        print(f"  {desc:10s}: ERR {e}", flush=True)

# Try _bi_st_global
print("\n=== Testing _bi_st_global ===", flush=True)
for args, desc in [
    ((b'make',), "string"),
    ((b'price',), "string"),
]:
    try:
        r = call_string("_bi_st_global", *args)
        print(f"  {desc:10s}: {r!r}", flush=True)
    except Exception as e:
        print(f"  {desc:10s}: ERR {e}", flush=True)

# Now try manually pushing + calling _bi_st_unab  
print("\n=== Manual push+call _bi_st_unab ===", flush=True)
fn_addr = base + manifest["symbols"]["_bi_st_unab"]
fn = ctypes.cast(fn_addr, ctypes.CFUNCTYPE(None, ctypes.c_int))

# Test 1: push string arg
sp_orig = ctypes.c_uint64.from_address(sp_addr).value
_pushstr(b'make price')
sp_after = ctypes.c_uint64.from_address(sp_addr).value
print(f"  SP after pushstr: {hex(sp_after)} delta={sp_after - sp_orig}", flush=True)

# Read the tsmat
tsmat = ctypes.c_uint64.from_address(sp_after).value
print(f"  tsmat: {hex(tsmat)}", flush=True)
for i in range(0, 64, 8):
    val = ctypes.c_uint64.from_address(tsmat + i).value
    print(f"    +{hex(i):4s}: {hex(val)}", flush=True)
# Check type at +0x34
type_val = ctypes.c_int16.from_address(tsmat + 0x34).value
print(f"  type at +0x34: {type_val} ({hex(type_val & 0xffff)})", flush=True)

# Call _bi_st_unab
err_before = ctypes.c_int32.from_address(err_addr).value
print(f"  Calling with w0=1...", flush=True)
try:
    fn(1)
    err_after = ctypes.c_int32.from_address(err_addr).value
    sp_fn = ctypes.c_uint64.from_address(sp_addr).value
    print(f"  Returned. err={err_before}->{err_after} SP={hex(sp_fn)}", flush=True)
    
    # Check for pushed result
    if sp_fn > sp_after:
        print(f"  Result pushed ({sp_fn - sp_after} bytes)", flush=True)
        tsmat_r = ctypes.c_uint64.from_address(sp_fn).value
        if tsmat_r:
            dp = ctypes.c_uint64.from_address(tsmat_r + 8).value
            print(f"  Result data ptr: {hex(dp)}", flush=True)
            if dp:
                str_p = ctypes.c_uint64.from_address(dp).value
                if str_p:
                    slen = ctypes.c_uint32.from_address(str_p).value
                    print(f"  Result str len: {slen}", flush=True)
                    if slen < 10000:
                        raw = ctypes.string_at(str_p + 4, min(slen, 200))
                        print(f"  Result: {raw!r}", flush=True)
except Exception as e:
    print(f"  CRASHED: {e}", flush=True)

_restore_sp(sp_orig)

# Check state
r = call_string("_bist_sdata", 1, 1)
print(f"\nState: {r!r}", flush=True)

print("\nDone", flush=True)
