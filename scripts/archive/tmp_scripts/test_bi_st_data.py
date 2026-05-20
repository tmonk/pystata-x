import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

base = eng._BASE

# _bi_st_data at offset 0x1d60d0 - this is the low-level data access
bi_st_data = base + eng._SYMS['_bi_st_data']
print(f"_bi_st_data at 0x{bi_st_data:x}")

# This function might take (obs, varno) as arguments directly
# Let's try calling it with ctypes
fn_type = ctypes.CFUNCTYPE(ctypes.c_double, ctypes.c_int, ctypes.c_int)
try:
    fn = fn_type(bi_st_data)
    result = fn(0, 0)  # obs=0, varno=0 (1-based? 0-based?)
    print(f"_bi_st_data(0, 0) = {result}")
    
    result2 = fn(0, 1)
    print(f"_bi_st_data(0, 1) = {result2}")
    
    # Price[1] = 4099 for obs=1, var=price(1-based index=2)
    # Stata might use 1-based
    result3 = fn(1, 2)  # obs=1, varno=2 (1-based for price)
    print(f"_bi_st_data(1, 2) = {result3}")
    
    result4 = fn(1, 1)  # obs=1, varno=1 (1-based for make)
    print(f"_bi_st_data(1, 1) = {result4}")
except Exception as e:
    print(f"Error: {e}")
