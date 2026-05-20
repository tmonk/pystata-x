"""Test _bist_matrix* using engine call_ helpers (not raw CFUNCTYPE)."""
import sys
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize, call_int, call_double, call_string, call_void
from pystata_x.sfi._core import SFIToolkit

initialize()

# Fresh state
SFIToolkit.executeCommand('clear all')
SFIToolkit.executeCommand('matrix A = (1,2,3 \\ 4,5,6)')
SFIToolkit.executeCommand('matrix list A')
print("Matrix A created", flush=True)

# Test via engine call_ helpers
print("\n1. call_void('_bist_matrix', b'A'):", flush=True)
try:
    call_void("_bist_matrix", b'A')
    print("   OK - no crash", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

print("\n2. call_string('_bist_matrix_hcat'):", flush=True)
try:
    r = call_string("_bist_matrix_hcat")
    print(f"   {r!r}", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

print("\n3. call_int('_bist_matrixrownumb', b'A'):", flush=True)
try:
    r = call_int("_bist_matrixrownumb", b'A')
    print(f"   {r}", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

print("\n4. call_int('_bist_matrixcolnumb', b'A'):", flush=True)
try:
    r = call_int("_bist_matrixcolnumb", b'A')
    print(f"   {r}", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

print("\n5. call_int('_bist_replacematrix', b'A'):", flush=True)
try:
    r = call_int("_bist_replacematrix", b'A')
    print(f"   {r}", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

print("\n6. call_string('_bist_matrixrowstripe', b'A'):", flush=True)
try:
    r = call_string("_bist_matrixrowstripe", b'A')
    print(f"   {r!r}", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

print("\n7. call_string('_bist_matrixcolstripe', b'A'):", flush=True)
try:
    r = call_string("_bist_matrixcolstripe", b'A')
    print(f"   {r!r}", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

# Now try _bi_st_putmatrixcolstripe via direct call (no engine helper for mixed arg types)
# But first, does _bi_st_putmatrixcolstripe crash with pushstr via engine?
print("\n8. Try _bi_st_putmatrixcolstripe via raw pushstr + CFUNCTYPE:", flush=True)
import ctypes, json
from pystata_x.sfi._engine import _BASE, _restore_sp
manifest = json.load(open('src/pystata_x/sfi/manifest.json'))
sp_addr = _BASE + 0x39b7000 + 0x108

pcs_addr = _BASE + manifest["symbols"]["_bi_st_putmatrixcolstripe"]
fn = ctypes.cast(pcs_addr, ctypes.CFUNCTYPE(None, ctypes.c_int))

pushstr_fn = ctypes.cast(
    _BASE + manifest["symbols"]["_pushstr"],
    ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_int64)
)

sp0 = ctypes.c_uint64.from_address(sp_addr).value
print(f"   SP before: {sp0:#x}", flush=True)

# Let the engine's call_string do the work - use temporary global macro approach
# Actually, let's try calling similar to how _bi_st_strlpart works

# Using call_void which pushes args via _pushint (might not work for _bi_st_*)
# But let's try
print("\n9. call_void('_bi_st_putmatrixcolstripe', b'A', b'x y z'):", flush=True)
try:
    call_void("_bi_st_putmatrixcolstripe", b'A', b'x y z')
    print("   OK", flush=True)
except Exception as e:
    print(f"   ERR: {e}", flush=True)

print("\nDone", flush=True)
