"""Detailed check: does _bist_addvar actually add variables?"""
import sys
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize, call_int
from pystata_x.sfi._core import SFIToolkit, Data

initialize()
SFIToolkit.executeCommand('clear all')
print("Before: vars =", [Data.getVarName(i) for i in range(Data.getVarCount())], flush=True)

# Add a double
print(f"\nAdding var 'mydouble' with code 'd'...", flush=True)
r = call_int("_bist_addvar", b'mydouble', ord('d'))
print(f"  result: {r}", flush=True)
print(f"  After: vars = {[Data.getVarName(i) for i in range(Data.getVarCount())]}", flush=True)

# Re-init to be safe
SFIToolkit.executeCommand('clear all')
SFIToolkit.executeCommand('sysuse auto, clear')
print(f"\nWith auto loaded: vars = {[Data.getVarName(i) for i in range(Data.getVarCount())]}", flush=True)

# Add
r = call_int("_bist_addvar", b'newdbl', ord('d'))
print(f"  addvar('newdbl', 'd'): result={r}", flush=True)
print(f"  After: vars = {[Data.getVarName(i) for i in range(Data.getVarCount())]}", flush=True)

print(f"\n  Looking for 'newdbl': ", flush=True)
for v in range(Data.getVarCount()):
    n = Data.getVarName(v)
    t = Data.getVarType(v)
    print(f"    var {v}: {n} type={t!r}", flush=True)

# Try str
SFIToolkit.executeCommand('drop newdbl')
r = call_int("_bist_addvar", b'mystr', ord('s'), 10)
print(f"\n  addvar('mystr', 's', 10): result={r}", flush=True)
for v in range(Data.getVarCount()):
    n = Data.getVarName(v)
    t = Data.getVarType(v)
    print(f"    var {v}: {n} type={t!r}", flush=True)

print("\nDone", flush=True)
