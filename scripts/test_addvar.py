"""Test _bist_addvar for adding strL variables."""
import sys, ctypes, json
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize, call_int, call_string, call_void
from pystata_x.sfi._core import SFIToolkit, Data
import pystata_x.sfi._engine as eng

initialize()
base = eng._BASE
manifest = json.load(open('src/pystata_x/sfi/manifest.json'))

SFIToolkit.executeCommand('sysuse auto, clear')

# _bist_addvar might take (varname, type_code) — let's see
# First, what types can we use?
print("=== Testing _bist_addvar ===", flush=True)
print(f"_bist_addvar at {hex(manifest['symbols']['_bist_addvar'])}", flush=True)

# Try adding a double variable
try:
    result = call_int("_bist_addvar", b'mynewvar')
    print(f"  addvar('mynewvar'): {result}", flush=True)
except Exception as e:
    print(f"  addvar error: {e}", flush=True)

# List variables
for v in range(Data.getVarCount()):
    name = Data.getVarName(v)
    typ = Data.getVarType(v)
    print(f"  var {v}: {name:12s} type={typ}", flush=True)

# Try adding a strL variable
# Maybe _bist_addvar takes (name, strL_flag?) or just creates a double by default
# Let me check if there's a type parameter

SFIToolkit.executeCommand('drop mynewvar')

# For strL, maybe we need a different approach
# Let's try: addVarStrL via Stata command is "generate strL varname = ..."
SFIToolkit.executeCommand('gen strL teststrl = "abc" if _n == 1')

print("\n=== After gen strL ===", flush=True)
testv = Data.getVarIndex('teststrl')
print(f"  teststrl index: {testv}", flush=True)
if testv is not None:
    typ = Data.getVarType(testv)
    print(f"  teststrl type: {typ}", flush=True)
    is_strl = Data.isVarTypeStrL(testv)
    print(f"  isVarTypeStrL: {is_strl}", flush=True)
    width = Data.getStrVarWidth(testv)
    print(f"  getStrVarWidth: {width}", flush=True)

print("\nDone", flush=True)
