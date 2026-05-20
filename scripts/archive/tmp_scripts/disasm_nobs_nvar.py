import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()

from capstone import Cs, CS_ARCH_X86, CS_MODE_64

base = eng._BASE

# Check _bist_nobs structure - does it also have multiple entries?
nobs_offset = eng._SYMS['_bist_nobs']
print(f"_bist_nobs at offset 0x{nobs_offset:x}")

# Read first 80 bytes
code = ctypes.string_at(base + nobs_offset, 80)
md = Cs(CS_ARCH_X86, CS_MODE_64)
print(f"_bist_nobs ({len(code)} bytes):")
for insn in md.disasm(code, base + nobs_offset):
    print(f"  0x{insn.address:x}:\t{insn.mnemonic}\t{insn.op_str}")

print()

# Check _bist_nvar
nvar_offset = eng._SYMS.get('_bist_nvar', 0)
print(f"_bist_nvar at offset 0x{nvar_offset:x}")
code = ctypes.string_at(base + nvar_offset, 80)
for insn in md.disasm(code, base + nvar_offset):
    print(f"  0x{insn.address:x}:\t{insn.mnemonic}\t{insn.op_str}")
