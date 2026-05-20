"""Ultra-simple: test _bist_matrix with call_void only (no result read)."""
import sys
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize, call_int, call_double, call_string, call_void
from pystata_x.sfi._core import SFIToolkit

initialize()

SFIToolkit.executeCommand('clear all')
SFIToolkit.executeCommand('matrix A = (1,2,3 \\ 4,5,6)')
print("Matrix A created", flush=True)

# call_void doesn't try to read a result
print("\n1. call_void('_bist_matrix', b'A') (should not crash):", flush=True)
try:
    call_void("_bist_matrix", b'A')
    print("   OK", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

# Now try call_int
print("\n2. call_int('_bist_matrix', b'A') (should crash or return 0):", flush=True)
try:
    r = call_int("_bist_matrix", b'A')
    print(f"   {r}", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

# Test rownumb with call_void first, then call_int
print("\n3. call_int('_bist_matrixrownumb', b'A'):", flush=True)
try:
    r = call_int("_bist_matrixrownumb", b'A')
    print(f"   {r}", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

# Test rownumb with integer arg
print("\n4. call_int('_bist_matrixrownumb', 0):", flush=True)
try:
    r = call_int("_bist_matrixrownumb", 0)
    print(f"   {r}", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

# N: what if rownumb expects the arg in SP[0] (not SP[-1])?
# Some _bist_* functions might read differently.
# Let me test with 0 args (reads internal state only)
print("\n5. call_int('_bist_matrixrownumb'):", flush=True)
try:
    r = call_int("_bist_matrixrownumb")
    print(f"   {r}", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

# hcat
print("\n6. call_string('_bist_matrix_hcat'):", flush=True)
try:
    r = call_string("_bist_matrix_hcat")
    print(f"   {r!r}", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

# test _bist_matrix with a number arg (maybe it expects an internal handle)
print("\n7. call_int('_bist_matrix', 1):", flush=True)
try:
    r = call_int("_bist_matrix", 1)
    print(f"   {r}", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

# test _bist_matrix with 0 args (maybe reads current e() matrix)
print("\n8. call_void('_bist_matrix') :", flush=True)
try:
    call_void("_bist_matrix")
    print("   OK", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

print("\nDone", flush=True)
