"""Test _bi_st_strlpart with correct tsmat types.
arg1 (SP[-2]): string tsmat (type=-3 at +0x34) ✓
arg2 (SP[-1]): int tsmat
arg3 (SP[0]):  int tsmat
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
# Make a strL variable
SFIToolkit.executeCommand('gen strL s = "hello world wide web" if _n == 1')

_restore_sp = eng._restore_sp
pushint = lambda v: eng._pushint_fn(v)
pushstr = lambda s: eng._pushstr_fn(s, len(s))

fn_addr = base + manifest["symbols"]["_bi_st_strlpart"]
fn = ctypes.cast(fn_addr, ctypes.CFUNCTYPE(None, ctypes.c_int))

sp_base = ctypes.c_uint64.from_address(sp_addr).value
print(f"SP base: {hex(sp_base)}", flush=True)

# Push args in order that achieves SP[-2]=string, SP[-1]=int, SP[0]=int
# First push = SP[-2] (deepest), last push = SP[0] (top)
# String first, then var index, then part index?
# Or: string name, obs, var?
# Let me try: str "s" (var name), int 1 (obs), int 1 (which part?)

pushstr(b's')     # arg1: variable name (string, type=-3)
pushint(1)        # arg2: obs index (1-based)  
pushint(1)        # arg3: part number (1-based? or 0-based?)

sp = ctypes.c_uint64.from_address(sp_addr).value
print(f"SP after pushes: {hex(sp)} delta={sp - sp_base}", flush=True)

# Check tsmat types
for i in range(-2, 1):
    addr = sp + i * 8
    tsmat = ctypes.c_uint64.from_address(addr).value
    if tsmat:
        typ = ctypes.c_int16.from_address(tsmat + 0x34).value
        print(f"  SP[{i:+d}] tsmat={hex(tsmat)} type={typ}", flush=True)

# Call
err_before = ctypes.c_int32.from_address(err_addr).value
print(f"\nCalling with w0=3...", flush=True)
try:
    fn(3)
    err_after = ctypes.c_int32.from_address(err_addr).value
    sp_fn = ctypes.c_uint64.from_address(sp_addr).value
    print(f"Returned: err={err_before}->{err_after} SP={hex(sp_fn)} delta={sp_fn - sp}", flush=True)
    
    if sp_fn > sp:
        tsmat = ctypes.c_uint64.from_address(sp_fn).value
        print(f"Result tsmat: {hex(tsmat)}", flush=True)
        if tsmat:
            dp = ctypes.c_uint64.from_address(tsmat + 8).value
            print(f"  data_ptr: {hex(dp)}", flush=True)
            if dp:
                sp2 = ctypes.c_uint64.from_address(dp).value
                print(f"  str_ptr: {hex(sp2)}", flush=True)
                if sp2 and sp2 > 0x100000:
                    slen = ctypes.c_uint32.from_address(sp2).value
                    print(f"  len: {slen}", flush=True)
                    if slen < 10000:
                        raw = ctypes.string_at(sp2 + 4, min(slen, 200))
                        print(f"  str: {raw!r}", flush=True)
except Exception as e:
    print(f"CRASHED: {e}", flush=True)

_restore_sp(sp_base)

# Check final state
try:
    r = call_string("_bist_sdata", 1, 1)
    print(f"\nState after: {r!r}", flush=True)
except Exception as e:
    print(f"\nState corrupted: {e}", flush=True)

print("Done", flush=True)
