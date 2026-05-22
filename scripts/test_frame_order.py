"""Test Frame operations in order, check if getCWF causes issues."""
import sys
sys.path.insert(0, '/pystata-x/src')
from pystata_x.sfi._engine import initialize, execute, call_double
initialize()
from pystata_x.sfi._engine import _LIB, call_string
from pystata_x.sfi._core import Frame

# Setup
execute("sysuse auto, clear")
execute("matrix mymat = (1,2\\3,4)")
execute("matrix rownames mymat = row1 row2")
execute("matrix colnames mymat = col1 col2")
execute("frame create testframe")

# Test getCWF
print("Testing Frame.getCWF()...", flush=True)
try:
    cwf = Frame.getCWF()
    print(f"  getCWF = {cwf!r}", flush=True)
except Exception as e:
    print(f"  getCWF error: {type(e).__name__}: {e}", flush=True)
    import traceback
    traceback.print_exc()

# Check matrix still exists
from pystata_x.sfi._core import Matrix
try:
    rows = Matrix.getRowTotal("mymat")
    print(f"  After getCWF: Matrix rows = {rows}", flush=True)
except Exception as e:
    print(f"  Matrix error after getCWF: {e}", flush=True)

# Test getFrames
print("Testing Frame.getFrames()...", flush=True)
try:
    frames = Frame.getFrames()
    print(f"  getFrames = {frames!r}", flush=True)
except Exception as e:
    print(f"  getFrames error: {e}", flush=True)

# Check matrix again
try:
    rows = Matrix.getRowTotal("mymat")
    print(f"  After getFrames: Matrix rows = {rows}", flush=True)
except Exception as e:
    print(f"  Matrix error after getFrames: {e}", flush=True)
