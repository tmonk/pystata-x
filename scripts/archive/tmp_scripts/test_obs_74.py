import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")
print("OK", flush=True)

from pystata_x.sfi._core import Data
# Check different obs
for obs in [0, 73, 74]:
    try:
        v = Data.getDouble(1, obs)
        print(f"getDouble(1, {obs}) = {v}", flush=True)
    except Exception as e:
        print(f"getDouble(1, {obs}) error: {e}", flush=True)
