#!/usr/bin/env python3
"""Debug oracle generator crash."""
import sys
print(f"Python {sys.version}", flush=True)
print(f"sys.path: {sys.path}", flush=True)

sys.path.insert(0, '/pystata-x/src')
print("Importing engine...", flush=True)

from pystata_x.sfi._engine import initialize, execute
print("Engine imported", flush=True)

print("Initializing...", flush=True)
initialize()
print("Initialized", flush=True)

print("Disabling fast path...", flush=True)
import pystata_x._stata_fast
pystata_x._stata_fast._bist_configured = False
print("Fast path disabled", flush=True)

print("Importing SFI classes...", flush=True)
from pystata_x.sfi._core import Data, Macro, Scalar, ValueLabel, Missing, Characteristic, Datetime, Frame, Matrix, Platform, SFIToolkit
print("SFI classes imported", flush=True)

print("Setup...", flush=True)
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
        print(f"  FAILED: {cmd!r} => {out[:100]!r}", flush=True)
print("Setup done", flush=True)

sys.stdout.flush()

print("Data section...", flush=True)
o = {}
o["data"] = {"d1": Data.getObsTotal(), "d2": Data.getVarCount()}
print(f"  Data done", flush=True)

print("Macro section...", flush=True)
o["macro"] = {"m1": Macro.getGlobal("testglobal")}
print(f"  Macro done", flush=True)

print("Scalar section...", flush=True)
o["scalar"] = {"s1": Scalar.getValue("myscalar")}
print(f"  Scalar done", flush=True)

print("ValueLabel section...", flush=True)
o["vl"] = {"v1": ValueLabel.getNames()}
print(f"  VL done", flush=True)

print("Characteristic section...", flush=True)
o["char"] = {"c1": Characteristic.getDtaChar("mychar")}
print(f"  Char done", flush=True)

print("Frame section...", flush=True)
o["frame"] = {"f1": Frame.getFrames()}
print(f"  Frame done", flush=True)

print("Matrix section...", flush=True)
o["matrix"] = {"r1": Matrix.getRowTotal("mymat")}
print(f"  Matrix done", flush=True)

print("ALL DONE!", flush=True)
