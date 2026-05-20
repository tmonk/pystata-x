import os, ctypes

os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
lib = eng._LIB
lib.StataSO_SetOutputBufferSz.restype = None
lib.StataSO_SetOutputBufferSz(65536)
lib.StataSO_ClearOutputBuffer.restype = None
lib.StataSO_Execute(b"sysuse auto, clear")

buf = lib.StataSO_GetOutputBuffer
buf.restype = ctypes.c_char_p

# Method 1: Use global macro directly with : value label
lib.StataSO_ClearOutputBuffer()
lib.StataSO_Execute(b"global _TMP_VL : value label foreign")
out = buf().decode()
print("global :", repr(out))

lib.StataSO_ClearOutputBuffer()
lib.StataSO_Execute(b"display \"$_TMP_VL\"")
out = buf().decode()
print("display global:", repr(out))
for line in out.split('\n'):
    s = line.strip()
    if s and not s.startswith('.') and not s.startswith('r('):
        print(f"  -> {repr(s)}")

# Method 2: Try with make (should be empty/not found)
lib.StataSO_ClearOutputBuffer()
lib.StataSO_Execute(b"global _TMP_VL2 : value label make")
out = buf().decode()
print("global make:", repr(out))

lib.StataSO_ClearOutputBuffer()
lib.StataSO_Execute(b"display \"$_TMP_VL2\"")
out = buf().decode()
print("display global make:", repr(out))
for line in out.split('\n'):
    s = line.strip()
    if s and not s.startswith('.') and not s.startswith('r('):
        print(f"  -> {repr(s)}")
