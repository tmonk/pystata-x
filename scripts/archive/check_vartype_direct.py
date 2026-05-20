"""Test what _bist_vartype actually returns — try both call_int and call_string."""
import sys, ctypes, json
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize, call_int, call_string
from pystata_x.sfi._core import SFIToolkit, Data
import pystata_x.sfi._engine as eng

initialize()
base = eng._BASE
manifest = json.load(open('src/pystata_x/sfi/manifest.json'))

SFIToolkit.executeCommand('sysuse auto, clear')
SFIToolkit.executeCommand('gen strL s = "hello world wide web" if _n == 1')

print("=== Test _bist_vartype (at {}) ===".format(hex(manifest['symbols']['_bist_vartype'])), flush=True)
for v in range(4):
    name = Data.getVarName(v)
    int_res = call_int("_bist_vartype", v + 1)
    str_res = call_string("_bist_vartype", v + 1)
    print(f"  var {v} ({name}): int={int_res} str={str_res!r}", flush=True)

# Also test _bist_vartype with 0 args (maybe it reads from self?)
int_res0 = call_int("_bist_vartype", 0)
print(f"\n  with arg=0: int={int_res0}", flush=True)

# Try directly reading the tsmat after _bist_vartype call
base = eng._BASE
sp_addr = base + 0x39b7000 + 0x108
pushint = lambda v: eng._pushint_fn(v)
fn_addr = base + manifest["symbols"]["_bist_vartype"]
fn = ctypes.cast(fn_addr, ctypes.CFUNCTYPE(None, ctypes.c_int))
_restore_sp = eng._restore_sp

print("\n=== Direct _bist_vartype call, read tsmat ===", flush=True)
sp_base = ctypes.c_uint64.from_address(sp_addr).value
pushint(1)  # varno=1 (1-based)
fn(1)
sp = ctypes.c_uint64.from_address(sp_addr).value
tsmat = ctypes.c_uint64.from_address(sp).value
print(f"  SP={hex(sp)}, tsmat={hex(tsmat)}", flush=True)
if tsmat and tsmat > 0x100000:
    for i in range(0, 64, 8):
        val = ctypes.c_uint64.from_address(tsmat + i).value
        print(f"    +{hex(i):4s}: {hex(val)}", flush=True)
    # Try reading as double
    dp = ctypes.c_uint64.from_address(tsmat).value
    if dp and dp > 0x100000:
        dval = ctypes.c_double.from_address(dp).value
        print(f"  as double: {dval}", flush=True)
    # Try reading as string
    gso = ctypes.c_uint64.from_address(tsmat).value
    if gso and gso > 0x100000:
        str_ptr = ctypes.c_uint64.from_address(gso).value
        if str_ptr and str_ptr > 0x100000:
            slen = ctypes.c_uint32.from_address(str_ptr).value
            data = ctypes.string_at(str_ptr + 4, min(slen, 100))
            print(f"  as string: {data!r}", flush=True)
_restore_sp(sp_base)

print("\nDone", flush=True)
