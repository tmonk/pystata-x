"""Test all x86 display-based readers."""
import os, sys
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
lib = eng._LIB
lib.StataSO_Execute(b"sysuse auto, clear")
print("Initialized OK", flush=True)

from pystata_x.sfi._x86_display import (
    read_double, read_string, read_scalar,
    read_string_scalar, get_macro, set_macro, del_macro
)

# 1. Numeric cell read
v = read_double(1, 0)
print(f"read_double(1, 0) = {v}", flush=True)
assert v == 4099.0, f"Expected 4099, got {v}"

# 2. String cell read
s = read_string(0, 0)
print(f"read_string(0, 0) = {s!r}", flush=True)
assert s, f"Expected non-empty string, got {s!r}"

# 3. Numeric scalar via display scalar()
lib.StataSO_Execute(b"scalar mytest = 42.5")
v = read_scalar("mytest")
print(f"read_scalar(mytest) = {v}", flush=True)

# 4. String scalar
lib.StataSO_Execute(b'global mytest_str "hello world"')
s = get_macro("mytest_str")
print(f"get_macro(mytest_str) = {s!r}", flush=True)
assert s == "hello world", f"Expected 'hello world', got {s!r}"

# 5. Set macro
ok = set_macro("e2e_test_global", "test_value")
print(f"set_macro(e2e_test_global, test_value) = {ok}", flush=True)
s = get_macro("e2e_test_global")
print(f"  -> get_macro = {s!r}", flush=True)

# 6. Del macro
ok = del_macro("e2e_test_global")
print(f"del_macro(e2e_test_global) = {ok}", flush=True)
# Note: get_macro will still return the cached value
from pystata_x.sfi._x86_display import clear_cache
clear_cache()
s = get_macro("e2e_test_global") 
print(f"  -> after delete, get_macro = {s!r}", flush=True)

# 7. Scalar operations
lib.StataSO_Execute(b"scalar pi = 3.14159")
v = read_scalar("pi")
print(f"read_scalar(pi) = {v}", flush=True)

# 8. Missing class
from pystata_x.sfi._core import Missing
print(f"Missing.getValue() = {Missing.getValue()}", flush=True)
print(f"Missing.isValueMissing(nan) = {Missing.isValueMissing(float('nan'))}", flush=True)
print(f"Missing.isValueMissing(0) = {Missing.isValueMissing(0.0)}", flush=True)

print("\nALL TESTS PASSED", flush=True)
