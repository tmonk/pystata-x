import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

from pystata_x.sfi._engine import (call_int, call_string, _push_args, _save_sp,
                                     _STACK_PTR_OFFSET, _LIB, _SYMS, _push_double, 
                                     _push_int, _push_str, _BASE)

# Trace what _bist_sdata does with numeric args (varno=1 (price), obs=0)
# _bist_sdata expects obs, varno (like sdata(obs, varno))
# Let's trace it
sp = ctypes.c_uint64.from_address(_STACK_PTR_OFFSET).value
print(f"Initial SP: 0x{sp:x}")

# Push obs=0 (double) then varno=1 (double) — this is the C calling convention?
_push_int(0)
_push_int(1)  # Actually wait, _bist_sdata takes two ints then returns a double

# Save SP
sp_val = _save_sp()
print(f"SP after push: 0x{sp_val:x}")

_dispatch_fn = _SYMS["_bist_sdata"]
print(f"Calling _bist_sdata at 0x{_dispatch_fn:x}")

# Call dispatch
result = _LIB._dispatch_fn(ctypes.c_int32(0), ctypes.c_int32(1))
print(f"Result: {result}")
