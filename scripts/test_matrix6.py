"""Test matrix functions after regression (e() matrices)."""
import sys
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize, call_int, call_string
from pystata_x.sfi._core import SFIToolkit

initialize()
SFIToolkit.executeCommand('clear all')
SFIToolkit.executeCommand('sysuse auto, clear')

# Run regression to populate e()
SFIToolkit.executeCommand('regress price mpg weight')

print("=== After regress ===", flush=True)

print("1. _bist_matrix_hcat...", flush=True)
r = call_string("_bist_matrix_hcat", b'')
print(f"   {r!r}", flush=True)

print("2. _bist_matrixrownumb('e(b)')...", flush=True)
r = call_int("_bist_matrixrownumb", b'e(b)')
print(f"   {r}", flush=True)

print("3. _bist_matrixcolnumb('e(b)')...", flush=True)
r = call_int("_bist_matrixcolnumb", b'e(b)')
print(f"   {r}", flush=True)

print("4. _bist_matrix('e(b)')...", flush=True)
try:
    r = call_string("_bist_matrix", b'e(b)')
    print(f"   {r!r}", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

print("5. _bist_matrix('e(V)')...", flush=True)
try:
    r = call_string("_bist_matrix", b'e(V)')
    print(f"   {r!r}", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

print("6. _bist_matrixrowstripe('e(b)')...", flush=True)
try:
    r = call_string("_bist_matrixrowstripe", b'e(b)')
    print(f"   {r!r}", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

print("7. _bist_matrixcolstripe('e(b)')...", flush=True)
try:
    r = call_string("_bist_matrixcolstripe", b'e(b)')
    print(f"   {r!r}", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

print("Done", flush=True)
