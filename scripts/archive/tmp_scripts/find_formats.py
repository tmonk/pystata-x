import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

base = eng._BASE
name_global = base + 0x832997 + 0x4469071
name_base = ctypes.c_uint64.from_address(name_global).value
print(f"Name base: 0x{name_base:x}")

# Search for format strings in a reasonable range
target = b"%-18s"
found = []
for offset in range(-0x5000, 0x5000, 1):
    addr = name_base + offset
    if addr < 0x100000:
        continue
    try:
        raw = ctypes.string_at(addr, 6)
        if raw == target:
            # Found a match - check nearby for other formats
            found.append(addr)
            near_formats = []
            for i in range(-8, 8):
                a = addr + i*16  # try stride 16
                if a > 0x100000:
                    r = ctypes.string_at(a, 6)
                    if r[0:1] == b"%":
                        near_formats.append((i, r[:8]))
            if len(near_formats) >= 3:
                print(f"Found at name_base+0x{offset:x}: ")
                for i, fmt in near_formats:
                    print(f"  stride[{i}] = {fmt!r}")
    except:
        pass
    if len(found) > 5:
        break

print(f"\nFound {len(found)} locations")
