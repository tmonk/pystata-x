"""Test value label extraction using StataSO_Execute."""
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

# First, create a global macro via Stata that captures the value label name
# Using extended macro functions through StataSO_Execute
# The trick: we use compound double quotes and backtick expansion

# Step 1: Create a global macro = the value label of variable foreign
# Stata command: global __tmp : value label foreign
# BUT: global cannot use extended functions directly!
# Instead: local first, then pass to global
lib.StataSO_Execute(b"local _vllbl : value label foreign")
lib.StataSO_Execute(b"global __vllbl `_vllbl'")

# Step 2: Display the global macro
lib.StataSO_ClearOutputBuffer()
lib.StataSO_Execute(b"display \"$__vllbl\"")
out = buf().decode()
print("foreign value label:", repr(out))
for line in out.split('\n'):
    s = line.strip()
    if s and not s.startswith('.') and not s.startswith('r('):
        print(f"  -> {repr(s)}")

# Step 3: For make (no value label)
lib.StataSO_Execute(b"local _vllbl2 : value label make")
lib.StataSO_Execute(b"global __vllbl2 `_vllbl2'")
lib.StataSO_ClearOutputBuffer()
lib.StataSO_Execute(b"display \"$__vllbl2\"")
out = buf().decode()
print("make value label:", repr(out))
for line in out.split('\n'):
    s = line.strip()
    if s and not s.startswith('.') and not s.startswith('r('):
        print(f"  -> {repr(s)}")
