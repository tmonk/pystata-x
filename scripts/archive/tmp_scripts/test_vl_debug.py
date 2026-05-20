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

# Test the global bridge approach by checking what the local macro contains
# Step 1: Set local
lib.StataSO_Execute(b"local __t2 : label e2e_lbl 1")

# Step 2: Check the actual bytes being sent for the global command
import sys
cmd = b"global __g2 `__t2'"
print(f"cmd bytes: {cmd}", flush=True)
print(f"cmd hex: {cmd.hex()}", flush=True)
print(f"backtick at pos 13: {cmd[13]:02x}", flush=True)  # should be 0x60

# Step 3: Execute
lib.StataSO_ClearOutputBuffer()
rc = lib.StataSO_Execute(cmd)
out = buf().decode()
print(f"global result: rc={rc} out={repr(out)}", flush=True)

# Step 4: Check the global
lib.StataSO_ClearOutputBuffer()
lib.StataSO_Execute(b"display \"$__g2\"")
out = buf().decode()
print(f"display global: {repr(out)}", flush=True)
for line in out.split('\n'):
    s = line.strip()
    if s and not s.startswith('.') and not s.startswith('r('):
        print(f"  GOT: {repr(s)}", flush=True)

# Step 5: Direct test of local macro content by invoking it
lib.StataSO_Execute(b"local __t3 : label e2e_lbl 1")
lib.StataSO_ClearOutputBuffer()
# di `"`__t3'"' in bytes
cmd2 = bytes([0x64, 0x69, 0x20, 0x60, 0x22, 0x60, 0x5f, 0x5f, 0x74, 0x33, 0x27, 0x22, 0x27])
lib.StataSO_Execute(cmd2)
out = buf().decode()
print(f"direct local: {repr(out)}", flush=True)
for line in out.split('\n'):
    s = line.strip()
    if s and not s.startswith('.') and not s.startswith('r('):
        print(f"  GOT: {repr(s)}", flush=True)

# Cleanup
lib.StataSO_Execute(b"label drop e2e_lbl")
lib.StataSO_Execute(b"macro drop __g2")
