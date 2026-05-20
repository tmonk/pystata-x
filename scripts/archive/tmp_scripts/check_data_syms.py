import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng

# Let's check what _bist functions exist and their signatures
print("=== Symbol list ===")
from pystata_x.sfi._engine import _SYMS
# Find data-related symbols
for name in sorted(_SYMS.keys()):
    if 'data' in name.lower() or 'sdata' in name.lower() or 'ndata' in name.lower():
        print(f"  {name}: 0x{_SYMS[name]:x}")
