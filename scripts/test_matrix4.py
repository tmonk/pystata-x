"""Find the crash — isolate to direct call or class method."""
import sys
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize, call_int, call_string
from pystata_x.sfi._core import SFIToolkit

initialize()
print("init OK", flush=True)

SFIToolkit.executeCommand('clear all')
print("clear all OK", flush=True)

SFIToolkit.executeCommand('matrix A = (1,2,3 \\ 4,5,6)')
print("matrix A created OK", flush=True)

# Test direct calls one by one
print("1. call_string('_bist_matrix_hcat', '')...", flush=True)
try:
    r = call_string("_bist_matrix_hcat", b'')
    print(f"   OK: {r!r}", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)
    raise SystemExit(0)

print("2. call_int('_bist_matrixrownumb', 'A')...", flush=True)
try:
    r = call_int("_bist_matrixrownumb", b'A')
    print(f"   OK: {r}", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

print("3. call_int('_bist_matrixcolnumb', 'A')...", flush=True)
try:
    r = call_int("_bist_matrixcolnumb", b'A')
    print(f"   OK: {r}", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

print("4. call_string('_bist_matrixrowstripe', 'A')...", flush=True)
try:
    r = call_string("_bist_matrixrowstripe", b'A')
    print(f"   OK: {r!r}", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

print("5. call_string('_bist_matrixcolstripe', 'A')...", flush=True)
try:
    r = call_string("_bist_matrixcolstripe", b'A')
    print(f"   OK: {r!r}", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

print("6. call_string('_bist_matrix', 'A')...", flush=True)
try:
    r = call_string("_bist_matrix", b'A')
    print(f"   OK: {r!r}", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

print("Done", flush=True)
