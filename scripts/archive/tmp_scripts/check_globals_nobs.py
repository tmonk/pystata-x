import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

base = eng._BASE

# _bist_nobs at 0x823b48, reading from rip + 0x4477f25
# The instruction is at base + 0x823b4c: lea rax, [rip + 0x4477f25]
# rip = base + 0x823b53 (next instruction)
# rax = base + 0x823b53 + 0x4477f25 = base + 0x4CABA78

nobs_global = base + 0x823b53 + 0x4477f25
print(f"nobs global at: 0x{nobs_global:x}")

try:
    nobs_val = ctypes.c_uint32.from_address(nobs_global).value
    print(f"nobs = {nobs_val}")
    
    # Try nearby globals
    print(f"\nNearby values:")
    for offset in range(-0x100, 0x100, 8):
        try:
            val = ctypes.c_uint64.from_address(nobs_global + offset).value
            print(f"  +0x{offset:x}: 0x{val:x}")
        except:
            pass
except Exception as e:
    print(f"Error: {e}")
