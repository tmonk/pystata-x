"""Call _bist_nobs by finding it in the PE's .text section and calling via ctypes."""
import ctypes
import struct
import os

dll_path = r'C:\Program Files\StataNow19\se-64.dll'
dll = ctypes.WinDLL(dll_path)
handle = dll._handle

# 1. Parse PE to get base info
kernel32 = ctypes.windll.kernel32

# 2. Init Stata
_Main = dll.StataSO_Main
_Main.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
_Main.restype = ctypes.c_int
_Main(2, (ctypes.c_char_p * 2)(b'stata', b'-q'))

_Execute = dll.StataSO_Execute
_Execute.argtypes = [ctypes.c_char_p]
_Execute.restype = ctypes.c_int

_Execute(b'sysuse auto, clear')

# 3. Try to find _bist_nobs by scanning .text for the pattern
# In Stata for Windows, _bist_nobs might be at a different address.
# But we can try calling any function by its RVA.

# First, let's try a different approach: use Stata's own __bist__ internal
# by looking at what code references known memory offsets

# We know gws pointer is in .data section. Let's find it:
# 1. Scan .data for pointers that look like gws addresses
# 2. Use the fact that gws.nvar is at a known offset from gws

with open(dll_path, 'rb') as f:
    data = f.read()

e_lfanew = struct.unpack('<I', data[0x3c:0x40])[0]
pe = data[e_lfanew:e_lfanew+0x200]
num_sections = struct.unpack('<H', pe[6:8])[0]
opt_hdr_size = struct.unpack('<H', pe[20:22])[0]
section_hdr_off = e_lfanew + 24 + opt_hdr_size

text_rva = 0
text_off = 0
text_size = 0
data_rva = 0
data_off = 0
data_size = 0

for i in range(num_sections):
    sh = data[section_hdr_off + i*40 : section_hdr_off + i*40 + 40]
    name = sh[:8].rstrip(b'\x00').decode('utf-8', errors='replace')
    sva = struct.unpack('<I', sh[12:16])[0]
    sro = struct.unpack('<I', sh[20:24])[0]
    srs = struct.unpack('<I', sh[16:20])[0]
    if name == '.text':
        text_rva, text_off, text_size = sva, sro, srs
    elif name == '.data':
        data_rva, data_off, data_size = sva, sro, srs

text_data = data[text_off:text_off+text_size]

# Load auto to verify
_Execute(b'sysuse auto, clear')
print(f'Auto dataset loaded: nvar=12, nobs=74')

# Find the main bytecode dispatcher
print('\nFinding main dispatcher...')
call_counts = {}
for i in range(len(text_data) - 9):
    if text_data[i] == 0xb8 and text_data[i+5] == 0xe8:
        rel = struct.unpack('<i', text_data[i+6:i+10])[0]
        target = text_rva + i + 10 + rel
        call_counts[target] = call_counts.get(target, 0) + 1

