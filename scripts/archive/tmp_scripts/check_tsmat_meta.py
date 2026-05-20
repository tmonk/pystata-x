import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

from pystata_x.sfi._engine import _push_int, _save_sp, _STACK_PTR_OFFSET

# Push two args and check the tsmat metadata
_push_int(42)  # first arg
_push_int(99)  # second arg

sp = _save_sp()
tsmat_ptr = ctypes.c_uint64.from_address(sp).value
print(f"Last pushed tsmat: 0x{tsmat_ptr:x}")

# Check tsmat[-0x10] 
tsmat_m10 = ctypes.c_uint64.from_address(tsmat_ptr - 0x10).value
print(f"tsmat[-0x10] = 0x{tsmat_m10:x}")

# Check pool header at tsmat[-0x94] 
pool_tag = ctypes.c_uint32.from_address(tsmat_ptr - 0x94).value
print(f"tsmat[-0x94] pool tag: 0x{pool_tag:x}")

# Check what _bist_data would compute
# rbx = tsmat[-0x10]
# check [rbx - 0x94]
if tsmat_m10 > 0x100000:
    rbx_pool_tag = ctypes.c_uint32.from_address(tsmat_m10 - 0x94).value
    print(f"rbx[-0x94] pool tag = 0x{rbx_pool_tag:x}")
    
    # Check rbx also has the same tsmat fields
    rbx_34 = ctypes.c_uint16.from_address(tsmat_m10 + 0x34).value
    print(f"rbx[0x34] = 0x{rbx_34:x}")
    
    rbx_36 = ctypes.c_uint8.from_address(tsmat_m10 + 0x36).value
    print(f"rbx[0x36] = 0x{rbx_36:x}")
