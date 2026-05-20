"""Test _bi_st_strlpart across parts of a strL cell."""
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

def read_part(var_name, obs, part):
    """Call _bi_st_strlpart and read the modified string from the tsmat."""
    sp_base = ctypes.c_uint64.from_address(sp_addr).value
    
    # Push string first (creates SP[-2], the output buffer tsmat)
    pushstr(var_name)
    pushint(obs)
    pushint(part)
    
    err_before = ctypes.c_int32.from_address(err_addr).value
    fn(3)
    err_after = ctypes.c_int32.from_address(err_addr).value
    
    sp = ctypes.c_uint64.from_address(sp_addr).value
    
    # Read the modified string from the tsmat remaining on stack
    result = None
    tsmat = ctypes.c_uint64.from_address(sp).value
    if tsmat and tsmat > 0x100000:
        gso = ctypes.c_uint64.from_address(tsmat).value
        if gso and gso > 0x100000:
            str_ptr = ctypes.c_uint64.from_address(gso).value
            if str_ptr and str_ptr > 0x100000:
                slen = ctypes.c_uint32.from_address(str_ptr).value
                if slen and slen < 100000:
                    data = ctypes.string_at(str_ptr + 4, slen)
                    # Strip null terminator if present
                    if data and data[-1:] == b'\x00':
                        data = data[:-1]
                    result = data
    
    _restore_sp(sp_base)
    return result, err_before, err_after

SFIToolkit.executeCommand('sysuse auto, clear')
SFIToolkit.executeCommand('gen strL s = "hello world wide web" if _n == 1')
SFIToolkit.executeCommand('gen strL longtext = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*()" if _n == 1')

print("=== _bi_st_strlpart part-by-part scan ===", flush=True)

# Scan 's' by single bytes
print("\nStrL 's' = 'hello world wide web' (obs=1):", flush=True)
for part in range(30):
    result, e_before, e_after = read_part(b's', 1, part)
    if result is None or len(result) == 0:
        print(f"  part {part:2d}: None (end)", flush=True)
        break
    print(f"  part {part:2d}: {result!r} (len={len(result)})", flush=True)

# Test obs=2 which should be empty
print("\nStrL 's' obs=2 (should be empty):", flush=True)
for part in range(3):
    result, _, _ = read_part(b's', 2, part)
    print(f"  part {part}: {result!r}", flush=True)

# Test a strL with different content
print("\nStrL 'longtext':", flush=True)
for part in range(5):
    result, _, _ = read_part(b'longtext', 1, part)
    if result is None or len(result) == 0:
        print(f"  part {part}: None (end)", flush=True)
        break
    print(f"  part {part}: {result!r} (len={len(result)})", flush=True)

# Test larger part sizes
print("\nStrL 'longtext' part 10:", flush=True)
result, _, _ = read_part(b'longtext', 1, 10)
print(f"  part 10: {result!r} (len={len(result) if result else 0})", flush=True)

# Test with a regular string (not strL)
print("\nRegular string 'make' obs=1:", flush=True)
result, _, _ = read_part(b'make', 1, 1)
print(f"  part 1: {result!r} (len={len(result) if result else 0})", flush=True)

print("\nDone", flush=True)
