"""TEST: Does 0x922C00 store gen'd expression values correctly?
Key question: does the scratch buffer at 0x922C00 work for expressions or just literals?"""
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
for i in range(struct.unpack('<H', pe_data[e_lfanew+6:e_lfanew+8])[0]):
    sh = pe_data[sh_off + i*40:sh_off + i*40 + 40]
    if sh[:8].rstrip(b'\x00').decode('utf-8', errors='replace') == '.data':
        data_rva = struct.unpack('<I', sh[12:16])[0]
        break
data_ptr = handle + data_rva

def scratch():
    buf = (ctypes.c_double * 1)()
    ctypes.memmove(buf, ctypes.c_void_p(data_ptr + 0x922C00), 8)
    return buf[0]

def run(cmd):
    rc = dll.StataSO_Execute(cmd.encode() if isinstance(cmd, str) else cmd)
    return rc

# Test with auto dataset
run('sysuse auto, clear')

# Test 1: Literal
print('=== Test 1: gen with literal ===')
run('capture drop __px_t')
run('gen double __px_t = 42')
print('  Literal 42: %.0f' % scratch())

# Test 2: Arithmetic expression (no bracket)
print('\n=== Test 2: gen with arithmetic ===')
run('capture drop __px_t')
run('gen double __px_t = 1 + 2')
print('  1+2: %.0f' % scratch())

# Test 3: Expression with strpos
print('\n=== Test 3: gen with strpos ===')
run('capture drop __px_t')
run('gen double __px_t = strpos("abcdef", "c") + 1')
print('  strpos("abcdef","c")+1: %.0f (expected 3)' % scratch())

# Test 4: Expression with bracket reference
print('\n=== Test 4: gen with bracket reference ===')
run('capture drop __px_t')
run('gen double __px_t = price[1]')
print('  price[1]: %.0f (expected 4099)' % scratch())

# Test 5: Using scalar intermediate
print('\n=== Test 5: gen via scalar intermediate ===')
run('scalar __px_s = price[1]')
print('  After scalar: scratch=%.0f' % scratch())
run('capture drop __px_t')
run('gen double __px_t = __px_s')
print('  scalar __px_s -> gen: %.0f (expected 4099)' % scratch())

# Test 6: Using local macro intermediate
print('\n=== Test 6: gen via local macro ===')
run('local __px_v = price[1]')
run('capture drop __px_t')
run('gen double __px_t = `__px_v\'')
print('  local macro -> gen: %.0f (expected 4099)' % scratch())

# Test 7: The actual encoding expression
print('\n=== Test 7: gen with encoding expression ===')
run('capture drop __px_t')
# Encode "make[1]" first 6 chars
src = 'make[1]'
terms = []
for i in range(6):
    pos = i + 1
    pow256 = 256 ** i
    terms.append(f'cond(substr({src}, {pos}, 1) == "", 0, (strpos("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_", substr({src}, {pos}, 1)) + 31) * {pow256})')
expr = ' + '.join(terms)
run(f'gen double __px_t = {expr}')
result = scratch()
print(f'  Scratch: {result}')

# Decode
tmp = int(result)
decoded = ''
for i in range(6):
    b = (tmp >> (i * 8)) & 0xFF
    if b == 0:
        break
    decoded += chr(b)
print(f'  Decoded: "{decoded}"')
print(f'  Expected: "AMC Co" (for make[1]="AMC Concord")')

# Test 8: Direct comparison - encode strpos vs actual value
print('\n=== Test 8: Local macro + gen for values ===')
run('capture drop __px_t')
run('local __px_v : variable 1')  # Get var1 name
# Store in a string var
run('gen str32 __px_vn = "`__px_v\'"')
print('  Stored var name in str32')
# Now encode each char of __px_vn[1]
run('capture drop __px_t')
src = '__px_vn[1]'
terms = []
for i in range(6):
    pos = i + 1
    pow256 = 256 ** i
    terms.append(f'cond(substr({src}, {pos}, 1) == "", 0, (strpos("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_", substr({src}, {pos}, 1)) + 31) * {pow256})')
expr = ' + '.join(terms)
run(f'gen double __px_t = {expr}')
result = scratch()
tmp = int(result)
decoded = ''
for i in range(6):
    b = (tmp >> (i * 8)) & 0xFF
    if b == 0:
        break
    decoded += chr(b)
print(f'  Decoded var1 name: "{decoded}"')
print(f'  Expected: "price"')

# Test 9: Read var name via Stata extended function + gen double
print('\n=== Test 9: Read var name directly ===')
run('scalar __px_vname = 0')
for var_idx in range(1, 5):
    run(f'local __px_name : variable {var_idx}')
    # Store as double: encode first 6 chars
    src_str = f'"`__px_name\'"'
    terms = []
    for i in range(6):
        pos = i + 1
        pow256 = 256 ** i
        terms.append(f'cond(substr({src_str}, {pos}, 1) == "", 0, (strpos("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_", substr({src_str}, {pos}, 1)) + 31) * {pow256})')
    expr = ' + '.join(terms)
    run(f'gen double __px_n{var_idx} = {expr}')
    r = scratch()
    tmp = int(r)
    decoded = ''
    for i in range(6):
        b = (tmp >> (i * 8)) & 0xFF
        if b <= 0 or b > 127:
            break
        decoded += chr(b)
    print(f'  var{var_idx}: scratch={r} decoded="{decoded}"')
    run(f'drop __px_n{var_idx}')

print('\nDone')
