import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()

base = eng._BASE

# The dispatch table is at 0x440aac0 (from earlier analysis)
# Let's check what entry nobs corresponds to
# From the manifest: _bist_nobs should have a dispatch entry

# Let's find the dispatch entry for _bist_nobs
# Actually let's just check the thunk address we already found
# The _bist_nobs function at its absolute address
fn_addr = base + eng._SYMS['_bist_nobs']
print(f"Absolute _bist_nobs: 0x{fn_addr:x}")

# Let's also check what _bist_data looks like
fn2_addr = base + eng._SYMS['_bist_data']
print(f"Absolute _bist_data: 0x{fn2_addr:x}")

# Use Capstone to partially disassemble _bist_data
from capstone import Cs, CS_ARCH_X86, CS_MODE_64

code = ctypes.string_at(fn2_addr, 100)
md = Cs(CS_ARCH_X86, CS_MODE_64)
print("\n_bist_data disassembly:")
for insn in md.disasm(code, fn2_addr):
    print(f"  0x{insn.address:x}:\t{insn.mnemonic}\t{insn.op_str}")
