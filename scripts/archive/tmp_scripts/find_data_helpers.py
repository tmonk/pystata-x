import os, ctypes, struct
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

base = eng._BASE

# Search for the dataset data by looking for patterns
# The data array should be at a known offset from a global variable
# Let me check the _bist_data code's called function at 0x788
# At 0x5e9: call 0x7ffffa050788

# But first, let me try reading /proc/self/mem for the data by searching
# in the known Stata heap area

# The Stata heap from /proc/self/maps is in the region starting at 0xba6000
# Let me search for price[0]=4099.0 in this region

with open('/proc/self/maps') as f:
    for line in f:
        parts = line.split()
        if 'libstata-se' in line and 'rw-p' in line:
            start, end = [int(x, 16) for x in parts[0].split('-')]
            print(f"Stata data section: 0x{start:x}-0x{end:x}")

# Let me look at the function that implements data reading
# at 0x7ffffa050788 (which is _bist_data internal helper)
# This should be st_data equivalent

from capstone import Cs, CS_ARCH_X86, CS_MODE_64
helper_addr = base + 0x050788
print(f"\nData helper at 0x{helper_addr:x}")

code = ctypes.string_at(helper_addr, 100)
md = Cs(CS_ARCH_X86, CS_MODE_64)
for insn in md.disasm(code, helper_addr):
    print(f"  0x{insn.address:x}:\t{insn.mnemonic}\t{insn.op_str}")
