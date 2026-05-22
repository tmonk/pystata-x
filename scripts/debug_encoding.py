"""Debug variable name reading step by step."""
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

# Load manifest for scratch rva
with open('src/pystata_x/sfi/manifests/manifest-windows-x86_64.json') as f:
    m = json.load(f)
scratch_rva = m['memory_offsets']['scratch_buffer_rva']

def exe(cmd):
    return dll.StataSO_Execute(cmd.encode() if isinstance(cmd, str) else cmd)

def scratch():
    buf = (ctypes.c_double * 1)()
    ctypes.memmove(buf, ctypes.c_void_p(dll._handle + scratch_rva), 8)
    return buf[0]

print("=== Step 1: Local macro ===")
rc = exe('local __px_name : variable 1')
print(f'local rc: {rc}')

print("\n=== Step 2: gen with macro expansion ===")
rc = exe('capture drop __px_vn')
print(f'drop rc: {rc}')
rc = exe('gen str32 __px_vn = "`__px_name\'"')
print(f'gen rc: {rc}')

print("\n=== Step 3: verify gen worked ===")
# Try to get a summary
rc = exe('describe __px_vn')
print(f'describe rc: {rc}')

print("\n=== Step 4: encode single char via scalar ===")
# Use stprpos with the gen'd variable
rc = exe('scalar __px_c = strpos("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_", substr(__px_vn[1], 1, 1))')
print(f'scalar rc: {rc}')
rc = exe('capture drop __px_tmp')
rc = exe('gen double __px_tmp = __px_c')
print(f'gen rc: {rc}')
code = scratch()
print(f'char code: {code}')

# Decode
alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
idx = int(code) - 1 if code and int(code) > 0 else -1
if 0 <= idx < len(alphabet):
    print(f'First char: "{alphabet[idx]}"')
else:
    print(f'Cannot decode code={code}')

print("\n=== Step 5: Try with double-quoted macro ===")
rc = exe('capture drop __px_vn2')
rc = exe('gen str32 __px_vn2 = "`__px_name\'"')  
rc = exe('scalar __px_c2 = strpos("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_", substr(__px_vn2[1], 1, 1))')
rc = exe('capture drop __px_tmp')
rc = exe('gen double __px_tmp = __px_c2')
code2 = scratch()
print(f'char code: {code2}')
idx2 = int(code2) - 1 if code2 and int(code2) > 0 else -1
if 0 <= idx2 < len(alphabet):
    print(f'First char: "{alphabet[idx2]}"')

print("\nDone")
