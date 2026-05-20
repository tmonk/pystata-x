import os, sys, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
lib = eng._LIB
lib.StataSO_Execute(b"sysuse auto, clear")
print("OK", flush=True)

from pystata_x.sfi._core import Scalar

# System string scalar — c(current_date) returns a date string
s = Scalar.getString("c(current_date)")
print(f"Scalar.getString(c(current_date)) = {s!r}", flush=True)

# Custom string scalar
lib.StataSO_Execute(b'global mystrscalar "hello"')
s = Scalar.getString("mystrscalar")
print(f"Scalar.getString(mystrscalar) = {s!r}", flush=True)
