"""Crack _bi_st_putmatrixcolstripe and _bi_st_putmatrixrowstripe.

These set the column/row names of a Stata matrix.
Expected: pushstr(matrix_name), pushstr(names_string), w0=2
"""
import sys, ctypes, json, struct
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize, _BASE, _restore_sp
from pystata_x.sfi._core import SFIToolkit, Matrix

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

SFIToolkit.executeCommand('clear all')
SFIToolkit.executeCommand('matrix A = (1,2,3 \\ 4,5,6)')

print("=== Matrix A created ===", flush=True)
print(f"Names: {Matrix.getNames()}", flush=True)
print(f"getRowNames: {Matrix.getRowNames('A')}", flush=True)
print(f"getColNames: {Matrix.getColNames('A')}", flush=True)
print(f"getRowCount: {Matrix.getRowCount('A')}", flush=True)  
print(f"getColCount: {Matrix.getColCount('A')}", flush=True)

# Test _bi_st_putmatrixcolstripe
# Address from manifest
pcs_addr = _BASE + manifest["symbols"].get("_bi_st_putmatrixcolstripe", 0)
print(f"\n_bi_st_putmatrixcolstripe at {hex(pcs_addr) if pcs_addr else 'NOT FOUND'}", flush=True)

if pcs_addr:
    fn = ctypes.cast(pcs_addr, ctypes.CFUNCTYPE(None, ctypes.c_int))
    
    # Try 1: pushstr name, pushstr names, w0=2
    print("\n=== Try 1: pushstr name, pushstr colnames, w0=2 ===", flush=True)
    sp_base = ctypes.c_uint64.from_address(sp_addr).value
    pushstr(b'A')
    pushstr(b'x y z')
    fn(2)
    sp = ctypes.c_uint64.from_address(sp_addr).value
    print(f"  SP: {sp_base:#x} -> {sp:#x}", flush=True)
    _restore_sp(sp_base)
    
    # Check if names changed
    print(f"  getColNames after: {Matrix.getColNames('A')}", flush=True)
    
    # Try 2: pushstr name, pushint, pushstr names, w0=3 (maybe needs col count?)
    print("\n=== Try 2: pushstr name, pushint, pushstr colnames, w0=3 ===", flush=True)
    sp_base = ctypes.c_uint64.from_address(sp_addr).value
    pushstr(b'A')
    pushint(3)
    pushstr(b'x y z')
    fn(3)
    _restore_sp(sp_base)
    print(f"  getColNames after: {Matrix.getColNames('A')}", flush=True)

    # Try 3: pushstr name, pushstr names (different format - space separated)
    print("\n=== Try 3: pushstr names first, pushstr name, w0=2 ===", flush=True)
    sp_base = ctypes.c_uint64.from_address(sp_addr).value
    pushstr(b'x y z')
    pushstr(b'A')
    fn(2)
    _restore_sp(sp_base)
    print(f"  getColNames after: {Matrix.getColNames('A')}", flush=True)

    # Try 4: pushstr(name) + pushstr(names) where func reads SP[-1], SP[0]
    print("\n=== Try 4: pushstr names (SP[0]), pushstr name (SP[-1]) ===", flush=True)
    sp_base = ctypes.c_uint64.from_address(sp_addr).value
    # Push in reverse: name first (will be SP[-1]), names second (will be SP[0])
    pushstr(b'A')  # SP[-1]
    pushstr(b'x y z')  # SP[0]
    fn(2)
    _restore_sp(sp_base)
    print(f"  getColNames after: {Matrix.getColNames('A')}", flush=True)

# Also test _bi_st_putmatrixrowstripe
prs_addr = _BASE + manifest["symbols"].get("_bi_st_putmatrixrowstripe", 0)
print(f"\n_bi_st_putmatrixrowstripe at {hex(prs_addr) if prs_addr else 'NOT FOUND'}", flush=True)

if prs_addr:
    fn = ctypes.cast(prs_addr, ctypes.CFUNCTYPE(None, ctypes.c_int))
    
    print("\n=== Try: pushstr name, pushstr rownames, w0=2 ===", flush=True)
    sp_base = ctypes.c_uint64.from_address(sp_addr).value
    pushstr(b'A')
    pushstr(b'r1 r2')
    fn(2)
    _restore_sp(sp_base)
    print(f"  getRowNames after: {Matrix.getRowNames('A')}", flush=True)

print("\nDone", flush=True)
