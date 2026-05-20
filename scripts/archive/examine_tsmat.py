"""Examine tsmat structure layout for pushint-created tsmats."""
import sys, ctypes, json
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize, call_string
from pystata_x.sfi._core import SFIToolkit
import pystata_x.sfi._engine as eng

initialize()
base = eng._BASE
sp_addr = base + 0x39b7000 + 0x108

SFIToolkit.executeCommand('sysuse auto, clear')

_pushint = eng._pushint_fn
_restore_sp = eng._restore_sp

sp_orig = ctypes.c_uint64.from_address(sp_addr).value

# Push one int and examine the tsmat
_pushint(42)

sp = ctypes.c_uint64.from_address(sp_addr).value
tsmat = ctypes.c_uint64.from_address(sp).value

print(f"SP after pushint(42): {hex(sp)}", flush=True)
print(f"Tsmat at SP[0]: {hex(tsmat)}", flush=True)
print(f"Tsmat hex dump (first 64 bytes):", flush=True)
for i in range(0, 64, 8):
    val = ctypes.c_uint64.from_address(tsmat + i).value
    print(f"  +{hex(i):>4s}: {hex(val)}", flush=True)

# Also check what's at tsmat - 0x94 range  
print(f"\nTsmat -0x94 range (0x50 bytes):", flush=True)
for i in range(-0x94, -0x94 + 0x50, 8):
    try:
        val = ctypes.c_uint64.from_address(tsmat + i).value
        print(f"  {i:+3d}: {hex(val)}", flush=True)
    except:
        print(f"  {i:+3d}: <invalid>", flush=True)

_restore_sp(sp_orig)

# Now push a double and compare
_pushdbl = eng._pushdbl_fn
_pushdbl(3.14)

sp2 = ctypes.c_uint64.from_address(sp_addr).value
tsmat2 = ctypes.c_uint64.from_address(sp2).value
print(f"\n\nSP after pushdbl(3.14): {hex(sp2)}", flush=True)
print(f"Tsmat double hex dump:", flush=True)
for i in range(0, 64, 8):
    val = ctypes.c_uint64.from_address(tsmat2 + i).value
    print(f"  +{hex(i):>4s}: {hex(val)}", flush=True)

_restore_sp(sp_orig)

# Now push a string and compare
_pushstr = eng._pushstr_fn
_pushstr(b'hello')

sp3 = ctypes.c_uint64.from_address(sp_addr).value
tsmat3 = ctypes.c_uint64.from_address(sp3).value
print(f"\n\nSP after pushstr(b'hello'): {hex(sp3)}", flush=True)
print(f"Tsmat string hex dump:", flush=True)
for i in range(0, 64, 8):
    val = ctypes.c_uint64.from_address(tsmat3 + i).value
    print(f"  +{hex(i):>4s}: {hex(val)}", flush=True)

_restore_sp(sp_orig)
print("\nDone", flush=True)
