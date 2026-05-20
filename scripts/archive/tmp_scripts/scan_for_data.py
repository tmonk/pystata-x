import os, ctypes, struct
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

base = eng._BASE

# Search for price[0]=4099 in the largest rw region
# The largest rw region from earlier: 0x7ffff45fa000-0x7ffff8980000 (67MB)
# Another: 0xefffff8000-0xf00004d3a000 (77MB) - but might be related to capstone

# Let's search in the 67MB region near the name table
# Or better: search in the nobs_global area +/- some range

nobs_global = base + 0x823b53 + 0x4477f25
print(f"nobs_global: 0x{nobs_global:x}")

# Search for 4099.0 (price[0]) as double
target = struct.pack('<d', 4099.0)

# Try reading /proc/self/mem with seek
found = []
with open('/proc/self/mem', 'rb') as f:
    # Search a reasonable range
    for start_offset in range(-0x2000000, 0x2000000, 0x100000):
        try:
            addr = nobs_global + start_offset
            f.seek(addr)
            chunk = f.read(0x100000)
            idx = chunk.find(target)
            if idx >= 0:
                found_addr = addr + idx
                print(f"Found 4099.0 at 0x{found_addr:x}")
                # Check if it's in a structured array
                f.seek(found_addr + 73*8)
                next_val = struct.unpack('<d', f.read(8))[0]
                print(f"  +73*8 (price[73]): {next_val}")
                if abs(next_val - 12985.0) < 0.1:
                    print(f"  CONFIRMED! Data table at 0x{found_addr:x}")
                    break
        except:
            pass
