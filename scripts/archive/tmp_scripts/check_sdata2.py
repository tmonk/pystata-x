import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

base = eng._BASE

# Verify nobs global
nobs_fn = base + eng._SYMS['_bist_nobs']
nobs_global = base + 0x823b53 + 0x4477f25
print(f"nobs global at: 0x{nobs_global:x}")
print(f"nobs = {ctypes.c_uint32.from_address(nobs_global).value}")

# Search for lea rdi in the full impl of _bist_data
bist_data_fn = base + eng._SYMS['_bist_data']
print(f"bist_data at: 0x{bist_data_fn:x}")

# Read 0x200 bytes from bist_data
search_region = ctypes.string_at(bist_data_fn, 0x200)
print(f"\nSearching for lea rdi (48 8d 3d) in +0x00 to +0x200:")
found = 0
for i in range(len(search_region) - 7):
    if search_region[i] == 0x48 and search_region[i+1] == 0x8d and search_region[i+2] == 0x3d:
        addr = bist_data_fn + i
        disp = int.from_bytes(search_region[i+3:i+7], 'little', signed=True)
        struct_addr = addr + 7 + disp
        print(f"\n  Found at +0x{i:x}: lea rdi, [rip + 0x{disp:x}] -> 0x{struct_addr:x}")
        found += 1
        
        try:
            data_ptr = ctypes.c_uint64.from_address(struct_addr).value
            dim = ctypes.c_uint64.from_address(struct_addr + 0x28).value
            print(f"     struct[0x00] = 0x{data_ptr:x}")
            print(f"     struct[0x28] = {dim}")
            
            if data_ptr > 0x100000 and data_ptr < 0x800000000000:
                first_val = ctypes.c_double.from_address(data_ptr).value
                print(f"     *struct[0x00][0] = {first_val}")
        except Exception as e:
            print(f"     Error: {e}")

print(f"\nFound {found} lea rdi instructions")
