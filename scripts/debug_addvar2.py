"""Test existing addVarDouble from the Data class."""
import sys
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize
from pystata_x.sfi._core import SFIToolkit, Data
import pystata_x.sfi._engine as eng

initialize()
# Use the engine directly to see what happens
base = eng._BASE
sp_addr = base + 0x39b7000 + 0x108
_restore_sp = eng._restore_sp
pushstr = lambda v: eng._pushstr_fn(v, len(v))
pushint = lambda v: eng._pushint_fn(v)

SFIToolkit.executeCommand('clear all')
print(f"Initial vars: {[Data.getVarName(i) for i in range(Data.getVarCount())]}", flush=True)

# Call Data.addVarDouble directly
print("\nCalling Data.addVarDouble('mynewvar')...", flush=True)
try:
    r = Data.addVarDouble('mynewvar')
    print(f"  result: {r}", flush=True)
except Exception as e:
    print(f"  ERROR: {e}", flush=True)

print(f"After add: vars = {[Data.getVarName(i) for i in range(Data.getVarCount())]}", flush=True)

# Let me also try calling _bist_addvar directly at the C level 
# to see what the return value actually is
import ctypes, json
manifest = json.load(open('src/pystata_x/sfi/manifest.json'))
fn_addr = base + manifest["symbols"]["_bist_addvar"]
fn = ctypes.cast(fn_addr, ctypes.CFUNCTYPE(None, ctypes.c_int))

print("\n=== Direct _bist_addvar call ===", flush=True)
SFIToolkit.executeCommand('clear all')
sp_base = ctypes.c_uint64.from_address(sp_addr).value
pushstr(b'directvar')
pushint(ord('d'))
fn(2)
sp = ctypes.c_uint64.from_address(sp_addr).value
# Read tsmat carefully
tsmat = ctypes.c_uint64.from_address(sp).value
print(f"  tsmat={hex(tsmat)}", flush=True)
if tsmat and tsmat > 0x100000:
    for i in range(0, 48, 8):
        val = ctypes.c_uint64.from_address(tsmat + i).value
        print(f"    +{hex(i):4s}: {hex(val)}", flush=True)
    dp = ctypes.c_uint64.from_address(tsmat).value
    if dp:
        dv = ctypes.c_double.from_address(dp).value
        iv = ctypes.c_int32.from_address(dp).value
        print(f"  as double={dv} as int32={iv}", flush=True)
_restore_sp(sp_base)
print(f"After direct: vars = {[Data.getVarName(i) for i in range(Data.getVarCount())]}", flush=True)

print("\nDone", flush=True)
