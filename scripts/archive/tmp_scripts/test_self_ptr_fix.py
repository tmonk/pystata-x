import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

from pystata_x.sfi._engine import call_double, call_int

# Test getDouble
print(f"nobs: {call_int('_bist_nobs')}")
print(f"nvar: {call_int('_bist_nvar')}")

# Test _bist_data with self-pointer patch
print("\n=== getDouble tests ===")
for obs in range(5):
    val = call_double("_bist_data", obs, 1)  # price (varno 1, 0-based)
    print(f"  price[{obs}] = {val}")
print(f"  price[73] = {call_double('_bist_data', 73, 1)}")

# Test via the public API
from pystata_x.sfi._core import Data
print(f"\n=== Via Data API ===")
print(f"  Data.getDouble(1, 0) = {Data.getDouble(1, 0)}")  # price, obs 0
print(f"  Data.getDouble(1, 73) = {Data.getDouble(1, 73)}")  # price, obs 73
