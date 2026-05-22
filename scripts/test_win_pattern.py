"""Find _bist_* functions by pattern matching in PE .text section."""
import ctypes
import struct

dll_path = r'C:\Program Files\StataNow19\se-64.dll'

with open(dll_path, 'rb') as f:
    data = f.read()

# Parse PE to find .text section offset
e_lfanew = struct.unpack('<I', data[0x3c:0x40])[0]
pe = data[e_lfanew:e_lfanew+0x200]

file_header = pe[4:24]
num_sections = struct.unpack('<H', file_header[2:4])[0]
opt_hdr_size = struct.unpack('<H', file_header[16:18])[0]
section_hdr_off = e_lfanew + 24 + opt_hdr_size

text_off = 0
text_size = 0
text_rva = 0
data_rva = 0
data_off = 0
data_size = 0

for i in range(num_sections):
    sh = data[section_hdr_off + i*40 : section_hdr_off + i*40 + 40]
    name = sh[:8].rstrip(b'\x00').decode()
    va = struct.unpack('<I', sh[12:16])[0]
    vs = struct.unpack('<I', sh[8:12])[0]
    rs = struct.unpack('<I', sh[16:20])[0]
    ro = struct.unpack('<I', sh[20:24])[0]
    if name == '.text':
        text_rva = va
        text_off = ro
        text_size = min(vs, rs)
        print(f'.text: RVA={va:#x}, file_off={ro:#x}, size={text_size}')
    elif name == '.data':
        data_rva = va
        data_off = ro
        data_size = min(vs, rs)
        print(f'.data: RVA={va:#x}, file_off={ro:#x}, size={data_size}')

# Read .text section from file
text_bytes = data[text_off:text_off+text_size]
print(f'.text size: {len(text_bytes)}')

# Search for patterns matching _bist_nobs-like functions
# On MSVC x64, a thin wrapper pattern is:
# sub rsp, 28h (48 83 ec 28) or push rbp etc.
# mov eax, <const>  (b8 xx xx xx xx)
# call <offset>     (e8 xx xx xx xx) relative call
# add rsp, 28h (48 83 c4 28)  
# ret (c3)

# Let's search for mov eax, <const> followed by call
# Pattern: b8 xx xx xx xx e8 xx xx xx xx
count = 0
call_targets = {}
print('\nScanning for mov eax, <const>; call <rel32> patterns...')
for i in range(len(text_bytes) - 9):
    if text_bytes[i] == 0xb8:  # mov eax, imm32
        const_val = struct.unpack('<I', text_bytes[i+1:i+5])[0]
        if text_bytes[i+5] == 0xe8:  # call rel32
            rel = struct.unpack('<i', text_bytes[i+6:i+10])[0]
            call_target = text_rva + i + 10 + rel  # RVA of call target
            call_targets[call_target] = call_targets.get(call_target, 0) + 1
            if count < 30:
                print(f'  @RVA={text_rva+i:#010x}: mov eax,{const_val:#x}, call -{rel if rel < 0 else abs(rel)},{rel} -> target={call_target:#010x}')
            count += 1

print(f'\nTotal mov+call patterns: {count}')
print(f'Unique call targets: {len(call_targets)}')

# Show most common call targets (the bytecode interpreter)
print('\nMost common call targets:')
for target, cnt in sorted(call_targets.items(), key=lambda x: -x[1])[:20]:
    print(f'  target={target:#010x}: {cnt} callers')

# Now find _bist_nobs ID
# On Linux, _bist_nobs has dispatch_slot=531 (0x213)
# On Windows, the dispatch IDs might be different
# But we can look for patterns where:
# 1. The function is just a thin wrapper around a call
# 2. The constant matches a range (likely 0-2000)

thin_wrappers = []
for i in range(len(text_bytes) - 9):
    if text_bytes[i] == 0xb8:
        const_val = struct.unpack('<I', text_bytes[i+1:i+5])[0]
        if text_bytes[i+5] == 0xe8:  # call
            rel = struct.unpack('<i', text_bytes[i+6:i+10])[0]
            call_target = text_rva + i + 10 + rel
            # Check for return instruction within 30 bytes
            for j in range(i+10, min(i+40, len(text_bytes))):
                if text_bytes[j] == 0xc3:  # ret
                    thin_wrappers.append((text_rva+i, const_val, call_target, j-i+1))
                    break
                if j > i+20 and text_bytes[j] in (0x48, 0x8b, 0x89):  # suspicious continuation (not ret)
                    # Maybe more complex function
                    break

print(f'\nThin wrappers (mov+call+ret within 30 bytes): {len(thin_wrappers)}')
for rva, const, target, size in thin_wrappers[:30]:
    print(f'  @RVA={rva:#010x}: const={const:#010x}({const}), target={target:#010x}, size={size}b')
