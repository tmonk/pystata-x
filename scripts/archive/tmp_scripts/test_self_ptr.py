import os, ctypes, sys
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
try:
    eng.initialize()
    eng._LIB.StataSO_Execute(b"sysuse auto, clear")
    print("Init OK", flush=True)

    from pystata_x.sfi._engine import _push_int, _save_sp, _STACK_PTR_OFFSET

    _push_int(0)
    _push_int(1)
    print("Push OK", flush=True)

    sp = _save_sp()
    tsmat = ctypes.c_uint64.from_address(sp).value
    print(f"tsmat: 0x{tsmat:x}", flush=True)

    # Self-pointer patch
    ctypes.c_uint64.from_address(tsmat - 0x10).value = tsmat
    print(f"Patched tsmat[-0x10] = 0x{ctypes.c_uint64.from_address(tsmat - 0x10).value:x}", flush=True)
    print(f"Pool tag: 0x{ctypes.c_uint32.from_address(tsmat - 0x94).value:x}", flush=True)

    # Call at +0x48 (push r15 entry)
    base = eng._BASE
    fn_addr = base + eng._SYMS['_bist_data'] + 0x48
    print(f"Calling fn at 0x{fn_addr:x}", flush=True)

    fn = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_int)(fn_addr)
    result = fn(2, 0)
    print(f"Result: {result}", flush=True)

    val = ctypes.c_double.from_address(tsmat).value
    print(f"tsmat[0] = {val}", flush=True)

except Exception as e:
    print(f"Exception: {e}", flush=True)
except BaseException:
    print("SIGSEGV/BaseException", flush=True)
