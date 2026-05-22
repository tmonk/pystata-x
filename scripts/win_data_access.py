"""BUILD COMPLETE WINDOWS SFI SOLUTION using scalar intermediate pattern.

data_get(obs, var) pattern:
1. scalar __px_val = varname[obs]
2. gen double __px_t = __px_val  (writes scalar value to 0x922C00)
3. Read double at 0x922C00
4. drop __px_t

For strings (var names, types, etc.):
1. Store in local macro first
2. Store macro value in a scalar (only for numeric) 
3. For strings: use the encode-as-double approach with intermediate gen through scalar

For var names specifically:
1. local __px_name : variable 1
2. gen str32 __px_s = "`__px_name'"  (creates string var, last variable)
3. Write each char as a double via scalar
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
for i in range(struct.unpack('<H', pe_data[e_lfanew+6:e_lfanew+8])[0]):
    sh = pe_data[sh_off + i*40:sh_off + i*40 + 40]
    if sh[:8].rstrip(b'\x00').decode('utf-8', errors='replace') == '.data':
        data_rva = struct.unpack('<I', sh[12:16])[0]
        break
data_ptr = handle + data_rva

SCRATCH_OFF = 0x922C00

def scratch():
    buf = (ctypes.c_double * 1)()
    ctypes.memmove(buf, ctypes.c_void_p(data_ptr + SCRATCH_OFF), 8)
    return buf[0]

def execute(cmd):
    if isinstance(cmd, str):
        cmd = cmd.encode()
    return dll.StataSO_Execute(cmd)

# Load auto
execute('sysuse auto, clear')

# === TEST: BUILD COMPLETE DATA ACCESS ===

# Create reusable temp variable once
execute('capture drop __px_t')
execute('scalar __px_tmp = 0')

print('=== WINDOWS SFI DATA ACCESS TEST ===')

# Test 1: data_get(obs, var) for numeric values
def win_data_get(obs, var, varname=None):
    """Read Stata data value on Windows.
    
    Pattern: scalar __px_tmp = varname[obs+1]; gen double __px_t = __px_tmp
    Last gen'd var's obs 0 value is at .data+0x922C00.
    """
    if varname is None:
        # Get varname via macro first
        execute(f'local __px_vn : variable {var}')
        varname = '`__px_vn\''  # Will expand to actual name
    
    # Store value in scalar
    execute(f'scalar __px_tmp = {varname}[{obs}]')
    # Write scalar to temp variable (goes to scratch buffer)
    execute('capture drop __px_t')
    execute('gen double __px_t = __px_tmp')
    val = scratch()
    return val

# Test: read all obs of price
print('\n--- data_get tests ---')
for obs in [1, 2, 10, 74]:
    val = win_data_get(obs, 1, 'price')
    print(f'  price[{obs}] = {val:.0f}')

# Test: read various variables
for var_idx, varname in enumerate(['price', 'mpg', 'rep78', 'weight', 'length', 'turn'], 1):
    val = win_data_get(1, var_idx, varname)
    print(f'  {varname}[1] = {val:.0f}')

# Test 2: Get variable names
print('\n--- Variable names ---')
for var_idx in range(1, 13):
    execute(f'local __px_name : variable {var_idx}')
    # Store the macro value in a string var  
    execute(f'gen str32 __px_s{var_idx} = "`__px_name\'"')
    # Now encode the first 6 chars
    # Use scalar for each char
    decoded = ''
    for chunk in range(3):
        encoded = 0
        for i in range(6):
            pos = chunk * 6 + i + 1
            execute(f'scalar __px_charcode = strpos("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_", substr(__px_s{var_idx}[1], {pos}, 1))')
            execute('capture drop __px_t')
            execute('gen double __px_t = __px_charcode')
            code = int(scratch())
            if code > 0:
                # code is strpos index, the actual char is at that position
                pass
        execute(f'drop __px_s{var_idx}')
    
    # Simpler approach: use local macro directly via scalar encoding
    execute(f'local __px_name : variable {var_idx}')
    decoded = ''
    for chunk in range(3):  # Up to 18 chars (3 groups of 6)
        encoded = 0
        for i in range(6):
            pos = chunk * 6 + i + 1
            # Use strpos to get character index, then encode
            execute(f'scalar __px_char = strpos("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_", substr("`__px_name\'", {pos}, 1))')
            execute('capture drop __px_t')
            execute('gen double __px_t = __px_char')
            code = int(scratch())
            if code > 0:
                # The character index in our alphabet = code - 1
                alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
                if 1 <= code <= len(alphabet):
                    decoded += alphabet[code - 1]
                    encoded += code * (256 ** i)
            else:
                break
        if not decoded:
            break
    
    print(f'  var{var_idx}: decoded="{decoded}"')

# Test 3: Get variable type
print('\n--- Variable types ---')
for var_idx in range(1, 13):
    execute(f'local __px_type : type `:variable {var_idx}\'')
    # The type is returned as a string like "byte", "int", "float", "double", "str##"
    execute(f'scalar __px_type_code = strpos("byte int float double str", substr("`__px_type\'", 1, 3))')
    execute('capture drop __px_t')
    execute('gen double __px_t = __px_type_code')
    type_code = int(scratch())
    type_names = ['', 'byte', 'int ', 'float', 'doubl', 'str']
    print(f'  var{var_idx}: type_code={type_code} (type={type_names[type_code] if 0 < type_code < len(type_names) else "?"})')

print('\nDone')
