import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

from pystata_x.sfi._engine import _LIB

# Set up output buffer
_LIB.StataSO_SetOutputBufferSz(65536)
_LIB.StataSO_SetOutputBufferSz.argtypes = [ctypes.c_size_t]
_LIB.StataSO_SetOutputBufferSz.restype = None
read_buf = _LIB.StataSO_GetOutputBuffer
read_buf.restype = ctypes.c_char_p

# Display price[1]
ret = _LIB.StataSO_Execute(b'display price[1]')
print(f"Return: {ret}")
out = read_buf()
print(f"Output: {out!r}")

# Try other approaches 
# 1. scalar from expression
_LIB.StataSO_SetOutputBufferSz(65536)
ret2 = _LIB.StataSO_Execute(b'scalar __px_tmp = price[1]')
print(f"\nscalar return: {ret2}")
if ret2 == 0:
    # Read scalar... but scalar reading is broken
    pass

# Let's try: store scalar, then create macro from scalar  
_LIB.StataSO_SetOutputBufferSz(65536)
ret3 = _LIB.StataSO_Execute(b'scalar __px_tmp2 = price[2]')
print(f"scalar2 return: {ret3}")

if ret3 == 0:
    # Try reading via _bist_numscalar
    from pystata_x.sfi._engine import call_double
    val = call_double("_bist_numscalar", b"__px_tmp2")
    print(f"numscalar: {val}")
