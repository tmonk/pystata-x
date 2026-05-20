import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

from pystata_x.sfi._engine import _push_int, _save_sp

# Push a tsmat and examine it
_push_int(42)
sp = _save_sp()
tsmat = ctypes.c_uint64.from_address(sp).value
print(f"tsmat: 0x{tsmat:x}")

# Dump tsmat fields
for off in range(0, 0x40, 8):
    val = ctypes.c_uint64.from_address(tsmat + off).value
    print(f"  tsmat[0x{off:02x}]: 0x{val:016x} ({val})")

# Key fields:
# [0x00]: double value or GSO pointer
# [0x08]: ?
# [0x10]: ?
# [0x18]: ?
# [0x20]: nrows/ncols
# [0x28]: ?
# [0x30]: size?
# [0x34]: type (u16, but we read at +0x34)
# [0x36]: flags (u8, at +0x36)
# [0x38]: ?
print("\nKey fields:")
print(f"  tsmat[0x34] type: 0x{ctypes.c_uint16.from_address(tsmat + 0x34).value:x}")
print(f"  tsmat[0x36] flags: 0x{ctypes.c_uint8.from_address(tsmat + 0x36).value:x}")
print(f"  tsmat[0x20] dim: {ctypes.c_uint64.from_address(tsmat + 0x20).value}")
print(f"  tsmat[0x00] double: {ctypes.c_double.from_address(tsmat).value}")
print(f"  tsmat[-0x10] self: 0x{ctypes.c_uint64.from_address(tsmat - 0x10).value:x}")
