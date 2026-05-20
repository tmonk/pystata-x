import os, sys
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
lib = eng._LIB
lib.StataSO_Execute(b"sysuse auto, clear")
print("OK", flush=True)

# Try getVarIndex with x86_64 fallback
from pystata_x.sfi._core import Data
try:
    idx = Data.getVarIndex("price")
    print(f"getVarIndex('price') = {idx}", flush=True)
    idx2 = Data.getVarIndex("foreign")
    print(f"getVarIndex('foreign') = {idx2}", flush=True)
except Exception as e:
    print(f"Error: {e}", flush=True)
