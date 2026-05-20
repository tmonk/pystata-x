import os, ctypes, struct
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

base = eng._BASE

# Read /proc/self/maps and dump all rw regions > 10MB
# These are candidate locations for the dataset
with open('/proc/self/maps') as f:
    for line in f:
        parts = line.split()
        start, end = [int(x, 16) for x in parts[0].split('-')]
        size = end - start
        if 'rw-p' in parts and size > 10000000:
            print(f"0x{start:x}-0x{end:x} ({size//1024//1024}MB)")

# The dataset is stored as arrays. For 74 obs * 12 vars each 8 bytes = 7104 bytes
# But there could be padding and string arrays
# Let's search for the data in the largest rw region

# Approach: the data pointer might be in a global variable
# Let's look at what the dissasembly of _bist_data's full impl shows
# At instruction 0x7ffffa0524f9: rax = *(SP_ADDR) = tsmat
# Then rbx = rax[-0x10]  (field before tsmat)
# Then checks rbx[-0x94] == 0x2b (pool tag on pool header)
# Then reads rax[0] and processes it

# Let me try to find the data by scanning one large rw region
# The largest rw is probably the Stata heap
# Look for values that make sense as dataset

# Let's check: what if we use _bist_data's internal helper?
# At 0x8264f9 after the pool-check passes, the function branches
# Let me follow the code path that would execute

# Actually let me use Stata's own evaluate function
# We know StataSO_Execute works - can we evaluate expressions?
ret = eng._LIB.StataSO_Execute(b"display price[1]")
print(f"execute return: {ret}")
