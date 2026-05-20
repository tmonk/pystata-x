import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()

from capstone import Cs, CS_ARCH_X86, CS_MODE_64
base = eng._BASE
md = Cs(CS_ARCH_X86, CS_MODE_64)

# Read more bytes from _bist_data full impl
fn_addr = base + eng._SYMS['_bist_data'] + 0x48
code = ctypes.string_at(fn_addr, 0x180)  # 384 bytes
for insn in md.disasm(code, fn_addr):
    print(f"  0x{insn.address:x}:\t{insn.mnemonic}\t{insn.op_str}")
