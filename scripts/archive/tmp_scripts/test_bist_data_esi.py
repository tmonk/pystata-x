import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

from pystata_x.sfi._engine import _push_int, _save_sp, _pop_and_read_double
from pystata_x.sfi._engine import _STACK_PTR_OFFSET, _BASE

base = eng._BASE

# Call _bist_data with TWO int args (edi=w0, esi=something)
fn_addr = base + eng._SYMS['_bist_data'] + 0x48  # +0x48 = push r15 entry
print(f"fn at 0x{fn_addr:x}")

# Create CFUNCTYPE with TWO int arguments
fn_type = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_int)
fn = fn_type(fn_addr)

# Now push args and call
sp_before = _save_sp()
_push_int(0)  # obs=0
_push_int(1)  # varno=1 (price)

sp = _save_sp()
tsmat = ctypes.c_uint64.from_address(sp).value
print(f"tsmat: 0x{tsmat:x}")
print(f"pool tag: 0x{ctypes.c_uint32.from_address(tsmat - 0x94).value:x}")

# Patch tsmat[-0x10] to be self-pointer
ctypes.c_uint64.from_address(tsmat - 0x10).value = tsmat
print(f"tsmat[-0x10] patched to: 0x{ctypes.c_uint64.from_address(tsmat - 0x10).value:x}")

# Call with (w0=2, esi=0)
try:
    result = fn(2, 0)
    print(f"fn(2, 0) returned: {result}")
    val = _pop_and_read_double(sp_before)
    print(f"Value: {val}")
except Exception as e:
    print(f"Error: {e}")

# Try again with different esi values
for esi_val in [0, 1, 2, 3]:
    sp_before = _save_sp()
    _push_int(0)
    _push_int(1)
    sp = _save_sp()
    tsmat = ctypes.c_uint64.from_address(sp).value
    ctypes.c_uint64.from_address(tsmat - 0x10).value = tsmat
    try:
        result = fn(2, esi_val)
        val = _pop_and_read_double(sp_before)
        print(f"  esi={esi_val}: result={result}, val={val}")
    except:
        print(f"  esi={esi_val}: CRASH")
