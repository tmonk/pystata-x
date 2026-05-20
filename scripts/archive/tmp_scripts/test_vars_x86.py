import os, sys
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")
from pystata_x.sfi._core import Data
print("getVarName(0):", repr(Data.getVarName(0)))
print("getVarName(1):", repr(Data.getVarName(1)))
print("getVarType(0):", repr(Data.getVarType(0)))
print("getVarType(1):", repr(Data.getVarType(1)))
print("getVarType(11):", repr(Data.getVarType(11)))
print("DONE")
sys.stdout.flush()
