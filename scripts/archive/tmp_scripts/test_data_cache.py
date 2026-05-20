import os, sys
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")
print("Initialized OK", flush=True)

from pystata_x.sfi._core import Data
print(f"price[0] = {Data.getDouble(1, 0)}", flush=True)
print(f"price[1] = {Data.getDouble(1, 1)}", flush=True)
print(f"price[73] = {Data.getDouble(1, 73)}", flush=True)
print(f"mpg[0] = {Data.getDouble(2, 0)}", flush=True)
