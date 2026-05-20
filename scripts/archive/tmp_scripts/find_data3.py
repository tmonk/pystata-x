import os, ctypes, struct
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

base = eng._BASE
print(f"BASE: 0x{base:x}")

# Known values from auto dataset
price_values = [4099.0, 4749.0, 3799.0, 4816.0, 7827.0, 5788.0, 4453.0, 5189.0, 
                10371.0, 4082.0, 11385.0, 14500.0, 15906.0, 6169.0, 3895.0, 2984.0,
                13290.0, 17950.0, 11995.0, 3988.0, 5798.0, 8129.0, 4376.0, 4697.0,
                11995.0, 4504.0, 5899.0, 5719.0, 9219.0, 6697.0, 7352.0, 9278.0, 
                16795.0, 7483.0, 6484.0, 5079.0, 5705.0, 11995.0, 9735.0, 7293.0, 
                3955.0, 3667.0, 6229.0, 4589.0, 10515.0, 4490.0, 11295.0, 16695.0, 
                5749.0, 9735.0, 4172.0, 6999.0, 11385.0, 9735.0, 8814.0, 4816.0, 
                6342.0, 4195.0, 10997.0, 11385.0, 8278.0, 6229.0, 4499.0, 5731.0, 
                11800.0, 8495.0, 6603.0, 3970.0, 5899.0, 6343.0, 7755.0, 4934.0, 
                5348.0, 11995.0, 12985.0]

# Data tables are usually contiguous arrays of doubles (stride 8)
# with padding between variables
# Try to find price[0]=4099 and price[73]=12985 in the large rw regions

# First, let's do a quick scan in the region near the name table
name_global = base + 0x823d5b + 0x4477ca5
name_base = ctypes.c_uint64.from_address(name_global).value

# Search for 4099.0 in the region around name_base
target = struct.pack('!d', 4099.0)  # network byte order
target_le = struct.pack('<d', 4099.0)  # little endian

# Scan a reasonable region for the first value
for offset in range(0, 0x10000000, 8):
    addr = name_base - 0x8000000 + offset
    if addr < 0x100000:
        continue
    if addr > 0x800000000000:
        break
    try:
        val = struct.unpack('<d', ctypes.string_at(addr, 8))[0]
        if abs(val - 4099.0) < 0.001:
            print(f"FOUND 4099.0 at 0x{addr:x} (name_base{'+' if addr >= name_base else '-'}{abs(addr - name_base):x})")
            # Check if price[73]=12985.0 is at addr + 73*8
            val73 = struct.unpack('<d', ctypes.string_at(addr + 73*8, 8))[0]
            print(f"  +73*8 = {val73}")
            if abs(val73 - 12985.0) < 0.001:
                print(f"  CONFIRMED! Data table at 0x{addr:x}")
                break
    except:
        pass
    if offset % 100000 == 0 and offset > 0:
        pass  # progress indicator
else:
    print("Not found in first scan")
