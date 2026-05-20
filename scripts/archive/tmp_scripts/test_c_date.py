import os, sys, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
lib = eng._LIB
lib.StataSO_Execute(b"sysuse auto, clear")
print("OK", flush=True)

# Clear cache first
from pystata_x.sfi._x86_display import clear_cache, read_string_scalar
clear_cache()

# Direct test of display c(current_date)
lib.StataSO_SetOutputBufferSz(65536)
lib.StataSO_ClearOutputBuffer.restype = None
lib.StataSO_ClearOutputBuffer()
rc = lib.StataSO_Execute(b"display c(current_date)")
print(f"display c(current_date) rc={rc}", flush=True)

buf = lib.StataSO_GetOutputBuffer
buf.restype = ctypes.c_char_p
out = buf()
print(f"Raw output: {out.decode()!r}", flush=True)

# Now try via our function
clear_cache()
s = read_string_scalar("c(current_date)")
print(f"read_string_scalar(c(current_date)) = {s!r}", flush=True)
