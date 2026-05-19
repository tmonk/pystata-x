"""Test basic Matrix methods."""
import sys
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize, call_int, call_string, call_void
from pystata_x.sfi._core import SFIToolkit, Matrix

initialize()
SFIToolkit.executeCommand('clear all')
SFIToolkit.executeCommand('matrix A = (1,2,3 \\ 4,5,6)')

print("=== Matrix Tests ===", flush=True)

print(f"getNames: {Matrix.getNames()}", flush=True)
print(f"exists('A'): {Matrix.exists('A')}", flush=True)
print(f"get('A'): {Matrix.get('A')}", flush=True)

# Row/col count
rc = call_int("_bist_matrixrownumb", b'A')
print(f"rownumb('A'): {rc}", flush=True)
cc = call_int("_bist_matrixcolnumb", b'A')
print(f"colnumb('A'): {cc}", flush=True)

# Row/col names  
rs = call_string("_bist_matrixrowstripe", b'A')
print(f"rowstripe('A'): {rs!r}", flush=True)
cs = call_string("_bist_matrixcolstripe", b'A')
print(f"colstripe('A'): {cs!r}", flush=True)

# _bist_matrix_hcat (list all)
hcat = call_string("_bist_matrix_hcat", b'')
print(f"matrix_hcat: {hcat!r}", flush=True)

print("\nDone, state OK", flush=True)
