"""Deep read of the tsmat structure created by _pushstr — 
tsmat[0] is 0x105fc2b80 which might be the string data pointer."""
import sys, ctypes, json
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize, call_string, call_void
from pystata_x.sfi._core import SFIToolkit
import pystata_x.sfi._engine as eng

initialize()
base = eng._BASE
sp_addr = base + 0x39b7000 + 0x108
manifest = json.load(open('src/pystata_x/sfi/manifest.json'))

_restore_sp = eng._restore_sp
pushint = lambda v: eng._pushint_fn(v)
pushstr = lambda s: eng._pushstr_fn(s, len(s))

# Push a string and examine the tsmat carefully
sp_base = ctypes.c_uint64.from_address(sp_addr).value
pushstr(b'make')  # push "make"

sp = ctypes.c_uint64.from_address(sp_addr).value
tsmat = ctypes.c_uint64.from_address(sp).value

print(f"String tsmat for 'make': {hex(tsmat)}", flush=True)
print(f"  Full tsmat dump:", flush=True)
for i in range(0, 64, 8):
    val = ctypes.c_uint64.from_address(tsmat + i).value
    print(f"    +{hex(i):4s}: {hex(val)}", flush=True)
    if i == 0 and val:
        # tsmat[0] could be a data pointer
        print(f"      -> reading tsmat[0] = {hex(val)}:", flush=True)
        for j in range(0, 32, 8):
            inner = ctypes.c_uint64.from_address(val + j).value
            print(f"        [{hex(j):4s}]: {hex(inner)}", flush=True)
        
        # Try reading as string structure
        # For string tsmat: *(char**)tsmat[0] -> [uint32 len][char data]
        inner_ptr = ctypes.c_uint64.from_address(val).value
        if inner_ptr and inner_ptr > 0x100000:
            slen = ctypes.c_uint32.from_address(inner_ptr).value
            print(f"      *(char**)tsmat[0] = {hex(inner_ptr)}, len={slen}", flush=True)
            if slen < 100:
                raw = ctypes.string_at(inner_ptr + 4, slen)
                print(f"      string content: {raw!r}", flush=True)
            else:
                raw8 = ctypes.string_at(inner_ptr + 4, 8)
                print(f"      first 8 bytes of supposed string: {raw8!r}", flush=True)
        elif inner_ptr <= 0x100000:
            # Might be a direct pointer, not double indirection
            print(f"      *(char**)tsmat[0] = {hex(inner_ptr)} (too small for string, try direct read)", flush=True)
            raw4 = ctypes.string_at(val, 16)
            print(f"      raw bytes at tsmat[0]: {raw4!r}", flush=True)
    
    if i == 8 and val:
        print(f"      -> reading tsmat[1] = {hex(val)}:", flush=True)
        if val and val > 0x100000:
            for j in range(0, 32, 8):
                inner = ctypes.c_uint64.from_address(val + j).value
                print(f"        [{hex(j):4s}]: {hex(inner)}", flush=True)

type_val = ctypes.c_int16.from_address(tsmat + 0x34).value
print(f"  type@+0x34: {type_val}", flush=True)

_restore_sp(sp_base)

# Now push a longer string to see differences
print("\n--- Same with 'hello' ---", flush=True)
sp_base = ctypes.c_uint64.from_address(sp_addr).value
pushstr(b'hello world')
sp = ctypes.c_uint64.from_address(sp_addr).value
tsmat = ctypes.c_uint64.from_address(sp).value
print(f"String tsmat for 'hello world': {hex(tsmat)}", flush=True)
for i in range(0, 64, 8):
    val = ctypes.c_uint64.from_address(tsmat + i).value
    print(f"    +{hex(i):4s}: {hex(val)}", flush=True)

tsmat0 = ctypes.c_uint64.from_address(tsmat).value
print(f"  tsmat[0] = {hex(tsmat0)}", flush=True)
if tsmat0 and tsmat0 > 0x100000:
    inner = ctypes.c_uint64.from_address(tsmat0).value
    print(f"  *(tsmat[0]) = {hex(inner)}", flush=True)
    if inner and inner > 0x100000:
        slen = ctypes.c_uint32.from_address(inner).value
        print(f"  len = {slen}", flush=True)
        if slen < 200:
            raw = ctypes.string_at(inner + 4, slen)
            print(f"  content: {raw!r}", flush=True)
    # Also try reading tsmat[0] directly as string
    raw4 = ctypes.string_at(tsmat0, 4)
    print(f"  tsmat[0] raw bytes: {raw4!r}", flush=True)

_restore_sp(sp_base)

print("\nDone", flush=True)
