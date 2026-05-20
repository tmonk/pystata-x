"""Find what type code _bist_vartype returns for strL variables."""
import sys, ctypes
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize, call_int
from pystata_x.sfi._core import SFIToolkit, Data

initialize()
SFIToolkit.executeCommand('sysuse auto, clear')
SFIToolkit.executeCommand('gen strL s = "hello" if _n == 1')
SFIToolkit.executeCommand('gen strL mys = "world" if _n == 2')
SFIToolkit.executeCommand('gen regular = "test" if _n == 1')
SFIToolkit.executeCommand('encode foreign, gen(foreign2)')

print("=== Variable type codes ===", flush=True)
for v in range(Data.getVarCount()):
    name = Data.getVarName(v)
    typ = call_int("_bist_vartype", v + 1)
    # Also check via Data class
    dtyp = Data.getVarType(v)
    print(f"  var {v}: {name:12s} type={typ} Data.type={dtyp}", flush=True)

print("\nDone", flush=True)
