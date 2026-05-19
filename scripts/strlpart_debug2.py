"""Debug: verify variable names and test _bi_st_strlpart directly."""
import sys, ctypes, json
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize
# Don't import call_void/call_string since they use internal functions
from pystata_x.sfi._core import SFIToolkit, Data
import pystata_x.sfi._engine as eng

initialize()
base = eng._BASE
sp_addr = base + 0x39b7000 + 0x108
manifest = json.load(open('src/pystata_x/sfi/manifest.json'))

_restore_sp = eng._restore_sp
pushint = lambda v: eng._pushint_fn(v)
pushstr = lambda s: eng._pushstr_fn(s, len(s))

fn_addr = base + manifest["symbols"]["_bi_st_strlpart"]
fn = ctypes.cast(fn_addr, ctypes.CFUNCTYPE(None, ctypes.c_int))

SFIToolkit.executeCommand('sysuse auto, clear')
SFIToolkit.executeCommand('gen strL s = "hello world wide web" if _n == 1')
SFIToolkit.executeCommand('gen strL longstr = "The quick brown fox jumps over the lazy dog. " * 5 if _n == 1')

print("=== Variable names ===", flush=True)
for v in range(Data.getVarCount()):
    name = Data.getVarName(v)
    typ = Data.getVarType(v)
    is_strl = Data.isVarTypeStrL(v)
    print(f"  var {v}: {name} type={typ} strL={is_strl}", flush=True)

print(f"\nnobs={Data.getObsTotal()}, nvar={Data.getVarCount()}", flush=True)

# Now test strlpart by finding the right var index for 's'
var_s = Data.getVarIndex('s')
var_longstr = Data.getVarIndex('longstr')
print(f"\nvar index for 's'={var_s}, 'longstr'={var_longstr}", flush=True)

# Direct test on 's' 
print("\n=== _bi_st_strlpart on 's' ===", flush=True)
sp_base = ctypes.c_uint64.from_address(sp_addr).value
pushstr(b's')
pushint(1)
pushint(5)  # part=5
fn(3)
sp = ctypes.c_uint64.from_address(sp_addr).value
tsmat = ctypes.c_uint64.from_address(sp).value
print(f"  tsmat={hex(tsmat)}", flush=True)
if tsmat and tsmat > 0x100000:
    gso = ctypes.c_uint64.from_address(tsmat).value
    print(f"  GSO={hex(gso)}", flush=True)
    if gso and gso > 0x100000:
        str_ptr = ctypes.c_uint64.from_address(gso).value
        print(f"  str_ptr={hex(str_ptr)}", flush=True)
        if str_ptr and str_ptr > 0x100000:
            slen = ctypes.c_uint32.from_address(str_ptr).value
            print(f"  len={slen}", flush=True)
            if slen and slen < 10000:
                data = ctypes.string_at(str_ptr + 4, min(slen, 500))
                print(f"  data={data!r}", flush=True)
_restore_sp(sp_base)

# Test on 'longstr'  
print("\n=== _bi_st_strlpart on 'longstr' ===", flush=True)
sp_base = ctypes.c_uint64.from_address(sp_addr).value
pushstr(b'longstr')
pushint(1)
pushint(50)  # part=50
fn(3)
sp = ctypes.c_uint64.from_address(sp_addr).value
tsmat = ctypes.c_uint64.from_address(sp).value
print(f"  tsmat={hex(tsmat)}", flush=True)
if tsmat and tsmat > 0x100000:
    gso = ctypes.c_uint64.from_address(tsmat).value
    print(f"  GSO={hex(gso)}", flush=True)
    if gso and gso > 0x100000:
        str_ptr = ctypes.c_uint64.from_address(gso).value
        print(f"  str_ptr={hex(str_ptr)}", flush=True)
        if str_ptr and str_ptr > 0x100000:
            slen = ctypes.c_uint32.from_address(str_ptr).value
            print(f"  len={slen}", flush=True)
            if slen and slen < 10000:
                data = ctypes.string_at(str_ptr + 4, min(slen, 500))
                print(f"  data={data!r}", flush=True)
_restore_sp(sp_base)

# Now try with larger buffer
print("\n=== _bi_st_strlpart on 'longstr' with 200-byte buffer ===", flush=True)
sp_base = ctypes.c_uint64.from_address(sp_addr).value
pushstr(b'X' * 200)  # 200-byte buffer
pushint(1)
pushint(200)  # part=200
fn(3)
sp = ctypes.c_uint64.from_address(sp_addr).value
tsmat = ctypes.c_uint64.from_address(sp).value
print(f"  tsmat={hex(tsmat)}", flush=True)
if tsmat and tsmat > 0x100000:
    gso = ctypes.c_uint64.from_address(tsmat).value
    print(f"  GSO={hex(gso)}", flush=True)
    if gso and gso > 0x100000:
        str_ptr = ctypes.c_uint64.from_address(gso).value
        print(f"  str_ptr={hex(str_ptr)}", flush=True)
        if str_ptr and str_ptr > 0x100000:
            slen = ctypes.c_uint32.from_address(str_ptr).value
            print(f"  len={slen}", flush=True)
            if slen and slen < 10000:
                data = ctypes.string_at(str_ptr + 4, min(slen, 500))
                print(f"  data={data!r}", flush=True)
_restore_sp(sp_base)

print("\nDone", flush=True)
