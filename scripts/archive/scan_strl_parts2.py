"""Test _bi_st_strlpart with small part values to understand the numbering."""
import sys, ctypes, json
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize
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
    sp_base = ctypes.c_uint64.from_address(sp_addr).value
    pushstr(var_name)
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
                if slen and slen < 100000:
                    data = ctypes.string_at(str_ptr + 4, slen)
                    if data and data[-1:] == b'\x00':
                        data = data[:-1]
                    result = data
    _restore_sp(sp_base)
    return result

SFIToolkit.executeCommand('sysuse auto, clear')
SFIToolkit.executeCommand('gen strL s = "hello world wide web" if _n == 1')

print("=== fine-grained part scan for 's' ===", flush=True)
for part in range(1, 31):
    result = read_part(b's', 1, part)
    if result is None:
        print(f"  part {part:2d}: None", flush=True)
    else:
        print(f"  part {part:2d}: {result!r} (len={len(result)})", flush=True)

print("\n=== possible 'part' = 'offset+1' vs 'length' ===", flush=True)
# If part=1 means offset=0,len=1: part=1→'h', part=2→'he'? No that doesn't match
# If part=N means read N bytes: part=1→'h', part=2→'he', part=3→'hel'...
# Let's test this theory
for offset in [0, 1, 2, 5, 10, 20]:
    result = read_part(b's', 1, offset)
    if result:
        expected = "hello world wide web"[:offset]
        print(f"  part {offset:2d}: {result!r} (expect {expected!r}) match={result.decode()==expected}", flush=True)

print("\n=== test with longtext part=1 vs part=5 ===", flush=True)
for part in [1, 3, 5, 10, 15]:
    result = read_part(b'longtext', 1, part)
    if result:
        expected = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*()"[:part]
        print(f"  part {part:2d}: {result!r} match_first_{part}={result.decode()==expected}", flush=True)

print("\nDone", flush=True)