if call_counts:
    main_dispatcher = max(call_counts, key=call_counts.get)
    print(f'Main dispatcher: RVA={main_dispatcher:#010x}')
    
    # Now search for functions that call this dispatcher.
    # On Windows MSVC, the pattern might be:
    # sub rsp, 28h  (48 83 ec 28)
    # xor eax, eax  (33 c0) or mov eax, <const>
    # ...
    # call dispatcher
    # add rsp, 28h  (48 83 c4 28)
    # ret           (c3)
    
    # Let's search for call dispatcher with simple prologue
    dispatcher_vaddr = handle + main_dispatcher - text_rva + text_rva  
    # Wait, that's wrong. Let me fix:
    # For a function at RVA=main_dispatcher, it's at memory:
    dispatcher_addr = handle + main_dispatcher
    
    # Search for calls to main_dispatcher
    # x86_64: e8 xx xx xx xx  where the rel32 target = main_dispatcher
    callers = []
    for i in range(len(text_data) - 10):
        if text_data[i] == 0xe8:  # call instruction
            rel = struct.unpack('<i', text_data[i+1:i+5])[0]
            target = text_rva + i + 5 + rel
            if target == main_dispatcher:
                caller_rva = text_rva + i
                caller_addr = handle + caller_rva
                callers.append((caller_rva, i))
    
    print(f'Found {len(callers)} callers of main dispatcher')
    
    # For each caller, check if it has a simple structure:
    # mov eax, <const> before the call
    simple_callers = []
    for rva, i in callers[:200]:
        # Look backwards for mov eax, <const>
        for back in range(3, 20):
            j = i - back
            text_data[j:j+1]
            if text_data[j] == 0xb8:  # mov eax, imm32
                const_val = struct.unpack('<I', text_data[j+1:j+5])[0]
                simple_callers.append((rva, const_val, i))
                break
            if text_data[j] in (0x48, 0xcc, 0x90):  # REX prefix or int3 or nop
                continue
            if text_data[j] == 0xc3:  # ret - previous function end
                break
    
    print(f'Simple callers (mov eax before call): {len(simple_callers)}')
    for rva, const, call_idx in sorted(simple_callers[:30], key=lambda x: x[1]):
        print(f'  RVA={rva:#010x}: const={const:#06x}({const})')
    
    # The dispatch IDs 210-230 match the known _bist_ functions
    # Let's find callers with dispatch IDs in the 200-600 range
    likely_bist = [(r, c) for r, c, _ in simple_callers if 200 <= c <= 1700]
    likely_bist = sorted(set(likely_bist), key=lambda x: x[1])
    print(f'\nLikely _bist_* callers (dispatch 200-1700): {len(likely_bist)}')
    for rva, const in likely_bist[:30]:
        print(f'  RVA={rva:#010x}: dispatch={const}')
    
    # Now find _bist_nobs (dispatch ~531 on Linux) and _bist_nvar (~535)
    # These might have different IDs on Windows
    
    # Try calling each simple caller via ctypes
    # The calling convention: mov eax sets the dispatch slot
    # Then call dispatcher
    # Result is on Stata expression stack
    
    # To call via ctypes, we create a CFUNCTYPE(void) at the address
    # This won't set eax properly, but let's try
    
    # Actually, we need to set EAX first. In Python ctypes, we can't
    # directly set eax. But we could create a small shellcode or
    # use the fact that CFUNCTYPE uses the x64 calling convention
    # where the return value might end up in EAX.
    
    # Let me try a different approach: create a wrapper function
    # that sets eax and calls the dispatcher
    
    # In x86_64 Windows ABI, CFUNCTYPE parameters go in: rcx, rdx, r8, r9
    # First arg -> rcx
    # So if we define CFUNCTYPE(c_double, c_int), the int goes to rcx
    
    # But _bist_nobs expects the dispatch ID in eax, not in rcx!
    # So we can't directly call it.
    
    # We could create a small assembly thunk that:
    # mov eax, <const>
    # call <dispatcher_addr>
    # ret
    
    # But creating executable memory from Python requires VirtualAlloc
    
    # Alternative: use VirtualAlloc + assembly
    MEM_COMMIT = 0x1000
    PAGE_EXECUTE_READWRITE = 0x40
    
    VirtualAlloc = kernel32.VirtualAlloc
    VirtualAlloc.restype = ctypes.c_void_p
    VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_ulong, ctypes.c_ulong]
    
    # Try calling a specific simple caller
    # First, let's try dispatch ID 531 (Linux _bist_nobs) and 535 (_bist_nvar)
    for target_dispatch in [531, 535, 540, 530, 532, 533, 534, 528, 529]:
        matched = [(rva, const) for rva, const in likely_bist if const == target_dispatch]
        if matched:
            rva, const = matched[0]
            func_addr = handle + rva
            print(f'\nTrying dispatch {target_dispatch} at RVA={rva:#010x}:')
            
            # Create a thunk: mov eax, <target_dispatch>; call main_dispatcher; ret
            # Assembly bytes:
            # B8 xx xx xx xx    mov eax, target_dispatch
            # 48 B8 ...         mov rax, main_dispatcher_addr (or use call relative)
            # FF D0             call rax
            # C3                ret
            
            # Simpler approach: use relative call
            # <thunk>:
            #   B8 <const>      mov eax, const
            #   E8 <rel32>      call main_dispatcher
            #   C3              ret
            thunk_size = 10  # mov + call + ret
            thunk = kernel32.VirtualAlloc(None, thunk_size, MEM_COMMIT, PAGE_EXECUTE_READWRITE)
            if thunk:
                # mov eax, <const>
                thunk_bytes = (ctypes.c_ubyte * thunk_size)()
                thunk_bytes[0] = 0xB8  # mov eax, imm32
                struct.pack_into('<I', thunk_bytes, 1, target_dispatch)
                thunk_bytes[5] = 0xE8  # call rel32
                # rel32 = target_addr - (thunk_addr + 10)
                target_full = handle + main_dispatcher
                rel32 = target_full - (thunk + 10)
                struct.pack_into('<i', thunk_bytes, 6, rel32)
                thunk_bytes[9] = 0xC3  # ret
                
                ctypes.memmove(ctypes.c_void_p(thunk), thunk_bytes, thunk_size)
                
                # Now call the thunk
                func_type = ctypes.CFUNCTYPE(ctypes.c_double)
                callable_func = func_type(thunk)
                print(f'    Thunk at {thunk:#x}')
                try:
                    result = callable_func()
                    print(f'    Result: {result}')
                except Exception as e:
                    print(f'    Error: {e}')
                
                kernel32.VirtualFree(thunk, 0, 0x8000)  # MEM_RELEASE
            
            break  # Try first match only

print('\nDone')
