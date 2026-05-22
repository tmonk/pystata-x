"""Test _bist_varlabel and matrix state."""
import sys
sys.path.insert(0, '/pystata-x/src')
from pystata_x.sfi._engine import initialize, execute, call_double, call_string
initialize()

execute("sysuse auto, clear")
execute("matrix mymat = (1,2\\3,4)")

# Test _bist_varlabel
for i in range(3):
    lbl = call_string('_bist_varlabel', i+1)  # varno+1 in getVarLabel
    print(f"  _bist_varlabel({i+1}) = {lbl!r}", flush=True)

# Check matrix
from pystata_x.sfi._core import Matrix
try:
    rows = Matrix.getRowTotal("mymat")
    print(f"  Matrix rows after varlabel: {rows}", flush=True)
except Exception as e:
    print(f"  MATRIX BROKEN: {e}", flush=True)

# Now test Data.getVarLabel
from pystata_x.sfi._core import Data
for i in range(3):
    lbl = Data.getVarLabel(i)
    print(f"  Data.getVarLabel({i}) = {lbl!r}", flush=True)

try:
    rows = Matrix.getRowTotal("mymat")
    print(f"  Matrix rows after Data.getVarLabel: {rows}", flush=True)
except Exception as e:
    print(f"  MATRIX BROKEN after Data.getVarLabel: {e}", flush=True)
