"""Find _bist_nobs-like thin wrappers and try calling them."""
import ctypes
import struct

dll_path = r'C:\Program Files\StataNow19\se-64.dll'

# Check exported symbols
dll = ctypes.WinDLL(dll_path)
handle = dll._handle
kernel32 = ctypes.windll.kernel32

for name in [b'_pushdbl', b'_pushint', b'_pushstr', b'_push',
              b'_bist_nobs', b'_bist_nvar', b'_bist_data',
              b'_bist_nobs@8', b'_bist_nvar@8', b'_bist_data@16',
              b'__bist_nobs']:
    try:
        addr = kernel32.GetProcAddress(ctypes.c_void_p(handle), name)
        if addr:
            print(f'EXPORTED: {name.decode()} @ {addr:#x}')
    except:
        pass

print('No _bist_ or _push* exported from se-64.dll')

# Parse PE via file (more reliable than memory)
with open(dll_path, 'rb') as f:
    file_data = f.read()

e_lfanew = struct.unpack('<I', file_data[0x3c:0x40])[0]
pe = file_data[e_lfanew:e_lfanew+0x200]
num_sections = struct.unpack('<H', pe[6:8])[0]
opt_hdr_size = struct.unpack('<H', pe[20:22])[0]
section_hdr_off = e_lfanew + 24 + opt_hdr_size

text_rva = 0
text_off = 0
text_size = 0
for i in range(num_sections):
    sh = file_data[section_hdr_off + i*40 : section_hdr_off + i*40 + 40]
    name = sh[:8].rstrip(b'\x00').decode('utf-8', errors='replace')
    sva = struct.unpack('<I', sh[12:16])[0]
    sro = struct.unpack('<I', sh[20:24])[0]
    srs = struct.unpack('<I', sh[16:20])[0]
    if name == '.text':
        text_rva = sva
        text_off = sro
        text_size = srs
        print(f'.text: RVA={sva:#x}, off={sro:#x}, size={srs}')

text_data = file_data[text_off:text_off+text_size]

# Find main dispatcher (most-called target from mov eax, <const>; call <rel32>)
call_counts = {}
for i in range(len(text_data) - 9):
    if text_data[i] == 0xb8 and text_data[i+5] == 0xe8:
        rel = struct.unpack('<i', text_data[i+6:i+10])[0]
        target = text_rva + i + 10 + rel
        call_counts[target] = call_counts.get(target, 0) + 1

if call_counts:
    sorted_targets = sorted(call_counts.items(), key=lambda x: -x[1])
    main_dispatcher = sorted_targets[0][0]
    print(f'\nMain dispatcher: RVA={main_dispatcher:#010x}, {sorted_targets[0][1]} callers')
    for t, c in sorted_targets[1:5]:
        print(f'  Alt target: RVA={t:#010x}, {c} callers')

    # Find thin wrappers calling main dispatcher
    wrappers = []
    for i in range(len(text_data) - 9):
        if text_data[i] == 0xb8:
            const_val = struct.unpack('<I', text_data[i+1:i+5])[0]
            if text_data[i+5] == 0xe8:
                rel = struct.unpack('<i', text_data[i+6:i+10])[0]
                target = text_rva + i + 10 + rel
                if target == main_dispatcher:
                    for j in range(i+10, min(i+30, len(text_data))):
                        if text_data[j] == 0xc3:
                            rva = text_rva + i
                            size = j - i + 1
                            wrappers.append((rva, const_val, size))
                            break
                        if j > i+15 and text_data[j] in (0x48, 0x8b, 0x89):
                            break

    print(f'\nThin wrappers (calling main dispatcher, ret <=30b): {len(wrappers)}')

    # Show dispatch ID range
    ids = sorted(set(c for _, c, _ in wrappers))
    max_id = max(ids)
    min_id = min(ids)
    print(f'Dispatch ID range: {min_id} to {max_id}')
    print(f'Unique dispatch IDs: {len(ids)}')

    # Show wrappers with IDs in the 500-600 range (known _bist_nobs/nvar range)
    bist_range = [(r, c, s) for r, c, s in wrappers if 200 <= c <= 2000]
    print(f'\nWrappers with dispatch ID 200-2000: {len(bist_range)}')
    for rva, const, size in sorted(bist_range, key=lambda x: x[1])[:30]:
        print(f'  RVA={rva:#010x}: const={const}, size={size}b')

    # Try to find the push functions by pattern matching
    # On x86, pushdbl looks like: sub rsp, 28h; ... inc rsp ptr; mov ...
    # Let's try a different approach: find _matherr or other known functions
    if main_dispatcher:
        # Read the bytecode dispatcher entry to understand calling convention
        print(f'\nMain dispatcher at file offset {text_off + (main_dispatcher - text_rva):#x}')
        # Show first 64 bytes of dispatcher
        disp_off = main_dispatcher - text_rva
        if disp_off < len(text_data):
            print('Disassembling first 64 bytes:')
            disp_bytes = text_data[disp_off:disp_off+64]
            for b in range(0, len(disp_bytes), 16):
                hex_str = ' '.join(f'{disp_bytes[b+bt]:02x}' for bt in range(min(16, len(disp_bytes)-b)))
                print(f'  {hex_str}')

print('\nDone')
