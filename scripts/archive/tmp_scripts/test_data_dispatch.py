import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

from pystata_x.sfi._engine import (call_int, call_string, _push_args, _save_sp,
                                     _STACK_PTR_OFFSET, _LIB, _SYMS, _push_double, 
                                     _push_int, _push_str, _BASE)

# Try _bist_data with 1-based varno
print("=== Testing _bist_data ===")
# _bist_data is a dispatch entry that takes tsmat args
# But we can also try calling it as a direct function with (obs, varno)

fn_addr = _BASE + _SYMS['_bist_data']
print(f"Calling _bist_data at 0x{fn_addr:x}")

# The function starts with sub rsp, 8 - needs arguments
# Let's try the push protocol: push(obs), push(varno), save_sp, call
_push_int(0)    # obs = 0 (1st push)
_push_int(1)    # varno = 1 (2nd push)

sp_val = _save_sp()
print(f"SP after push: 0x{sp_val:x}")

# Create CFUNCTYPE for the dispatch with no args (reads from tsmat stack)
_fn_type = ctypes.CFUNCTYPE(ctypes.c_double)
actual_fn = _fn_type(eng._BASE + _SYMS['_bist_data'])
result = actual_fn()
print(f"Result: {result}")

# Test with just nobs to verify protocol still works
print("\n=== Testing _bist_nobs ===")
result2 = call_int("nobs")
print(f"nobs: {result2}")

# Test with _bist_data reading price[0] via call_int approach
# call_int expects the function to return an int from the single-tsmat protocol
# but _bist_data reads from tsmat args and returns data value
# Let's try: push(0), push(1), call _bist_data through call_int

print("\n=== Testing _bist_data via push protocol ===")
# Sp_reset: push obs=0, push varno=1
_push_int(0)
_push_int(1)
sp2 = _save_sp()

# Call dispatch function 
fn = ctypes.CFUNCTYPE(ctypes.c_double)(eng._BASE + _SYMS['_bist_data'])
result2 = fn()
print(f"_bist_data(obs=0, varno=1) = {result2}")

# Try with price[1] = 4749.0
_push_int(1)
_push_int(1)
sp3 = _save_sp()
result3 = fn()
print(f"_bist_data(obs=1, varno=1) = {result3}")
