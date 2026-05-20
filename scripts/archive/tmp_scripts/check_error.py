import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

from pystata_x.sfi._engine import call_string, _LIB

# Set up output buffer
_LIB.StataSO_SetOutputBufferSz(65536)
_LIB.StataSO_SetOutputBufferSz.argtypes = [ctypes.c_size_t]
_LIB.StataSO_SetOutputBufferSz.restype = None

# Try the command
ret = _LIB.StataSO_Execute(b'global __px_test = strofreal(price[1])')
print(f"Return: {ret}")

# Read output buffer
read_buf = _LIB.StataSO_GetOutputBuffer
read_buf.restype = ctypes.c_char_p
out = read_buf()
print(f"Output: {out!r}")

# Try without the '=' sign  
ret2 = _LIB.StataSO_Execute(b'display "hello world"')
print(f"\nReturn2: {ret2}")
out2 = read_buf()
print(f"Output2: {out2!r}")
