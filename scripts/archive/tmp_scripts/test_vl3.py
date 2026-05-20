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
    lines = out.split('\n')
    for line in lines:
        s = line.strip()
        if s and not s.startswith('.') and not s.startswith('r(') and not s.startswith('>'):
            return s
    return ""

# Try Stata local macro approach
c1 = b"local lbl : value label foreign\ndis `\"`lbl'\""  
c2 = b"local lbl : value label foreign\ndis `\"`lbl'\""

for name, cmd in [("local+dis", c2)]:
    lib.StataSO_ClearOutputBuffer()
    rc = lib.StataSO_Execute(cmd)
    buf = lib.StataSO_GetOutputBuffer
    buf.restype = ctypes.c_char_p
    out = buf().decode()
    print(f"{name}: rc={rc} out={out!r}")
