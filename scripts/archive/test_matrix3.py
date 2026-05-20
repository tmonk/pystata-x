"""Find the crash point in matrix calls."""
import sys
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize, call_int, call_string
from pystata_x.sfi._core import SFIToolkit, Matrix

initialize()
print("init OK", flush=True)

SFIToolkit.executeCommand('clear all')
print("clear all OK", flush=True)

SFIToolkit.executeCommand('matrix A = (1,2,3 \\ 4,5,6)')
print("matrix A created OK", flush=True)

print(f"getNames... {Matrix.getNames()}", flush=True)

# Step by step
print("Testing call_string('_bist_matrix_hcat', '')...", flush=True)
r = call_string("_bist_matrix_hcat", b'')
print(f"  OK: {r!r}", flush=True)

print("Testing call_int('_bist_matrixrownumb', 'A')...", flush=True)
try:
    r = call_int("_bist_matrixrownumb", b'A')
    print(f"  OK: {r}", flush=True)
except Exception as e:
    print(f"  ERR: {e}", flush=True)

print("Testing call_int('_bist_matrixcolnumb', 'A')...", flush=True)
try:
    r = call_int("_bist_matrixcolnumb", b'A')
    print(f"  OK: {r}", flush=True)
except Exception as e:
    print(f"  ERR: {e}", flush=True)

print("Testing call_string('_bist_matrix', 'A')...", flush=True)
try:
    r = call_string("_bist_matrix", b'A')
    print(f"  OK: {r!r}", flush=True)
except Exception as e:
    print(f"  ERR: {e}", flush=True)

print("Done", flush=True)
