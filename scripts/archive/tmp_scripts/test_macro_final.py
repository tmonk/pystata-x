import os, sys, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
lib = eng._LIB
lib.StataSO_Execute(b"sysuse auto, clear")
print("OK", flush=True)

lib.StataSO_SetOutputBufferSz(65536)
lib.StataSO_ClearOutputBuffer.restype = None

# Direct test of the macro mechanism
lib.StataSO_ClearOutputBuffer()
rc = lib.StataSO_Execute(b'global e2e_test "hello_stata"')
buf = lib.StataSO_GetOutputBuffer
buf.restype = ctypes.c_char_p
out = buf()
print(f"after global: rc={rc} out={out.decode()!r}", flush=True)

lib.StataSO_ClearOutputBuffer()
rc = lib.StataSO_Execute(b'display "$e2e_test"')
out = buf()
print(f"display: rc={rc} out={out.decode()!r}", flush=True)

# Now via the Macro class  
from pystata_x.sfi._x86_display import clear_cache, get_macro, set_macro

clear_cache()
ok = set_macro("e2e_test2", "world")
print(f"set_macro(e2e_test2, world) = {ok}", flush=True)

clear_cache()
v = get_macro("e2e_test2")
print(f"get_macro(e2e_test2) via _x86_disp = {v!r}", flush=True)

clear_cache()
from pystata_x.sfi._core import Macro
Macro.setGlobal("e2e_test3", "test_val")
v = Macro.getGlobal("e2e_test3")
print(f"Macro.getGlobal(e2e_test3) via _core = {v!r}", flush=True)
