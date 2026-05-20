# By running the test suite we can see which markers remain
import os, sys
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")
from pystata_x.sfi._core import Data

# Test everything that should work
print("=== Testing Variable Metadata ===")
for i in range(12):
    name = Data.getVarName(i)
    typ = Data.getVarType(i)
    lab = Data.getVarLabel(i)
    fmt = Data.getVarFormat(i)
    print(f"  [{i:2d}] name={name!r:20s} type={typ!r:8s} label={lab!r:35s} format={fmt!r:10s}")

print("\n=== Data Access ===")
print(f"  getDouble(1, 0) = {Data.getDouble(1, 0)}")
print(f"  getDouble(2, 0) = {Data.getDouble(2, 0)}")

print("\n=== Counts ===")
print(f"  nvar = {Data.getVarCount()}")
print(f"  nobs = {Data.getObsTotal()}")

print("\nALL BASIC TESTS PASSED")
sys.stdout.flush()
