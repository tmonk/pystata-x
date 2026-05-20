import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

# Test: can we read data values through macros?
from pystata_x.sfi._engine import call_string, _LIB

# Method: use Stata to set a temp scalar, then read the scalar via 
# store_scalar + _bist_scalarval
# But scalar functions are also broken...

# Let's try: use ereturn/post to store values then read through _bist calls
# Or: use Stata's `_st_data` which is the internal C-level function

# Actually, let's try calling the internal bi_st_data function directly
# _bi_st_data at offset 0x1d60d0 from the manifest?
# Wait, that's the macOS manifest. The linux symbols are different.

# Let me search all known symbols for data reader names
for name, addr in sorted(eng._SYMS.items()):
    if 'st_data' in name or 'cell' in name or 'sdata' in name or 'viewobs' in name:
        print(f"  {name}: 0x{addr:x}")

# Also check what bi_ symbols exist
print("\nAll _bi_ symbols:")
for name, addr in sorted(eng._SYMS.items()):
    if name.startswith('_bi_'):
        print(f"  {name}: 0x{addr:x}")
