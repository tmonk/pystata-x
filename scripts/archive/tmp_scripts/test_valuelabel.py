import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
lib = eng._LIB
lib.StataSO_SetOutputBufferSz.restype = None
lib.StataSO_SetOutputBufferSz(65536)
lib.StataSO_ClearOutputBuffer.restype = None
lib.StataSO_ClearOutputBuffer()
lib.StataSO_Execute(b"sysuse auto, clear")

def exec_cmd(cmd: bytes) -> str:
    lib.StataSO_ClearOutputBuffer()
    rc = lib.StataSO_Execute(cmd)
    buf = lib.StataSO_GetOutputBuffer
    buf.restype = ctypes.c_char_p
    out = buf().decode()
    return repr(out)

# Try di with char list using backtick syntax
print('Test 1 - char list:', exec_cmd(b"di `:char list foreign[_lblname]'"))

# Try the lblname char
print('Test 2 - lblname:', exec_cmd(b"di `:char list foreign[_lblname]'"))

# Try another char approach  
print('Test 3 - list:', exec_cmd(b"char list foreign[_lblname]"))

# Try help to find the right syntax
print('Test 4 - short describe:', exec_cmd(b"describe, short"))
