import os, sys
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
lib = eng._LIB
lib.StataSO_Execute(b"sysuse auto, clear")
print("OK", flush=True)

from pystata_x.sfi._core import Data, Scalar, Macro
from pystata_x.sfi._x86_display import clear_cache

# Simulate oracle setup
lib.StataSO_Execute(b"global testglobal = 42")
lib.StataSO_Execute(b"scalar myscalar = 3.14")
lib.StataSO_Execute(b"scalar mystr = hello")
lib.StataSO_Execute(b"label define yesno 0 No 1 Yes")
lib.StataSO_Execute(b"label values foreign yesno")

clear_cache()

# Test var_index
print(f"getVarIndex('price') = {Data.getVarIndex('price')!r}", flush=True)  # should be 1
print(f"getVarIndex('foreign') = {Data.getVarIndex('foreign')!r}", flush=True)  # should be 11

# Test max_vars
print(f"getMaxVars() = {Data.getMaxVars()!r}", flush=True)  # should be 32767 or 50000

# Test scalar_string
print(f"getString('mystr') = {Scalar.getString('mystr')!r}", flush=True)  # should be 'hello'

# Test macro_global_level
print(f"getGlobal('c(level)') = {Macro.getGlobal('c(level)')!r}", flush=True)  # should be '95'

# Test formatted_values
print(f"getFormattedValue(1,0,False) = {Data.getFormattedValue(1,0,False)!r}", flush=True)  # should be '4,099'
