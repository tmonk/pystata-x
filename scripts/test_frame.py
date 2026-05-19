"""Test Frame functions."""
import sys
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize, call_int, call_string, call_void
from pystata_x.sfi._core import SFIToolkit, Frame

initialize()
SFIToolkit.executeCommand('clear all')
SFIToolkit.executeCommand('sysuse auto, clear')

print("=== Frame Tests ===", flush=True)

# Frame basics
print(f"CWF: {Frame.getCWF()!r}", flush=True)
print(f"Frame count: {Frame.getFrameCount()}", flush=True)
print(f"Frames: {Frame.getFrames()}", flush=True)

# Create a new frame
SFIToolkit.executeCommand('frame create myframe')
print(f"Frames after create: {Frame.getFrames()}", flush=True)
print(f"exists('myframe'): {Frame.exists('myframe')}", flush=True)

# Connect to frame
f = Frame.connect('myframe')
print(f"Connected frame: {f}", flush=True)

# Test _bist_framecur (returns current frame name)
r = call_string("_bist_framecur", b'')
print(f"_bist_framecur: {r!r}", flush=True)

# Test _bist_frame_solve (if it exists)  
# Let me check what _bist_frame_solve expects
import ctypes, json
import pystata_x.sfi._engine as eng
base = eng._BASE
sp_addr = base + 0x39b7000 + 0x108
manifest = json.load(open('src/pystata_x/sfi/manifest.json'))

# Check if _bist_frame_solve is in manifest
fs = manifest["symbols"].get("_bist_frame_solve", 0)
print(f"\n_bist_frame_solve at {hex(fs) if fs else 'NOT FOUND'}", flush=True)

# Frame.getFrames
frames = Frame.getFrames()
print(f"\nAll frames: {frames}", flush=True)

# Test changeToCWF via Stata
SFIToolkit.executeCommand('frame change myframe')
r = call_string("_bist_framecur", b'')
print(f"CWF after change: {r!r}", flush=True)

# Switch back
SFIToolkit.executeCommand('frame change default')
r = call_string("_bist_framecur", b'')
print(f"CWF after back: {r!r}", flush=True)

print("\nDone", flush=True)
