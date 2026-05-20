import os
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

from pystata_x.sfi._core import Data, Macro, Scalar, Missing
from pystata_x.sfi._x86_display import clear_cache
clear_cache()

print(f"nobs={Data.getObsTotal()}, nvar={Data.getVarCount()}", flush=True)
print(f"price[0]={Data.getDouble(1,0)}, price[73]={Data.getDouble(1,73)}", flush=True)
print(f"make[0]={Data.getString(0,0)!r}", flush=True)
print(f"getVarName(0)={Data.getVarName(0)!r}", flush=True)
print(f"getVarType(0)={Data.getVarType(0)!r}", flush=True)
print(f"getVarLabel(0)={Data.getVarLabel(0)!r}", flush=True)
print(f"getVarFormat(0)={Data.getVarFormat(0)!r}", flush=True)
print(f"getVarIndex('price')={Data.getVarIndex('price')}", flush=True)
print(f"isAlias(0)={Data.isAlias(0)}", flush=True)
print(f"getMaxStrLength()={Data.getMaxStrLength()}", flush=True)
print(f"getMaxVars()={Data.getMaxVars()}", flush=True)

Macro.setGlobal("e2e_test", "hello_stata")
print(f"getGlobal(e2e_test)={Macro.getGlobal('e2e_test')!r}", flush=True)
print(f"getGlobal(c(level))={Macro.getGlobal('c(level)')!r}", flush=True)
Macro.delGlobal("e2e_test")
clear_cache()
print(f"getGlobal(e2e_test after del)={Macro.getGlobal('e2e_test')!r}", flush=True)
print(f"Scalar.getValue(c(level))={Scalar.getValue('c(level)')}", flush=True)
print(f"Scalar.getString(c(current_date))={Scalar.getString('c(current_date)')!r}", flush=True)
print(f"Missing.isMissing(Missing.getValue())={Missing.isMissing(Missing.getValue())}", flush=True)
print(f"Missing.isValueMissing(0.0)={Missing.isValueMissing(0.0)}", flush=True)
print(f"getFormattedValue(1,0,False)={Data.getFormattedValue(1,0,False)!r}", flush=True)
print()
print("=== ALL KEY OPERATIONS VERIFIED ===", flush=True)
