#!/usr/bin/env python3
"""Find _bist_putglobal in x86_64 libstata-se.so via call-graph analysis.

Uses the StataBinary framework exclusively (no ad-hoc scripts).

Strategy:
1. Scan the dispatch implementation of _bist_global (dispatch[1314])
   for all CALL instructions to find functions called in its write path.
2. Scan _bist_macroexpand (dispatch[148]) for all CALL instructions.
3. Cross-reference to find the macro-setting function.
"""

import struct, sys, os, json, capstone
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

CAPSTONE_OK = hasattr(capstone, '__version__')

def find_text_calls(elf_path):
    """Scan entire .text section for CALL instructions to find all call targets."""
    from pystata_x.sfi._manifest import _read_elf_sections
    sections, endian, raw = _read_elf_sections(elf_path)
    text = sections.get('.text')
    if not text:
        return {}
    if not CAPSTONE_OK:
        return {}
    
    text_off = text['offset']
    text_va = text['addr']
    text_sz = text['size']
    code = bytes(raw[text_off:text_off + text_sz])
    
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True  # Need detail for call targets
    
    callers = {}  # target_addr -> [(caller_addr, ...)]
    
    for i in md.disasm(code, text_va):
        if i.mnemonic == 'call':
            # Get the target address
            target = None
            if i.operands and i.operands[0].type == capstone.x86.X86_OP_IMM:
                target = i.operands[0].imm
            elif i.operands and i.operands[0].type == capstone.x86.X86_OP_MEM:
                # Maybe it's a call [rax] etc - skip these for now
                continue
            if target and text_va <= target < text_va + text_sz:
                if target not in callers:
                    callers[target] = []
                callers[target].append(i.address)
    
    return callers

def analyze_function_calls(elf_path, func_addr, depth=1):
    """Get all CALL targets from a specific function."""
    from pystata_x.sfi._manifest import _read_elf_sections
    sections, endian, raw = _read_elf_sections(elf_path)
    text = sections.get('.text')
    if not text:
        return set()
    if not CAPSTONE_OK:
        return set()
    
    text_off = text['offset']
    text_va = text['addr']
    text_sz = text['size']
    
    # Read function bytes (estimate size up to 2000 bytes)
    foff = func_addr - text_va
    if not (0 <= foff < text_sz - 10):
        return set()
    
    code = bytes(raw[text_off + foff:text_off + min(foff + 2000, text_sz)])
    
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    
    calls = set()
    seen_ret = False
    
    for i in md.disasm(code, func_addr):
        if i.mnemonic in ('ret', 'retq'):
            seen_ret = True
            break
        if i.mnemonic == 'call':
            if i.operands and i.operands[0].type == capstone.x86.X86_OP_IMM:
                target = i.operands[0].imm
                calls.add(target)
    
    return calls

