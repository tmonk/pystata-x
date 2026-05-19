"""Systematic test of _bi_st_strlpart buffer behavior.
Push a buffer of size B, call with part=P, see what comes back."""
import sys, ctypes, json
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize
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

def try_strlpart(buffer_str, obs, part):
    """Push buffer, call strlpart, return result."""
    sp_base = ctypes.c_uint64.from_address(sp_addr).value
    pushstr(buffer_str)
    pushint(obs)
    pushint(part)
    fn(3)
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
    return result

print("=== Buffer size vs part value ===\ns = 'hello world wide web' (20 bytes)\n", flush=True)

# Test with variable name as buffer (the working approach)
print("Buffer = var name 's' (1 char):", flush=True)
for part in [1, 5, 10, 20, 50, 100]:
    result = try_strlpart(b's', 1, part)
    print(f"  part={part:3d}: {result!r} (len={len(result) if result else 0})", flush=True)

# Test with exact part-sized buffers
print("\nBuffer = 'X'*buffer_size:", flush=True)
for buf_size in [1, 5, 10, 25, 50, 100, 200, 500]:
    for part in [buf_size, buf_size//2 + 1, buf_size * 2]:
        result = try_strlpart(b'X' * buf_size, 1, part)
        rlen = len(result) if result else 0
        rstr = result[:20] if result else b''
        print(f"  buf={buf_size:3d} part={part:3d}: len={rlen:3d} data={rstr!r}...", flush=True)
        if result is None:
            break

print("\nDone", flush=True)
