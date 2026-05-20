"""Read the result left on stack by _bi_st_strlpart."""
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

SFIToolkit.executeCommand('sysuse auto, clear')
SFIToolkit.executeCommand('gen strL s = "hello world wide web" if _n == 1')
SFIToolkit.executeCommand('gen strL longtext = "The quick brown fox jumps over the lazy dog repeatedly at the zoo near the big red barn" if _n == 1')

_restore_sp = eng._restore_sp
pushint = lambda v: eng._pushint_fn(v)
pushstr = lambda s: eng._pushstr_fn(s, len(s))

fn_addr = base + manifest["symbols"]["_bi_st_strlpart"]
fn = ctypes.cast(fn_addr, ctypes.CFUNCTYPE(None, ctypes.c_int))

def try_strlpart(var_name, obs, part):
    """Try _bi_st_strlpart with string name + obs + part."""
    sp_base = ctypes.c_uint64.from_address(sp_addr).value
    pushstr(var_name)
    pushint(obs)
    pushint(part)
    
    err_before = ctypes.c_int32.from_address(err_addr).value
    try:
        fn(3)
        err_after = ctypes.c_int32.from_address(err_addr).value
        sp_fn = ctypes.c_uint64.from_address(sp_addr).value
        
        # Read what's on the stack (1 item should remain)
        tsmat = ctypes.c_uint64.from_address(sp_fn).value
        result_str = None
        if tsmat and tsmat > 0x100000:
            # Read string at tsmat
            dp = ctypes.c_uint64.from_address(tsmat + 8).value
            if dp:
                str_ptr = ctypes.c_uint64.from_address(dp).value
                if str_ptr and str_ptr > 0x100000:
                    slen = ctypes.c_uint32.from_address(str_ptr).value
                    if slen < 10000:
                        result_str = ctypes.string_at(str_ptr + 4, slen)
        
        state_ok = False
        _restore_sp(sp_base)
        try:
            state_ok = (call_string("_bist_sdata", 1, 1) is not None)
        except:
            pass
        
        print(f"strlpart({var_name!r}, {obs}, {part}): err={err_before}->{err_after} SP_delta={sp_fn - sp_base} result={result_str!r} state={'OK' if state_ok else 'CORRUPT'}", flush=True)
        return result_str
    except Exception as e:
        _restore_sp(sp_base)
        print(f"strlpart({var_name!r}, {obs}, {part}): ERR {e}", flush=True)
        return None

print("=== Testing _bi_st_strlpart with various strings ===", flush=True)

# Test with variable named 's' (strL)
for obs in [1, 1]:
    for part in [0, 1, 2]:
        try_strlpart(b's', obs, part)

# Test with variable named 'longtext'
print("\n--- longtext ---", flush=True)
for part in [0, 1, 2, 10, 20]:
    try_strlpart(b'longtext', 1, part)

# Test with regular string variable 'make'
print("\n--- regular string 'make' ---", flush=True)
for part in [0, 1]:
    try_strlpart(b'make', 1, part)

# Test with numerical variable (var name 'price')
print("\n--- numerical 'price' ---", flush=True)
for part in [0, 1]:
    try_strlpart(b'price', 1, part)

print("\nDone", flush=True)
