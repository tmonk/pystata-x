"""Test _bi_st_* functions from C shared library (eliminating ctypes FFI variable).

The C library test_bi_st_harness.dylib uses the exact same push+stack
mechanism but from C code, proving whether the calling convention
works correctly.
"""
import sys, ctypes, json
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize, call_string
from pystata_x.sfi._core import SFIToolkit
import pystata_x.sfi._engine as eng

initialize()
base = eng._BASE
sp_addr = base + 0x39b7000 + 0x108
err_addr = base + 0x39b7000 + 0x11c
manifest = json.load(open('src/pystata_x/sfi/manifest.json'))

SFIToolkit.executeCommand('sysuse auto, clear')
SFIToolkit.executeCommand('gen strL s = "hello world" if _n == 1')

# Load the C shared library
lib = ctypes.CDLL('./scripts/test_bi_st_harness.dylib')

# Set up function signatures
lib.call_bist_strlpart.restype = ctypes.c_int64
lib.call_bist_strlpart.argtypes = [
    ctypes.c_void_p,  # fn_addr
    ctypes.c_void_p,  # pushint_addr
    ctypes.c_void_p,  # pushstr_addr
    ctypes.c_void_p,  # sp_ptr
    ctypes.c_void_p,  # err_ptr
    ctypes.c_char_p,  # str_arg
    ctypes.c_size_t,  # str_len
    ctypes.c_int,     # int_arg2
    ctypes.c_int,     # int_arg3
]

lib.probe_function.restype = ctypes.c_int
lib.probe_function.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_int,
]

lib.call_bist_with_ints.restype = ctypes.c_int64
lib.call_bist_with_ints.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_int64),
]

lib.print_findings.restype = None
lib.print_findings.argtypes = []

# Get function addresses
fn_strlpart = ctypes.c_void_p(base + manifest["symbols"]["_bi_st_strlpart"])
fn_unab = ctypes.c_void_p(base + manifest["symbols"]["_bi_st_unab"])
fn_addalias = ctypes.c_void_p(base + manifest["symbols"]["_bi_st_addalias"])
pushint_addr = ctypes.c_void_p(base + manifest["symbols"]["_pushint"])
pushstr_addr = ctypes.c_void_p(base + manifest["symbols"]["_pushstr"])
sp_ptr = ctypes.c_void_p(sp_addr)
err_ptr = ctypes.c_void_p(err_addr)

print("=== Testing _bi_st_strlpart from C ===", flush=True)
for name, obs, part in [("s", 1, 0), ("s", 1, 1), ("s", 1, 2), ("make", 1, 0)]:
    err = lib.call_bist_strlpart(
        fn_strlpart, pushint_addr, pushstr_addr,
        sp_ptr, err_ptr,
        name.encode(), len(name), obs, part
    )
    sp_val = ctypes.c_uint64.from_address(sp_addr).value
    state_ok = False
    try:
        r = call_string("_bist_sdata", 1, 1)
        state_ok = (r is not None)
    except:
        pass
    print(f"  strlpart({name}, {obs}, {part}): err={err} state={'OK' if state_ok else 'CORRUPT'}", flush=True)
    if not state_ok:
        break

# Re-init for more tests
SFIToolkit.executeCommand('sysuse auto, clear')
SFIToolkit.executeCommand('gen strL s = "hello world" if _n == 1')

print("\n=== Testing _bi_st_unab from C ===", flush=True)

# Test with string arg (via probe)
result = lib.probe_function(fn_unab, pushint_addr, pushstr_addr, sp_ptr, err_ptr, 0x10)
print(f"  probe with string: result_mask={result:#x}", flush=True)

# Test with 2 ints
result = lib.probe_function(fn_unab, pushint_addr, pushstr_addr, sp_ptr, err_ptr, 0x04)
print(f"  probe with 2 ints: result_mask={result:#x}", flush=True)

# Try calling unab with explicit string arg
err = lib.call_bist_with_ints(
    fn_unab, pushint_addr, sp_ptr, err_ptr, 1,
    (ctypes.c_int64 * 1)(1)
)
print(f"  call_bist_with_ints(unab, 1): err={err}", flush=True)

print("\n=== Testing _bi_st_addalias from C ===", flush=True)
SFIToolkit.executeCommand('sysuse auto, clear')
result = lib.call_bist_with_ints(
    fn_addalias, pushint_addr, sp_ptr, err_ptr, 1,
    (ctypes.c_int64 * 1)(0)
)
print(f"  call_bist_with_ints(addalias, 0): err={result}", flush=True)
state_ok = False
try:
    r = call_string("_bist_sdata", 1, 1)
    state_ok = (r == "AMC Concord")
except:
    pass
print(f"  state={'OK' if state_ok else 'CORRUPT'}", flush=True)

print("\n=== C Library Findings ===", flush=True)
lib.print_findings()

print("\nDone!", flush=True)
