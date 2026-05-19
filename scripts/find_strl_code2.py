"""Find strL type code for _bist_addvar using call_int."""
import sys
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize, call_int
from pystata_x.sfi._core import SFIToolkit, Data

initialize()
SFIToolkit.executeCommand('clear all')
SFIToolkit.executeCommand('sysuse auto, clear')

# Standard codes that work
print("=== Standard type codes ===", flush=True)
for code, name in [('b', 'bytevar'), ('i', 'intvar'), ('l', 'longvar'), 
                     ('f', 'floatvar'), ('d', 'doublevar'), ('s', 'strvar')]:
    SFIToolkit.executeCommand(f'drop _all')
    SFIToolkit.executeCommand('sysuse auto, clear')
    try:
        if code == 's':
            result = call_int("_bist_addvar", name.encode(), ord(code), 10)
        else:
            result = call_int("_bist_addvar", name.encode(), ord(code))
        print(f"  code '{code}': {name} result={result}", flush=True)
    except Exception as e:
        print(f"  code '{code}': ERROR {e}", flush=True)

# Now try strL-specific codes
print("\n=== Testing strL codes ===", flush=True)
for code in ['g', 'G', 'L', 'S', 'h', 'e', 'E', 'w', 'W', 'z', 'Z', 'v', 'V', 'u', 'U']:
    SFIToolkit.executeCommand(f'drop _all')
    SFIToolkit.executeCommand('sysuse auto, clear')
    try:
        result = call_int("_bist_addvar", b'strltest', ord(code))
        # Check if created
        if result is not None and result >= 0:
            typ = Data.getVarType(result)
            print(f"  code '{code}' ({ord(code)}): added at idx={result}, type={typ}", flush=True)
        else:
            print(f"  code '{code}' ({ord(code)}): result={result} (maybe not created, retrying)", flush=True)
    except Exception as e:
        print(f"  code '{code}' ({ord(code)}): ERROR {e}", flush=True)

# Try some numeric codes 
print("\n=== Testing numeric codes ===", flush=True)
for ncode in [-1, 0, 7, 8, 9, 10, 255, 256, 65535]:
    SFIToolkit.executeCommand(f'drop _all')
    SFIToolkit.executeCommand('sysuse auto, clear')
    try:
        result = call_int("_bist_addvar", b'numtest', ncode)
        print(f"  ncode {ncode}: result={result}", flush=True)
    except Exception as e:
        print(f"  ncode {ncode}: ERROR {e}", flush=True)

SFIToolkit.executeCommand('clear all')
print("\nDone", flush=True)
