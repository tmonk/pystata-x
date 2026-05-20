"""Test Matrix methods systematically."""
import sys
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize, call_int, call_string, call_void
from pystata_x.sfi._core import SFIToolkit, Matrix

initialize()
SFIToolkit.executeCommand('clear all')
SFIToolkit.executeCommand('matrix A = (1,2,3 \\ 4,5,6)')
SFIToolkit.executeCommand('matrix B = J(3,4,0)')

print("=== Matrix Tests ===", flush=True)

# getNames
print(f"\ngetNames: {Matrix.getNames()}", flush=True)

# exists
print(f"exists('A'): {Matrix.exists('A')}", flush=True)
print(f"exists('C'): {Matrix.exists('C')}", flush=True)

# get
print(f"get('A'): {Matrix.get('A')}", flush=True)

# getRowCount / getColCount
print(f"getRowCount('A'): {Matrix.getRowCount('A')}", flush=True)
print(f"getColCount('A'): {Matrix.getColCount('A')}", flush=True)
print(f"getRowCount('B'): {Matrix.getRowCount('B')}", flush=True)
print(f"getColCount('B'): {Matrix.getColCount('B')}", flush=True)

# getRowNames / getColNames
print(f"getRowNames('A'): {Matrix.getRowNames('A')}", flush=True)
print(f"getColNames('A'): {Matrix.getColNames('A')}", flush=True)

# Test _bist_matrixrownumb/colnumb directly
print(f"\n=== Direct calls ===", flush=True)
rc = call_int("_bist_matrixrownumb", b'A')
print(f"call_int('_bist_matrixrownumb', 'A'): {rc}", flush=True)
cc = call_int("_bist_matrixcolnumb", b'A')
print(f"call_int('_bist_matrixcolnumb', 'A'): {cc}", flush=True)

# Test _bist_matrixrowstripe/colstripe
rs = call_string("_bist_matrixrowstripe", b'A')
print(f"call_string('_bist_matrixrowstripe', 'A'): {rs!r}", flush=True)
cs = call_string("_bist_matrixcolstripe", b'A')
print(f"call_string('_bist_matrixcolstripe', 'A'): {cs!r}", flush=True)

# Test _bist_matrix_hcat
hcat = call_string("_bist_matrix_hcat", b'')
print(f"call_string('_bist_matrix_hcat', ''): {hcat!r}", flush=True)

# Test _bist_replacematrix
SFIToolkit.executeCommand('matrix C = (99, 98, 97 \\ 96, 95, 94)')
SFIToolkit.executeCommand('matrix list C')
rm = call_int("_bist_replacematrix", b'C')
print(f"\ncall_int('_bist_replacematrix', 'C'): {rm}", flush=True)
# Check the matrix content
print(f"get('C') after replacematrix: {Matrix.get('C')}", flush=True)

# Test _bi_st_putmatrixcolstripe / _bi_st_putmatrixrowstripe
import ctypes, json
import pystata_x.sfi._engine as eng
base = eng._BASE
sp_addr = base + 0x39b7000 + 0x108
manifest = json.load(open('src/pystata_x/sfi/manifest.json'))
_restore_sp = eng._restore_sp
pushstr = lambda v: eng._pushstr_fn(v, len(v))
pushint = lambda v: eng._pushint_fn(v)

# Test _bi_st_putmatrixcolstripe with string name + list of names
fn_addr = base + manifest["symbols"].get("_bi_st_putmatrixcolstripe", 0)
if fn_addr:
    print(f"\n=== _bi_st_putmatrixcolstripe at {hex(fn_addr)} ===", flush=True)
    fn = ctypes.cast(fn_addr, ctypes.CFUNCTYPE(None, ctypes.c_int))
    sp_base = ctypes.c_uint64.from_address(sp_addr).value
    pushstr(b'C')     # matrix name
    pushstr(b'r1')    # a column name?
    fn(2)
    err = ctypes.c_int32.from_address(base + 0x39b7000 + 0x11c).value
    print(f"  err={err}", flush=True)
    _restore_sp(sp_base)

print("\nDone", flush=True)
