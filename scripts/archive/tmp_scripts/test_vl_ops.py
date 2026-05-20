"""Test ValueLabel operations via StataSO_Execute."""
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
    for line in out.split('\n'):
        s = line.strip()
        if s and not s.startswith('.') and not s.startswith('r(') and not s.startswith('>'):
            return s
    return ""

# Test label list output structure
print("=== Value Label Tests ===")

# check existing label
s = run(b"label list origin")
print(f"origin: {s!r}")

# check nonexistent label
s = run(b"label list nonexistent")
print(f"nonexistent: {s!r}")

# create test label
s = run(b"label define e2e_test_lbl . \"\"")
print(f"create: {s!r}")

# check it exists
s = run(b"label list e2e_test_lbl")
print(f"list after create: {s!r}")

# define a mapping with modify
s = run(b"label define e2e_test_lbl 0 \"No\", modify")
print(f"define 0: {s!r}")

s = run(b"label define e2e_test_lbl 1 \"Yes\", modify")
print(f"define 1: {s!r}")

s = run(b"label list e2e_test_lbl")
print(f"list after defines: {s!r}")

# get specific label by value
# using extended macro: local lbl : label e2e_test_lbl 0
from pystata_x.sfi._x86_display import _exec
s = _exec("local __vllbl : label e2e_test_lbl 0\ndi $__vllbl")
print(f"label of 0: {s!r}")

lib.StataSO_Execute(b"local __vllbl : label e2e_test_lbl 1")
lib.StataSO_Execute(b"global __gg `__vllbl'")
s = run(b"display \"$__gg\"")
print(f"label of 1: {s!r}")

# drop the label
s = run(b"label drop e2e_test_lbl")
print(f"drop: {s!r}")

s = run(b"label list e2e_test_lbl")
print(f"list after drop: {s!r}")
