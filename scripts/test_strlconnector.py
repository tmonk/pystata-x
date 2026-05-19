"""Test the new StrLConnector implementation."""
import sys
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize
from pystata_x.sfi._core import SFIToolkit, Data, StrLConnector

initialize()
SFIToolkit.executeCommand('sysuse auto, clear')
SFIToolkit.executeCommand('gen strL s = "hello world wide web" if _n == 1')

print("=== StrLConnector tests ===", flush=True)

# Create connector using var name
sc = StrLConnector('s', 0)  # var='s', obs=0 (0-based)
print(f"strLConnector: var={sc.var}, obs={sc.obs}, pos={sc.pos}", flush=True)

# Test getSize
size = sc.getSize()
print(f"getSize: {size}", flush=True)

# Test readBytes
r = sc.readBytes(5)
print(f"readBytes(5): {r!r}", flush=True)
print(f"  pos after: {sc.pos}", flush=True)

r2 = sc.readBytes(5)
print(f"readBytes(5) again: {r2!r}", flush=True)
print(f"  pos after: {sc.pos}", flush=True)

# Test reset + read
sc.reset()
r3 = sc.readBytes(11)
print(f"readBytes(11) after reset: {r3!r}", flush=True)

# Test setPosition
sc.setPosition(6)
r4 = sc.readBytes(5)
print(f"readBytes(5) from pos 6: {r4!r}", flush=True)

# Test reading entire string
sc.reset()
r5 = sc.readBytes(100)  # gets entire ~20 bytes
print(f"readBytes(100): {r5!r} (len={len(r5)})", flush=True)

# Test with var index
sc2 = StrLConnector(Data.getVarIndex('s'), 0)
r6 = sc2.readBytes(5)
print(f"\nVia index: readBytes(5): {r6!r}", flush=True)

# Test empty read
r7 = sc2.readBytes(0)
print(f"readBytes(0): {r7!r}", flush=True)

# Test close
sc2.close()
print(f"After close: pos={sc2.pos}", flush=True)

# Test non-strL var
print("\n=== Non-strL test ===", flush=True)
sc3 = StrLConnector('make', 0)
try:
    r8 = sc3.readBytes(5)
    print(f"readBytes on 'make': {r8!r}", flush=True)
except Exception as e:
    print(f"Error: {e}", flush=True)

print("\nDone!", flush=True)
