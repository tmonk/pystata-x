import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

from pystata_x.sfi._engine import _push_int, _save_sp

# Push two args
_push_int(0)
_push_int(1)

sp = _save_sp()
tsmat = ctypes.c_uint64.from_address(sp).value
print(f"tsmat: 0x{tsmat:x}")

# Read fields that _bist_data accesses:
print(f"tsmat[-0x20]: 0x{ctypes.c_uint64.from_address(tsmat - 0x20).value:x}")
print(f"tsmat[-0x18]: 0x{ctypes.c_uint64.from_address(tsmat - 0x18).value:x}")
print(f"tsmat[-0x10]: 0x{ctypes.c_uint64.from_address(tsmat - 0x10).value:x}")
print(f"tsmat[-0x08]: 0x{ctypes.c_uint64.from_address(tsmat - 0x08).value:x}")
print(f"tsmat[0x00]:  0x{ctypes.c_uint64.from_address(tsmat).value:x}")

# Also check what r15 points to (the value at tsmat[-0x20])
r15_val = ctypes.c_uint64.from_address(tsmat - 0x20).value
print(f"\nr15 (tsmat[-0x20]) = 0x{r15_val:x}")
if r15_val > 0x100000:
    try:
        r15_target = ctypes.c_uint64.from_address(r15_val).value
        print(f"  *r15 = 0x{r15_target:x}")
    except:
        print(f"  *r15 = <invalid>")

r13_val = ctypes.c_uint64.from_address(tsmat - 0x18).value
print(f"r13 (tsmat[-0x18]) = 0x{r13_val:x}")

r14_val = ctypes.c_uint64.from_address(tsmat - 0x08).value
print(f"r14 (tsmat[-0x08]) = 0x{r14_val:x}")

# Let's see where the malloc'd tsmat region boundaries are
# Read /proc/self/maps around the tsmat
with open('/proc/self/maps') as f:
    for line in f:
        parts = line.split()
        start, end = [int(x, 16) for x in parts[0].split('-')]
        if start <= tsmat < end:
            print(f"\nMapped region: 0x{start:x}-0x{end:x} {parts[1]} {parts[2]}")
            # Check if the negative offsets are still within the same region
            for off in [-0x94, -0x20, -0x18, -0x10, -0x8]:
                check = tsmat + off
                if not (start <= check < end):
                    print(f"  WARNING: tsmat[{off:x}] = 0x{check:x} is OUTSIDE mapped region!")
            break
