import os, ctypes

os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
lib = eng._LIB
lib.StataSO_SetOutputBufferSz.restype = None
lib.StataSO_SetOutputBufferSz(65536)
lib.StataSO_ClearOutputBuffer.restype = None
lib.StataSO_Execute(b"sysuse auto, clear")

# The STATA_SO_API takes a char* command. Let's just pass the byte string directly.
cmd = bytes([0x64, 0x69, 0x20, 0x60, 0x22, 0x3a, 0x20, 0x76, 0x61, 0x6c, 0x75, 0x65, 0x20, 0x6c, 0x61, 0x62, 0x65, 0x6c, 0x20, 0x66, 0x6f, 0x72, 0x65, 0x69, 0x67, 0x6e, 0x22, 0x27, 0x0a])
# That's: di `": value label foreign"'\n
# But let me also try without the final '
cmd2 = bytes([0x64, 0x69, 0x20, 0x60, 0x22, 0x3a, 0x20, 0x76, 0x61, 0x6c, 0x75, 0x65, 0x20, 0x6c, 0x61, 0x62, 0x65, 0x6c, 0x20, 0x66, 0x6f, 0x72, 0x65, 0x69, 0x67, 0x6e, 0x22, 0x27, 0x0a])
# di `": value label foreign"'\n

print("cmd:", cmd)
lib.StataSO_ClearOutputBuffer()
rc = lib.StataSO_Execute(cmd)
buf = lib.StataSO_GetOutputBuffer
buf.restype = ctypes.c_char_p
out = buf().decode()
print(f"rc={rc} out={repr(out)}")

# Now try di `": value label varname'" directly 
# Stata syntax: display `"`: value label foreign'"'
# This is: di <backtick><doublequote><backtick>: value label foreign<singlequote><doublequote><singlequote>
stata_cmd = b'di `"`: value label foreign'"\'"\''
print("stata_cmd:", stata_cmd)
lib.StataSO_ClearOutputBuffer()
rc = lib.StataSO_Execute(stata_cmd)
out = buf().decode()
print(f"rc={rc} out={repr(out)}")

# Let's just print raw output
stata_cmd2 = b'di `": value label foreign"\'' 
print("cmd2:", stata_cmd2)
lib.StataSO_ClearOutputBuffer()
rc = lib.StataSO_Execute(stata_cmd2)
out = buf().decode()
print(f"rc={rc} out={repr(out)}")
