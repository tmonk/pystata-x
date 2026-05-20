import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

base = eng._BASE

# At 0x7ffffa0525df: lea rdi, [rip + 0x3c6c76a]
# This is the instruction at _bist_data+0x48 + (0x5df - 0x4dc) = _bist_data+0x48 + 0x103 = _bist_data+0x14b
# Let me compute: the `lea` is at absolute 0x7ffffa0525df
# rip = 0x7ffffa0525e6 (next insn)
# rdi = 0x7ffffa0525e6 + 0x3c6c76a = 0x7ffff9e8ed50

lea_addr = 0x7ffffa0525e6
rdi_val = lea_addr + 0x3c6c76a
print(f"Global struct addr: 0x{rdi_val:x}")
print(f"Global offset from base: 0x{rdi_val - base:x}")

# Read this global struct
# At 0x788: [rdi + 0x0] = pointer to data array
#           [rdi + 0x28] = dim info
data_ptr_ptr = ctypes.c_uint64.from_address(rdi_val).value
print(f"\nStruct[0x00] (data array ptr): 0x{data_ptr_ptr:x}")

dim = ctypes.c_uint64.from_address(rdi_val + 0x28).value
print(f"Struct[0x28] (dim): {dim}")

# Read some values from the data array
if data_ptr_ptr > 0x100000:
    print(f"\nReading from data array at 0x{data_ptr_ptr:x}:")
    for i in range(5):
        val = ctypes.c_double.from_address(data_ptr_ptr + i * 16).value
        print(f"  [{i}] = {val}")
    
    # Check if this looks like price data
    # Price[0] = 4099 = 0x40A00C0000000000 as double
    # Price values: 4099, 4749, 3799, ...
    price_0 = ctypes.c_double.from_address(data_ptr_ptr).value
    print(f"\nData[0] = {price_0}")
    if abs(price_0 - 4099) < 0.1:
        print("   ^^^^^ This IS the price data!")
    
    # Try indexing with obs*stride
    # Stata stores data as: data = [obs0_var0, obs1_var0, ..., obsN_var0, obs0_var1, ...]
    # or: data = [obs0_var0, obs0_var1, ..., obs0_varN, obs1_var0, ...]
    # Let's check stride 8, stride 16, and stride 12*nvar
    
    for stride in [8, 16, 4, 12, 24]:
        val = ctypes.c_double.from_address(data_ptr_ptr + 1 * stride).value
        if abs(val - 4749) < 0.1:
            print(f"Data[{stride}] = {val}: stride {stride} matches price[1]=4749!")
            
    # Try: Stata uses row-major: data[obs * nvar + var]
    # nvar = 12, so for price (var=1): data[obs*12 + 1]
    nvar = 12
    for obs in range(3):
        idx = obs * 12 + 1
        val = ctypes.c_double.from_address(data_ptr_ptr + idx * 8).value
        print(f"  data[obs={obs}][var=1] (stride 8, idx={idx}) = {val}")
        if obs == 0 and abs(val - 4099) < 0.1:
            print(f"    *** COLUMN MAJOR! data[obs*nvar + var] works")
        if obs == 0 and abs(val - 4749) < 0.1:
            print(f"    *** ROW MAJOR! data[obs + var*nobs] pattern")
    
    # Try row-major: data[var*nobs + obs]
    for obs in range(3):
        idx = obs + 1 * 74  # var=1, nobs=74
        val = ctypes.c_double.from_address(data_ptr_ptr + idx * 8).value
        print(f"  data[var=1][obs={obs}] (stride 8, idx={idx}) = {val}")
