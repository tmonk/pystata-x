"""Find alternative ways to get variable names on Windows."""
import ctypes, sys, json
sys.path.insert(0, 'src')

dll_path = r'C:\Program Files\StataNow19\se-64.dll'
dll = ctypes.WinDLL(dll_path)
dll.StataSO_Main.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
dll.StataSO_Main.restype = ctypes.c_int
dll.StataSO_Main(2, (ctypes.c_char_p * 2)(b'stata', b'-q'))
dll.StataSO_Execute.argtypes = [ctypes.c_char_p]
dll.StataSO_Execute.restype = ctypes.c_int
dll.StataSO_Execute(b'sysuse auto, clear')

def exe(cmd):
    return dll.StataSO_Execute(cmd.encode() if isinstance(cmd, str) else cmd)

# Load manifest for scratch rva
with open('src/pystata_x/sfi/manifests/manifest-windows-x86_64.json') as f:
    m = json.load(f)
scratch_rva = m['memory_offsets']['scratch_buffer_rva']

def scratch():
    buf = (ctypes.c_double * 1)()
    ctypes.memmove(buf, ctypes.c_void_p(dll._handle + scratch_rva), 8)
    return buf[0]

# Approach 1: ds + r(varlist)
print('=== Approach 1: ds + r(varlist) ===')
rc = exe('quietly ds')
print(f'ds rc: {rc}')

# Store r(varlist) in a macro
rc = exe('local __px_vlist = "`r(varlist)\'"')
print(f'local vlist rc: {rc}')

# Get first word
rc = exe('local __px_first : word 1 of `__px_vlist\'')
print(f'local first rc: {rc}')

# Store and read
rc = exe('capture drop __px_vn')
rc = exe('gen str32 __px_vn = "`__px_first\'"')
print(f'gen first rc: {rc}')

# Encode first char
rc = exe('scalar __px_c = strpos("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_", substr(__px_vn[1], 1, 1))')
rc = exe('capture drop __px_tmp')
rc = exe('gen double __px_tmp = __px_c')
code = scratch()
print(f'first char code: {code}')

alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
idx = int(code) - 1 if code and int(code) > 0 else -1
if 0 <= idx < len(alphabet):
    print(f'First char: "{alphabet[idx]}"')

# Approach 2: capture all variables via ds and iterate
print('\n=== Approach 2: all variables ===')
for nvars in range(1, 6):  # Get first 5 var names
    # Use word nvars of the varlist
    rc = exe(f'local __px_v : word {nvars} of `__px_vlist\'')
    rc = exe('capture drop __px_vn')
    rc = exe(f'gen str32 __px_vn = "`__px_v\'"')
    # Read the full name via encoding (chunk by chunk)
    full_name = ''
    for chunk in range(3):  # Up to 18 chars
        terms = []
        for i in range(6):
            pos = chunk * 6 + i + 1
            pow256 = 256 ** i
            terms.append(
                f'cond(substr(__px_vn[1], {pos}, 1) == "", 0,'
                f' (strpos("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_",'
                f' substr(__px_vn[1], {pos}, 1)) + 1) * {pow256})')
        expr = ' + '.join(terms)
        rc = exe(f'scalar __px_enc_c{chunk} = {expr}')
        rc = exe('capture drop __px_tmp')
        rc = exe(f'gen double __px_tmp = __px_enc_c{chunk}')
        val = scratch()
        if val is None or val <= 0:
            break
        raw_int = int(val)
        for i in range(6):
            b = (raw_int >> (i * 8)) & 0xFF
            if b == 0:
                break
            full_name += chr(b)
        if b == 0:
            break
    print(f'  var{nvars}: "{full_name}"')

print('\nDone')
