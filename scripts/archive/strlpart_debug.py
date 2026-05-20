"""Debug: verify 'longstr' was created, then test _bi_st_strlpart on it."""
import sys, ctypes, json
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize, call_string, call_void
from pystata_x.sfi._core import SFIToolkit
import pystata_x.sfi._engine as eng

initialize()
base = eng._BASE
sp_addr = base + 0x39b7000 + 0x108
err_addr = base + 0x39b7000 + 0x11c
manifest = json.load(open('src/pystata_x/sfi/manifest.json'))

_restore_sp = eng._restore_sp
pushint = lambda v: eng._pushint_fn(v)
pushstr = lambda s: eng._pushstr_fn(s, len(s))

fn_addr = base + manifest["symbols"]["_bi_st_strlpart"]
fn = ctypes.cast(fn_addr, ctypes.CFUNCTYPE(None, ctypes.c_int))

SFIToolkit.executeCommand('sysuse auto, clear')
SFIToolkit.executeCommand('gen strL s = "hello world wide web" if _n == 1')

# Check if s exists and is strL
print("=== Verify variable 's' ===", flush=True)
nobs = call_int("_bist_nobs", 0)
print(f"  nobs: {nobs}", flush=True)
nvar = call_int("_bist_nvar", 0)
print(f"  nvar: {nvar}", flush=True)

# Read 's' as regular string
r = call_string("_bist_sdata", 1, 3)  # var index 3 (s would be 4th var? Let me check)
print(f"  sdata(1,3): {r!r}", flush=True)

# List variable names
for v in range(1, 10):
    name = call_string("_bist_varname", v)
    if name:
        print(f"  var {v}: {name!r}", flush=True)

print("\n=== Test _bi_st_strlpart on var by INDEX ===", flush=True)
# Try with variable INDEX (int) instead of name (string)
def read_part_by_idx(var_idx, obs, part, buffer_size=100):
    sp_base = ctypes.c_uint64.from_address(sp_addr).value
    pushstr(b'X' * buffer_size)  # output buffer
    pushint(var_idx)  # maybe arg1 should be int index?
    pushint(obs)
    pushint(part)
    fn(4 if var_idx else 3)  # try w0=4 for 4 args?
    err = ctypes.c_int32.from_address(err_addr).value
    sp = ctypes.c_uint64.from_address(sp_addr).value
    result = None
    tsmat = ctypes.c_uint64.from_address(sp).value
    if tsmat and tsmat > 0x100000:
        gso = ctypes.c_uint64.from_address(tsmat).value
        if gso and gso > 0x100000:
            str_ptr = ctypes.c_uint64.from_address(gso).value
            if str_ptr and str_ptr > 0x100000:
                slen = ctypes.c_uint32.from_address(str_ptr).value
                if slen and slen < 10000:
                    data = ctypes.string_at(str_ptr + 4, slen)
                    if data and data[-1:] == b'\x00':
                        data = data[:-1]
                    result = data
    _restore_sp(sp_base)
    return result, err

# With int index
print("  With int var index (3='s'):", flush=True)
result, err = read_part_by_idx(3, 1, 10, 200)
print(f"    result={result!r} err={err}", flush=True)

# Try original string-name approach but on var 3
print("\n  With string name 's':", flush=True)
sp_base = ctypes.c_uint64.from_address(sp_addr).value
pushstr(b'X' * 200)
pushint(1)  # obs
pushint(20)  # part=20
fn(3)
err = ctypes.c_int32.from_address(err_addr).value
sp = ctypes.c_uint64.from_address(sp_addr).value
tsmat = ctypes.c_uint64.from_address(sp).value
print(f"    SP {hex(sp)} tsmat={hex(tsmat)} err={err}", flush=True)
if tsmat and tsmat > 0x100000:
    gso = ctypes.c_uint64.from_address(tsmat).value
    print(f"    GSO={hex(gso)}", flush=True)
    if gso and gso > 0x100000:
        str_ptr = ctypes.c_uint64.from_address(gso).value
        print(f"    str_ptr={hex(str_ptr)}", flush=True)
        if str_ptr and str_ptr > 0x100000:
            slen = ctypes.c_uint32.from_address(str_ptr).value
            print(f"    len={slen}", flush=True)
            if slen and slen < 10000:
                data = ctypes.string_at(str_ptr + 4, min(slen, 500))
                print(f"    data={data!r}", flush=True)
_restore_sp(sp_base)

# Directly test like the original working scan
print("\n=== Direct test on 's' (like scan_strl_parts.py) ===", flush=True)
sp_base = ctypes.c_uint64.from_address(sp_addr).value
pushstr(b's')
pushint(1)
pushint(5)  # part=5
fn(3)
sp = ctypes.c_uint64.from_address(sp_addr).value
tsmat = ctypes.c_uint64.from_address(sp).value
print(f"    SP={hex(sp)} tsmat={hex(tsmat)}", flush=True)
if tsmat:
    gso = ctypes.c_uint64.from_address(tsmat).value
    print(f"    GSO={hex(gso)}", flush=True)
    if gso and gso > 0x100000:
        str_ptr = ctypes.c_uint64.from_address(gso).value
        print(f"    str_ptr={hex(str_ptr)}", flush=True)
        slen = ctypes.c_uint32.from_address(str_ptr).value
        print(f"    len={slen}", flush=True)
        if slen and slen < 10000:
            data = ctypes.string_at(str_ptr + 4, min(slen, 500))
            print(f"    data={data!r}", flush=True)
_restore_sp(sp_base)

print("\nDone", flush=True)
