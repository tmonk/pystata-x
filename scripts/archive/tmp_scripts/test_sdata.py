import os, sys, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
eng._LIB.StataSO_Execute(b"sysuse auto, clear")

# Test _bist_sdata with push(obs=1, var=1) = make[0]
sp_before = eng._save_sp()
eng._push_int(1)          # obs = 1
eng._push_int(1)          # var = 1 (make)

addr = eng._resolve_name("_bist_sdata")
fn = eng._get_fn(eng._BASE + addr, None, ctypes.c_int)

sys.stdout.flush()
ret = fn(2)
sys.stdout.flush()

sp_after = eng._save_sp()
if sp_after > sp_before:
    tsmat_r = ctypes.c_uint64.from_address(sp_after).value
    if tsmat_r:
        data_ptr = ctypes.c_uint64.from_address(tsmat_r).value
        type_f = ctypes.c_uint16.from_address(tsmat_r + 0x34).value
        print(f"type: 0x{type_f:04x}, data: 0x{data_ptr:x}")
        if type_f == 0 and data_ptr:
            val = ctypes.c_double.from_address(data_ptr).value
            print(f"  double: {val}")
        elif type_f != 0 and data_ptr > 0x100000:
            str_ptr = ctypes.c_uint64.from_address(data_ptr).value
            if str_ptr and str_ptr > 0x100000:
                slen = ctypes.c_uint32.from_address(str_ptr).value
                raw = ctypes.string_at(str_ptr + 4, min(slen, 64))
                print(f"  STRING: {raw!r}")

eng._restore_sp(sp_before)
print("DONE")
sys.stdout.flush()
