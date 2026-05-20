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
    # Extract first non-command line
    lines = out.split('\n')
    for line in lines:
        stripped = line.rstrip()
        if stripped and not stripped.startswith('.'):
            return stripped
    return ""

# Try: local lbl : value label foreign; display "`lbl'"
print("local approach:", exec_cmd(b"""local lbl : value label foreign
di "`lbl'""""))

# Try with variable index
print("local index approach:", exec_cmd(b"""local lbl : value label 11-var 11+1
local lbl : value label foreign
di "`lbl'""" ))

# Try getVarValueLabel directly
print("direct getLabelName:", exec_cmd(b"""local lbl : value label foreign
di "`lbl'""" ))
