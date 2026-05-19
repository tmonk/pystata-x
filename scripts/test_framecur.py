"""Test _bist_framecur with different arg patterns."""
import sys, ctypes, json
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize
from pystata_x.sfi._core import SFIToolkit, Frame
import pystata_x.sfi._engine as eng

initialize()
base = eng._BASE
sp_addr = base + 0x39b7000 + 0x108
manifest = json.load(open('src/pystata_x/sfi/manifest.json'))
_restore_sp = eng._restore_sp
pushstr = lambda v: eng._pushstr_fn(v, len(v))
pushint = lambda v: eng._pushint_fn(v)

SFIToolkit.executeCommand('clear all')
SFIToolkit.executeCommand('sysuse auto, clear')

fn_addr = base + manifest["symbols"]["_bist_framecur"]
fn = ctypes.cast(fn_addr, ctypes.CFUNCTYPE(None, ctypes.c_int))

# Try 0 args (might just read from internal state)
print("=== _bist_framecur tests ===", flush=True)
for args in [(), (b'',), (0,)]:
    sp_base = ctypes.c_uint64.from_address(sp_addr).value
    for a in args:
        if isinstance(a, bytes):
            pushstr(a)
        else:
            pushint(a)
    fn(len(args))
    sp = ctypes.c_uint64.from_address(sp_addr).value
    result = None
    tsmat = ctypes.c_uint64.from_address(sp).value
    if tsmat and tsmat > 0x100000:
        gso = ctypes.c_uint64.from_address(tsmat).value
        if gso and gso > 0x100000:
            str_ptr = ctypes.c_uint64.from_address(gso).value
            if str_ptr and str_ptr > 0x100000:
                slen = ctypes.c_uint32.from_address(str_ptr).value
                if slen and slen < 1000:
                    data = ctypes.string_at(str_ptr + 4, slen)
                    if data and data[-1:] == b'\x00':
                        data = data[:-1]
                    result = data
    print(f"  args={args!r}: result={result!r}", flush=True)
    _restore_sp(sp_base)

# Change frame and retry
SFIToolkit.executeCommand('frame create myframe')
SFIToolkit.executeCommand('frame change myframe')

print("\n=== After frame change ===", flush=True)
for args in [(), (b'',), (0,)]:
    sp_base = ctypes.c_uint64.from_address(sp_addr).value
    for a in args:
        if isinstance(a, bytes):
            pushstr(a)
        else:
            pushint(a)
    fn(len(args))
    sp = ctypes.c_uint64.from_address(sp_addr).value
    result = None
    tsmat = ctypes.c_uint64.from_address(sp).value
    if tsmat and tsmat > 0x100000:
        gso = ctypes.c_uint64.from_address(tsmat).value
        if gso and gso > 0x100000:
            str_ptr = ctypes.c_uint64.from_address(gso).value
            if str_ptr and str_ptr > 0x100000:
                slen = ctypes.c_uint32.from_address(str_ptr).value
                if slen and slen < 1000:
                    data = ctypes.string_at(str_ptr + 4, slen)
                    if data and data[-1:] == b'\x00':
                        data = data[:-1]
                    result = data
    print(f"  args={args!r}: result={result!r}", flush=True)
    _restore_sp(sp_base)

SFIToolkit.executeCommand('frame change default')
print("\nDone", flush=True)
