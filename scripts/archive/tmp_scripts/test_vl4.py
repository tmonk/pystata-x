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

# Approach 1: local macro + display
cmd1 = b"local lbl : value label foreign\n" \
       b"di `\"`lbl'\"'"
out = exec_cmd(cmd1)
print("Approach 1 (local + di):", repr(out))

# Approach 2: just the local macro test
cmd2 = b"local lbl : value label foreign"
out = exec_cmd(cmd2)
print("Approach 2 (local only):", repr(out))

# Approach 3: macro to global, then read
cmd3 = b"local lbl : value label foreign\n" \
       b"global _TMP_VL `\"`lbl'\"'"
out = exec_cmd(cmd3)
print("Approach 3 (global):", repr(out))

# Now read the global
cmd4 = b"display \"$_TMP_VL\""
out = exec_cmd(cmd4)
print("Approach 3 read:", repr(out))
