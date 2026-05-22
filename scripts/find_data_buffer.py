"""Find and call _bist_data dispatch function on Windows via thunk."""
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
dll.StataSO_Execute(b'sysuse auto, clear')

with open(dll_path, 'rb') as f:
    data = f.read()
e_lfanew = struct.unpack('<I', data[0x3c:0x40])[0]
pe = data[e_lfanew:e_lfanew+0x200]
num_sections = struct.unpack('<H', pe[6:8])[0]
opt_hdr_size = struct.unpack('<H', pe[20:22])[0]
section_hdr_off = e_lfanew + 24 + opt_hdr_size

text_rva = 0
text_offset = 0
text_size = 0
data_rva = 0
for i in range(num_sections):
    sh = data[section_hdr_off + i*40 : section_hdr_off + i*40 + 40]
    name = sh[:8].rstrip(b'\x00').decode('utf-8', errors='replace')
    sva = struct.unpack('<I', sh[12:16])[0]
    sro = struct.unpack('<I', sh[20:24])[0]
    srs = struct.unpack('<I', sh[16:20])[0]
    if name == '.text':
        text_rva, text_offset, text_size = sva, sro, srs
    elif name == '.data':
        data_rva = sva

text_data = data[text_offset:text_offset+text_size]
tdata_len = len(text_data)

# Find main dispatcher (most-called function)
call_counts = {}
for i in range(tdata_len - 9):
    if text_data[i] == 0xb8 and text_data[i+5] == 0xe8:
        rel = struct.unpack('<i', text_data[i+6:i+10])[0]
        target = text_rva + i + 10 + rel
        call_counts[target] = call_counts.get(target, 0) + 1

main_disp = max(call_counts, key=call_counts.get)
print('Main dispatcher RVA:', hex(main_disp))
print('Main dispatcher addr:', hex(handle + main_disp))

# Find callers with known dispatch IDs
simple_callers = []
for i in range(tdata_len - 10):
    if text_data[i] == 0xE8:  # call
        rel = struct.unpack('<i', text_data[i+1:i+5])[0]
        target = text_rva + i + 5 + rel
        if target == main_disp:
            # Look backwards for mov eax, <const>
            for back in range(3, 25):
                j = i - back
                if j < 0: break
                if text_data[j] == 0xB8:  # mov eax, imm32
                    const_val = struct.unpack('<I', text_data[j+1:j+5])[0]
                    if 100 <= const_val <= 1700:
                        simple_callers.append((text_rva + j, const_val))
                    break
                if text_data[j] == 0xC3:  # ret - function boundary
                    break

# Build dispatch map
dispatch_map = sorted(set((c, r) for r, c in simple_callers), key=lambda x: x[0])
print('\nDispatch IDs found:')
for did, rva in dispatch_map[:50]:
    print('  disp=%-4d RVA=%x' % (did, rva))

# Try calling each dispatch that looks like data/nobs/nvar
# Linux dispatch IDs (may differ):
# _bist_nvar=535, _bist_nobs=531, _bist_data=540
# _bist_varname=?, _bist_numscalar=?, _bist_strscalar=?, _bist_macroexpand=?

MEM_COMMIT = 0x1000
PAGE_EXECUTE_READWRITE = 0x40
VirtualAlloc = ctypes.windll.kernel32.VirtualAlloc
VirtualAlloc.restype = ctypes.c_void_p
VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_ulong, ctypes.c_ulong]

# Read nvar for verification
nv_buf = (ctypes.c_int * 1)()
ctypes.memmove(nv_buf, ctypes.c_void_p(handle + data_rva + 0x211644), 4)
actual_nvar = nv_buf[0]
print('\nActual nvar:', actual_nvar)

# Test dispatch function
def call_dispatch(dispatch_id):
    """Call main dispatcher with a specific dispatch ID via shellcode thunk."""
    # Create thunk: mov eax, <dispatch_id>; call main_disp; ret
    thunk_size = 10
    thunk = VirtualAlloc(None, thunk_size, MEM_COMMIT, PAGE_EXECUTE_READWRITE)
    if not thunk:
        return None
    thunk_bytes = (ctypes.c_ubyte * thunk_size)()
    thunk_bytes[0] = 0xB8
    struct.pack_into('<I', thunk_bytes, 1, dispatch_id)
    thunk_bytes[5] = 0xE8
    target_full = handle + main_disp
    rel32 = target_full - (thunk + 10)
    struct.pack_into('<i', thunk_bytes, 6, rel32)
    thunk_bytes[9] = 0xC3
    ctypes.memmove(ctypes.c_void_p(thunk), thunk_bytes, thunk_size)
    func_type = ctypes.CFUNCTYPE(ctypes.c_double)
    callable_func = func_type(thunk)
    try:
        result = callable_func()
        return result
    except:
        return None
    finally:
        ctypes.windll.kernel32.VirtualFree(thunk, 0, 0x8000)

# Test dispatch IDs that look useful
print('\n=== Testing dispatch functions ===')
test_ids = [did for did, _ in dispatch_map[:200]]
for did in test_ids:
    result = call_dispatch(did)
    if result is not None and result != 0:
        print('  dispatch %d: result=%f' % (did, result))

print('\nDone')
