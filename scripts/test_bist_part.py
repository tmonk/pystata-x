"""Test _bi_st_strlpart calling convention using manual stack manipulation.

Based on disassembly analysis: _bi_st_strlpart reads 3 args from
internal stack at positions SP[-2], SP[-1], SP[0].
"""
import sys, ctypes, json
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize, call_string, call_void
from pystata_x.sfi._core import SFIToolkit
import pystata_x.sfi._engine as eng

initialize()
base = eng._BASE
sp_addr = base + 0x39b7000 + 0x108
err_addr = base + 0x39b7000 + 0x11c

manifest = json.load(open('src/pystata_x/sfi/manifest.json'))
SFIToolkit.executeCommand('sysuse auto, clear')

_pushint = eng._pushint_fn
_restore_sp = eng._restore_sp

sp_orig = ctypes.c_uint64.from_address(sp_addr).value
orig_err = ctypes.c_int32.from_address(err_addr).value

print(f"=== Pre-call state ===", flush=True)
print(f"  SP: {hex(sp_orig)}", flush=True)
print(f"  err: {orig_err}", flush=True)

# Push 3 int args as observed by disassembly
_pushint(1)
_pushint(2)
_pushint(3)

sp = ctypes.c_uint64.from_address(sp_addr).value
print(f"\n=== After push 1,2,3 ===", flush=True)
print(f"  SP: {hex(sp)} (delta {sp - sp_orig})", flush=True)

for i in range(-3, 3):
    val = ctypes.c_uint64.from_address(sp + i * 8).value
    print(f"  SP[{i:+d}] = {hex(val)}", flush=True)

# Call _bi_st_strlpart with 3 arg count
fn_addr = base + manifest["symbols"]["_bi_st_strlpart"]
fn = ctypes.cast(fn_addr, ctypes.CFUNCTYPE(None, ctypes.c_int))
print(f"\n=== Calling _bi_st_strlpart w0=3 at {hex(fn_addr)} ===", flush=True)

fn(3)  # arg count in w0

err_after = ctypes.c_int32.from_address(err_addr).value
sp_after = ctypes.c_uint64.from_address(sp_addr).value

print(f"  Returned. err: {err_after}  SP: {hex(sp_after)} (delta {sp_after - sp})", flush=True)

if sp_after > sp:
    tsmat = ctypes.c_uint64.from_address(sp_after).value
    if tsmat and tsmat > 0x100000:
        dp = ctypes.c_uint64.from_address(tsmat + 8).value
        print(f"  Result tsmat: {hex(tsmat)} data={hex(dp)}", flush=True)
        if dp:
            print(f"  Result double: {ctypes.c_double.from_address(dp).value}", flush=True)

# Restore and check state
_restore_sp(sp_orig)

print(f"\n=== State check ===", flush=True)
try:
    r = call_string("_bist_sdata", 1, 1)
    print(f"  State OK: {r!r}", flush=True)
except Exception as e:
    print(f"  STATE CORRUPTED: {e}", flush=True)

print("\nDone", flush=True)
