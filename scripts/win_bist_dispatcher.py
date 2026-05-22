"""PRAGMATIC APPROACH: Use Stata's internal bytecode dispatcher to call _bist_data.

The main bytecode dispatcher handles ALL _bist_* calls. Find it, create a thunk
that sets up Stata's internal argument stack, then call the dispatcher.
"""
import ctypes
import struct

dll_path = r'C:\Program Files\StataNow19\se-64.dll'
dll = ctypes.WinDLL(dll_path)
handle = dll._handle

dll.StataSO_Main.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
dll.StataSO_Main.restype = ctypes.c_int
dll.StataSO_Main(2, (ctypes.c_char_p * 2)(b'stata', b'-q'))
dll.StataSO_Execute.argtypes = [ctypes.c_char_p]
dll.StataSO_Execute.restype = ctypes.c_int

with open(dll_path, 'rb') as f:
    pe_data = f.read()
e_lfanew = struct.unpack('<I', pe_data[0x3c:0x40])[0]
opt_hdr_size = struct.unpack('<H', pe_data[e_lfanew+20:e_lfanew+22])[0]
sh_off = e_lfanew + 24 + opt_hdr_size
num_sections = struct.unpack('<H', pe_data[e_lfanew+6:e_lfanew+8])[0]

for i in range(num_sections):
    sh = pe_data[sh_off + i*40:sh_off + i*40 + 40]
    name = sh[:8].rstrip(b'\x00').decode('utf-8', errors='replace')
    if name == '.text':
        text_rva = struct.unpack('<I', sh[12:16])[0]
        text_offset = struct.unpack('<I', sh[20:24])[0]
        text_size = struct.unpack('<I', sh[16:20])[0]
    elif name == '.data':
        data_rva = struct.unpack('<I', sh[12:16])[0]
        data_vsize = struct.unpack('<I', sh[8:12])[0]
        data_rawsize = struct.unpack('<I', sh[16:20])[0]

text_data = pe_data[text_offset:text_offset+text_size]
data_ptr = handle + data_rva

# Load auto
dll.StataSO_Execute(b'sysuse auto, clear')

# Find main dispatcher
call_counts = {}
for i in range(len(text_data) - 9):
    if text_data[i] == 0xB8 and text_data[i+5] == 0xE8:
        rel = struct.unpack('<i', text_data[i+6:i+10])[0]
        target = text_rva + i + 10 + rel
        call_counts[target] = call_counts.get(target, 0) + 1

main_disp = max(call_counts, key=call_counts.get)
print('Main dispatcher RVA:', hex(main_disp))
print('Main dispatcher addr:', hex(handle + main_disp))

# Find the Stata expression stack pointer (SP) location
# In x86_64, the dispatcher reads arguments from a stack in memory
# SP is a global variable. We can find it by looking at dispatcher code.
# Read some dispatcher code to find SP references
disp_off = main_disp - text_rva
disp_bytes = text_data[disp_off:disp_off+300]
print('\nDispatcher code (first 100 bytes):')
for k in range(0, min(100, len(disp_bytes)), 8):
    chunk = disp_bytes[k:k+8]
    hex_str = ' '.join('%02x' % b for b in chunk)
    print('  %+04x: %s' % (k, hex_str))

# Look for LEA instructions that reference globals (RIP-relative)
# Pattern: 48 8d 0d XX XX XX XX  (lea rcx, [rip+offset])
# Pattern: 48 8d 15 XX XX XX XX  (lea rdx, [rip+offset])
# Pattern: 48 8d 05 XX XX XX XX  (lea rax, [rip+offset])
print('\nLooking for RIP-relative LEA references to globals in dispatcher...')
for i in range(len(disp_bytes) - 7):
    if disp_bytes[i] == 0x48 and disp_bytes[i+1] == 0x8d and disp_bytes[i+2] in (0x05, 0x0d, 0x15, 0x1d, 0x25, 0x2d, 0x35, 0x3d):
        modrm = disp_bytes[i+2]
        rel32 = struct.unpack('<i', disp_bytes[i+3:i+7])[0]
        target = main_disp + (disp_off - main_disp) + i + 7 + rel32  # Actually: text_rva + (text_offset disp in file)...
        # Correct calculation: the lea instruction is at main_disp + i offset in the virtual address space
        # The RIP at the time of the instruction is main_disp + i + 7
        # The target is RIP + rel32
        rip = main_disp + i + 7
        target = rip + rel32
        # r/m field
        rm = modrm & 7
        reg = (modrm >> 3) & 7
        reg_names = ['rax', 'rcx', 'rdx', 'rbx', 'rsp', 'rbp', 'rsi', 'rdi']
        print('  %+04x: lea %s, [rip+%+d] -> RVA %x' % (i, reg_names[reg], rel32, target))

# Also find call_double's entry: it's a function that pushes args and calls dispatcher
# On ELF, call_double is at _BASE + 0x1E0CEB0 on Linux
# It reads from SP (stack pointer) and stores results on stack

print('\nDone')
