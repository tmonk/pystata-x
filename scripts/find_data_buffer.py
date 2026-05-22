"""Call Java SFI exports directly to read Stata values.
Java_com_stata_sfi_Data_getNum is exported - try calling it."""
import ctypes

dll_path = r'C:\Program Files\StataNow19\se-64.dll'
dll = ctypes.WinDLL(dll_path)
handle = dll._handle

# Init Stata
dll.StataSO_Main.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
dll.StataSO_Main.restype = ctypes.c_int
dll.StataSO_Main(2, (ctypes.c_char_p * 2)(b'stata', b'-q'))
dll.StataSO_Execute.argtypes = [ctypes.c_char_p]
dll.StataSO_Execute.restype = ctypes.c_int

# Load dataset
dll.StataSO_Execute(b'sysuse auto, clear')

# Try to find and call Java_com_stata_sfi_Data_getNum
# The JNI signature: jdouble JNICALL Java_com_stata_sfi_Data_getNum(JNIEnv*, jclass, jlong, jint)

func = getattr(dll, 'Java_com_stata_sfi_Data_getNum', None)
if func is None:
    print('Function not found as attribute, trying pointer...')
    # Try getting by name
    from ctypes import c_void_p, c_double, c_longlong, c_int
    func_ptr = ctypes.cast(
        ctypes.c_void_p(handle + 0x21b5bd0),  # wrong, this is the dispatcher
        ctypes.CFUNCTYPE(c_double, c_void_p, c_void_p, c_longlong, c_int)
    )
else:
    print('Found Java_com_stata_sfi_Data_getNum via attribute!')
    from ctypes import c_double, c_longlong, c_int, c_void_p
    
    # Try calling with NULL env and class
    print('Calling getNum(NULL, NULL, obs=1, var=1)...')
    try:
        # On x64 Windows, CFUNCTYPE = __fastcall (same as stdcall)
        restype = c_double
        argtypes = [c_void_p, c_void_p, c_longlong, c_int]
        
        # Option 1: direct attribute call (dll.func()) uses WinDLL convention
        result = func(ctypes.c_void_p(0), ctypes.c_void_p(0), 0, 0)  # obs=1, var=1
        print('Result:', result)
    except Exception as e:
        print('Error calling getNum:', e)

print('\nAlso try data_getStr...')
func_str = getattr(dll, 'Java_com_stata_sfi_Data_getStr', None)
if func_str is not None:
    print('Found getStr!')
    from ctypes import c_char_p, c_longlong, c_int, c_void_p, c_byte
    
    # jstring JNICALL Java_com_stata_sfi_Data_getStr(JNIEnv*, jclass, jlong, jint)
    # Calling with NULL will crash (needs JNI to allocate jstring)
    print('  (skipping - jstring return requires JNI)')

print('\nTrying Java_com_stata_sfi_Scalar_getValue...')
func_scalar = getattr(dll, 'Java_com_stata_sfi_Scalar_getValue', None)
if func_scalar is not None:
    print('Found Scalar_getValue!')
    # jdouble JNICALL Java_com_stata_sfi_Scalar_getValue(JNIEnv*, jclass, jstring)
    # This needs a jstring, hard to construct without JNI

print('\nChecking ALL Java exports for usable functions...')
import struct
with open(dll_path, 'rb') as f:
    pe_data = f.read()
e_lfanew = struct.unpack('<I', pe_data[0x3c:0x40])[0]
opt_hdr_size = struct.unpack('<H', pe_data[e_lfanew+20:e_lfanew+22])[0]
sh_off = e_lfanew + 24 + opt_hdr_size
for i in range(struct.unpack('<H', pe_data[e_lfanew+6:e_lfanew+8])[0]):
    sh = pe_data[sh_off + i*40:sh_off + i*40 + 40]
    if sh[:8].rstrip(b'\x00').decode('utf-8', errors='replace') == '.edata':
        edata_rva = struct.unpack('<I', sh[12:16])[0]
        edata_vsize = struct.unpack('<I', sh[8:12])[0]
        edata_ptr = handle + edata_rva
        buf = (ctypes.c_char * edata_vsize)()
        ctypes.memmove(buf, ctypes.c_void_p(edata_ptr), edata_vsize)
        edata = bytes(buf)
        
        # Parse export directory
        exp_flags = struct.unpack('<I', edata[0:4])[0]
        exp_ts = struct.unpack('<I', edata[4:8])[0]
        exp_maj = struct.unpack('<H', edata[8:10])[0]
        exp_min = struct.unpack('<H', edata[10:12])[0]
        name_rva = struct.unpack('<I', edata[12:16])[0]
        ord_base = struct.unpack('<I', edata[16:20])[0]
        num_addr = struct.unpack('<I', edata[20:24])[0]
        num_name = struct.unpack('<I', edata[24:28])[0]
        addr_rva = struct.unpack('<I', edata[28:32])[0]
        name_ptr_rva = struct.unpack('<I', edata[32:36])[0]
        ord_rva = struct.unpack('<I', edata[36:40])[0]
        
        # Read address table and name pointer table
        addr_buf = (ctypes.c_char * (num_addr * 4))()
        ctypes.memmove(addr_buf, ctypes.c_void_p(handle + addr_rva), num_addr * 4)
        addr_table = bytearray(addr_buf)
        
        name_ptr_buf = (ctypes.c_char * (num_name * 4))()
        ctypes.memmove(name_ptr_buf, ctypes.c_void_p(handle + name_ptr_rva), num_name * 4)
        
        print('\nAll exports by name:')
        count = 0
        for k in range(num_name):
            name_off = struct.unpack('<I', name_ptr_buf[k*4:k*4+4])[0]
            # Read the name string
            nbuf = (ctypes.c_char * 256)()
            ctypes.memmove(nbuf, ctypes.c_void_p(handle + name_off), 256)
            name = nbuf.value.decode('utf-8', errors='replace') if nbuf.value else ''
            if 'getNum' in name or 'getStr' in name or 'getValue' in name or 'getDouble' in name:
                addr_off = struct.unpack('<I', addr_table[k*4:k*4+4])[0]
                print('  %s rva=%x' % (name, addr_off))
                count += 1
            if count >= 20:
                print('  ... (showing first 20 matching)')
                break
        break

print('\nDone')
