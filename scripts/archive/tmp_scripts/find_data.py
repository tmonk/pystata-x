import os, ctypes, struct
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

base = eng._BASE
print(f"BASE: 0x{base:x}")

# Known values
price_0 = 4099.0
price_73 = 12985.0
target_0 = struct.pack('d', price_0)
target_73 = struct.pack('d', price_73)

# Read /proc/self/maps
with open('/proc/self/maps') as f:
    maps = f.read()

# Find the huge rw region that likely contains the dataset
for line in maps.split('\n'):
    if not line.strip():
        continue
    parts = line.split()
    if 'rw-p' in line:
        start_str, end_str = parts[0].split('-')
        start = int(start_str, 16)
        end = int(end_str, 16)
        size = end - start
        if size > 1000000:
            print(f"Large rw: 0x{start:x}-0x{end:x} ({size//1024//1024}MB)")
