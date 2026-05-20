import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()

base = eng._BASE

# The lea rdi instruction at 0x7ffffa0525df in the previous run
# But base changes due to ASLR. Let me compute correctly.
bist_data = base + eng._SYMS['_bist_data']
lea_insn = bist_data + 0x48 + 0x103  # +0x48 for full impl, +0x103 for lea within it

print(f"bist_data: 0x{bist_data:x}")
print(f"lea insn:  0x{lea_insn:x}")

# Read the instruction and compute target
code = ctypes.string_at(lea_insn, 7)
print(f'Bytes at lea: {code.hex()}')
# The instruction might not be exactly at this offset - let's scan +/- 10 bytes
for delta in range(-20, 20):
    check_addr = lea_insn + delta
    try:
        b = ctypes.string_at(check_addr, 7)
        if b[0] == 0x48 and b[1] == 0x8d and b[2] == 0x3d:
            disp = int.from_bytes(b[3:7], 'little', signed=True)
            next_ip = check_addr + 7
            target = next_ip + disp
            print(f"Found lea at delta={delta}, addr=0x{check_addr:x}, disp=0x{disp:x}, target=0x{target:x}")

# Look at the exact offset that should have the lea
lea_exact = bist_data + 0x48 + 0x103
print(f"\nExpected lea at delta=0, addr=0x{lea_exact:x}")
print(f"Bytes: {ctypes.string_at(lea_exact, 7).hex()}")

# Also try several bytes before
for d in range(-10, 5):
    a = lea_exact + d
    b = ctypes.string_at(a, 4)
    if b[0] == 0x48 and b[1] == 0x8d:
        print(f"  lea-like at delta={d}: {b.hex()}")
    except:
        pass
    
    # Verify the memory is readable
    with open('/proc/self/maps') as f:
        for line in f:
            parts = line.split()
            start, end = [int(x, 16) for x in parts[0].split('-')]
            if start <= target < end:
                print(f"Mapped: 0x{start:x}-0x{end:x} {parts[1]} {parts[2]}")
                
                # Read the struct
                data_ptr = ctypes.c_uint64.from_address(target).value
                print(f"struct[0x00] = 0x{data_ptr:x}")
                
                dim = ctypes.c_uint64.from_address(target + 0x28).value
                print(f"struct[0x28] = 0x{dim:x}")
                
                if data_ptr > 0x100000:
                    val0 = ctypes.c_double.from_address(data_ptr).value
                    print(f"*struct[0x00][0] = {val0}")
                break
