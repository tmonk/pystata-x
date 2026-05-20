import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

from pystata_x.sfi._engine import call_double, call_int

# Test numeric data reading
print("=== Testing direct data reading ===")
print(f"nobs: {call_int('_bist_nobs')}")
print(f"nvar: {call_int('_bist_nvar')}")

# Try _bist_data with obs=0, varno=1 (price[0] = 4099)
result = call_double("_bist_data", 0, 1)
print(f"call_double('_bist_data', 0, 1): {result}")

# Try with varno=0 (make[0] is str18 - should fail)
result2 = call_double("_bist_data", 0, 0)
print(f"call_double('_bist_data', 0, 0): {result2}")

# Try _bist_data reading prices for various obs/varno
for obs in [0, 1, 73]:
    result = call_double("_bist_data", obs, 1)
    print(f"price[{obs}]: {result}")
