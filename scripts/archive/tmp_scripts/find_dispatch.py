import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()

base = eng._BASE

# _bist_data symbol at offset 0x826494
# This is the rel offset within libstata
# Let's find which dispatch entry points to this function

# The dispatch table is at a known vaddr. Let me find it.
# From earlier analysis: dispatch table at 0x440aac0
# But that's an absolute vaddr before PIE relocation.
# With PIE, it's at base + 0x440aac0 (if it's in .data/.bss)
# or at a fixed offset from the base.

# Actually, the dispatch table address is in a global variable.
# Let me search for it.

# First, let's read all _bist_ symbols and their addresses
bist_syms = {n: a for n, a in eng._SYMS.items() if n.startswith('_bist_')}

# The dispatch table is usually at a fixed address in .data section
# Let me scan memory around the .data section for pointers

print(f"BASE: 0x{base:x}")

# Try the known dispatch table offset
dispatch_table_vaddr = base + 0x440aac0
print(f"Dispatch table at calculated: 0x{dispatch_table_vaddr:x}")

# Read first few entries
try:
    for i in range(5):
        addr = ctypes.c_uint64.from_address(dispatch_table_vaddr + i * 16).value
        typ = ctypes.c_uint64.from_address(dispatch_table_vaddr + i * 16 + 8).value
        print(f"  dispatch[{i}]: func=0x{addr:x} type=0x{typ:x}")
except:
    print("Can't read at 0x{0:x}".format(dispatch_table_vaddr))
