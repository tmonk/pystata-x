"""Direct test of _bi_st_putmatrixcolstripe/rowstripe.
Bypasses Matrix class methods entirely."""
import sys, ctypes, json
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize, _BASE, _restore_sp, call_string, call_int
from pystata_x.sfi._core import SFIToolkit

initialize()
manifest = json.load(open('src/pystata_x/sfi/manifest.json'))
sp_addr = _BASE + 0x39b7000 + 0x108

pushstr_fn = ctypes.cast(
    _BASE + manifest["symbols"]["_pushstr"],
    ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_int64)
)
pushint_fn = ctypes.cast(
    _BASE + manifest["symbols"]["_pushint"],
    ctypes.CFUNCTYPE(None, ctypes.c_int64)
)

def pushstr(s):
    pushstr_fn(ctypes.c_char_p(s), len(s))

def pushint(v):
    pushint_fn(v)

def save_sp():
    return ctypes.c_uint64.from_address(sp_addr).value

# Create a matrix first via Stata command
SFIToolkit.executeCommand('clear all')
SFIToolkit.executeCommand('matrix A = (1,2,3 \\ 4,5,6)')

# Test _bi_st_putmatrixcolstripe
pcs_addr = _BASE + manifest["symbols"].get("_bi_st_putmatrixcolstripe", 0)
prs_addr = _BASE + manifest["symbols"].get("_bi_st_putmatrixrowstripe", 0)
print(f"putmatrixcolstripe: {hex(pcs_addr)}", flush=True)
print(f"putmatrixrowstripe: {hex(prs_addr)}", flush=True)

if pcs_addr:
    fn = ctypes.cast(pcs_addr, ctypes.CFUNCTYPE(None, ctypes.c_int))
    # Try pushstr, pushstr convention (type=-3 for first arg)
    sp0 = save_sp()
    pushstr(b'A')
    pushstr(b'col1 col2 col3')
    print(f"\nBefore call: SP={hex(save_sp())}, base={hex(sp0)}", flush=True)
    fn(2)
    sp = save_sp()
    print(f"After call: SP={hex(sp)}", flush=True)
    _restore_sp(sp0)
    
    # Check if names changed by using Stata command to verify
    SFIToolkit.executeCommand('matrix list A')
    print("(check output above for column names)", flush=True)

if prs_addr:
    fn2 = ctypes.cast(prs_addr, ctypes.CFUNCTYPE(None, ctypes.c_int))
    sp0 = save_sp()
    pushstr(b'A')
    pushstr(b'row1 row2')
    fn2(2)
    _restore_sp(sp0)
    
    SFIToolkit.executeCommand('matrix list A')
    print("(check output above for row names)", flush=True)

# Now test _bist_matrix (with various argument patterns)
print("\n=== Rownumb/colnumb direct tests ===", flush=True)
fn_rownumb = ctypes.cast(
    _BASE + manifest["symbols"].get("_bist_matrixrownumb", 0),
    ctypes.CFUNCTYPE(None, ctypes.c_int)
)
fn_colnumb = ctypes.cast(
    _BASE + manifest["symbols"].get("_bist_matrixcolnumb", 0),
    ctypes.CFUNCTYPE(None, ctypes.c_int)
)

# Try pushstr for rownumb (type=-3 tsmat convention from _bi_st_ family)
sp0 = save_sp()
pushstr(b'A')  # type=-3 tsmat
fn_rownumb(1)
sp = save_sp()
# Read result from stack
tsmat = ctypes.c_uint64.from_address(sp).value
if tsmat and tsmat > 0x100000:
    val = ctypes.c_double.from_address(tsmat).value
    print(f"rownumb(pushstr A): {val}", flush=True)
else:
    print(f"rownumb(pushstr A): tsmat={hex(tsmat) if tsmat else 0}", flush=True)
_restore_sp(sp0)

# Try pushint for rownumb (standard _bist_ convention)  
sp0 = save_sp()
pushint(0)  # maybe it expects an index, not a name
fn_rownumb(1)
sp = save_sp()
tsmat = ctypes.c_uint64.from_address(sp).value
if tsmat and tsmat > 0x100000:
    val = ctypes.c_double.from_address(tsmat).value
    print(f"rownumb(pushint 0): {val}", flush=True)
else:
    print(f"rownumb(pushint 0): tsmat={hex(tsmat) if tsmat else 0}", flush=True)
_restore_sp(sp0)

print("\nDone", flush=True)
