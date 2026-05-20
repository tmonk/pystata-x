import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()

from capstone import Cs, CS_ARCH_X86, CS_MODE_64

base = eng._BASE
full_impl = base + eng._SYMS['_bist_data'] + 0x44

# Read 400 bytes
code = ctypes.string_at(full_impl, 400)
md = Cs(CS_ARCH_X86, CS_MODE_64)
print("_bist_data full impl (offset +0x44):")
for insn in md.disasm(code, full_impl):
    print(f"  0x{insn.address:x}:\t{insn.mnemonic}\t{insn.op_str}")
