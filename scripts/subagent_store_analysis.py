"""
Deep analysis of _bist_store write protocol on x86_64.

Analyzes dispatch[87] (the combined data/store function at 0x826494).
Key questions:
1. Why does the write path reject valid values (rc=3300)?
2. What calling convention does the write path expect?
3. Is there an alternative entry point or raw C function?

Usage:
  docker exec pystata-x-persist env STATA_LIB_PATH=/usr/local/stata19/libstata-se.so \\
    python3 scripts/subagent_store_analysis.py

Output: writes findings to scripts/store_findings.json
"""
import json, os, sys, struct
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pystata_x.sfi._manifest import _read_elf_sections
import capstone

def main():
    lib = os.environ.get("STATA_LIB_PATH", "/usr/local/stata19/libstata-se.so")
    sections, endian, raw = _read_elf_sections(lib)
    text = sections[".text"]
    text_off = text["offset"]
    text_va = text["addr"]
    
    findings = {}
    
    # 1. Analyze the value checker at 0x823241 - what threshold does it use?
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    
    # Read the global threshold used at 0x823298
    # lea rdx, [rip + 0x4838791] at 0x823298
    thresh_addr = 0x823298 + 7 + 0x4838791  # next_instruction + offset
    findings["threshold_global_vaddr"] = hex(thresh_addr)
    
    # Read the raw bytes at that global in .data/.bss
    for sec_name in ['.data', '.bss', '.rodata']:
        sec = sections.get(sec_name)
        if sec and sec['addr'] <= thresh_addr < sec['addr'] + sec['size']:
            off = thresh_addr - sec['addr']
            try:
                val = struct.unpack('<d', raw[sec['offset']+off:sec['offset']+off+8])[0]
                findings[f"threshold_value_{sec_name}"] = val
            except:
                pass
            break
    
    # 2. Check what the second comparison at 0x8232b1 checks
    # lea rax, [rip + 0x4477230] at 0x8232b1
    special_addr = 0x8232b1 + 7 + 0x4477230
    findings["special_value_global_vaddr"] = hex(special_addr)
    
    for sec_name in ['.data', '.bss', '.rodata']:
        sec = sections.get(sec_name)
        if sec and sec['addr'] <= special_addr < sec['addr'] + sec['size']:
            off = special_addr - sec['addr']
            try:
                val = struct.unpack('<d', raw[sec['offset']+off:sec['offset']+off+8])[0]
                findings[f"special_value_{sec_name}"] = val
            except:
                pass
            break
    
    # 3. Full disassembly of the value checker at 0x823241
    findings["value_checker_full"] = _disasm_range(md, raw, text, 0x823241, 300)
    
    # 4. Full disassembly of the store entry at 0x8253ab
    findings["store_impl_full"] = _disasm_range(md, raw, text, 0x8253ab, 500)
    
    # 5. Check if there are alternative store functions
    # Search for functions called with edi=1 or edi=2 pattern near dispatch[87]
    findings["dispatch_87_thunk"] = _disasm_range(md, raw, text, 0x826494, 80)
    
    out = os.path.join(os.path.dirname(__file__), "subagent_store_findings.json")
    with open(out, "w") as f:
        json.dump(findings, f, indent=2, default=str)
    print(json.dumps(findings, indent=2, default=str))
    return findings

def _disasm_range(md, raw, text_sec, start_addr, size):
    rel_off = start_addr - text_sec["addr"]
    code = bytes(raw[text_sec["offset"] + rel_off : text_sec["offset"] + rel_off + size])
    result = []
    for i in md.disasm(code, start_addr):
        result.append(f"0x{i.address:x}: {i.mnemonic} {i.op_str}")
        if len(result) > 300:
            break
    return result

if __name__ == "__main__":
    main()
