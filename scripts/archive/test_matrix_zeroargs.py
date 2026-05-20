"""Test _bist_matrix* with 0 args (reads internal state)."""
import sys
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize, call_int, call_double, call_string, call_void
from pystata_x.sfi._core import SFIToolkit

initialize()

SFIToolkit.executeCommand('clear all')
SFIToolkit.executeCommand('sysuse auto, clear')
SFIToolkit.executeCommand('regress price mpg weight')
print("After regress (estimation results available)", flush=True)

# Test _bist_matrix with 0 args
print("\n1. call_string('_bist_matrix'):", flush=True)
try:
    r = call_string("_bist_matrix")
    print(f"   {r!r}", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

# Test rownumb with 0 args
print("\n2. call_int('_bist_matrixrownumb'):", flush=True)
try:
    r = call_int("_bist_matrixrownumb")
    print(f"   {r}", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

# Test colnumb with 0 args
print("\n3. call_int('_bist_matrixcolnumb'):", flush=True)
try:
    r = call_int("_bist_matrixcolnumb")
    print(f"   {r}", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

# Test hcat with 0 args
print("\n4. call_string('_bist_matrix_hcat'):", flush=True)
try:
    r = call_string("_bist_matrix_hcat")
    print(f"   {r!r}", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

# Test replacematrix with 0 args
print("\n5. call_int('_bist_replacematrix'):", flush=True)
try:
    r = call_int("_bist_replacematrix")
    print(f"   {r}", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

# Create a regular matrix and test again
SFIToolkit.executeCommand('clear all')
SFIToolkit.executeCommand('matrix A = (1,2,3 \\ 4,5,6)')
print("\nAfter creating matrix A:", flush=True)

print("\n6. call_int('_bist_matrixrownumb'):", flush=True)
try:
    r = call_int("_bist_matrixrownumb")
    print(f"   {r}", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

# Test rownumb with int arg
print("\n7. call_int('_bist_matrixrownumb', 0):", flush=True)
try:
    r = call_int("_bist_matrixrownumb", 0)
    print(f"   {r}", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

# Test rownumb with float arg
print("\n8. call_double('_bist_matrixrownumb', 1.0):", flush=True)
try:
    r = call_double("_bist_matrixrownumb", 1.0)
    print(f"   {r}", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

print("\nDone", flush=True)
