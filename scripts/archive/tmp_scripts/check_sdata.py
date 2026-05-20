import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

from capstone import Cs, CS_ARCH_X86, CS_MODE_64
base = eng._BASE
md = Cs(CS_ARCH_X86, CS_MODE_64)

# Verify nobs global
nobs_fn = base + eng._SYMS['_bist_nobs']
nobs_global = base + 0x823b53 + 0x4477f25
print(f"nobs global at: 0x{nobs_global:x}")
print(f"nobs = {ctypes.c_uint32.from_address(nobs_global).value}")

# Find the data struct global for _bist_data
bist_data_fn = base + eng._SYMS['_bist_data']
full_impl = bist_data_fn + 0x48

# The lea rdi instruction is in the helper call at +0x10e
# Let's search for 48 8d 3d (lea rdi, [rip + ...])
search_start = full_impl + 0x100

print(f"\nSearching for lea rdi in _bist_data full impl at +0x{full_impl - bist_data_fn:x}")
for delta in range(0, 0x200):
    addr = search_start + delta
    b = ctypes.string_at(addr, 7)
    if b[0] == 0x48 and b[1] == 0x8d and b[2] == 0x3d:
        disp = int.from_bytes(b[3:7], 'little', signed=True)
        struct_addr = addr + 7 + disp
        print(f"  Found at +0x{addr - bist_data_fn:x}: lea rdi, [rip + 0x{disp:x}]")
        print(f"  -> struct addr = 0x{struct_addr:x}")
        
        # Try to read the struct
        try:
            data_ptr = ctypes.c_uint64.from_address(struct_addr).value
            dim = ctypes.c_uint64.from_address(struct_addr + 0x28).value
            print(f"     struct[0x00] = 0x{data_ptr:x}")
            print(f"     struct[0x28] = {dim}")
            
            if data_ptr > 0x100000 and data_ptr < 0x800000000000:
                first_val = ctypes.c_double.from_address(data_ptr).value
                print(f"     *struct[0x00][0] = {first_val}")
                
                # Check if this is the price array
                for stride in [8, 16, 12*8]:
                    val = ctypes.c_double.from_address(data_ptr + stride).value
                    print(f"     data[{stride}] = {val}")
        except Exception as e:
            print(f"     Error: {e}")
