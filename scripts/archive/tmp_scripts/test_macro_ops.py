import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")
from pystata_x.sfi._engine import call_string, call_int, _LIB

# Test 1: Use StataSO_Execute to set macro
ret = _LIB.StataSO_Execute(b'global testmacro hello_value')
print(f"StataSO_Execute(global) returned: {ret}")

# Read it back with macroexpand
r = call_string("_bist_macroexpand", b"$testmacro")
print(f"macroexpand($testmacro): {r!r}")

# Also try _bist_global
r = call_string("_bist_global", b"testmacro")
print(f"_bist_global(testmacro): {r!r}")

# Test 2: Delete macro
ret = _LIB.StataSO_Execute(b'macro drop testmacro')
print(f"\nStataSO_Execute(macro drop) returned: {ret}")
r = call_string("_bist_macroexpand", b"$testmacro")
print(f"macroexpand($testmacro) after drop: {r!r}")

# Test 3: Try _bist_putglobal with more investigation
print("\n=== Testing _bist_putglobal ===")

# First, set macro via Stata to ensure it exists
_LIB.StataSO_Execute(b'global testabc hello_abc')

# Now read via _bist_global (should work if the macro exists)
r = call_string("_bist_global", b"testabc")
print(f"_bist_global(testabc): {r!r}")

# Now try _bist_putglobal to modify it
r = call_int("_bist_putglobal", b"testabc", b"modified_value")
print(f"_bist_putglobal returned: {r!r}")

# Check if it was modified
r = call_string("_bist_macroexpand", b"$testabc")
print(f"macroexpand($testabc) after putglobal: {r!r}")
