import os, sys
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
lib = eng._LIB
lib.StataSO_Execute(b"sysuse auto, clear")
print("OK", flush=True)

from pystata_x.sfi._x86_display import clear_cache, _exec

# Simulate oracle setup
lib.StataSO_Execute(b"global testglobal = 42")
lib.StataSO_Execute(b"scalar myscalar = 3.14")
lib.StataSO_Execute(b"scalar mystr = hello")
lib.StataSO_Execute(b"label define yesno 0 No 1 Yes")
lib.StataSO_Execute(b"label values foreign yesno")
clear_cache()

from pystata_x.sfi._core import Data, Scalar, Macro

# Max vars
out = _exec(b"display c(maxvar)")
print(f"display c(maxvar) = {out!r}", flush=True)

# Scalar mystr
out = _exec(b"display scalar(mystr)")
print(f"display scalar(mystr) = {out!r}", flush=True)

# c(level)
out = _exec(b"display c(level)")
print(f"display c(level) = {out!r}", flush=True)

# Macro.getGlobal("c(level)")
print(f"Macro.getGlobal(c(level)) = {Macro.getGlobal('c(level)')!r}", flush=True)

# Formatted value
out = _exec(b"display price[1]")
print(f"display price[1] = {out!r}", flush=True)
print(f"Data.getFormattedValue(1,0,False) = {Data.getFormattedValue(1,0,False)!r}", flush=True)
