import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

from pystata_x.sfi._engine import _push_int, _save_sp, _get_fn, _pop_and_read_double
from capstone import Cs, CS_ARCH_X86, CS_MODE_64

base = eng._BASE
full_impl = base + eng._SYMS['_bist_data'] + 0x48
print(f"Full impl at 0x{full_impl:x}")

# Verify code
md = Cs(CS_ARCH_X86, CS_MODE_64)
code = ctypes.string_at(full_impl, 8)
for insn in md.disasm(code, full_impl):
    print(f"  0x{insn.address:x}: {insn.mnemonic} {insn.op_str}")

sp_before = _save_sp()
_push_int(0)  # obs=0
_push_int(1)  # varno=1 (price)

sp = _save_sp()
tsmat = ctypes.c_uint64.from_address(sp).value
print(f"\ntsmat: 0x{tsmat:x}")
print(f"pool tag: 0x{ctypes.c_uint32.from_address(tsmat - 0x94).value:x}")
print(f"tsmat[-0x10] before: 0x{ctypes.c_uint64.from_address(tsmat - 0x10).value:x}")

# Patch self-pointer
ctypes.c_uint64.from_address(tsmat - 0x10).value = tsmat
print(f"tsmat[-0x10] after: 0x{ctypes.c_uint64.from_address(tsmat - 0x10).value:x}")

# Call full impl at +0x48
fn = _get_fn(full_impl, None, ctypes.c_int)
try:
    result = fn(2)
    print(f"\nfn(2) returned: {result}")
    val = _pop_and_read_double(sp_before)
    print(f"Value: {val}")
except Exception as e:
    print(f"Exception: {e}")
