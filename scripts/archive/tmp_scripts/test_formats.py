import os, sys
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
lib = eng._LIB
lib.StataSO_Execute(b"sysuse auto, clear")
print("OK", flush=True)

from pystata_x.sfi._core import Data
# Print what getVarFormat returns
for i in range(12):
    try:
        name = Data.getVarName(i)
        fmt = Data.getVarFormat(i)
        print(f"varno={i}: name={name!r} format={fmt!r}", flush=True)
    except Exception as e:
        print(f"varno={i}: error={e}", flush=True)
