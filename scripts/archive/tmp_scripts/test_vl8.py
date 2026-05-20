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

def run(cmd: bytes) -> str:
    lib.StataSO_ClearOutputBuffer()
    rc = lib.StataSO_Execute(cmd)
    out = buf().decode()
    lines = out.split('\n')
    result = []
    for line in lines:
        s = line.strip()
        if s and not s.startswith('.') and not s.startswith('r(') and not s.startswith('>'):
            result.append(s)
    return '\n'.join(result), out

# Method: local -> global -> display
lib.StataSO_ClearOutputBuffer()
lib.StataSO_Execute(b"local tbl : value label foreign")
out = buf().decode()
print("local:", repr(out))

# Now display the local - use backtick-quote in proper bytes
# di `"foreign has value label `tbl'"'
# Command bytes: d i space ` " f o r e i g n ...
cmd = bytes([0x64, 0x69, 0x20, 0x60, 0x22, 0x66, 0x6f, 0x72, 0x65, 0x69, 0x67, 0x6e, 0x20, 0x68, 0x61, 0x73, 0x20, 0x76, 0x61, 0x6c, 0x75, 0x65, 0x20, 0x6c, 0x61, 0x62, 0x65, 0x6c, 0x20, 0x60, 0x74, 0x62, 0x6c, 0x27, 0x22, 0x27])  
# di `"foreign has value label `tbl'"'
print("cmd hex:", cmd.hex())
lib.StataSO_ClearOutputBuffer()
lib.StataSO_Execute(cmd)
out = buf().decode()
print("di backtick:", repr(out))

# Actually, let me just try a simpler Stata approach using the "char" machinery
# In Stata, chars on variables can store the value label name
# char list foreign[_lblname] showed empty earlier, let me check if it's somewhere else
lib.StataSO_ClearOutputBuffer()
lib.StataSO_Execute(b"char list")
out = buf().decode()
print("char list:", repr(out))
