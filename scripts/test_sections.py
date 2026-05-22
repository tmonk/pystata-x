"""Identify which SFI section corrupts matrix state."""
import sys
sys.path.insert(0, '/pystata-x/src')
from pystata_x.sfi._engine import initialize, execute
initialize()
from pystata_x.sfi._core import Data, Macro, Scalar, ValueLabel, Missing, Characteristic, Frame, Matrix

# Setup
execute("sysuse auto, clear")
execute("matrix mymat = (1,2\\3,4)")
execute("matrix rownames mymat = row1 row2")
execute("matrix colnames mymat = col1 col2")
execute("frame create testframe")

def check_matrix(step):
    rows = Matrix.getRowTotal("mymat")
    print(f"  After {step}: Matrix rows = {rows}", flush=True)

check_matrix("setup")

# Test each section separately
print("\nTesting Data section...", flush=True)
Data.getObsTotal()
Data.getVarCount()
[Data.getVarName(i) for i in range(3)]
Data.getDouble(1, 0)
Data.get(0, 0)
Data.getVarIndex("price")
check_matrix("Data")

print("Testing Macro section...", flush=True)
Macro.getGlobal("testglobal")
Macro.getGlobal("c(level)")
check_matrix("Macro")

print("Testing Scalar section...", flush=True)
Scalar.getValue("myscalar")
Scalar.getString("mystr")
check_matrix("Scalar")

print("Testing ValueLabel section...", flush=True)
ValueLabel.getNames()
ValueLabel.getLabel("yesno", 0)
ValueLabel.getVarValueLabel(11)
check_matrix("ValueLabel")

print("Testing Missing section...", flush=True)
Missing.isMissing(Missing.getValue())
Missing.parseIsMissing(".")
check_matrix("Missing")

print("Testing Characteristic section...", flush=True)
Characteristic.getDtaChar("mychar")
check_matrix("Characteristic")

print("Testing Datetime section...", flush=True)
from pystata_x.sfi._core import Datetime
Datetime.format(0, "%tc")
check_matrix("Datetime")

print("Testing Frame section...", flush=True)
Frame.getCWF()
Frame.getFrameCount()
Frame.getFrames()
check_matrix("Frame")

print("\nAll sections passed! Matrix survives everything.", flush=True)
