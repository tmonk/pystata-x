import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()

from capstone import Cs, CS_ARCH_X86, CS_MODE_64
base = eng._BASE
md = Cs(CS_ARCH_X86, CS_MODE_64)

# _bist_data at 0x826494
offset = eng._SYMS['_bist_data']

# Disassemble from offset to offset+0x80
code = ctypes.string_at(base + offset, 0x80)
for insn in md.disasm(code, base + offset):
    print(f"  0x{insn.address:x}:\t{insn.mnemonic}\t{insn.op_str}")
