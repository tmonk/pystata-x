"""Find the type code for _bist_addvar to create strL variables."""
import sys, ctypes, json
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize, call_int, call_string, call_void
from pystata_x.sfi._core import SFIToolkit, Data
import pystata_x.sfi._engine as eng

initialize()

SFIToolkit.executeCommand('clear all')
SFIToolkit.executeCommand('sysuse auto, clear')

# Test different type codes for _bist_addvar
# Known: 'b'=byte, 'i'=int, 'l'=long, 'f'=float, 'd'=double, 's'=str(with len)
# Try for strL: various codes
codes_to_try = [
    'g', 'G',  # guess
    'L',       # long string
    'h', 'H',  # huge string?
    'S',       # string long?
    'e', 'E',  # extended?
    '1',       # numeric code 1?
    '2',       # numeric code 2?
    '7',       # numeric code 7?
    '9',       # numeric code 9?
]

base = eng._BASE
_restore_sp = eng._restore_sp
sp_addr = base + 0x39b7000 + 0x108
pushstr = lambda v: eng._pushstr_fn(v, len(v))
pushint = lambda v: eng._pushint_fn(v)

manifest = json.load(open('src/pystata_x/sfi/manifest.json'))
fn_addr = base + manifest["symbols"]["_bist_addvar"]
fn = ctypes.cast(fn_addr, ctypes.CFUNCTYPE(None, ctypes.c_int))

# For each code, try to add a var
for code in codes_to_try:
    SFIToolkit.executeCommand('clear all')
    SFIToolkit.executeCommand('sysuse auto, clear')
    
    varname = f'test_{code}'.encode()
    
    sp_base = ctypes.c_uint64.from_address(sp_addr).value
    pushstr(varname)
    pushint(ord(code))
    if code in ('s',):  
        # str needs a length argument (3rd arg)
        pushint(10)  # fixed length 10
        fn(3)
    else:
        fn(2)  # name + code
    
    sp = ctypes.c_uint64.from_address(sp_addr).value
    # Read result as int
    tsmat = ctypes.c_uint64.from_address(sp).value
    result = None
    if tsmat and tsmat > 0x100000:
        dp = ctypes.c_uint64.from_address(tsmat).value
        if dp and dp > 0x100000:
            result = ctypes.c_int32.from_address(dp).value
    _restore_sp(sp_base)
    
    # Check if added
    added = False
    for v in range(Data.getVarCount()):
        if Data.getVarName(v) == f'test_{code}':
            added = True
            typ = Data.getVarType(v)
            print(f"  code '{code}' ({ord(code)}): added var={v} type={typ} result={result}", flush=True)
            break
    
    if not added:
        print(f"  code '{code}' ({ord(code)}): NOT ADDED result={result}", flush=True)

print("\nDone", flush=True)
