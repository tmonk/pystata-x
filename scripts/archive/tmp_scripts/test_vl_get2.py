import os, ctypes

os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
lib = eng._LIB
lib.StataSO_SetOutputBufferSz.restype = None
lib.StataSO_SetOutputBufferSz(65536)
lib.StataSO_ClearOutputBuffer.restype = None
lib.StataSO_Execute(b"sysuse auto, clear")
lib.StataSO_Execute(b"label define e2e_getlbl 0 Domestic")
lib.StataSO_Execute(b"label define e2e_getlbl 1 Foreign, modify")

buf = lib.StataSO_GetOutputBuffer
buf.restype = ctypes.c_char_p

# Try: does the local macro get set correctly?
lib.StataSO_ClearOutputBuffer()
lib.StataSO_Execute(b"local __vlx : label e2e_getlbl 0")
out = buf().decode()
print("local __vlx set:", repr(out))

# Now check if local is set by getting it into a global
lib.StataSO_Execute(b"di `__vlx'")

lib.StataSO_ClearOutputBuffer()
# Use display with backtick expansion of local
# di `"`__vlx'"'
# hex: 64 69 20 60 22 60 5f 5f 76 6c 78 27 22 27
cmd = bytes([0x64,0x69,0x20,0x60,0x22,0x60,0x5f,0x5f,0x76,0x6c,0x78,0x27,0x22,0x27])
rc = lib.StataSO_Execute(cmd)
out = buf().decode()
print(f"di backtick_lbl: rc={rc} out={repr(out)}")
for line in out.split('\n'):
    s = line.strip()
    if s and not s.startswith('.') and not s.startswith('r('):
        print(f"  -> {repr(s)}")

# Also try simple di with compound double quotes
lib.StataSO_ClearOutputBuffer()
lib.StataSO_Execute(b"di `\": label e2e_getlbl 0\"'")
out = buf().decode()
print(f"inline: {repr(out)}")
for line in out.split('\n'):
    s = line.strip()
    if s and not s.startswith('.') and not s.startswith('r('):
        print(f"  -> {repr(s)}")

# Clean up
lib.StataSO_Execute(b"label drop e2e_getlbl")
