import os, ctypes, sys
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

base = eng._BASE

# RIP-offset calculation for instruction at 0x8264f9:
# lea rax, [rip + 0x47e61a0] (7 bytes: 48 8d 05 a0 61 e6 47)
# rip = address of next instruction = 0x826500
# rax = 0x826500 + 0x47e61a0 = 0x4C866A0
# So the global is at base + 0x4C866A0? No wait...
# Let me just compute: the address is at base + 0x826500 (next insn) + 0x47e61a0

target = base + 0x826500 + 0x47e61a0
print(f"Target global addr: 0x{target:x}")

# Read safely with /proc/self/mem
with open('/proc/self/mem', 'rb') as f:
    f.seek(target)
    data = f.read(8)
    global_val = int.from_bytes(data, 'little')
    print(f"Global value: 0x{global_val:x}")
    
    if global_val > 0x100000 and global_val < 0x800000000000:
        # Read the struct pointer (double dereference)
        f.seek(global_val)
        data2 = f.read(8)
        struct_ptr = int.from_bytes(data2, 'little')
        print(f"Struct ptr (*global): 0x{struct_ptr:x}")
        
        if struct_ptr > 0x100000 and struct_ptr < 0x800000000000:
            # Read fields around the struct
            for off in [-0x20, -0x18, -0x10, -0x8, 0x0]:
                try:
                    pos = struct_ptr + off
                    if pos > 0x100000:
                        f.seek(pos)
                        val = int.from_bytes(f.read(8), 'little')
                        print(f"  struct[0x{off:x}] = 0x{val:x}")
                except:
                    print(f"  struct[0x{off:x}] = <error>")
            
            # Read tsmat at struct[-0x10]
            tsmat_ptr = struct_ptr - 0x10
            f.seek(tsmat_ptr)
            tsmat = int.from_bytes(f.read(8), 'little')
            print(f"\ntsmat_ptr at struct[-0x10]: 0x{tsmat:x}")
            
            if tsmat > 0x100000 and tsmat < 0x800000000000:
                f.seek(tsmat - 0x94)
                pool_tag = int.from_bytes(f.read(4), 'little')
                print(f"Pool tag: 0x{pool_tag:x}")
                
                f.seek(tsmat + 0x34)
                tsmat_34 = int.from_bytes(f.read(2), 'little')
                print(f"tsmat[0x34]: 0x{tsmat_34:x}")
                
                f.seek(tsmat + 0x36)
                tsmat_36 = int.from_bytes(f.read(1), 'little')
                print(f"tsmat[0x36]: 0x{tsmat_36:x}")
                
                f.seek(tsmat)
                dbl = int.from_bytes(f.read(8), 'little')
                import struct as _s
                dbl_val = _s.unpack('<d', dbl.to_bytes(8, 'little'))[0]
                print(f"tsmat[0] double: {dbl_val}")
