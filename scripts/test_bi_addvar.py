"""Test _bi_st_addvar (the _bi_st_* variant) for adding strL."""
import sys, ctypes, json
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize, call_int, call_string
from pystata_x.sfi._core import SFIToolkit, Data
import pystata_x.sfi._engine as eng

initialize()
base = eng._BASE
sp_addr = base + 0x39b7000 + 0x108
err_addr = base + 0x39b7000 + 0x11c
manifest = json.load(open('src/pystata_x/sfi/manifest.json'))

_restore_sp = eng._restore_sp
pushstr = lambda v: eng._pushstr_fn(v, len(v))
pushint = lambda v: eng._pushint_fn(v)

SFIToolkit.executeCommand('sysuse auto, clear')

# Try _bi_st_addvar with (name_string, type_char, ?) using string-tsmat convention
fn_addr = base + manifest["symbols"]["_bi_st_addvar"]
fn = ctypes.cast(fn_addr, ctypes.CFUNCTYPE(None, ctypes.c_int))

print(f"Testing _bi_st_addvar at {hex(fn_addr)}", flush=True)

# Try: pushstr(name), pushint(type_code) — the _bi_st_* convention
# Since _bi_st_* first arg must be string tsmat (type=-3)
varname = b'strltest'
sp_base = ctypes.c_uint64.from_address(sp_addr).value
pushstr(varname)   # arg1: name (type=-3 tsmat)
pushint(ord('L'))  # arg2: type code
fn(2)
sp = ctypes.c_uint64.from_address(sp_addr).value
err = ctypes.c_int32.from_address(err_addr).value
# Read result
result_tsmat = ctypes.c_uint64.from_address(sp).value
result_val = None
if result_tsmat and result_tsmat > 0x100000:
    dp = ctypes.c_uint64.from_address(result_tsmat).value
    if dp:
        result_val = ctypes.c_int32.from_address(dp).value
print(f"  code 'L': err={err} result={result_val}", flush=True)
_restore_sp(sp_base)

# Try different codes via call_int for safety
# First, try _bist_addvar directly (the non-_bi_st_ version we know works)
for code in ['d', 's', 'L', 'S', 'g', 'h']:
    SFIToolkit.executeCommand('clear all')
    SFIToolkit.executeCommand('sysuse auto, clear')
    try:
        if code == 's':
            result = call_int("_bist_addvar", b'test', ord(code), 10)
        else:
            result = call_int("_bist_addvar", b'test', ord(code))
        # Check what type was created
        for v in range(Data.getVarCount()):
            if Data.getVarName(v) == 'test':
                typ = Data.getVarType(v)
                print(f"  _bist_addvar code '{code}' ({ord(code)}): var={v} type={typ!r} result={result}", flush=True)
                break
        else:
            print(f"  _bist_addvar code '{code}' ({ord(code)}): not created result={result}", flush=True)
    except Exception as e:
        print(f"  _bist_addvar code '{code}': ERROR {e}", flush=True)

SFIToolkit.executeCommand('clear all')
print("\nDone", flush=True)
