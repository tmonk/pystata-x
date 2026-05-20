import os, sys, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
lib = eng._LIB
lib.StataSO_Execute(b"sysuse auto, clear")
print("OK", flush=True)

lib.StataSO_SetOutputBufferSz(65536)
lib.StataSO_ClearOutputBuffer.restype = None

# Display with format
lib.StataSO_ClearOutputBuffer()
rc = lib.StataSO_Execute(b"display price[1]")
buf = lib.StataSO_GetOutputBuffer
buf.restype = ctypes.c_char_p
out = buf()
print(f"display price[1]: rc={rc}", flush=True)
print(f"  raw: {out.decode()!r}", flush=True)

# Explicit format
lib.StataSO_ClearOutputBuffer()
rc = lib.StataSO_Execute(b"display %8.0gc price[1]")
out = buf()
print(f"display %8.0gc price[1]:", flush=True)
print(f"  raw: {out.decode()!r}", flush=True)

# Format with comma
lib.StataSO_ClearOutputBuffer()
rc = lib.StataSO_Execute(b"display %9.2gc 4099")
out = buf()
print(f"display %9.2gc 4099:", flush=True)
print(f"  raw: {out.decode()!r}", flush=True)

# Get the last data value for comparison
import json
with open('/pystata-x/tests/e2e/oracle.json') as f:
    o = json.load(f)
print(f"Oracle formatted_price_obs0: {o['data']['formatted_price_obs0']!r}", flush=True)

# Check what Stata's describe says
lib.StataSO_ClearOutputBuffer()
rc = lib.StataSO_Execute(b"describe price")
out = buf()
print(f"describe price:", flush=True)
print(f"  raw: {out.decode()!r}", flush=True)
