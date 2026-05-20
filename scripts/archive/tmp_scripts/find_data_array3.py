import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

base = eng._BASE

# The instruction at 0x5df is: lea rdi, [rip + 0x3c6c76a]
# This is inside _bist_data at full impl offset +0x48 + (0x5df - 0x4dc) = +0x48 + 0x103
# Absolute addr = base + _bist_data_offset + 0x48 + 0x103 = base + 0x826494 + 0x14b

target_insn = base + 0x826494 + 0x14b
print(f"lea instruction at: 0x{target_insn:x}")

# Verify it's lea rdi, [rip + ...]
code = ctypes.string_at(target_insn, 7)
print(f"Bytes: {code.hex()}")

if code[0] == 0x48 and code[1] == 0x8d and code[2] == 0x3d:
    disp = int.from_bytes(code[3:7], 'little', signed=True)
    next_ip = target_insn + 7
    target = next_ip + disp
    print(f"lea rdi, [rip + 0x{disp:x}]")
    print(f"rdi = 0x{next_ip:x} + 0x{disp:x} = 0x{target:x}")
    
    # READ THE GLOBAL STRUCT
    # The global at 'target' is the struct itself (not a pointer to struct)
    print(f"\nGlobal struct at 0x{target:x}:")
    
    # Read the data array pointer (offset 0)
    data_array_ptr = ctypes.c_uint64.from_address(target).value
    print(f"  [0x00] data_array ptr: 0x{data_array_ptr:x}")
    
    # Read field at 0x28 (dimension)
    dim = ctypes.c_uint64.from_address(target + 0x28).value  
    print(f"  [0x28] dim: {dim}")
    
    # Read field at 0x20 (nrows or similar)
    rows = ctypes.c_uint64.from_address(target + 0x20).value
    print(f"  [0x20] nrows: {rows}")
    
    # Try reading values from data_array
    if data_array_ptr > 0x100000:
        for i in range(5):
            val = ctypes.c_double.from_address(data_array_ptr + i * 8).value
            print(f"  data[{i}] = {val}")
        
        # Try to find price[0] = 4099
        # Stata stores data as: for each obs [var1, var2, ..., varn], repeated
        # Expected layout: data[obs * nvar * 8 + var * 8]
        # For obs=0, var=1 (price): data[0*12*8 + 1*8] = data[8]
        nvar = 12
        for obs in range(3):
            idx_col = obs * nvar + 1  # price is var index 1 (0-based)
            val_col = ctypes.c_double.from_address(data_array_ptr + idx_col * 8).value
            print(f"  column-major[obs={obs}, var=1] at offset {idx_col*8}: {val_col}")
        
        # Try row-major: data[var * nobs + obs]
        nobs = 74
        for obs in range(3):
            idx_row = 1 * nobs + obs  # price is var 1, row-major
            val_row = ctypes.c_double.from_address(data_array_ptr + idx_row * 8).value
            print(f"  row-major[var=1, obs={obs}] at offset {idx_row*8}: {val_row}")
        
        # Try: data[var][obs] layout (array of pointers)
        # data_array might be an array of pointers, one per var
        for var in range(3):
            var_ptr = ctypes.c_uint64.from_address(data_array_ptr + var * 8).value  
            print(f"  var[{var}] ptr: 0x{var_ptr:x}")
            if var_ptr > 0x100000:
                for obs in range(3):
                    val = ctypes.c_double.from_address(var_ptr + obs * 8).value
                    print(f"    obs[{obs}] = {val}")
