"""Find _bist_putglobal in x86_64 libstata-se.so.

This function is NOT in the dispatch table (no st_putglobal entry).
We find it by:
1. Searching for callers of _bist_global's write path
2. Following call chains from known functions
3. Scanning for specific byte patterns

Usage:
  docker exec pystata-x-persist env STATA_LIB_PATH=/usr/local/stata19/libstata-se.so \\
    python3 scripts/analyze_macro_write.py

Output: Writes findings to scripts/macro_write_findings.json
"""

import json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

def main():
    lib_path = os.environ.get("STATA_LIB_PATH", "/usr/local/stata19/libstata-se.so")
    
    from pystata_x.sfi._analyzer import StataBinary
    from pystata_x.sfi._manifest import _read_elf_sections
    import capstone, ctypes
    
    b = StataBinary(lib_path)
    b._analyze_elf_x86_64()
    b._discover_st_names()
    b._discover_dispatch_table()
    
    findings = {
        "method_1_str_search": None,
        "method_2_callers_of_global": None,
        "method_3_nearby_functions": None,
        "method_4_text_pattern": None,
        "conclusion": None,
    }
    
    de = b.dispatch_entries
    
    # Method 1: Search for string "putglobal" in binary
    for sec_name in ['.rodata', '.data', '.text']:
        try:
            sec = b._elf.sec_of(sec_name)
            raw_section = b._elf.raw_of(sec_name)
            idx = raw_section.find(b'putglobal')
            if idx >= 0:
                findings["method_1_str_search"] = f"Found in {sec_name} at offset 0x{idx:x}, vaddr=0x{sec['addr'] + idx:x}"
                break
        except:
            pass
    
    if findings["method_1_str_search"] is None:
        findings["method_1_str_search"] = "NOT FOUND in any section"
    
    # Method 2: Find all functions that call _bist_global (dispatch[1314])
    # _bist_global address: de[1314]
    global_addr = de[1314]
    
    # Use find_callers from the framework
    try:
        callers = b.find_callers(global_addr)
        findings["method_2_callers_of_global"] = f"Found {len(callers)} callers of _bist_global"
        # Check each caller - look for one that takes 2 string args
        for caller_vaddr, caller_name in callers[:20]:
            findings["method_2_callers_of_global"] += f"\n  caller: 0x{caller_vaddr:x} ({caller_name or 'unnamed'})"
    except Exception as e:
        findings["method_2_callers_of_global"] = f"Error: {e}"
    
    # Method 3: Check functions near _bist_global in the dispatch table
    # _bist_putglobal might be in a secondary table or nearby
    nearby = {}
    for i in range(max(0, 1314-20), min(len(de), 1314+20)):
        if de[i] > 0x810000 and de[i] < 0x900000:  # Reasonable code range
            nearby[i] = hex(de[i])
    findings["method_3_nearby_functions"] = nearby
    
    # Method 4: Find _bist_putglobal by pattern matching ARM64 code
    # On ARM64, _bist_putglobal at 0x1cff60 is ~1104 bytes before _bist_global (0x1d03b0)
    # On x86_64, if _bist_putglobal is proportionally near _bist_global (0x8221ea),
    # it might be at 0x8221ea - 0x450 = 0x821d9a or nearby
    # Check this range
    candidate_range = []
    if global_addr > 0x100000:
        for offset in range(-0x1000, 0x1000, 0x10):
            candidate = global_addr + offset
            if candidate > 0x800000 and candidate < 0x900000:
                candidate_range.append(hex(candidate))
    findings["method_4_nearby_relative"] = {
        "global_addr": hex(global_addr),
        "candidates": candidate_range[:50],  # limit
    }
    
    # Conclusion
    # Use framework's find_string_functions to check if any nearby function calls _pushstr
    try:
        pushstr_addr = b.push_fns.get("_pushstr") or b.push_fns.get("pushstr")
        if pushstr_addr:
            # Find callers of _pushstr near _bist_global
            nearby_callers = []
            for i in range(1314-20, 1314+20):
                if i >= len(de): 
                    continue
                addr = de[i]
                if addr == 0:
                    continue
                try:
                    code_bytes, impl_addr, sections = b._follow_thunk(addr, max_depth=1, include_full=False)
                    # Check if any section has a call to pushstr
                    for level, a, mnem, op in code_bytes:
                        if 'call' in mnem and hex(pushstr_addr)[:8] in op:
                            nearby_callers.append((i, addr, f"dispatch[{i}] calls pushstr"))
                            break
                except:
                    pass
            findings["nearby_pushstr_callers"] = nearby_callers
    except Exception as e:
        findings["nearby_pushstr_error"] = str(e)
    
    # Save to file
    out_path = os.path.join(os.path.dirname(__file__), "macro_write_findings.json")
    with open(out_path, "w") as f:
        json.dump(findings, f, indent=2, default=str)
    print(f"Findings saved to {out_path}")
    print(json.dumps(findings, indent=2, default=str))
    return findings

if __name__ == "__main__":
    main()
