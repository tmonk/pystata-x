import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

base = eng._BASE

# From _bist_varformat at 0x8322ad:
# lea rax, [rip + 0x3e2adb3] at 0x8322a6 -> target at 0x8322ad + 0x3e2adb3
format_display_global = base + 0x8322ad + 0x3e2adb3
fmt_display = ctypes.c_uint64.from_address(format_display_global).value
print(f"Format display global: 0x{format_display_global:x}")
print(f"Format display value: 0x{fmt_display:x}")

# From _bist_varformat at 0x832260:
# lea rax, [rip + 0x44658ee] at 0x83226b -> target = 0x83226b + 0x44658ee + 7?
# Actually: 0x832260: lea rax, [rip + 0x44658ee]
# rip = 0x832267 (next instruction)
# target = 0x832267 + 0x44658ee
default_fmt_global = base + 0x832267 + 0x44658ee
default_fmt = ctypes.c_uint64.from_address(default_fmt_global).value
print(f"Default format global: 0x{default_fmt_global:x}")
print(f"Default format: 0x{default_fmt:x}")
if default_fmt:
    raw = ctypes.string_at(default_fmt, 10)
    print(f"  content: {raw!r}")

# From _bist_varlabel which also uses similar format:
# At 0x832997: the name table access we already use works

# Let me try a different approach: search for format GSO pointers
# in a small region near the type table with stride 32 or similar
type_global = base + 0x823d5b + 0x4477ca5
type_base = ctypes.c_uint64.from_address(type_global).value
print(f"\nType base: 0x{type_base:x}")

# Search for format string pointers near type_base
# Format strings are GSO with length prefix, so look for 4-byte length + '%'
import struct
for stride in [16, 24, 32, 48, 64, 128, 256]:
    for start in range(0, 0x2000, 8):
        addr = type_base - start
        try:
            p = ctypes.c_uint64.from_address(addr).value
            if p and p > 0x1000000 and p < 0x800000000000:
                raw = ctypes.string_at(p, 4)
                if raw[0:1] == b"%":
                    # Found a format string pointer
                    print(f"Format GSO ptr at type_base-0x{start:x}: *0x{addr:x} -> 0x{p:x} -> {raw!r}")
                    if start > 0:
                        break
        except:
            pass
