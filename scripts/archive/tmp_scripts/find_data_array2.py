import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

base = eng._BASE

# The lea rdi, [rip + ...] instruction is in _bist_data at the full impl (+0x48)
# Let's find it by searching the binary
bist_data_fn = base + eng._SYMS['_bist_data'] + 0x48

# Search for 'lea rdi, [rip + ...]' pattern: 48 8d 3d XX XX XX XX
# We know it's around offset 0x5df - 0x4dc = 0x103 from fn start
target_offset = bist_data_fn + 0x103
print(f"Searching at 0x{target_offset:x}")

# Read the lea instruction (7 bytes: 48 8d 3d XX XX XX XX)
code = ctypes.string_at(target_offset, 7)
print(f"Bytes: {code.hex()}")

# Verify it's lea rdi, [rip + ...]
if code[0] == 0x48 and code[1] == 0x8d and code[2] == 0x3d:
    disp = int.from_bytes(code[3:7], 'little', signed=True)
    next_ip = target_offset + 7
    target = next_ip + disp
    print(f"lea rdi, [rip + 0x{disp:x}] -> 0x{target:x}")
    print(f"Offset from base: 0x{target - base:x}")
    
    # Read the data struct at this address
    data_ptr = ctypes.c_uint64.from_address(target).value
    print(f"*(target) = 0x{data_ptr:x}")
    
    # This pointer might be a struct with a data array pointer at offset 0
    if data_ptr > 0x100000:
        array_ptr = ctypes.c_uint64.from_address(data_ptr).value
        print(f"*(*(target)) = array ptr = 0x{array_ptr:x}")
        
        if array_ptr > 0x100000:
            # Read first few values
            for i in range(3):
                val = ctypes.c_double.from_address(array_ptr + i * 8).value
                print(f"  array[{i}] = {val}")
            
            print(f"\nNow check stride patterns...")
            # Try different strides for price (var=1)
            obs = 0
            for stride in [8, 16, 4]:
                val = ctypes.c_double.from_address(array_ptr + obs * stride).value
                print(f"  stride {stride}: array[{obs}*{stride}] = {val}")
            
            # Try row-major: data[obs * nvar + var] * 8
            nvar = 12
            idx = (0 * nvar + 1) * 8  # obs=0, var=1
            val = ctypes.c_double.from_address(array_ptr + idx).value
            print(f"  row-major col-wise: {val}")
            
            # Try column-major: data[var * nobs + obs] * 8
            nobs = 74
            idx2 = (1 * nobs + 0) * 8  # var=1, obs=0
            val2 = ctypes.c_double.from_address(array_ptr + idx2).value
            print(f"  column-major row-wise: {val2}")
            
            # Direct scan for 4099
            for offset in range(0, 10000, 8):
                try:
                    v = ctypes.c_double.from_address(array_ptr + offset).value
                    if abs(v - 4099.0) < 0.1:
                        print(f"  FOUND 4099 at offset {offset} (var={offset//8//74 if offset//8 >=74 else '?'})" )
                        # Check next values
                        for j in range(3):
                            vj = ctypes.c_double.from_address(array_ptr + offset + j*8).value
                            print(f"    [{j}] = {vj}")
                except:
                    break
