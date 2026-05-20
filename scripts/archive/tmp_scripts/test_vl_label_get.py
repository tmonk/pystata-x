"""Test label extraction with backtick expansion."""
import os, ctypes

os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
lib = eng._LIB
lib.StataSO_SetOutputBufferSz.restype = None
lib.StataSO_SetOutputBufferSz(65536)
lib.StataSO_ClearOutputBuffer.restype = None
lib.StataSO_Execute(b"sysuse auto, clear")

# Setup test label
lib.StataSO_Execute(b"label define e2e_get 0 Domestic")
lib.StataSO_Execute(b"label define e2e_get 1 Foreign, modify")

buf = lib.StataSO_GetOutputBuffer
buf.restype = ctypes.c_char_p

# Use local macro to capture label text, then pass to a global
lib.StataSO_Execute(b"local __vlx : label e2e_get 0")
lib.StataSO_Execute(b"global __gvlx `__vlx'")

lib.StataSO_ClearOutputBuffer()
lib.StataSO_Execute(b"display \"$__gvlx\"")
out = buf().decode()
print(f"label 0: {out!r}")
for line in out.split('\n'):
    s = line.strip()
    if s and not s.startswith('.') and not s.startswith('r('):
        print(f"  -> {repr(s)}")

# For nonexistent mapping
lib.StataSO_Execute(b"local __vlx2 : label origin 999")  
lib.StataSO_Execute(b"global __gvlx2 `__vlx2'")
lib.StataSO_ClearOutputBuffer()
lib.StataSO_Execute(b"display \"$__gvlx2\"")
out = buf().decode()
print(f"label 999: {out!r}")

# Cleanup
lib.StataSO_Execute(b"label drop e2e_get")
lib.StataSO_Execute(b"macro drop __gvlx __gvlx2")
