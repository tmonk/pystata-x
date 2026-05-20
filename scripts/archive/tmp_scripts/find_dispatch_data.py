import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()

base = eng._BASE

# The dispatch table is referenced from code. Let me find it.
# At _bist_nobs: lea rax, [rip + 0x4477f25] -> base + 0x823b53 + 0x4477f25
# Let's compute: data section contains the dispatch table

# The dispatch table vaddr is in the PIE-relative address space
# Let me look for it in the data section

# First, let me search relative to base for the dispatch table at 0x440aac0
dispatch_vaddr = base + 0x440aac0
print(f"Dispatch table at 0x{dispatch_vaddr:x}")

try:
    # Read some entries
    for i in range(3):
        data = ctypes.string_at(dispatch_vaddr + i * 16, 16)
        func_addr = int.from_bytes(data[0:8], 'little')
        type_info = int.from_bytes(data[8:16], 'little')
        print(f"  dispatch[{i}]: func=0x{func_addr:x} type=0x{type_info:x}")
except:
    print("  Can't read dispatch table")

# Let me also search for functions that call _bist_data
# Looking at the dispatcher code that checks dispatch entries
# The dispatcher at dispatch[...] has:
# - thunk jump (unconditional jmp) or
# - call + _pushstr

# For NUMERIC functions like _bist_data, the dispatch entry points to
# a different kind of thunk

# Let me check what dispatch index maps to _bist_data by finding
# references to _bist_data's address in the dispatch table
bist_data_offset = eng._SYMS['_bist_data']  # 0x826494
target_addr = base + bist_data_offset

# Search for this address in the dispatch table (1686 entries * 16 bytes = 26976 bytes)
for i in range(1686):
    addr = dispatch_vaddr + i * 16
    func_addr = ctypes.c_uint64.from_address(addr).value
    if func_addr == target_addr or func_addr == target_addr + 0x48:
        print(f"Found _bist_data at dispatch[{i}] (func=0x{func_addr:x})")
    elif abs(func_addr - target_addr) <= 0x50:
        print(f"Dispatch[{i}]: func=0x{func_addr:x} (near _bist_data)")
