"""Check if _bi_st_strlpart modifies the string tsmat in-place.
We examine the GSO and string content before and after the call."""
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

def read_tsmat(tsmat_addr, label):
    """Dump a tsmat and its GSO/string content."""
    print(f"\n{label} tsmat@{hex(tsmat_addr)}:", flush=True)
    for i in range(0, 64, 8):
        val = ctypes.c_uint64.from_address(tsmat_addr + i).value
        print(f"  +{hex(i):4s}: {hex(val)}", flush=True)
    
    # Read type
    typ = ctypes.c_int16.from_address(tsmat_addr + 0x34).value
    print(f"  type@+0x34: {typ}", flush=True)
    
    # Read GSO (tsmat[0])
    gso = ctypes.c_uint64.from_address(tsmat_addr).value
    if gso and gso > 0x100000:
        print(f"  GSO@{hex(gso)}:", flush=True)
        gso_str_ptr = ctypes.c_uint64.from_address(gso).value
        print(f"    [0]: {hex(gso_str_ptr)} (string ptr)", flush=True)
        for j in range(1, 5):
            val = ctypes.c_uint64.from_address(gso + j*8).value
            print(f"    [{j}]: {hex(val)}", flush=True)
        
        # Read string content
        if gso_str_ptr and gso_str_ptr > 0x100000:
            slen = ctypes.c_uint32.from_address(gso_str_ptr).value
            print(f"    string@len={slen}", flush=True)
            if slen < 10000:
                raw = ctypes.string_at(gso_str_ptr + 4, min(slen, 500))
                print(f"    string@{hex(gso_str_ptr+4)}: {raw!r}", flush=True)

SFIToolkit.executeCommand('sysuse auto, clear')
SFIToolkit.executeCommand('gen strL s = "hello world wide web" if _n == 1')

sp_base = ctypes.c_uint64.from_address(sp_addr).value

# Push args: string name, obs, part
pushstr(b's')    # arg1: variable name
pushint(1)       # arg2: obs
pushint(1)       # arg3: part (try 1 first)

sp = ctypes.c_uint64.from_address(sp_addr).value
str_tsmat_addr = ctypes.c_uint64.from_address(sp - 16).value  # SP[-2] = string arg

# Read tsmat BEFORE call
read_tsmat(str_tsmat_addr, "BEFORE")

# Call
fn(3)

sp_after = ctypes.c_uint64.from_address(sp_addr).value
remaining_tsmat = ctypes.c_uint64.from_address(sp_after).value

# Read tsmat AFTER call (the one remaining on stack)
if remaining_tsmat:
    read_tsmat(remaining_tsmat, "AFTER")
else:
    print("\nNo tsmat on stack after call", flush=True)

print(f"\nSP: {hex(sp_base)} -> {hex(sp)} -> {hex(sp_after)}", flush=True)
print(f"delta from base: {sp_after - sp_base}", flush=True)
print(f"Remaining tsmat addr: {hex(remaining_tsmat)} same as original str tsmat? {remaining_tsmat == str_tsmat_addr}", flush=True)

_restore_sp(sp_base)
print("\nDone", flush=True)
