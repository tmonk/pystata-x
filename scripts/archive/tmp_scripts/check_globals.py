import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

base = eng._BASE

# The global pointer used by _bist_data is at rip + 0x47e61a0
# at the instruction: lea rax, [rip + 0x47e61a0]
# The lea is at 0x7ffffa0524f9 = base + 0x8264f9
# So rax = 0x7ffffa0524f9 + 0x47e61a0 + 7? No, lea uses the next instruction address
# rip after lea = 0x7ffffa052500 (instruction is 7 bytes)
# So target = 0x7ffffa052500 + 0x47e61a0 = 0x7ffffa04c866a0

rip_offset = base + 0x826500
global_addr = rip_offset + 0x47e61a0
print(f"Global address: 0x{global_addr:x}")

# Read the global
try:
    global_val = ctypes.c_uint64.from_address(global_addr).value
    print(f"Global value: 0x{global_val:x}")
    
    if global_val and global_val > 0x100000:
        # Dereference to get the data globals struct
        struct_ptr = ctypes.c_uint64.from_address(global_val).value
        print(f"Struct ptr (*global): 0x{struct_ptr:x}")
        
        if struct_ptr and struct_ptr > 0x100000:
            # Read the tsmat pointer from struct at offset -0x10
            tsmat_ptr = ctypes.c_uint64.from_address(struct_ptr - 0x10).value
            print(f"tsmat_ptr from struct[-0x10]: 0x{tsmat_ptr:x}")
            
            if tsmat_ptr and tsmat_ptr > 0x100000:
                # Check pool header
                pool_tag = ctypes.c_uint32.from_address(tsmat_ptr - 0x94).value
                print(f"Pool header tag: 0x{pool_tag:x}")
                
                # Read tsmat fields
                tsmat_34 = ctypes.c_uint16.from_address(tsmat_ptr + 0x34).value
                tsmat_36 = ctypes.c_uint8.from_address(tsmat_ptr + 0x36).value
                print(f"tsmat[0x34]: 0x{tsmat_34:x}")
                print(f"tsmat[0x36]: 0x{tsmat_36:x}")
                
                # Read the double value from tsmat[0]
                dbl_val = ctypes.c_double.from_address(tsmat_ptr).value
                print(f"tsmat[0] double: {dbl_val}")
except Exception as e:
    print(f"Error: {e}")

# Let's also check what the other fields point to
# Print memory around the struct
if global_val and global_val > 0x100000:
    try:
        struct_ptr = ctypes.c_uint64.from_address(global_val).value
        print(f"\nStruct at 0x{struct_ptr:x}:")
        for off in [-0x20, -0x18, -0x10, -0x8, 0x0]:
            val = ctypes.c_uint64.from_address(struct_ptr + off).value
            print(f"  +0x{off:x}: 0x{val:x}")
    except:
        pass
