"""Test _bi_st_unab with call_void (no result read) and manually check stack."""
import sys, ctypes, json
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize, call_void, call_string
from pystata_x.sfi._core import SFIToolkit
import pystata_x.sfi._engine as eng

initialize()
base = eng._BASE
sp_addr = base + 0x39b7000 + 0x108
err_addr = base + 0x39b7000 + 0x11c
manifest = json.load(open('src/pystata_x/sfi/manifest.json'))

SFIToolkit.executeCommand('sysuse auto, clear')

_restore_sp = eng._restore_sp
pushint = lambda v: eng._pushint_fn(v)
pushstr = lambda s: eng._pushstr_fn(s, len(s))
pushdbl = lambda v: eng._pushdbl_fn(ctypes.addressof(ctypes.c_double(v)))

sp_orig = ctypes.c_uint64.from_address(sp_addr).value

# Test _bi_st_unab with string arg via call_void
print("=== _bi_st_unab tests ===", flush=True)
for args, desc in [
    ((b'make',), "str='make'"),
]:
    err_before = ctypes.c_int32.from_address(err_addr).value
    sp_before = ctypes.c_uint64.from_address(sp_addr).value
    try:
        call_void("_bi_st_unab", *args)
        err_after = ctypes.c_int32.from_address(err_addr).value
        sp_after = ctypes.c_uint64.from_address(sp_addr).value
        pushed = sp_after - sp_before
        # Don't trust automatic result reading, just check SP delta
        print(f"  {desc}: err={err_before}->{err_after} SP={hex(sp_before)}->{hex(sp_after)} pushed={pushed}", flush=True)
    except Exception as e:
        print(f"  {desc}: ERR {e}", flush=True)

# Now manually push str + call unab to check result pattern
print("\n=== Manual unab ===", flush=True)
fn_addr = base + manifest["symbols"]["_bi_st_unab"]
fn = ctypes.cast(fn_addr, ctypes.CFUNCTYPE(None, ctypes.c_int))

sp_base = ctypes.c_uint64.from_address(sp_addr).value
print(f"SP base: {hex(sp_base)}", flush=True)

pushstr(b'make')
sp = ctypes.c_uint64.from_address(sp_addr).value
print(f"SP after pushstr: {hex(sp)} delta={sp - sp_base}", flush=True)

# Read tsmat
tsmat = ctypes.c_uint64.from_address(sp).value
type_val = ctypes.c_int16.from_address(tsmat + 0x34).value
print(f"string tsmat: {hex(tsmat)} type@+0x34={type_val} ({hex(type_val & 0xffff)})", flush=True)

# Call
err_before = ctypes.c_int32.from_address(err_addr).value
print(f"Calling w0=1...", flush=True)
fn(1)
err_after = ctypes.c_int32.from_address(err_addr).value
sp_fn = ctypes.c_uint64.from_address(sp_addr).value
print(f"Returned: err={err_before}->{err_after} SP={hex(sp_fn)} delta={sp_fn - sp}", flush=True)

if sp_fn > sp:
    tsmat_r = ctypes.c_uint64.from_address(sp_fn).value
    print(f"Result tsmat: {hex(tsmat_r)}", flush=True)
    if tsmat_r:
        for i in range(0, 48, 8):
            v = ctypes.c_uint64.from_address(tsmat_r + i).value
            print(f"  +{hex(i):4s}: {hex(v)}", flush=True)
        dp = ctypes.c_uint64.from_address(tsmat_r + 8).value
        if dp:
            sp2 = ctypes.c_uint64.from_address(dp).value
            print(f"  str_ptr: {hex(sp2)}", flush=True)
            if sp2:
                slen = ctypes.c_uint32.from_address(sp2).value
                print(f"  str_len: {slen}", flush=True)
                if slen < 10000:
                    raw = ctypes.string_at(sp2 + 4, min(slen, 200))
                    print(f"  str: {raw!r}", flush=True)

_restore_sp(sp_base)

# Final state check
r = call_string("_bist_sdata", 1, 1)
print(f"\nFinal state: {r!r}", flush=True)
print("Done", flush=True)
