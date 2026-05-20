import os, ctypes

os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
lib = eng._LIB
lib.StataSO_SetOutputBufferSz.restype = None
lib.StataSO_SetOutputBufferSz(65536)
lib.StataSO_ClearOutputBuffer.restype = None
lib.StataSO_Execute(b"sysuse auto, clear")
lib.StataSO_Execute(b"label define e2e_lbl 0 First")
lib.StataSO_Execute(b"label define e2e_lbl 1 Second, modify")

buf = lib.StataSO_GetOutputBuffer
buf.restype = ctypes.c_char_p

# Approach 1: Set local, then use compound backtick di
lib.StataSO_Execute(b"local __t1 : label e2e_lbl 0")
lib.StataSO_ClearOutputBuffer()
# di `"`__t1'"'
lib.StataSO_Execute(bytes([0x64,0x69,0x20,0x60,0x22,0x60,0x5f,0x5f,0x74,0x31,0x27,0x22,0x27]))
out = buf().decode()
print("Approach 1 (di compound):", repr(out))
for line in out.split('\n'):
    s = line.strip()
    if s and not s.startswith('.') and not s.startswith('r('):
        print(f"  GOT: {repr(s)}")

# Approach 2: Read label list output and parse
from pystata_x.sfi._x86_display import _exec
out = _exec("label list e2e_lbl")
print(f"\nApproach 2 (label list): {repr(out)}")
if out:
    for line in out.split('\n'):
        s = line.strip()
        if s and not s.startswith('.') and not s.startswith('r('):
            print(f"  LINE: {repr(s)}")

# Approach 3: Direct output of label list
lib.StataSO_ClearOutputBuffer()
lib.StataSO_Execute(b"label list e2e_lbl")
out = buf().decode()
print(f"\nApproach 3 (raw): {repr(out)}")
for line in out.split('\n'):
    s = line.strip()
    if s and not s.startswith('.') and not s.startswith('r('):
        print(f"  RAW: {repr(s)}")

# Approach 4: Convert local to global then display
lib.StataSO_Execute(b"local __t2 : label e2e_lbl 1")
lib.StataSO_Execute(b"global __g2 `__t2'")
lib.StataSO_ClearOutputBuffer()
lib.StataSO_Execute(b"display \"$__g2\"")
out = buf().decode()
print(f"\nApproach 4 (global bridge): {repr(out)}")
for line in out.split('\n'):
    s = line.strip()
    if s and not s.startswith('.') and not s.startswith('r('):
        print(f"  GOT: {repr(s)}")

# Cleanup
lib.StataSO_Execute(b"label drop e2e_lbl")
lib.StataSO_Execute(b"macro drop __g2")
