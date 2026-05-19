"""Quick test: strlpart edge cases — non-existent obs, empty strL, binary test."""
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

def strlpart_read(var_name, obs, part):
    sp_base = ctypes.c_uint64.from_address(sp_addr).value
    pushstr(var_name.encode() if isinstance(var_name, str) else var_name)
    pushint(obs + 1)  # 1-based
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
                if slen and slen < 100000:
                    data = ctypes.string_at(str_ptr + 4, slen)
                    if data and data[-1:] == b'\x00':
                        data = data[:-1]
                    result = data
    _restore_sp(sp_base)
    return result

SFIToolkit.executeCommand('sysuse auto, clear')
SFIToolkit.executeCommand('gen strL s = "hello world" if _n == 1')
SFIToolkit.executeCommand('gen strL empty = "" if _n == 2')

# Test: getSize via part=65535 (max unsigned short?)
print("=== getSize() via part=65535 ===", flush=True)
r = strlpart_read(b's', 0, 65535)  # obs=0 (0-based), 1-based internally
print(f"  part=65535: {r!r} (len={len(r) if r else 0})", flush=True)

r = strlpart_read(b's', 0, 100)
print(f"  part=100: {r!r} (len={len(r) if r else 0})", flush=True)

# Test: empty strL
print("\n=== Empty strL ===", flush=True)
r = strlpart_read(b'empty', 1, 10)  # obs=1 (0-based) = obs 2
print(f"  empty@obs2 part=10: {r!r} (len={len(r) if r else 0})", flush=True)

# Test: non-existent obs
r = strlpart_read(b's', 99, 10)  # obs 100 (1-based) — out of range
print(f"  s@obs100 part=10: {r!r}", flush=True)

# Check state
try:
    r = Data.getString(0, 0)  # first var, first obs
    print(f"  State check: {r!r}", flush=True)
except Exception as e:
    print(f"  STATE CORRUPTED: {e}", flush=True)

print("\nDone", flush=True)
