import os, sys, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
lib = eng._LIB
lib.StataSO_Execute(b"sysuse auto, clear")
print("OK", flush=True)

# Test the display module directly
from pystata_x.sfi._x86_display import get_macro, set_macro, del_macro, clear_cache

# Set macro via Stata command
lib.StataSO_Execute(b'global e2e_test "hello_stata"')
clear_cache()

# Now read it via display module
v = get_macro("e2e_test")
print(f"get_macro(e2e_test) = {v!r}", flush=True)

# Set macro via our module
ok = set_macro("e2e_test2", "world")
print(f"set_macro(e2e_test2, world) = {ok}", flush=True)
clear_cache()
v = get_macro("e2e_test2")
print(f"get_macro(e2e_test2) = {v!r}", flush=True)

# Test non-existent macro
clear_cache()
v = get_macro("e2e_nonexist")
print(f"get_macro(nonexist) = {v!r}", flush=True)
print(f"  v is None = {v is None}", flush=True)
