"""Run all sections in oracle order to find the exact failure point."""
import sys
sys.path.insert(0, '/pystata-x/src')
from pystata_x.sfi._engine import initialize, execute
initialize()
from pystata_x.sfi._core import Data, Macro, Scalar, ValueLabel, Missing, Characteristic, Datetime, Frame, Matrix

# Setup
execute("sysuse auto, clear")
execute("global testglobal = 42")
execute("scalar myscalar = 3.14")
execute('scalar mystr = "hello"')
execute('label define yesno 0 No 1 Yes')
execute("label values foreign yesno")
execute("matrix mymat = (1,2\\3,4)")
execute("matrix rownames mymat = row1 row2")
execute("matrix colnames mymat = col1 col2")
execute("char _dta[mychar] hello")
execute("frame create testframe")

def check_matrix(tag):
    try:
        r = Matrix.getRowTotal("mymat")
        print(f"  [{tag}] Matrix OK: rows={r}", flush=True)
    except Exception as e:
        print(f"  [{tag}] MATRIX BROKEN: {e}", flush=True)

check_matrix("setup")

# Data section
print("Data section:", flush=True)
Data.getObsTotal()
Data.getVarCount()
[Data.getVarName(i) for i in range(12)]
[Data.getVarLabel(i) for i in range(12)]
[Data.getVarType(i) for i in range(12)]
[Data.getVarFormat(i) for i in range(12)]
Data.get(1, 0)
Data.get(1, 73)
Data.get(2, 0)
Data.get(0, 0)
Data.get(0, 1)
Data.getVarIndex("price")
Data.isAlias(0)
Data.getMaxStrLength()
Data.getMaxVars()
Data.getFormattedValue(1, 0, False)
check_matrix("after Data")

# Macro section
print("Macro section:", flush=True)
Macro.getGlobal("c(level)")
Macro.getGlobal("testglobal")
Macro.getGlobal("nonexistent_xyz")
check_matrix("after Macro")

# Scalar section
print("Scalar section:", flush=True)
Scalar.getValue("myscalar")
Scalar.getString("mystr")
check_matrix("after Scalar")

# ValueLabel section
print("ValueLabel section:", flush=True)
ValueLabel.getNames()
ValueLabel.getLabel("yesno", 0)
ValueLabel.getLabel("yesno", 1)
ValueLabel.getVarValueLabel(11)
ValueLabel.getLabels("yesno")
ValueLabel.getValues("yesno")
check_matrix("after ValueLabel")

# Missing
print("Missing section:", flush=True)
Missing.isMissing(Missing.getValue())
check_matrix("after Missing")

# Characteristic
print("Characteristic section:", flush=True)
Characteristic.getDtaChar("mychar")
check_matrix("after Characteristic")

# Datetime
print("Datetime section:", flush=True)
Datetime.format(0, "%tc")
check_matrix("after Datetime")

# Frame
print("Frame section:", flush=True)
Frame.getCWF()
Frame.getFrameCount()
Frame.getFrames()
check_matrix("after Frame")

print("\nALL DONE - Matrix survived!", flush=True)
