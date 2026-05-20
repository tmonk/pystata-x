import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()

base = eng._BASE
syms = eng._SYMS

# Check key symbols
fn = syms.get('_bist_data')
print(f"_bist_data addr: 0x{fn:x}")
print(f"_bist_data + BASE: 0x{fn + base:x}")

fn2 = syms.get('_bist_sdata')
print(f"_bist_sdata addr: 0x{fn2:x}")
print(f"_bist_sdata + BASE: 0x{fn2 + base:x}")

fn3 = syms.get('_bist_nobs')
print(f"_bist_nobs addr: 0x{fn3:x}")
print(f"_bist_nobs + BASE: 0x{fn3 + base:x}")

# Read the dispatch table entry for _bist_data's index?
# Actually, the dispatch table is at 0x440aac0 (from earlier analysis)
# Let's check a different approach: look at fn as-is

# Is fn a valid address?
try:
    code = ctypes.string_at(fn, 16)
    print(f"_bist_data code: {code.hex()}")
except:
    print("_bist_data address NOT valid (segfault)")
    
try:
    code = ctypes.string_at(eng._BASE + fn, 16)
    print(f"_bist_data + BASE code: {code.hex()}")
except:
    print("_bist_data + BASE NOT valid")
    
# Check if the Stata text section is at 0x1d7000 range
with open('/proc/self/maps') as f:
    for line in f:
        if 'stata' in line and 'r-xp' in line:
            print(f"Text: {line.strip()}")
