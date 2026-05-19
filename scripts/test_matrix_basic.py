"""Step-by-step test of _bist_matrix* functions after matrix creation."""
import sys, ctypes, json
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize, _BASE, _restore_sp, call_int, call_string, call_void
from pystata_x.sfi._core import SFIToolkit

initialize()
manifest = json.load(open('src/pystata_x/sfi/manifest.json'))
sp_addr = _BASE + 0x39b7000 + 0x108

# Create a matrix first
SFIToolkit.executeCommand('clear all')
SFIToolkit.executeCommand('matrix A = (1,2,3 \\ 4,5,6)')
print("Matrix A created", flush=True)

# Test various _bist_matrix* calls

# 1. _bist_matrix_hcat (list matrices)
print("\n1. _bist_matrix_hcat:", flush=True)
try:
    r = call_string("_bist_matrix_hcat", b'')
    print(f"   {r!r}", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

# 2. _bist_matrix('A') - crash-prone but try
print("\n2. _bist_matrix('A'):", flush=True)
try:
    r = call_string("_bist_matrix", b'A')
    print(f"   {r!r}", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

# 3. _bist_matrixrownumb
print("\n3. _bist_matrixrownumb('A'):", flush=True)
try:
    r = call_int("_bist_matrixrownumb", b'A')
    print(f"   {r}", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

# 4. _bist_matrixcolnumb
print("\n4. _bist_matrixcolnumb('A'):", flush=True)
try:
    r = call_int("_bist_matrixcolnumb", b'A')
    print(f"   {r}", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

# 5. _bist_replacematrix
print("\n5. _bist_replacematrix('A'):", flush=True)
try:
    r = call_int("_bist_replacematrix", b'A')
    print(f"   {r}", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

# 6. _bist_isnumvar - non-matrix, confirm still works
print("\n6. _bist_nobs (sanity check):", flush=True)
try:
    r = call_double("_bist_nobs")
    print(f"   {r}", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

print("\nDone", flush=True)
