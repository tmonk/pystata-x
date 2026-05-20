"""Debug backtick expansion in StataSO_Execute."""
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

# Test 1: Simple local macro set and display
lib.StataSO_ClearOutputBuffer()
rc = lib.StataSO_Execute(b"local myvar = 42")
print(f"local set: rc={rc}")
out = buf().decode()
print(f"  out={repr(out)}")

lib.StataSO_ClearOutputBuffer()
# di "value is `myvar'"
rc = lib.StataSO_Execute(bytes([0x64,0x69,0x20,0x22,0x76,0x61,0x6c,0x75,0x65,0x20,0x69,0x73,0x20,0x60,0x6d,0x79,0x76,0x61,0x72,0x27,0x22]))
# di "value is `myvar'"
out = buf().decode()
print(f"di local: rc={rc}")
for line in out.split('\n'):
    s = line.strip()
    if s and not s.startswith('.') and not s.startswith('r('):
        print(f"  GOT: {repr(s)}")

# Test 2: global with local expansion
lib.StataSO_ClearOutputBuffer()
rc = lib.StataSO_Execute(b"local mylabel : label origin 1")
print(f"local label: rc={rc}")

lib.StataSO_ClearOutputBuffer()
# di `"`mylabel'"'
rc = lib.StataSO_Execute(bytes([0x64,0x69,0x20,0x60,0x22,0x60,0x6d,0x79,0x6c,0x61,0x62,0x65,0x6c,0x27,0x22,0x27]))
out = buf().decode()
print(f"di label: rc={rc}")
for line in out.split('\n'):
    s = line.strip()
    if s and not s.startswith('.') and not s.startswith('r('):
        print(f"  GOT: {repr(s)}")

# Test 3: Different approach - set a temp scalar instead of local
lib.StataSO_ClearOutputBuffer()
lib.StataSO_Execute(b"scalar __tmp = 42")
lib.StataSO_ClearOutputBuffer()
rc = lib.StataSO_Execute(b"display scalar(__tmp)")
out = buf().decode()
print(f"scalar approach: rc={rc}")
for line in out.split('\n'):
    s = line.strip()
    if s and not s.startswith('.') and not s.startswith('r('):
        print(f"  GOT: {repr(s)}")
