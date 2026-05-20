import os, ctypes, struct
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

base = eng._BASE

# Get the data section of libstata-se from /proc/self/maps
data_sections = []
with open('/proc/self/maps') as f:
    for line in f:
        if 'libstata-se' in line and 'rw-p' in line:
            parts = line.split()
            start, end = [int(x, 16) for x in parts[0].split('-')]
            offset = int(parts[1], 16)
            data_sections.append((start, end, offset))

print("Stata data sections:")
for start, end, offset in data_sections:
    print(f"  0x{start:x}-0x{end:x} (file offset 0x{offset:x})")

# The name table address is:
name_global = base + 0x823d5b + 0x4477ca5
name_base = ctypes.c_uint64.from_address(name_global).value
print(f"\nName base: 0x{name_base:x}")

# Check if name_base is in any mapped section
for start, end, offset in data_sections:
    if start <= name_base < end:
        print(f"Name base is in data section at 0x{start:x}-0x{end:x}")
        break

# Search nearby for the data pointer
# The data pointer should be stored somewhere near the name table pointer
# Let's look at values around name_global
print(f"\nNear name_global (0x{name_global:x}):")
for off in range(-0x40, 0x40, 8):
    addr = name_global + off
    val = ctypes.c_uint64.from_address(addr).value
    if val > 0x100000:
        # Check if val looks like a data pointer (large allocation)
        print(f"  [{off:+d}]: 0x{val:x}")
