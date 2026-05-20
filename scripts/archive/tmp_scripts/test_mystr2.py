import os, sys, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
lib = eng._LIB
lib.StataSO_Execute(b"sysuse auto, clear")
print("OK", flush=True)

lib.StataSO_SetOutputBufferSz(65536)
lib.StataSO_ClearOutputBuffer.restype = None

# Try quoted
lib.StataSO_ClearOutputBuffer()
rc = lib.StataSO_Execute(b'scalar mystr = "hello"')
buf = lib.StataSO_GetOutputBuffer
buf.restype = ctypes.c_char_p
out = buf()
print(f"scalar mystr = \"hello\": rc={rc} out={out.decode()!r}", flush=True)

# Maybe the oracle setup on macOS uses the Python API, not Stata commands?
# Let me try setting a string scalar via Stata's S_* system
lib.StataSO_ClearOutputBuffer()
rc = lib.StataSO_Execute(b'global S_mystr "hello"')
out = buf()
print(f"global S_mystr: rc={rc} out={out.decode()!r}", flush=True)

# Try reading S_mystr
lib.StataSO_ClearOutputBuffer()
rc = lib.StataSO_Execute(b'display c(mystr)')
out = buf()
print(f"display c(mystr): rc={rc} out={out.decode()!r}", flush=True)
