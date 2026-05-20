import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()

# Use Capstone to disassemble _bist_nobs on x86_64
from capstone import Cs, CS_ARCH_X86, CS_MODE_64

base = eng._BASE
addr = base + eng._SYMS.get('_bist_nobs', 0)
print(f"nobs at 0x{addr:x}")

# Read first 100 bytes
code = ctypes.string_at(addr, 100)
md = Cs(CS_ARCH_X86, CS_MODE_64)
for insn in md.disasm(code, addr):
    print(f"  0x{insn.address:x}:\t{insn.mnemonic}\t{insn.op_str}")
