"""Find SIGSEGV point in oracle generator."""
import sys, json, hashlib
sys.path.insert(0, '/pystata-x/src')
from pystata_x.sfi._engine import initialize, execute
initialize()
import pystata_x._stata_fast
pystata_x._stata_fast._bist_configured = False

from pystata_x.sfi._core import Data, Macro, Scalar, ValueLabel, Missing
from pystata_x.sfi._core import Characteristic, Datetime, Frame, Matrix, Platform, SFIToolkit

print("Starting oracle gen...", flush=True)

# Setup
for cmd in [
    "sysuse auto, clear",
    "global testglobal = 42",
    "scalar myscalar = 3.14",
    'scalar mystr = "hello"',
    'label define yesno 0 No 1 Yes',
    "label values foreign yesno",
    "matrix mymat = (1,2\\3,4)",
    "matrix rownames mymat = row1 row2",
    "matrix colnames mymat = col1 col2",
    "char _dta[mychar] hello",
    "frame create testframe",
]:
    out, rc = execute(cmd)
    if rc != 0:
        print(f"  Setup FAILED: {cmd!r}", flush=True)

print("Setup done", flush=True)

# Data
print("Data...", flush=True)
Data.getObsTotal()
print("  nobs OK", flush=True)
Data.getVarCount()
print("  nvar OK", flush=True)
[Data.getVarName(i) for i in range(12)]
print("  names OK", flush=True)
[Data.getVarLabel(i) for i in range(12)]
print("  labels OK", flush=True)
[Data.getVarType(i) for i in range(12)]
print("  types OK", flush=True)
[Data.getVarFormat(i) for i in range(12)]
print("  formats OK", flush=True)
Data.get(1, 0)
print("  get(1,0) OK", flush=True)
Data.get(0, 0)
print("  get(0,0) OK", flush=True)
Data.getMaxVars()
print("  maxvars OK", flush=True)
Data.getFormattedValue(1, 0, False)
print("  formatted OK", flush=True)

print("Data section complete!", flush=True)

# Macro
print("Macro...", flush=True)
Macro.getGlobal("testglobal")
print("  macro testglobal OK", flush=True)

# Scalar
print("Scalar...", flush=True)
Scalar.getValue("myscalar")
print("  scalar OK", flush=True)

# ValueLabel
print("ValueLabel...", flush=True)
ValueLabel.getNames()
print("  vl names OK", flush=True)

# Frame  
print("Frame...", flush=True)
Frame.getFrames()
print("  frames OK", flush=True)

# Matrix
print("Matrix...", flush=True)
print("  names:", Matrix.getNames(), flush=True)
print("  rows:", Matrix.getRowTotal("mymat"), flush=True)
print("  cols:", Matrix.getColTotal("mymat"), flush=True)
print("  rownames:", Matrix.getRowNames("mymat"), flush=True)
print("  colnames:", Matrix.getColNames("mymat"), flush=True)

print("ALL OK!", flush=True)
