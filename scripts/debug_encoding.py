"""Debug macro expansion."""
import ctypes, json, sys
sys.path.insert(0, 'src')

dll_path = r'C:\Program Files\StataNow19\se-64.dll'
dll = ctypes.WinDLL(dll_path)
dll.StataSO_Main.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
dll.StataSO_Main.restype = ctypes.c_int
dll.StataSO_Main(2, (ctypes.c_char_p * 2)(b'stata', b'-q'))
dll.StataSO_Execute.argtypes = [ctypes.c_char_p]
dll.StataSO_Execute.restype = ctypes.c_int

dll.StataSO_Execute(b'sysuse auto, clear')

with open('src/pystata_x/sfi/manifests/manifest-windows-x86_64.json') as f:
    m = json.load(f)
scratch_rva = m['memory_offsets']['scratch_buffer_rva']

def exe(cmd):
    if isinstance(cmd, str): cmd = cmd.encode()
    return dll.StataSO_Execute(cmd)

def scratch():
    buf = (ctypes.c_double * 1)()
    ctypes.memmove(buf, ctypes.c_void_p(dll._handle + scratch_rva), 8)
    return buf[0]

# Set a global macro
rc = exe('global px_test_g = "hello_global"')
print(f'global rc: {rc}')

# Try to read it via display
rc = exe('capture drop __px_t')
rc = exe('gen str2000 __px_t = "$px_test_g"')
print(f'gen from $ rc: {rc}')
print(f'  value: gen variable created')

# Read it via encode
alphabet = ' abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_%.-+#/'
for chunk in range(2):
    terms = []
    for i in range(5):
        p = chunk * 5 + i + 1
        pw = 256 ** i
        terms.append(f'cond(substr(__px_t[1], {p}, 1) == "", 0, (strpos("{alphabet}", substr(__px_t[1], {p}, 1)) + 1) * {pw})')
    expr = ' + '.join(terms)
    rc = exe(f'scalar __px_c{chunk} = {expr}')
    if rc != 0: print(f'chunk {chunk} FAILED rc={rc}')
    exe('capture drop __px_d')
    exe(f'gen double __px_d = __px_c{chunk}')
    val = scratch()
    decoded = ''
    raw_int = int(val)
    for i in range(5):
        b = (raw_int >> (i * 8)) & 0xFF
        if b == 0: break
        idx = b - 2
        if 0 <= idx < len(alphabet): decoded += alphabet[idx]
    print(f'  chunk {chunk}: decoded="{decoded}"')

# Try with display
rc = exe('capture drop __px_t')
rc = exe('gen str2000 __px_t = "": display "$px_test_g""')
print(f'gen from display rc: {rc}')

# Try di capture
rc = exe('capture drop __px_t')
rc = exe('gen str2000 __px_t = "`=c(level)\'"')
rc = exe('capture drop __px_d')
rc = exe('gen double __px_d = 1')
terms = []
for i in range(2):
    p = i + 1
    pw = 256 ** i
    terms.append(f'cond(substr(__px_t[1], {p}, 1) == "", 0, (strpos("{alphabet}", substr(__px_t[1], {p}, 1)) + 1) * {pw})')
expr = ' + '.join(terms)
exe(f'scalar __px_c0 = {expr}')
exe('capture drop __px_d')
exe('gen double __px_d = __px_c0')
val = scratch()
print(f'c(level) encoded: {val}')
raw_int = int(val)
decoded = ''
for i in range(2):
    b = (raw_int >> (i * 8)) & 0xFF
    if b == 0: break
    idx = b - 2
    if 0 <= idx < len(alphabet): decoded += alphabet[idx]
print(f'  decoded: "{decoded}"')

print('\nDone')
