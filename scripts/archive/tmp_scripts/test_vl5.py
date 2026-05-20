"""Test extracting value label name from Stata."""
import os, ctypes

os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
lib = eng._LIB
lib.StataSO_SetOutputBufferSz.restype = None
lib.StataSO_SetOutputBufferSz(65536)
lib.StataSO_ClearOutputBuffer.restype = None
lib.StataSO_Execute(b"sysuse auto, clear")

def exec_cmd(cmd: bytes) -> str:
    lib.StataSO_ClearOutputBuffer()
    rc = lib.StataSO_Execute(cmd)
    buf = lib.StataSO_GetOutputBuffer
    buf.restype = ctypes.c_char_p
    out = buf().decode()
    return out

# Approach: use Stata's value label local macro and a display
# In Stata: `: value label varname` returns the label name
# local lbl : value label foreign
# This stores "origin" in lbl
# Then display `"`lbl'"' shows the value
# BUT the quoting is trixy across the python/Stata boundary

# Let's try a single-command approach with display
# di `"`: value label foreign'"'
cmd = b'di `": value label foreign"\'' 
out = exec_cmd(cmd)
print("Direct di:", repr(out))

# Let me try without the extended function quoting 
cmd2 = b'di ": value label foreign"'
out = exec_cmd(cmd2)
print("String di:", repr(out))
