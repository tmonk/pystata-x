"""Bisect to find which Data call breaks matrix."""
import sys
sys.path.insert(0, '/pystata-x/src')
from pystata_x.sfi._engine import initialize, execute
initialize()
from pystata_x.sfi._core import Data, Matrix

execute("sysuse auto, clear")
execute("matrix mymat = (1,2\\3,4)")

def chk(tag):
    try:
        Matrix.getRowTotal("mymat")
        print(f"  [{tag}] OK", flush=True)
    except:
        print(f"  [{tag}] BROKEN", flush=True)

# Test individual Data calls
print("Testing Data.getVarName...")
for i in range(12): Data.getVarName(i)
chk("getVarName")

print("Testing Data.getVarLabel...")
for i in range(12): Data.getVarLabel(i)
chk("getVarLabel")

print("Testing Data.getVarType...")
for i in range(12): Data.getVarType(i)
chk("getVarType")

print("Testing Data.getVarFormat...")
for i in range(12): Data.getVarFormat(i)
chk("getVarFormat")

print("Testing Data.get (numeric)...")
Data.get(1, 0)  # price obs 0
chk("get(1,0)")

print("Testing Data.get (string)...")
Data.get(0, 0)  # make obs 0
chk("get(0,0)")

print("Testing Data.getVarIndex...")
Data.getVarIndex("price")
chk("getVarIndex")

print("Testing Data.getMaxStrLength...")
Data.getMaxStrLength()
chk("getMaxStrLen")

print("Testing Data.getMaxVars...")
Data.getMaxVars()
chk("getMaxVars")

print("Testing Data.getFormattedValue...")
Data.getFormattedValue(1, 0, False)
chk("getFormatted")
