import os, ctypes, struct as _s
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

base = eng._BASE

# Global = base + 0x826500 + 0x47e61a0
global_addr = base + 0x826500 + 0x47e61a0
print(f"Global addr: 0x{global_addr:x}")

# Read the global value using from_address
global_val = ctypes.c_uint64.from_address(global_addr).value
print(f"Global value (pointer to struct): 0x{global_val:x}")

if global_val > 0x100000:
    # Read fields at negative offsets
    # The struct 'base' is at global_val, with fields at:
    # [x-0x20], [x-0x18], [x-0x10], [x-0x8], [x]
    struct_base = global_val
    print(f"\nStruct at 0x{struct_base:x}:")
    
    for off_str, name in [("-0x20", "field0"), ("-0x18", "field1"),
                           ("-0x10", "tsmat_ptr"), ("-0x8", "field3"),
                           ("0x0", "sp_ptr")]:
        off = int(off_str, 16)
        try:
            val = ctypes.c_uint64.from_address(struct_base + off).value
            print(f"  [0x{off_str}]: 0x{val:x} ({name})")
        except:
            print(f"  [0x{off_str}]: <SEGFAULT>")
    
    # Read the tsmat at struct[-0x10]
    tsmat_ptr = ctypes.c_uint64.from_address(struct_base - 0x10).value
    if tsmat_ptr > 0x100000 and tsmat_ptr < 0x800000000000:
        print(f"\ntsmat at 0x{tsmat_ptr:x}:")
        try:
            pool_tag = ctypes.c_uint32.from_address(tsmat_ptr - 0x94).value
            print(f"  pool tag: 0x{pool_tag:x}")
            
            tsmat_34 = ctypes.c_uint16.from_address(tsmat_ptr + 0x34).value
            print(f"  [0x34]: 0x{tsmat_34:x}")
            
            tsmat_36 = ctypes.c_uint8.from_address(tsmat_ptr + 0x36).value
            print(f"  [0x36]: 0x{tsmat_36:x}")
            
            dbl_val = ctypes.c_double.from_address(tsmat_ptr).value
            print(f"  [0]: double = {dbl_val}")
        except Exception as e:
            print(f"  error reading tsmat: {e}")
