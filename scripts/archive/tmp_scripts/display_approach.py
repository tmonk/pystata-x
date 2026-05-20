import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

from pystata_x.sfi._engine import _LIB

# Set up output buffer
_LIB.StataSO_SetOutputBufferSz.restype = None
_LIB.StataSO_SetOutputBufferSz.argtypes = [ctypes.c_size_t]
_LIB.StataSO_SetOutputBufferSz(65536)
_LIB.StataSO_ClearOutputBuffer.restype = None

read_buf = _LIB.StataSO_GetOutputBuffer
read_buf.restype = ctypes.c_char_p

clear_buf = _LIB.StataSO_ClearOutputBuffer

# Clear and display price[1]
clear_buf()
ret = _LIB.StataSO_Execute(b'display price[1]')
print(f"Return: {ret}")
out = read_buf()
print(f"Output: {out!r}")

# Extract the value - it's after the command echo
# Stata output: ". display price[1]\n4099\n"
# or with leading banner if not cleared
lines = out.decode().strip().split('\n')
print(f"Lines: {lines}")
for line in lines:
    line = line.strip()
    if line and not line.startswith('.') and not line.startswith('.'):
        try:
            val = float(line)
            print(f"  Parsed: {val}")
        except:
            pass
