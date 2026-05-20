import os, sys, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
lib = eng._LIB
lib.StataSO_Execute(b"sysuse auto, clear")
print("OK", flush=True)

lib.StataSO_SetOutputBufferSz(65536)
lib.StataSO_ClearOutputBuffer.restype = None

# Test scalar mystr = hello
lib.StataSO_ClearOutputBuffer()
rc = lib.StataSO_Execute(b"scalar mystr = hello")
buf = lib.StataSO_GetOutputBuffer
buf.restype = ctypes.c_char_p
out = buf()
print(f"After 'scalar mystr = hello': rc={rc}", flush=True)
print(f"Output: {out.decode()!r}", flush=True)

# Check what Stata stores
lib.StataSO_ClearOutputBuffer()
rc = lib.StataSO_Execute(b"display mystr")
out = buf()
print(f"display mystr: rc={rc} out={out.decode()!r}", flush=True)

lib.StataSO_ClearOutputBuffer()
rc = lib.StataSO_Execute(b"describe mystr")
out = buf()
print(f"describe mystr: rc={rc} out={out.decode()!r}", flush=True)

# Try with quotes
lib.StataSO_ClearOutputBuffer()
rc = lib.StataSO_Execute(b'global mystrscalar "hello"')
out = buf()
print(f"After 'global mystrscalar \"hello\"': rc={rc} out={out.decode()!r}", flush=True)

lib.StataSO_ClearOutputBuffer()
rc = lib.StataSO_Execute(b'display "$mystrscalar"')
out = buf()
print(f"display \"\$mystrscalar\": rc={rc} out={out.decode()!r}", flush=True)

lib.StataSO_ClearOutputBuffer()
rc = lib.StataSO_Execute(b'display scalar(mystrscalar)')
out = buf()
print(f"display scalar(mystrscalar): rc={rc} out={out.decode()!r}", flush=True)
