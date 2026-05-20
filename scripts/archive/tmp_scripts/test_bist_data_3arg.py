import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

from pystata_x.sfi._engine import _push_int, _save_sp, _pop_and_read_double

base = eng._BASE

# Try _bist_data with 3 args: obs, varno, result_tsmat
# Push result tsmat first, then obs, then varno
# Or: push obs, push varno, push result

# Approach 1: push obs, push varno, push result tsmat
sp_before = _save_sp()

_push_int(0)    # obs
_push_int(1)    # varno

# The 3rd arg should be a RESULT tsmat - push another int
_push_int(0)    # result tsmat (will be overwritten)

sp = _save_sp()
print(f"SP after 3 pushes: 0x{sp:x}")

# Read the 3 tsmat pointers
tsmat3 = ctypes.c_uint64.from_address(sp).value         # last pushed = result
tsmat2 = ctypes.c_uint64.from_address(sp - 8).value     # varno
tsmat1 = ctypes.c_uint64.from_address(sp - 16).value    # obs
print(f"tsmat[result]: 0x{tsmat3:x}")
print(f"tsmat[varno]:  0x{tsmat2:x}")
print(f"tsmat[obs]:     0x{tsmat1:x}")

# Patch all tsmats' [-0x10] to be self-pointers
for tsmat in [tsmat1, tsmat2, tsmat3]:
    ctypes.c_uint64.from_address(tsmat - 0x10).value = tsmat

# Now call _bist_data at the full impl with edi=3 (3 args)
fn_addr = base + eng._SYMS['_bist_data'] + 0x48  # +0x48 for push r15 entry
fn = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_int)(fn_addr)

try:
    result = fn(3, 0)  # w0=3, esi=0
    print(f"\nfn(3, 0) returned: {result}")
    
    # The result should be in the RESULT tsmat (tsmat3)
    val = ctypes.c_double.from_address(tsmat3).value
    print(f"result tsmat[0] double: {val}")
    
    # Also try 4 args
    sp_before = _save_sp()
    _push_int(0)  # obs
    _push_int(1)  # varno
    _push_int(0)  # result
    _push_int(0)  # extra?
    sp = _save_sp()
    for offset in range(0, -32, -8):
        t = ctypes.c_uint64.from_address(sp + offset).value
        if t > 0x100000:
            ctypes.c_uint64.from_address(t - 0x10).value = t
    result4 = fn(4, 0)
    print(f"fn(4, 0) returned: {result4}")
    
except Exception as e:
    print(f"Error: {e}")

# Also try calling the 3-arg-special entry point
# At offset 0x494 + (0x53e - 0x4dc) = 0x494 + 0x62 = 0x4f6?
# The 3-arg special entry starts at 0x7ffffa05253e
three_arg_entry = base + eng._SYMS['_bist_data'] + (0x53e - 0x4dc + 0x48)
print(f"\n3-arg special entry at 0x{three_arg_entry:x}")

sp_before = _save_sp()
_push_int(0)  # obs
_push_int(1)  # varno  
_push_int(999)  # result tsmat with marker value

sp = _save_sp()
tsmat_r = ctypes.c_uint64.from_address(sp).value
ctypes.c_uint64.from_address(tsmat_r - 0x10).value = tsmat_r

fn3 = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_int)(three_arg_entry)
try:
    r = fn3(3, 0)
    print(f"3-arg special returned: {r}")
    val = ctypes.c_double.from_address(tsmat_r).value
    print(f"result double: {val}")
except Exception as e:
    print(f"3-arg special error: {e}")
