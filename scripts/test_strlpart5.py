"""Check if _bi_st_strlpart modifies the string tsmat in-place."""
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
SFIToolkit.executeCommand('gen strL s = "hello world wide web" if _n == 1')

_restore_sp = eng._restore_sp
pushint = lambda v: eng._pushint_fn(v)
pushstr = lambda s: eng._pushstr_fn(s, len(s))

fn_addr = base + manifest["symbols"]["_bi_st_strlpart"]
fn = ctypes.cast(fn_addr, ctypes.CFUNCTYPE(None, ctypes.c_int))

sp_base = ctypes.c_uint64.from_address(sp_addr).value

# Push args
pushstr(b's')
pushint(1)
pushint(0)  # part 0

sp = ctypes.c_uint64.from_address(sp_addr).value

# Read the string tsmat BEFORE the call
tsmat_addr = ctypes.c_uint64.from_address(sp - 16).value  # SP[-2] = string arg
print(f"String tsmat before: {hex(tsmat_addr)}", flush=True)
if tsmat_addr:
    for i in range(0, 48, 8):
        val = ctypes.c_uint64.from_address(tsmat_addr + i).value
        print(f"  +{hex(i):4s}: {hex(val)}", flush=True)
    dp_before = ctypes.c_uint64.from_address(tsmat_addr + 8).value
    print(f"  data_ptr before: {hex(dp_before)}", flush=True)
    if dp_before:
        # Read the string through data pointer
        str_ptr = ctypes.c_uint64.from_address(dp_before).value
        print(f"  str_ptr before: {hex(str_ptr)}", flush=True)
        if str_ptr:
            slen = ctypes.c_uint32.from_address(str_ptr).value
            raw = ctypes.string_at(str_ptr + 4, min(slen, 100))
            print(f"  str content before: {raw!r} (len={slen})", flush=True)

# Call
fn(3)

sp_after = ctypes.c_uint64.from_address(sp_addr).value
print(f"\nSP after call: {hex(sp_after)} (base+{sp_after - sp_base})", flush=True)

# Read the string tsmat AFTER the call  
tsmat_addr_after = ctypes.c_uint64.from_address(sp_after).value  # the remaining tsmat
print(f"\nString tsmat after: {hex(tsmat_addr_after)}", flush=True)
if tsmat_addr_after:
    for i in range(0, 48, 8):
        val = ctypes.c_uint64.from_address(tsmat_addr_after + i).value
        print(f"  +{hex(i):4s}: {hex(val)}", flush=True)
    dp_after = ctypes.c_uint64.from_address(tsmat_addr_after + 8).value
    print(f"  data_ptr after: {hex(dp_after)}", flush=True)
    if dp_after:
        str_ptr = ctypes.c_uint64.from_address(dp_after).value
        print(f"  str_ptr after: {hex(str_ptr)}", flush=True)
        if str_ptr:
            slen = ctypes.c_uint32.from_address(str_ptr).value
            raw = ctypes.string_at(str_ptr + 4, min(slen, 100))
            print(f"  str content after: {raw!r} (len={slen})", flush=True)

_restore_sp(sp_base)
print("\nDone", flush=True)
