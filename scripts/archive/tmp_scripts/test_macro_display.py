import os, sys, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
lib = eng._LIB
lib.StataSO_Execute(b"sysuse auto, clear")
print("Initialized OK", flush=True)

# Direct test of display $macro via StataSO_Execute
lib.StataSO_SetOutputBufferSz(65536)
lib.StataSO_ClearOutputBuffer.restype = None

# Create a global macro
lib.StataSO_ClearOutputBuffer()
rc = lib.StataSO_Execute(b'global e2e_test "hello_stata"')
print(f"global command rc={rc}", flush=True)

# Read back via display
lib.StataSO_ClearOutputBuffer()
rc = lib.StataSO_Execute(b'display "$e2e_test"')
print(f"display rc={rc}", flush=True)

buf = lib.StataSO_GetOutputBuffer
buf.restype = ctypes.c_char_p
out = buf()
print(f"display output: {out.decode()!r}", flush=True)

# Also try with backtick quoting
lib.StataSO_ClearOutputBuffer()
rc = lib.StataSO_Execute(b"display `e2e_test'")
print(f"backtick display rc={rc}", flush=True)
out2 = buf()
print(f"backtick output: {out2.decode()!r}", flush=True)

# Try without quotes
lib.StataSO_ClearOutputBuffer()
rc = lib.StataSO_Execute(b"display $e2e_test")
print(f"no-quotes display rc={rc}", flush=True)
out3 = buf()
print(f"no-quotes output: {out3.decode()!r}", flush=True)

# List all macros
lib.StataSO_ClearOutputBuffer()
rc = lib.StataSO_Execute(b"macro list")
print(f"macro list rc={rc}", flush=True)
out4 = buf()
print(f"macro list: {out4.decode()!r}", flush=True)
