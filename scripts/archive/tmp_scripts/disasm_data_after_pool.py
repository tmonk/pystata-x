import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()

from capstone import Cs, CS_ARCH_X86, CS_MODE_64
base = eng._BASE
md = Cs(CS_ARCH_X86, CS_MODE_64)

# Disassemble from 0x5a4 onwards (the je 0x5da target)
fn_addr = base + eng._SYMS['_bist_data'] + 0x48
# 0x5a2 -> 0x5da is at fn_addr + (0x5da - 0x48) = fn_addr + 0x592
code = ctypes.string_at(fn_addr + 0x592, 0x80)  # from 0x592
for insn in md.disasm(code, fn_addr + 0x592):
    print(f"  0x{insn.address:x}:\t{insn.mnemonic}\t{insn.op_str}")
