"""Test if C fast path causes matrix corruption."""
import sys
sys.path.insert(0, '/pystata-x/src')
from pystata_x.sfi._engine import initialize, execute
initialize()
from pystata_x.sfi._engine import _LIB, call_string, call_double
from pystata_x.sfi._core import Data, Matrix

execute("sysuse auto, clear")
execute("matrix mymat = (1,2\\3,4)")

# Disable C fast path
from pystata_x import _stata_fast
print(f"Fast path before: {_stata_fast._bist_configured}", flush=True)
_stata_fast._bist_configured = False
print(f"Fast path after disable: {_stata_fast._bist_configured}", flush=True)

# Now call Data.getVarLabel
for i in range(3):
    lbl = Data.getVarLabel(i)
    print(f"  Data.getVarLabel({i}) = {lbl!r}", flush=True)

# Check matrix
try:
    rows = Matrix.getRowTotal("mymat")
    print(f"  Matrix rows: {rows}", flush=True)
except Exception as e:
    print(f"  MATRIX BROKEN: {e}", flush=True)
