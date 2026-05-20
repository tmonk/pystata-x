import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

base = eng._BASE

# _bist_data symbol at offset 0x826494
# The full implementation for w0 >= 2 is at offset 0x826494 + 0x44 = 0x8264d8
bist_data_impl = base + eng._SYMS['_bist_data'] + 0x44
print(f"Full impl at 0x{bist_data_impl:x}")

# Call with push protocol: args (obs=0, varno=1 for price)
from pystata_x.sfi._engine import (_push_int, _save_sp, _push_args,
                                     _restore_sp, _pop_and_read_double,
                                     _get_fn, _STACK_PTR_OFFSET)

# Save sp
sp_before = _save_sp()
print(f"SP before: 0x{sp_before:x}")

# Push args
_push_int(0)  # obs
_push_int(1)  # varno (1-based)

sp_after = _save_sp()
print(f"SP after push: 0x{sp_after:x}")

# Call the full implementation with w0=2
fn = _get_fn(bist_data_impl, None, ctypes.c_int)  # fn takes one int arg (w0)
result = fn(2)
print(f"Raw result: {result}")

# Read result
tsmat_ptr = ctypes.c_uint64.from_address(sp_after).value
print(f"Result tsmat at: 0x{tsmat_ptr:x}")

if tsmat_ptr > 0x100000:
    dbl_val = ctypes.c_double.from_address(tsmat_ptr).value
    print(f"tsmat[0] double: {dbl_val}")

# Also read from _pop_and_read_double
val = _pop_and_read_double(sp_before)
print(f"_pop_and_read_double: {val}")
