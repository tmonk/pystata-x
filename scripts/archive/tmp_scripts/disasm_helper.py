import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()

from capstone import Cs, CS_ARCH_X86, CS_MODE_64
base = eng._BASE

# The call from _bist_data at 0x5e9 calls 0x7ffffa050788
helper_abs = 0x7ffffa050788
print(f"Helper at 0x{helper_abs:x}, offset: 0x{helper_abs - base:x}")

code = ctypes.string_at(helper_abs, 200)
md = Cs(CS_ARCH_X86, CS_MODE_64)
for insn in md.disasm(code, helper_abs):
    print(f"  0x{insn.address:x}:\t{insn.mnemonic}\t{insn.op_str}")
