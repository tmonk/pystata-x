import os, sys
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
lib = eng._LIB
lib.StataSO_Execute(b"sysuse auto, clear")
print("Initialized OK", flush=True)

from pystata_x.sfi._core import Scalar, Macro
lib.StataSO_Execute(b"scalar e2e_test_num = 42.5")
v = Scalar.getValue("e2e_test_num")
print(f"Scalar.getValue(e2e_test_num) = {v}", flush=True)

# System scalar
lib.StataSO_Execute(b"scalar c(level) = 95")
v = Scalar.getValue("c(level)")
print(f"Scalar.getValue(c(level)) = {v}", flush=True)

# String scalar
s = Scalar.getString("c(current_date)")
print(f"Scalar.getString(c(current_date)) = {s!r}", flush=True)

# Macro
Macro.setGlobal("e2e_test_macro", "hello_stata")
s = Macro.getGlobal("e2e_test_macro")
print(f"Macro.getGlobal(e2e_test_macro) = {s!r}", flush=True)

# Non-existent macro
s = Macro.getGlobal("e2e_nonexistent_global")
print(f"Macro.getGlobal(nonexistent) = {s!r}", flush=True)

# Del macro
Macro.setGlobal("e2e_test_macro2", "value")
Macro.delGlobal("e2e_test_macro2")
s = Macro.getGlobal("e2e_test_macro2")
print(f"After delGlobal, get = {s!r}", flush=True)
print(f"  s is None = {s is None}", flush=True)

print("ALL DONE", flush=True)
