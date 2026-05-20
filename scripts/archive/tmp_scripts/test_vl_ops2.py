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

from pystata_x.sfi._x86_display import _exec

# Test: can we use label define with a real value?
s = _exec("label define e2e_test2 0 No")
print(f"define 0 No: {s!r}")

# Check label exists via label list
s = _exec("label list e2e_test2")
print(f"list: {s!r}")

# Add another mapping with modify
s = _exec("label define e2e_test2 1 Yes, modify")
print(f"define 1 Yes: {s!r}")

s = _exec("label list e2e_test2")
print(f"list after 1: {s!r}")

# Get label for value 0
s = _exec("local __vl0 : label e2e_test2 0\ndi $__vl0")
print(f"label of 0: {s!r}")

# Get label for value 1
s = _exec("local __vl1 : label e2e_test2 1\ndi $__vl1")
print(f"label of 1: {s!r}")

# Drop
s = _exec("label drop e2e_test2")
print(f"drop: {s!r}")

s = _exec("label list e2e_test2")
print(f"list after drop: {s!r}")

# Also test: label define with modify option FIRST (no need to create separately)
s = _exec("label define e2e_test3 5 Five, modify")
print(f"define 5 Five (modify without create): {s!r}")
s = _exec("label list e2e_test3")
print(f"list: {s!r}")
s = _exec("label drop e2e_test3")
print(f"drop: {s!r}")