def main():
    lib_path = sys.argv[1] if len(sys.argv) > 1 else '/usr/local/stata19/libstata-se.so'
    
    if not os.path.exists(lib_path):
        print(f"Library not found: {lib_path}")
        sys.exit(1)
    
    # Import framework
    from pystata_x.sfi._manifest import _read_elf_sections
    from pystata_x.sfi._analyzer import StataBinary
    
    b = StataBinary(lib_path)
    b._analyze_elf_x86_64()
    b._discover_st_names()
    b._discover_dispatch_table()
    
    de = b.dispatch_entries
    print(f"Dispatch table: {len(de)} entries")
    
    # Get known function addresses
    bist_global_addr = de[1314]  # _bist_global
    bist_macroexpand_addr = de[148] if len(de) > 148 else None  # _bist_macroexpand
    pushstr_addr = b.push_fns.get('pushstr') or b.push_fns.get('_pushstr')
    
    print(f"\nKey function addresses:")
    print(f"  _bist_global (dispatch[1314]): 0x{bist_global_addr:x}")
    print(f"  _bist_macroexpand (dispatch[148]): 0x{bist_macroexpand_addr:x}" if bist_macroexpand_addr else "  _bist_macroexpand: NOT FOUND")
    print(f"  _pushstr: 0x{pushstr_addr:x}" if pushstr_addr else "  _pushstr: NOT FOUND")
    
    # Analyze all call targets from _bist_global read and write paths
    print(f"\n=== Analyzing _bist_global calls ===")
    global_calls = analyze_function_calls(lib_path, bist_global_addr)
    
    # Follow thunk jumps first
    trace = b._follow_thunk(bist_global_addr, max_depth=1)
    impl_addrs = set()
    for level, a, mnem, op in trace:
        if mnem == 'call':
            # Extract target from op_str
            if op.startswith('0x'):
                try:
                    target = int(op.split(',')[0], 16)
                    impl_addrs.add(target)
                except:
                    pass
        impl_addrs.add(a)
    
    print(f"  Instruction count in thunk trace: {len(trace)}")
    print(f"  CALL targets found: {[hex(t) for t in sorted(impl_addrs) if t != bist_global_addr]}")
    
    # Now analyze _bist_macroexpand for its calls
    if bist_macroexpand_addr:
        print(f"\n=== Analyzing _bist_macroexpand calls ===")
        macro_calls = analyze_function_calls(lib_path, bist_macroexpand_addr)
        print(f"  CALL targets: {[hex(t) for t in sorted(macro_calls)]}")
    
    # Also scan ALL dispatch entries for their call targets
    # to find functions that call pushstr but are NOT pushstr
    print(f"\n=== Scanning dispatch implementations ===")
    
    # Read the text section
    sections, endian, raw = _read_elf_sections(lib_path)
    text = sections.get('.text')
    
    if CAPSTONE_OK and text and pushstr_addr:
        # Find all functions that call _pushstr
        pushstr_callers_configs = {}
        text_off = text['offset']
        text_va = text['addr']
        text_sz = text['size']
        code = bytes(raw[text_off:text_off + text_sz])
        
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        md.detail = True
        
        found_funcs = set()
        for i in md.disasm(code, text_va):
            if i.mnemonic == 'call' and i.operands:
                if i.operands[0].type == capstone.x86.X86_OP_IMM:
                    target = i.operands[0].imm
                    if target == pushstr_addr:
                        # Find function start (look backwards for 'push rbp' or 'sub rsp')
                        caller = i.address
                        # Find the function containing this call
                        found_funcs.add(caller)
        
        print(f"  Functions calling _pushstr: {len(found_funcs)}")
        
        # Cross-reference with dispatch entries
        for idx, addr in enumerate(de):
            if addr and addr in found_funcs:
                pass  # This dispatch entry calls _pushstr
    
    # Only search around _bist_global for nearby functions
    # The full .text scan is too slow (~57MB)
    print(f"\n=== Searching for _bist_putglobal pattern near _bist_global ===")
    
    # On ARM64, _bist_putglobal and _bist_global are close together.
    # Let's find functions within 0x2000 bytes of _bist_global
    
    if text:
        text_off = text['offset']
        text_va = text['addr']
        text_sz = text['size']
        code = bytes(raw[text_off:text_off + text_sz])
        
        # Search 0x2000 before to 0x2000 after _bist_global
        search_start = max(text_va, bist_global_addr - 0x2000)
        search_end = min(text_va + text_sz, bist_global_addr + 0x2000)
        search_off = search_start - text_va
        search_sz = search_end - search_start
        code_seg = code[search_off:search_off + search_sz]
        
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        
        # Find function starts without detail mode (faster)
        func_starts = []
        for i in md.disasm(code_seg, search_start):
            if i.address >= search_end:
                break
            if i.mnemonic in ('push', 'endbr64'):
                if i.op_str in ('rbp', 'r12', 'r13', 'r14', 'r15', 'rbx', 'rdi', 'rsi'):
                    func_starts.append(i.address)
            elif i.mnemonic == 'sub' and i.op_str.startswith('rsp,'):
                func_starts.append(i.address)
        
        known_addrs = set(de) | {0}
        unknown_starts = [a for a in func_starts if a not in known_addrs]
        
        # Find functions that are called by _bist_global's write path
        print(f"\n  Searching 0x{search_start:x} to 0x{search_end:x}...")
        print(f"  Found {len(func_starts)} func starts, {len(unknown_starts)} unknown")
        
        if unknown_starts:
            # Analyze the top candidates
            for addr in list(unknown_starts)[:15]:
                off = addr - text_va
                if 0 <= off < text_sz - 60:
                    snippet = code[off:off + 60]
                    instrs = list(md.disasm(snippet, addr))
                    # Check if this function calls _pushstr
                    calls_pushstr = False
                    for i in instrs:
                        if i.mnemonic == 'call':
                            try:
                                target = i.op_str.strip()
                                if target.startswith('0x'):
                                    t = int(target, 16)
                                    if t == (pushstr_addr or 0):
                                        calls_pushstr = True
                            except:
                                pass
                    marker = '[*]' if calls_pushstr else '   '
                    print(f"    {marker} 0x{addr:x}: first instrs = {[(i.mnemonic,i.op_str) for i in instrs[:6]]}")
        
    # Also check: what functions does _bist_global call in its implementation?
    print(f"\n=== _bist_global implementation calls ===")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    
    sections2, endian2, raw2 = _read_elf_sections(lib_path)
    text2 = sections2.get('.text')
    text_va2 = text2['addr']
    text_off2 = text2['offset']
    text_sz2 = text2['size']
    code2 = bytes(raw2[text_off2:text_off2 + text_sz2])
    
    # Scan a small region around _bist_global for CALL instructions
    scan_start = max(0, bist_global_addr - text_va2 - 200)
    scan_end = min(text_sz2, scan_start + 0x2000)
    for i in md.disasm(code2[scan_start:scan_end], text_va2 + scan_start):
        if i.mnemonic == 'call':
            if i.operands and i.operands[0].type == capstone.x86.X86_OP_IMM:
                target = i.operands[0].imm
                if target != pushstr_addr:  # skip _pushstr
                    print(f"    call 0x{target:x} @ 0x{i.address:x}")

if __name__ == '__main__':
    main()
