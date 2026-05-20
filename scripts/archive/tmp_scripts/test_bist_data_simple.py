import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

from pystata_x.sfi._engine import _push_int, _save_sp, _pop_and_read_double

base = eng._BASE

# Create a CFUNCTYPE with 2 int params (edi, esi)
fn_addr = base + eng._SYMS['_bist_data'] + 0x48
fn = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_int)(fn_addr)

# Push args
sp_before = _save_sp()
_push_int(0)  # obs=0
_push_int(1)  # varno=1 (price)

sp = _save_sp()
tsmat = ctypes.c_uint64.from_address(sp).value
print(f"SP: 0x{sp:x}")
print(f"tsmat: 0x{tsmat:x}")

# Check tsmat fields
print(f"tsmat[0] pointer: 0x{ctypes.c_uint64.from_address(tsmat).value:x}")
print(f"tsmat[-0x10] before: 0x{ctypes.c_uint64.from_address(tsmat - 0x10).value:x}")
print(f"tsmat[-0x94] pool: 0x{ctypes.c_uint32.from_address(tsmat - 0x94).value:x}")

# Patch tsmat[-0x10] to be tsmat
ctypes.c_uint64.from_address(tsmat - 0x10).value = tsmat
print(f"tsmat[-0x10] after: 0x{ctypes.c_uint64.from_address(tsmat - 0x10).value:x}")

# Also check tsmat[0x20] (dims)
print(f"tsmat[0x20] nrows: {ctypes.c_uint64.from_address(tsmat + 0x20).value}")

# Now call
print(f"\nCalling fn(2, 0)...")
try:
    result = fn(2, 0)
    print(f"Result code: {result}")
    
    # Read result tsmat from stack
    sp_after = _save_sp()
    print(f"SP after: 0x{sp_after:x}")
    
    # Try reading from the current SP
    result_tsmat = ctypes.c_uint64.from_address(sp_after).value
    print(f"Result tsmat: 0x{result_tsmat:x}")
    
    # Read double
    if result_tsmat > 0x100000:
        val = ctypes.c_double.from_address(result_tsmat).value
        print(f"Result value: {val}")
except Exception as e:
    print(f"Exception: {e}")
