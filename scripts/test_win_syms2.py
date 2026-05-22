"""Scan PE exports for _bist_ functions using pystata-analyzer."""
import ctypes
import sys

dll_path = r'C:\Program Files\StataNow19\se-64.dll'

# Try direct lookup via kernel32.GetProcAddress
dll_handle = ctypes.WinDLL(dll_path)
kernel32 = ctypes.windll.kernel32

# List of known _bist_ functions from Linux
names = [
    b'_bist_nobs', b'_bist_nvar', b'_bist_data',
    b'_bist_varname', b'_bist_vartype', b'_bist_varlabel',
    b'_bist_varformat', b'_bist_sdata', b'_bist_dir',
    b'_bist_FrameCount', b'_bist_framedir', b'_bist_global',
    b'_bist_numscalar', b'_bist_strscalar', b'_bist_value',
    b'_bist_vlmap', b'_bist_vlload', b'_bist_vlexists',
    b'_bist_macroexpand', b'_bist_MataFcn', b'_bist_MatrixGet',
    b'_bist_MatrixSet', b'_bist_assert', b'_bist_char',
    b'_bist_charval', b'_bist_pref', b'_bist_c',
    b'_bist_lb', b'_bist_cb',
    # Aliases that might be used on Windows
    b'_bist_nobs@8', b'_bist_nvar@8', b'_bist_data@16',
    b'__bist_nobs', b'__bist_nvar', b'__bist_data',
    b'__bist_varname',
    # StataSO functions
    b'StataSO_Main', b'StataSO_Execute',
]

print(f'Trying {len(names)} names via GetProcAddress...')
for name in sorted(set(names)):
    try:
        addr = kernel32.GetProcAddress(ctypes.c_void_p(dll_handle._handle), name)
        if addr:
            print(f'  FOUND: {name.decode(errors="replace")} @ {addr:#018x}')
    except:
        pass

print()

# Try using pystata-analyzer
sys.path.insert(0, r'C:\Users\tom\projects\pystata-x\src')
try:
    from pystata_analyzer import binary
    print('Using pystata-analyzer to read PE symbols...')
    
    # Use the analyze_binary function
    result = binary.analyze_binary(dll_path)
    if result:
        pe_info = result.get('pe_info', result)
        exports = pe_info.get('exports', [])
        bist_exports = [e for e in exports if '_bist_' in e.get('name', '')]
        print(f'Found {len(bist_exports)} _bist_ exports via analyzer:')
        for e in bist_exports[:30]:
            print(f'  {e["name"]} @ 0x{e["address"]:x}')
        if len(bist_exports) > 30:
            print(f'  ... and {len(bist_exports) - 30} more')
except Exception as e:
    print(f'pystata-analyzer failed: {e}')
    import traceback
    traceback.print_exc()
