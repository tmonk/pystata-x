"""Clean isolated test of _bist_matrix* functions.
Fresh Stata state, one function at a time."""
import sys, ctypes, json, os
sys.path.insert(0, 'src')

from pystata_x.sfi._engine import initialize, _BASE, _restore_sp
from pystata_x.sfi._engine import call_int, call_double, call_string, call_void
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

# ============================
# STEP 1: Verify basics work
# ============================
print("=== Phase 1: Sanity check ===", flush=True)
SFIToolkit.executeCommand('clear all')
nobs = call_double("_bist_nobs")
print(f"nobs after clear: {nobs}", flush=True)

# ============================
# STEP 2: Create matrix and verify
# ============================
print("\n=== Phase 2: Create matrix ===", flush=True)
SFIToolkit.executeCommand('matrix A = (1,2,3 \\ 4,5,6)')
print("matrix A created", flush=True)

# Verify via Stata that matrix exists
SFIToolkit.executeCommand('matrix list A')
print("(matrix listed - confirm no crash)", flush=True)

# ============================
# STEP 3: Test _bist_matrix_hcat
# ============================
print("\n=== Phase 3: _bist_matrix_hcat ===", flush=True)
r = call_string("_bist_matrix_hcat", b'')
print(f"result: {r!r}", flush=True)

# ============================
# STEP 4: Test _bist_matrix 
# with proper SP management
# ============================
print("\n=== Phase 4: _bist_matrix ===", flush=True)
fn_matrix = ctypes.cast(
    _BASE + manifest["symbols"]["_bist_matrix"],
    ctypes.CFUNCTYPE(None, ctypes.c_int)
)

# Try pushstr (type=-3) for arg1, following _bi_st_ convention
print("4a. pushstr name, w0=1:", flush=True)
sp0 = save_sp()
pushstr(b'A')
fn_matrix(1)
sp = save_sp()
# Read result tsmat
tsmat = ctypes.c_uint64.from_address(sp).value
print(f"    SP: {sp0:#x} -> {sp:#x}, tsmat={hex(tsmat) if tsmat else 0}", flush=True)
if tsmat and tsmat > 0x100000:
    gso = ctypes.c_uint64.from_address(tsmat).value
    if gso and gso > 0x100000:
        str_ptr = ctypes.c_uint64.from_address(gso).value
        if str_ptr and str_ptr > 0x100000:
            slen = ctypes.c_uint32.from_address(str_ptr).value
            print(f"    slen={slen}, str={ctypes.string_at(str_ptr+4, min(slen,200))!r}", flush=True)
_restore_sp(sp0)

# Try pushint (type=0) for arg1, standard _bist_ convention
print("\n4b. pushint name, w0=1:", flush=True)
sp0 = save_sp()
# Can't pushint a string name... this would interpret bytes as double
# What does _bist_matrix actually expect?
r = call_string("_bist_matrix", b'A')
print(f"    call_string result: {r!r}", flush=True)

# ============================
# STEP 5: Test _bist_matrixrownumb
# ============================
print("\n=== Phase 5: _bist_matrixrownumb ===", flush=True)
r = call_int("_bist_matrixrownumb", b'A')
print(f"call_int result: {r}", flush=True)

# ============================
# STEP 6: Test _bist_matrixcolnumb
# ============================
print("\n=== Phase 6: _bist_matrixcolnumb ===", flush=True)
r = call_int("_bist_matrixcolnumb", b'A')
print(f"call_int result: {r}", flush=True)

# ============================
# STEP 7: Test _bist_replacematrix
# ============================
print("\n=== Phase 7: _bist_replacematrix ===", flush=True)
r = call_int("_bist_replacematrix", b'A')
print(f"call_int result: {r}", flush=True)

# ============================
# STEP 8: Test rownumb/colnumb with 
# different arg patterns (maybe need int index)
# ============================
print("\n=== Phase 8: Direct raw rownumb tests ===", flush=True)
fn_rownumb = ctypes.cast(
    _BASE + manifest["symbols"]["_bist_matrixrownumb"],
    ctypes.CFUNCTYPE(None, ctypes.c_int)
)

# Various arg attempts - pushint versions
for arg_desc, arg_val in [("pushint 0", 0), ("pushint 1", 1), ("pushint 2", 2),
                           ("pushstr 'A'", b'A'), ("pushstr 'e(b)'", b'e(b)')]:
    sp0 = save_sp()
    try:
        if isinstance(arg_val, bytes):
            pushstr(arg_val)
        else:
            pushint(arg_val)
        fn_rownumb(1)
        sp = save_sp()
        tsmat = ctypes.c_uint64.from_address(sp).value
        val = None
        if tsmat and tsmat > 0x100000:
            val = ctypes.c_double.from_address(tsmat).value
        print(f"  {arg_desc:25s}: SP delta={sp-sp0:+3d} tsmat={hex(tsmat) if tsmat else 0} val={val}", flush=True)
    except Exception as e:
        print(f"  {arg_desc:25s}: ERR {e}", flush=True)
    _restore_sp(sp0)

# Also try with 0 args (maybe it reads internal state)
print("\n  rownumb with 0 args:", flush=True)
sp0 = save_sp()
try:
    fn_rownumb(0)
    sp = save_sp()
    tsmat = ctypes.c_uint64.from_address(sp).value
    val = None
    if tsmat and tsmat > 0x100000:
        val = ctypes.c_double.from_address(tsmat).value
    print(f"    SP delta={sp-sp0:+3d} tsmat={hex(tsmat) if tsmat else 0} val={val}", flush=True)
except Exception as e:
    print(f"    ERR {e}", flush=True)
_restore_sp(sp0)

print("\nDone - all phases complete", flush=True)
