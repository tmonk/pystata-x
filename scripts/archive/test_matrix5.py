"""Save matrix first, then test."""
import sys
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize, call_int, call_string
from pystata_x.sfi._core import SFIToolkit

initialize()
SFIToolkit.executeCommand('prog drop _all')
SFIToolkit.executeCommand('clear all')

# Create + save matrix
SFIToolkit.executeCommand('matrix A = (1,2,3 \\ 4,5,6)')
SFIToolkit.executeCommand('ereturn matrix A')

print("1. _bist_matrix_hcat...", flush=True)
r = call_string("_bist_matrix_hcat", b'')
print(f"   {r!r}", flush=True)

print("2. _bist_matrixrownumb...", flush=True)
r = call_int("_bist_matrixrownumb", b'A')
print(f"   {r}", flush=True)

print("3. _bist_matrixcolnumb...", flush=True)
r = call_int("_bist_matrixcolnumb", b'A')
print(f"   {r}", flush=True)

print("4. _bist_matrixrowstripe...", flush=True)
r = call_string("_bist_matrixrowstripe", b'A')
print(f"   {r!r}", flush=True)

print("5. _bist_matrixcolstripe...", flush=True)
r = call_string("_bist_matrixcolstripe", b'A')
print(f"   {r!r}", flush=True)

print("6. _bist_matrix...", flush=True)
try:
    r = call_string("_bist_matrix", b'A')
    print(f"   {r!r}", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

print("Done", flush=True)
