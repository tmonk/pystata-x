import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

from pystata_x.sfi._engine import call_string, call_int, _LIB

# Test macro operations
print("=== Macro tests ===")

# Test _bist_macroexpand with a non-existent global
r = call_string("_bist_macroexpand", b"$nonexistent_xyz")
print(f"Macroexpand($nonexistent_xyz): {r!r}")

# Test _bist_putglobal
r = call_int("_bist_putglobal", b"testmacro", b"hello_value")
print(f"putglobal(testmacro, hello_value): {r}")

# Now try to read it back
r = call_string("_bist_global", b"testmacro")
print(f"getGlobal(testmacro): {r!r}")

r = call_string("_bist_macroexpand", b"$testmacro")
print(f"macroexpand($testmacro): {r!r}")

# Try delGlobal
r = call_int("_bist_putglobal", b"testmacro", b" ")
print(f"putglobal(testmacro, ' '): {r}")

# Read back after delete
r = call_string("_bist_global", b"testmacro")
print(f"getGlobal(testmacro) after delete: {r!r}")

# Test _bist_numscalar
print("\n=== Scalar tests ===")
r = call_string("_bist_numscalar", b"pi")
print(f"numscalar(pi) via call_string: {r!r}")

r = None
try:
    r = call_double("_bist_numscalar", b"pi")
except:
    pass
print(f"numscalar(pi) via call_double: {r}")

# Test _bist_strscalar
r = call_string("_bist_strscalar", b"some_scalar")
print(f"strscalar(some_scalar): {r!r}")
