import os, sys
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
lib = eng._LIB
lib.StataSO_Execute(b"sysuse auto, clear")
print("OK", flush=True)

from pystata_x.sfi._engine import _read_var_name_x86
for i in range(12):
    name = _read_var_name_x86(i)
    print(f"varno={i}: name={name!r}", flush=True)
    if name and name.lower() == "price":
        print(f"  -> FOUND at {i}", flush=True)
