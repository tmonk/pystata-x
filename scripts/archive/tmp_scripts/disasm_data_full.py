import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()

base = eng._BASE
# _bist_data is at offset 0x826494, full implementation starts at +0x44
full_impl = base + eng._SYMS['_bist_data'] + 0x44
print(f"Full impl at 0x{full_impl:x}")

from capstone import Cs, CS_ARCH_X86, CS_MODE_64, CS_GRP_CALL, CS_GRP_RET, CS_GRP_JUMP

code = ctypes.string_at(full_impl, 200)
md = Cs(CS_ARCH_X86, CS_MODE_64)
md.detail = True

for insn in md.disasm(code, full_impl):
    groups = [insn.group_name(g) for g in insn.groups]
    print(f"  0x{insn.address:x}:\t{insn.mnemonic}\t{insn.op_str}")
    if 'ret' in insn.mnemonic or 'call' in insn.mnemonic:
        if 'call' in insn.mnemonic and 'rax' not in insn.op_str and 'rdi' not in insn.op_str:
            print(f"    *** CALL at {insn.address:x} -> {insn.op_str}")
