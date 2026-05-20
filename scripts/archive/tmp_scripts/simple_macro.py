import os, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

from pystata_x.sfi._engine import call_string, _LIB

# Try simpler approach: read one value at a time
ret = _LIB.StataSO_Execute(b'global __px_test = strofreal(price[1])')
print(f"Return: {ret}")

val = call_string("_bist_macroexpand", b"$__px_test")
print(f"price[1] = {val!r}")

# Try with data() function
ret = _LIB.StataSO_Execute(b'global __px_test2 = strofreal(data[1, 2])')
print(f"\nReturn (data): {ret}")

val2 = call_string("_bist_macroexpand", b"$__px_test2")
print(f"data[1,2] = {val2!r}")

# Try just global macro set with literal
ret = _LIB.StataSO_Execute(b'global __px_test3 = "hello123"')
print(f"\nReturn (literal): {ret}")

val3 = call_string("_bist_macroexpand", b"$__px_test3")
print(f"literal = {val3!r}")

# Try display to see if strofreal works
ret = _LIB.StataSO_Execute(b'display strofreal(price[1])')
print(f"\nReturn (display): {ret}")
