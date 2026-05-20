import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

from pystata_x.sfi._engine import call_string, _LIB

# Export all numeric data to a single macro
# Use strofreal to convert each value to string, pipe-separated
# Non-numeric values (strings) will become "."
cmd = b"""
forvalues i = 1/74 {
    forvalues j = 1/12 {
        local val = strofreal(data[`i', `j'], "%20.10g")
        global __px_`j'_`i' = "`val'"
    }
}
"""
ret = _LIB.StataSO_Execute(cmd)
print(f"StataSO_Execute returned: {ret}")

# Read a few values
for obs in [0, 1, 73]:
    macro_name = f"$__px_2_{obs+1}"  # price (var=2, 1-based)
    val = call_string("_bist_macroexpand", macro_name.encode())
    print(f"  price[{obs}] = {val}")

# Read make (var=1, string) - should be "."
val = call_string("_bist_macroexpand", b"$__px_1_1")
print(f"  make[0] = {val}")
