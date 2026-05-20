import os, ctypes, struct
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

base = eng._BASE

# Find Stata's data section in /proc/self/maps
with open('/proc/self/maps') as f:
    for line in f:
        if 'libstata-se' in line and 'rw-p' in line:
            parts = line.split()
            start, end = [int(x, 16) for x in parts[0].split('-')]
            offset = int(parts[1], 16)
            print(f"Stata data: 0x{start:x}-0x{end:x} offset=0x{offset:x} {parts[4]}")
            
            # This is the writable data section of libstata-se
            # The globals we need are here

# The data section starts at some offset and has all the global variables
# Let's read the start of the data section to find pointer chains

# Actually, we know where the name table is:
name_global = base + 0x823d5b + 0x4477ca5
name_base = ctypes.c_uint64.from_address(name_global).value
print(f"\nName base: 0x{name_base:x}")
print(f"Name global addr: 0x{name_global:x}")

# Type table
type_global = base + 0x823d5b + 0x4477ca5
# Actually the type global is at a different address, but let me find it
# I found it earlier: type_global = base + 0x823d5b + 0x4477ca5
# Wait, that's the SAME address as name_global!

# Let me check what the actual type table address calculation was
# From the working code in _engine.py:
# type_global_addr = _BASE + 0x823d5b + 0x4477ca5
# But _bist_vartype stores type_base at different offset within the struct

# Let me look at the _bist_vartype implementation to find the type table
# At 0x823d5b: lea rax, [rip + 0x4477ca5]
# rip = 0x7ffff9fd3d62 (next insn)
# rax = 0x7ffff9fd3d62 + 0x4477ca5 = ???

bist_vartype = base + 0x823d5b
insn_addr = base + 0x823d62  # next instruction
type_global_addr = insn_addr + 0x4477ca5
print(f"\nType global at: 0x{type_global_addr:x}")
print(f"type offset in rel terms: 0x{type_global_addr - base:x}")

try:
    type_base = ctypes.c_uint64.from_address(type_global_addr).value
    print(f"Type base: 0x{type_base:x}")
except:
    print("Can't read type global")
