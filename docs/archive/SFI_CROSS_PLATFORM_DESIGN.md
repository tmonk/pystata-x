# SFI Cross-Platform Implementation Design

**Date**: 2026-05-22
**Scope**: Complete SFI implementation on x86_64 Linux (Docker) and x86_64 Windows (SSH)
**Status**: Step 1 design document — pre-implementation

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Current State Assessment](#2-current-state-assessment)
3. [Linux (Docker) Strategy](#3-linux-docker-strategy)
4. [Windows (SSH) Strategy](#4-windows-ssh-strategy)
5. [Environment Sync Workflow](#5-environment-sync-workflow)
6. [Framework Extension Plan](#6-framework-extension-plan)
7. [Framework Introspection Protocol](#7-framework-introspection-protocol)
8. [Per-Platform Manifest System](#8-per-platform-manifest-system)
9. [Oracle Update & Reconciliation](#9-oracle-update--reconciliation)
10. [SFI Class/Method Inventory](#10-sfi-classmethod-inventory)
11. [Implementation Order & Dependencies](#11-implementation-order--dependencies)
12. [Risk Register](#12-risk-register)

---

## 1. Architecture Overview

### Current Five-Layer Stack

```
┌─────────────────────────────────────────────┐
│  Layer 5: pystata_x.sfi._core.py            │  ← Public API classes
├─────────────────────────────────────────────┤
│  Layer 4: pystata_x._stata_fast.py           │  ← Python ctypes bridge to C fast path
├─────────────────────────────────────────────┤
│  Layer 3: libstata_fast.{so,dll}             │  ← C shared library
├─────────────────────────────────────────────┤
│  Layer 2: pystata_x.sfi._engine.py           │  ← Low-level ctypes bridge
├─────────────────────────────────────────────┤
│  Layer 1: pystata_x.sfi._manifest.py          │  ← Symbol discovery & manifest mgmt
├─────────────────────────────────────────────┤
│  Framework: pystata-analyzer/                 │  ← Disassembly & protocol analysis
└─────────────────────────────────────────────┘
```

### Target Architecture (Post-Implementation)

Same five-layer stack, but with:
- **Platform Strategy Pattern** replacing scattered `_IS_X86_64` branches
- **Per-platform manifests** (Linux ELF + Windows PE) tracked in version control
- **Extended framework** with memory-layout discovery and manifest diff tooling
- **C fast path** covering all feasible `_bist_*` dispatch functions
- **Unified oracle test harness** that runs on both platforms

```
┌──────────────────────────────────────────────────┐
│  _core.py  (platform-agnostic API layer)          │
│    └─ platform_strategy.py                        │
│       ├─ LinuxX86Strategy()                       │
│       └─ WindowsX86Strategy()                     │
├──────────────────────────────────────────────────┤
│  _engine.py  (push+stack protocol, platform-      │
│               specific offsets from manifest)      │
├──────────────────────────────────────────────────┤
│  _manifest.py  (auto-discover, cache, diff)       │
│    ├─ manifests/manifest-linux-{sha256}.json       │
│    └─ manifests/manifest-win-{sha256}.json         │
├──────────────────────────────────────────────────┤
│  pystata-analyzer/  (extended)                    │
│    ├─ analyze_memory_layout()                     │
│    ├─ generate_manifest()                         │
│    └─ diff_manifests()                            │
└──────────────────────────────────────────────────┘
```

---

## 2. Current State Assessment

### What Works on ARM64 macOS

| Class | Status | Notes |
|-------|--------|-------|
| Data | ✅ Full | All ~42 implemented methods working |
| Macro | ✅ Full | All 5 methods |
| Scalar | ✅ Full | All 4 methods |
| ValueLabel | ✅ Full | All ~20 methods |
| Missing | ✅ Full | Pure Python |
| SFIToolkit | ✅ Full | execute()-based |
| StrLConnector | ✅ Read-only | write/allocate NotImplementedError |

### What Works on x86_64 Linux

| Class | Status | Notes |
|-------|--------|-------|
| Data.getObsTotal | ✅ | call_double("_bist_nobs") |
| Data.getVarCount | ✅ | call_double("_bist_nvar") |
| Data.getDouble | ✅ | call_double("_bist_data") |
| Data.getVarLabel | ✅ | call_string("_bist_varlabel") |
| Data.getVarName | 🟡 | Direct memory read (hardcoded offset) |
| Data.getVarType | 🟡 | Direct memory read (hardcoded offset) |
| Data.getVarFormat | 🔴 | Hardcoded auto formats (fails on non-auto) |
| Data.getMaxVars | 🔴 | Hardcoded 32767 |
| Data.storeDouble | 🟡 | execute() fallback |
| Data.storeString | 🟡 | execute() fallback |
| Scalar.getValue | 🟡 | Hybrid execute+read |
| Scalar.getString | 🔴 | Returns "" |
| Scalar.setValue | 🟡 | execute() |
| Scalar.setString | 🟡 | execute() |
| Macro.getGlobal | 🔴 | Echoes input |
| Macro.setGlobal | 🟡 | execute() |
| ValueLabel.* | 🔴 | All echo/crash |
| Frame | ❌ | Not implemented |
| Matrix | ❌ | Not implemented |
| Mata | ❌ | Not implemented |
| Characteristic | ❌ | Not implemented |
| Datetime | ❌ | Not implemented |
| Platform | ❌ | Not implemented |
| Preference | ❌ | Not implemented |

### x86_64 Dispatch Function Status

**Works (correct data):**
`_bist_nobs`, `_bist_nvar`, `_bist_data`, `_bist_varlabel`, `_bist_store`, `_bist_sstore`, `_bist_putglobal`

**Safe but echoes (no crash, wrong data):**
`_bist_varname`, `_bist_sdata`, `_bist_numscalar`, `_bist_strscalar`, `_bist_macroexpand`, `_bist_global`, `_bist_vlexists`, `_bist_vlmap`, `_bist_vlsearch`, `_bist_vldrop`, `_bist_vllabel`, `_bist_dir`, `_bist_varformat`, `_bist_varvaluelabel`, `_bist_varindex`, `_bist_isstrvar`, `_bist_isnumvar`, `_bist_isalias`

**Never worked / no dispatch:**
`_bist_vartype` (echo), `_bist_framedir`, `_bist_frameexists`, `_bist_framecreate`, `_bist_framedrop`, `_bist_framerename`, `_bist_framecopy`, `_bist_framechange`, `_bist_framecurrent`, `_bist_matrix_hcat`, `_bist_matrix`, `_bist_replacematrix`, etc.

### x86_64 Root Causes

The echo problem on x86_64 dispatch functions stems from:
1. **Identity stubs**: Many dispatch entries are wrappers that return their input unchanged — the real computation happens in Stata's expression evaluator
2. **Pool-header checks**: Functions check `tsmat[-0x94] == 0x2b` — the self-pointer patch (`_patch_last_tsmat()`) fixes this for pool-allocated tsmats
3. **ARG_PTR vs SP_global confusion**: Already resolved — `_save_sp()` reads from ARG_PTR (`_BASE + 0x500C6A0`)
4. **String storage location**: String scalars and value labels are stored in Stata's internal hash tables, not at dispatch-level memory locations

### Windows x86_64 Status

- StataNow19 at `C:\Program Files\StataNow19\`
- Library: `libstata-se.dll` (PE format)
- PE symbol discovery: Partial (exports only, no COFF symbols yet)
- Push+stack dispatch: Untested
- oracle.json: Does not exist for Windows
- Framework analysis: PE scanner exists but incomplete

---

## 3. Linux (Docker) Strategy

### Environment

```
Docker Desktop (macOS host, Rosetta 2)
  └── pystata-x-persist container (linux/amd64)
       ├── Stata 19 Linux: /usr/local/stata19/
       │   └── libstata-se.so (ELF64, x86_64)
       ├── Source: /pystata-x/ (bind mount from host)
       │   └── Live code changes reflected immediately
       ├── Python: /venv/ (editable install)
       └── Tests: via docker exec
```

### Commands

```bash
# Build (one-time)
docker build -f Dockerfile.amd64 -t pystata-x-linux .

# Create persistent container (one-time)
docker create --name pystata-x-persist \
  -v "$(pwd):/pystata-x" \
  -v "$(pwd)/stata19-linux:/usr/local/stata19" \
  pystata-x-linux \
  /pystata-x/docker-entrypoint.sh

# Start
docker start pystata-x-persist
sleep 2

# Run tests
docker exec pystata-x-persist /pystata-x/docker-entrypoint.sh unit     # unit tests
docker exec pystata-x-persist /pystata-x/docker-entrypoint.sh e2e      # e2e (requires Stata)
docker exec pystata-x-persist /pystata-x/docker-entrypoint.sh framework # analyzer tests
docker exec pystata-x-persist /pystata-x/docker-entrypoint.sh all      # everything

# Framework analysis
docker exec pystata-x-persist /pystata-x/docker-entrypoint.sh analyze _bist_data
docker exec pystata-x-persist /pystata-x/docker-entrypoint.sh catalog

# Interactive shell
docker exec -it pystata-x-persist /pystata-x/docker-entrypoint.sh shell

# Rebuild (after changing deps)
docker build -f Dockerfile.amd64 -t pystata-x-linux .
docker rm pystata-x-persist
docker create ... # as above
```

### Implementation Steps (Linux)

1. **Framework: Extend memory-layout discovery**
   - Add `analyze_memory_layout()` to `StataBinary` — traces each echo function's code to find `.bss`/heap references
   - Add hash-table tracing for scalar, macro, and value-label storage
   - Add per-platform manifest generation (`generate_manifest()`)
   - Add manifest diff tool (`diff_manifests()`)

2. **Framework: Extend PE support** (initially tested on ELF, later ported)
   - Complete `_read_pe_syms()` for COFF symbol table scanning
   - Add `_scan_pe_dispatch_table()` (analogous to `_scan_elf_dispatch_table()`)
   - Add PE `.reloc` section parsing

3. **Fix echo dispatch functions via framework memory discovery**
   - For each echo function, disassemble to find `.bss`/heap references
   - Create direct memory readers (like `_read_var_name_x86()` but for all types)
   - Store discovered offsets in manifest under `memory_offsets` key

4. **Replace hardcoded offsets with manifest-discovered**
   - Replaces `0x832997 + 0x4469071` (var name table), `0x823d5b + 0x4477ca5` (var type), etc.

5. **Implement missing SFI classes**
   - Frame (via _bist_frame* dispatch calls — should work)
   - Matrix (via execute(), no _bist_matrix* for user matrices)
   - Mata (via execute())
   - Characteristic (via execute())
   - Datetime (pure Python)
   - Platform (pure Python)
   - Preference (via execute())

6. **Platform strategy pattern**
   - Create `PlatformStrategy` base class with `LinuxX86Strategy`, `WindowsX86Strategy`, `ARM64Strategy`
   - Register at init time based on platform detection
   - Replace all `_IS_X86_64` branches

7. **Expand C fast path (libstata_fast)**
   - Add remaining slot IDs in `stata_fast.h`
   - Add C wrappers for all `_bist_*` functions
   - Ensure x86_64 patches (type tag, self-pointer) cover all functions

---

## 4. Windows (SSH) Strategy

### Environment

```
macOS host
  └── SSH: thomasmonkae28.ojos-tritone.ts.net
       └── Windows Server / Windows 10+
            └── StataNow19: C:\Program Files\StataNow19\
                 ├── libstata-se.dll (PE, x86_64)
                 └── utilities\pystata\config.py
```

### Approach

Windows implementation is **sequential after Linux** because:
1. Both use x86_64 architecture (same calling convention fundamentals)
2. Linux work establishes the memory-discovery patterns
3. PE format is structurally different from ELF (COFF symbols vs ELF sections)
4. Microsoft x64 ABI differs from SysV ABI (rcx/rsp vs rdi/rsi)
5. SSH access allows remote testing but complicates debugging

### Sync Workflow

```bash
# After Linux work is committed and tested:
# Option A: rsync via SSH
rsync -avz --exclude='.git' --exclude='stata19-linux' \
  /Users/tom/projects/pystata-x/ \
  thomasmonkae28.ojos-tritone.ts.net:/path/to/pystata-x/

# Option B: git pull on Windows
ssh thomasmonkae28.ojos-tritone.ts.net "cd pystata-x && git pull"

# Run framework analysis on Windows
ssh thomasmonkae28.ojos-tritone.ts.net \
  "cd pystata-x && python -m pystata_analyzer \
  'C:\Program Files\StataNow19\libstata-se.dll' --manifest"

# Generate Windows oracle
ssh thomasmonkae28.ojos-tritone.ts.net \
  "cd pystata-x && python scripts/gen_oracle.py"

# Run tests
ssh thomasmonkae28.ojos-tritone.ts.net \
  "cd pystata-x && python -m pytest tests/ -v"
```

### Windows-Specific Challenges

1. **PE format**: COFF symbol table is often stripped; need `.reloc` parsing
2. **Calling convention**: Microsoft x64 ABI — push function args in rcx/rdx/r8/r9 (not rdi/rsi/rdx)
3. **Base address**: DLLs use ASLR — `_BASE` must come from `GetModuleHandle` and `GetProcAddress`
4. **Stata library name**: `libstata-se.dll` (not `StataSE-64.dll`)
5. **Process memory**: No `/proc/self/mem` — need `ReadProcessMemory` or ctypes `memmove` from known offsets
6. **Python env**: May need to install pystata-x dependencies + capstone on Windows

### Windows Implementation Steps

1. **Set up Windows environment**
   - rsync/git clone pystata-x to Windows
   - Install Python + dependencies (pip install -e .)
   - Install capstone for framework analysis
   - Verify Stata loads via ctypes

2. **Complete PE symbol discovery**
   - Extend `_manifest.py:_read_pe_syms()` for COFF symbol table
   - Add `_scan_pe_dispatch_table()` using `.reloc` section
   - Test against `libstata-se.dll`

3. **Run framework analysis**
   - `docker exec`-style analysis via SSH
   - Generate Windows manifest with discovered offsets

4. **Generate Windows oracle**
   - Run `gen_oracle.py` on Windows (requires Stata's embedded Python)
   - Save as `tests/e2e/oracle-windows.json`

5. **Adapt push+stack protocol**
   - Microsoft x64 ABI: push function args via rcx, rdx, r8, r9 (not rdi, rsi)
   - Update ctypes CFUNCTYPE signatures
   - Test `call_double`/`call_string` on known-working functions (nobs, nvar)

6. **Fix Windows-specific dispatch issues**
   - Apply the same memory-discovery patterns from Linux
   - Handle PE-specific memory layout differences

7. **Get all tests passing**

---

## 5. Environment Sync Workflow

### Code Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    macOS Development Host                        │
│  ┌─────────────────────┐   ┌──────────────────────────────────┐ │
│  │  Editor (VS Code)    │   │  Git Repository                  │ │
│  │  Edit source files   │──▶│  /Users/tom/projects/pystata-x/ │ │
│  └─────────────────────┘   └──────────┬───────────────────────┘ │
│                                       │                          │
│                        bind mount     │  rsync / git push        │
│                        (live)         │  (after commit)          │
│                        ▼              ▼                          │
│  ┌──────────────────────────┐  ┌──────────────────────────────┐ │
│  │ Docker: pystata-x-persist│  │ SSH: thomasmonkae28...       │ │
│  │ /pystata-x/ (live edit)  │  │ /path/to/pystata-x/         │ │
│  │ /usr/local/stata19/      │  │ C:\Program Files\StataNow19\│ │
│  └──────────────────────────┘  └──────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### Sync Protocol

**Phase 1 (Development):**
- Edit source on macOS host
- Changes are live in Docker via bind mount (no sync needed)
- Run tests in Docker immediately

**Phase 2 (Commit):**
1. `docker exec pystata-x-persist ... all` — all tests pass in Linux Docker
2. `git commit` + `git push`
3. Oracle comparison passes on Linux

**Phase 3 (Windows sync):**
1. `ssh thomasmonkae28... "cd pystata-x && git pull"` (or rsync)
2. Run `pystata-analyzer` on Windows DLL to regenerate PE manifest
3. Generate Windows oracle: `python scripts/gen_oracle.py`
4. Run all tests on Windows
5. If failures, diagnose platform-specific issues
6. Commit fixes, loop back to Phase 1

**Phase 4 (Cross-platform verification):**
1. Linux manifest vs Windows manifest diff — zero unexpected differences
2. Both platform oracles cover same methods
3. All tests pass on both platforms

### Preventing Drift

The framework's **manifest diff** is the single source of truth:

```bash
# Generate both manifests
docker exec pystata-x-persist python -c "
from pystata_analyzer import StataBinary
b = StataBinary('/usr/local/stata19/libstata-se.so')
b.analyze()
b.generate_manifest('manifests/manifest-linux.json')
"

ssh thomasmonkae28... "cd pystata-x && python -c "
from pystata_analyzer import StataBinary
b = StataBinary('C:\\Program Files\\StataNow19\\libstata-se.dll')
b.analyze()
b.generate_manifest('manifests/manifest-win.json')
"

# Diff
python -c "
from pystata_analyzer import diff_manifests
diff = diff_manifests('manifests/manifest-linux.json', 'manifests/manifest-win.json')
print(diff)
"
```

Any diff in the expected symbol set, stack pointer offset, or memory layout is flagged. Code that would cause drift (e.g., Linux-only hardcoded offset that doesn't exist on Windows) is caught.

---

## 6. Framework Extension Plan

### Current Framework Capabilities

| Capability | Status | Location |
|------------|--------|----------|
| ELF64 loader | ✅ | `elf.py` — pure ctypes section reader |
| Dispatch-table scanner | ✅ | `binary.py:_scan_dispatch_table()` |
| st_* name table parser | ✅ | `binary.py:_read_name_table()` |
| Push function discovery | ✅ | `binary.py:find_push_functions()` |
| Protocol analysis | ✅ | `binary.py:analyze_full_protocol()` |
| ARG_PTR read detection | ✅ | `binary.py:_trace_arg_ptr_reads()` |
| Error code extraction | ✅ | `binary.py:trace_error_codes()` |
| CrashSafeProtocolTester | ✅ | `live_protocol.py` |
| Plugin system | ✅ | `plugin.py` + `framework.py` |
| Manifest generation | ✅ | Framework `.generate_report()` — verbose, not compact |
| Registry | ✅ | `registry.py` |

### Needed Extensions

#### 1. `analyze_memory_layout()` — Memory Map Discovery

**Purpose**: For each echo dispatch function, find what memory location it reads from (the hash table or .bss variable it's supposed to access).

**How it works**:
```python
def analyze_memory_layout(self) -> dict:
    """Analyze all echo functions to discover internal memory locations.
    
    Returns:
        {
            "scalar_table": vaddr or None,
            "macro_table": vaddr or None,
            "valuelabel_table": vaddr or None,
            "var_name_table": vaddr or None,
            "var_type_table": vaddr or None,
            "var_format_table": vaddr or None,
            "c_maxvar": vaddr or None,
        }
    """
```

**Method**: For each function that echoes:
1. Disassemble its code with Capstone
2. Look for RIP-relative addressing patterns (`lea reg, [rip + offset]`)
3. Resolve the target address (base + offset from RIP)
4. Cross-reference: if multiple echo functions reference the same table, confirm it
5. For hash tables, trace the hash function call to find the backing storage

#### 2. `generate_manifest()` — Compact Per-Platform Manifest

**Purpose**: Generate the runtime manifest (`manifest.json`) from framework analysis, compact enough for shipping.

```python
def generate_manifest(self, output_path: str) -> dict:
    """Generate a compact per-platform manifest.
    
    Output format:
    {
        "version": 3,
        "platform": "linux" | "windows" | "darwin",
        "arch": "x86_64" | "arm64",
        "sha256": "...",
        "symbols": {"_bist_data": 0x1234, ...},
        "data_offsets": {
            "stack_ptr_delta": 0x500C6A0,
            "err_addr_delta": 0x500C6B0,
        },
        "memory_offsets": {
            "var_name_table": 0x1234000,
            "var_name_stride": 96,
            "var_type_table": 0x1235000,
            "var_type_stride": 2,
            "max_vars_addr": 0x1236000,
        },
        "push_functions": {
            "_pushint": 0x..., "_pushdbl": 0x..., "_pushstr": 0x...
        },
        "dispatch_table": {
            "vaddr": 0x440aac0,
            "count": 1686
        }
    }
    """
```

#### 3. `diff_manifests()` — Cross-Platform Drift Detection

```python
def diff_manifests(m1_path: str, m2_path: str) -> dict:
    """Compare two manifests and report differences.
    
    Returns:
    {
        "same_symbols": {"_bist_data": {"linux": 0x1234, "windows": 0x5678}},
        "linux_only": ["_bist_linux_only_fn"],
        "windows_only": ["_bist_windows_only_fn"],
        "offset_diffs": [
            {"field": "stack_ptr_delta", "linux": "0x500C6A0", "windows": "0x600C6A0"},
        ],
        "compatible": True|False  # False if structural differences
    }
    """
```

#### 4. PE Support in Binary Scanner

Extend `binary.py` (or add `pe_reader.py`) with:
- `_read_pe_syms()` — read COFF symbol table section
- `_scan_pe_dispatch_table()` — scan `.reloc` section for function pointer arrays
- `_read_pe_name_table()` — parse `st_*` name strings in `.rdata` or `.data`
- `_find_pe_push_functions()` — discover push function vaddrs

#### 5. Live Memory Probing (Windows)

On Windows there's no `/proc/self/mem`. Instead:
```python
# Read process memory via ctypes
def read_process_memory(addr: int, size: int) -> bytes:
    """Read memory from the current process at addr."""
    buf = ctypes.create_string_buffer(size)
    ctypes.memmove(buf, ctypes.c_void_p(addr), size)
    return buf.raw
```

This already works in `_engine.py` for ARM64 and x86_64 — the same technique works on Windows since `_BASE` is resolved via `GetModuleHandle`. The framework can use this for verification but must NOT depend on it at runtime.

---

## 7. Framework Introspection Protocol

### Trigger

After every **3-5 disassembly/diagnosis turns** within the framework, pause and evaluate:

"A diagnosis turn" is defined as:
- Running `analyze_full_protocol()` on one or more functions and acting on the results
- Running the catalog or dispatch table scanner and acting on the results
- Extending the framework with a new analysis method
- Running `CrashSafeProtocolTester` on one or more functions

### Introspection Questions

1. **Did the framework provide the interface I needed?**
   - Was the information I needed available from a single method call?
   - Or did I have to chain multiple calls or manually parse raw output?
   - If manual parsing was needed → the framework needs a new method

2. **Did the framework give me correct results?**
   - Did the protocol analysis correctly identify the calling convention?
   - Did the dispatch table scanner find all expected entries?
   - If wrong → fix the framework method

3. **Is there a pattern I'm repeating?**
   - Am I doing the same analysis on multiple functions?
   - Could a new framework method automate this?

4. **Does the framework's output match reality?**
   - Cross-reference framework predictions with actual `CrashSafeProtocolTester` results
   - If they disagree → framework model is wrong, update it

### After Introspection

- If framework worked perfectly → continue with implementation
- If framework was usable but missing a method → extend it NOW (don't defer)
- If framework was wrong → fix the bug NOW before using results
- If framework was completely inadequate → rewrite the relevant module

### Documentation

Each introspection session produces a brief log entry:
```markdown
## Framework Introspection #1
**Turn**: 4 (after analyzing _bist_varname, _bist_numscalar, _bist_vlmap, _bist_global)
**Needed**: Memory offset discovery for scalar hash table
**Provided?**: No — analyze_protocol only traces dispatch, not memory
**Action**: Added `analyze_memory_layout()` method to StataBinary
**Result**: Now finds scalar hash table at 0x1234000
```

---

## 8. Per-Platform Manifest System

### Current Manifest

Currently `_manifest.py` maintains a single `manifest.json` keyed by file SHA256. This works for the current single-platform use case but doesn't scale to multiple platforms.

### Target Manifest System

```
src/pystata_x/sfi/manifests/
├── manifest-linux-x86_64-{sha256[:16]}.json   ← Linux x86_64
├── manifest-windows-x86_64-{sha256[:16]}.json  ← Windows x86_64
└── manifest-darwin-arm64-{sha256[:16]}.json     ← macOS ARM64 (existing)
```

### Manifest Resolution

In `_manifest.py`:
```python
def _load_platform_manifest() -> dict:
    plat = sys.platform
    arch = platform.machine()
    sha = file_sha256(_lib_path)
    prefix = f"manifest-{plat}-{arch}-{sha[:16]}"
    for f in MANIFESTS_DIR.glob(f"{prefix}*.json"):
        with open(f) as fh:
            return json.load(fh)
    # Not found — auto-discover (slow path)
    return _auto_discover_manifest(plat, arch)
```

### Manifest Version

Bump from version 2 to version 3:
- Add `memory_offsets` section
- Add `platform` and `arch` fields
- Add `dispatch_function_status` section (working/echo/crash per function)

### Git Workflow

Manifests are **committed to git**:
```bash
git add src/pystata_x/sfi/manifests/
git commit -m "chore: update Linux manifest after framework analysis"
```

When a new Stata version is installed, re-generate manifests for all platforms.

---

## 9. Oracle Update & Reconciliation

### Current Oracle

`tests/e2e/oracle.json` — generated on macOS ARM64 via `scripts/gen_oracle.py`.
Covers: Data, Macro, Scalar, ValueLabel, Missing, Characteristic, Datetime, Frame, Matrix, Platform, SFIToolkit.

### Target Oracle System

```
tests/e2e/
├── oracle.json                    ← macOS ARM64 (primary reference)
├── oracle-linux-x86_64.json       ← Linux x86_64
├── oracle-windows-x86_64.json     ← Windows x86_64
├── test_sfi.py                    ← Oracle comparison tests (all platforms)
└── conftest.py                    ← Platform detection + oracle path selection
```

### Oracle Generation

```bash
# Linux
docker exec pystata-x-persist python scripts/gen_oracle.py --platform linux \
  --output tests/e2e/oracle-linux-x86_64.json

# Windows
ssh thomasmonkae28... "cd pystata-x && python scripts/gen_oracle.py --platform windows \
  --output tests/e2e/oracle-windows-x86_64.json"
```

### Test Harness

`TestOracleCompliance` selects the right oracle file based on platform:
```python
class TestOracleCompliance:
    _ORACLE: dict = None
    
    @classmethod
    def setup_class(cls):
        plat = _detect_platform()  # "darwin-arm64", "linux-x86_64", "windows-x86_64"
        oracle_path = Path(__file__).parent / f"oracle-{plat}.json"
        if not oracle_path.exists():
            oracle_path = Path(__file__).parent / "oracle.json"  # fallback
        with open(oracle_path) as f:
            cls._ORACLE = json.load(f)
```

### Reconciliation Protocol

When a new Stata version ships or oracle values change:

1. **Regenerate on all platforms**:
   ```bash
   # macOS (ARM64)
   python scripts/gen_oracle.py --output tests/e2e/oracle-darwin-arm64.json
   # Linux (Docker)
   docker exec pystata-x-persist python scripts/gen_oracle.py --output tests/e2e/oracle-linux-x86_64.json
   # Windows (SSH)
   ssh ... python scripts/gen_oracle.py --output tests/e2e/oracle-windows-x86_64.json
   ```

2. **Diff the oracles**: Cross-platform oracle values should be identical (same Stata version, same dataset). If they differ, investigate platform-specific formatting/binary representation issues.

3. **Commit all three oracles** together so they stay in sync.

---

## 10. SFI Class/Method Inventory

### Data (vendor: ~60 methods)

| Method | ARM64 | Linux Strategy | Windows Strategy | Notes |
|--------|-------|----------------|------------------|-------|
| getObsTotal | ✅ C | Live → keep: `call_double("_bist_nobs")` | Same as Linux | ✅ Already works |
| getVarCount | ✅ C | Live → keep: `call_double("_bist_nvar")` | Same as Linux | ✅ Already works |
| getDouble | ✅ C | Live → keep: `call_double("_bist_data")` | Same as Linux | ✅ Already works |
| getString | ✅ C | 🔴 Echo → **Framework: discover memory reader** | Same pattern | After Linux fix |
| getVarName | ✅ C | 🟡 Hardcoded mem → **Manifest-discovered offset** | Same pattern | After manifest update |
| getVarLabel | ✅ C | Live → keep: `call_string("_bist_varlabel")` | Same as Linux | ✅ Already works |
| getVarType | ✅ C | 🔴 Echo → **Framework: discover memory reader** | Same pattern | After Linux fix |
| getVarFormat | ✅ C | 🔴 Hardcoded → **Framework: discover format table** | Same pattern | After framework ext |
| getVarIndex | ✅ C | 🔴 Echo → **Framework: discover via memory scan** | Same pattern | |
| storeDouble | ✅ C | 🟡 execute() → Try C dispatch `_bist_store` | Same as Linux | C dispatch preferred |
| storeString | ✅ C | 🟡 execute() → Try C dispatch `_bist_sstore` | Same as Linux | C dispatch preferred |
| addObs | ✅ C | ✅ Works → keep | Same as Linux | |
| addVarDouble | ✅ C | ✅ Works → keep | Same as Linux | |
| addVarStr | ✅ C | ✅ Works → keep | Same as Linux | |
| addVarByte/Int/Long/Float | ✅ C | ✅ Works → keep | Same as Linux | |
| addVarStrL | ✅ C | execute() → keep (no C dispatch) | Same as Linux | |
| dropVar | ✅ C | ✅ Works → keep | Same as Linux | |
| renameVar | ✅ C | ✅ Works → keep | Same as Linux | |
| keepVar | ✅ C | ✅ Works → keep | Same as Linux | |
| isVarTypeStr | ✅ C | 🔴 Echo → dispatch fix or memory | Same pattern | |
| isVarTypeNumeric | ✅ C | ✅ Derived from type | Same as Linux | |
| isAlias | ✅ C | 🔴 Echo → dispatch fix or memory | Same pattern | |
| getStrVarWidth | ✅ C | ✅ Derived from type | Same as Linux | |
| getMaxStrLength | ✅ C | ✅ Constant 2045 | Same as Linux | |
| getMaxVars | ✅ C | 🔴 Hardcoded → **Framework: discover c(maxvar)** | Same pattern | |
| getVarValueLabel | ✅ C | 🔴 Echo → dispatch fix or memory | Same pattern | |
| getFormattedValue | ✅ C | 🔴 Depends on format fix | Same pattern | |
| setVarFormat | ✅ C | ✅ Works → keep | Same as Linux | |
| setVarLabel | ✅ C | ✅ Works → keep | Same as Linux | |
| setObsTotal | ✅ C | ✅ Works → keep | Same as Linux | |
| get / getAsDict | ✅ C | 🟡 Python loop → keep (acceptable) | Same as Linux | |
| store | ✅ C | 🟡 Delegates → keep | Same as Linux | |
| toNPArray / fromNPArray | ✅ | 🟡 Python loop → keep | Same as Linux | |
| toPDataFrame / fromPDataFrame | ✅ | 🟡 Python loop → keep | Same as Linux | |
| allocateStrL | ❌ | ❌ NotImplementedError | Same | _stpy_* requirement |
| readBytes | ✅ | ✅ Works → keep | Same as Linux | |
| writeBytes | ❌ | ❌ NotImplementedError | Same | _stpy_* requirement |
| storeBytes | ❌ | ❌ NotImplementedError | Same | _stpy_* requirement |

### Macro (vendor: 5 methods)

| Method | ARM64 | Linux Strategy | Windows Strategy |
|--------|-------|----------------|------------------|
| getGlobal | ✅ C | 🔴 Echo → **Memory reader for macro hash table** | Same pattern |
| setGlobal | ✅ C | 🟡 execute() → Try C dispatch `_bist_putglobal` | Same as Linux |
| delGlobal | ✅ C | 🟡 execute() → Try C dispatch | Same as Linux |
| getLocal | ✅ C | 🔴 Echo → Same as getGlobal | Same pattern |
| setLocal | ✅ C | 🟡 execute() → Try C dispatch | Same as Linux |

### Scalar (vendor: 4 methods)

| Method | ARM64 | Linux Strategy | Windows Strategy |
|--------|-------|----------------|------------------|
| getValue | ✅ C | 🟡 Hybrid execute+read → **Framework: discover scalar table** | Same pattern |
| setValue | ✅ C | 🟡 execute() → Try C dispatch | Same as Linux |
| getString | ✅ C | 🔴 Returns "" → **Framework: discover string scalar storage** | Same pattern |
| setString | ✅ C | 🟡 execute() → Try C dispatch | Same as Linux |

### ValueLabel (vendor: ~20 methods)

| Method | ARM64 | Linux Strategy | Windows Strategy |
|--------|-------|----------------|------------------|
| exists | ✅ C | 🔴 Echo → **Framework: discover VL hash table** | Same pattern |
| getLabel | ✅ C | 🔴 Echo → Same | Same pattern |
| getValueLabel | ✅ C | 🔴 Echo → Same | Same pattern |
| getNames | ✅ C | 🔴 Echo → Same | Same pattern |
| getLabels | ✅ C | 🔴 Echo → Same | Same pattern |
| getValues | ✅ C | 🔴 Echo → Same | Same pattern |
| create | ✅ C | 🟡 execute() → Try C dispatch `_bist_vlload`? | Same as Linux |
| define | ✅ C | 🟡 execute() → Try C dispatch | Same as Linux |
| drop | ✅ C | 🟡 execute() → Try C dispatch | Same as Linux |
| setLabelValue | ✅ C | 🟡 execute() → Try C dispatch | Same as Linux |
| setVarValueLabel | ✅ C | ✅ Works → keep | Same as Linux |
| removeVarValueLabel | ✅ C | ✅ Works → keep | Same as Linux |
| removeLabel | ✅ C | 🟡 execute() → keep (acceptable for mutation) | Same as Linux |
| removeLabelValue | ✅ C | 🟡 execute() → keep | Same as Linux |

### Frame (vendor: 8+ methods)

| Method | ARM64 | Linux Strategy | Windows Strategy |
|--------|-------|----------------|------------------|
| createFrame | ❌ | ✅ Dispatch exists → `call_void("_bist_framecreate")` | Same as Linux |
| dropFrame | ❌ | ✅ Dispatch exists → `call_void("_bist_framedrop")` | Same as Linux |
| renameFrame | ❌ | ✅ Dispatch exists | Same as Linux |
| copyFrame | ❌ | ✅ Dispatch exists | Same as Linux |
| changeCurrentFrame | ❌ | ✅ Dispatch exists | Same as Linux |
| getFrameDir | ❌ | ✅ Dispatch exists → `call_string("_bist_framedir")` | Same as Linux |
| getFrameExists | ❌ | ✅ Dispatch exists → `call_int("_bist_frameexists")` | Same as Linux |
| getCWF | ❌ | ✅ Dispatch exists → `call_string("_bist_framecurrent")` | Same as Linux |

**Note**: Frame has working `_bist_*` dispatch entries on x86_64 (unlike many other echo functions). These should work with push+stack protocol directly.

### Matrix (vendor: 17 methods)

All via `execute()` (no `_bist_matrix*` for user matrices — those work on estimation results):
| Method | Strategy |
|--------|----------|
| create, drop, get, set | `execute("matrix ...")` |
| getAt, setAt | `execute("matrix ...")` |
| getRowNames, setRowNames | `execute("matrix rownames ...")` |
| getColNames, setColNames | `execute("matrix colnames ...")` |
| getRowTotal, getColTotal | `execute("matrix ...")` + parse output (⚠️) |
| getMatrixStripe, setMatrixStripe | `execute()` |
| getRowNames, getColNames | `execute()` |
| rename | `execute()` |

**⚠️ Parsing warning**: `getRowTotal`/`getColTotal` need the matrix dimension. Use `call_double("_bist_matrix")` if available, else `execute("display rowsof(mat)")` — but this reads output buffer. **Preferred**: Store result in a scalar via Stata command, then read via `Scalar.getValue()` or temp variable hybrid pattern.

### Mata (vendor: 17 methods)

All via `execute()`:
| Method | Strategy |
|--------|----------|
| get, put | `execute("mata: ...")` |
| create, drop | `execute("mata: ...")` |
| execute | `execute("mata: ...")` |
| evaluate | `execute("mata: ...")` |
| getSize, getColNames, etc. | `execute("mata: ...")` |

**Output avoidance**: Use `mata: st_numscalar("r(val)", ...)` to pass Mata values back to Stata, then read via `Scalar.getValue()` or temp variable.

### Characteristic (vendor: ~6 methods)

| Method | Strategy |
|--------|----------|
| getDtaChar | `execute("char _dta[name]")` + read via temp var |
| setDtaChar | `execute('char _dta[name] "val"')` |
| getVariableChar | `execute("char varname[name]")` |
| setVariableChar | `execute('char varname[name] "val"')` |
| getCharNames | `execute("char list")` + parse |
| getDataType | Always "string" |

### Datetime (vendor: ~10 methods)

Pure Python — no Stata calls needed.

### Platform (vendor: ~8 methods)

Pure Python — `sys.platform`, `platform.machine()`, etc.

### Preference (vendor: ~8 methods)

| Method | Strategy |
|--------|----------|
| get/set | `execute("set prefname value")` / `execute("display c(prefname)")` |
| getDefault | Constant or `execute()` |

**Output avoidance**: For `get`, use temp variable: `execute("quietly generate __tmp = c(prefname) in 1")` then `call_double("_bist_data")`.

### StrLConnector (vendor: ~6 methods)

| Method | Strategy | Notes |
|--------|----------|-------|
| readBytes | ✅ `_bi_st_strlpart` | Works on all platforms |
| writeBytes | ❌ NotImplementedError | Requires `_stpy_writebytes` |
| storeBytes | ❌ NotImplementedError | Requires `_stpy_storebytes` |
| allocate | ❌ NotImplementedError | Requires `_stpy_allocatestrl` |
| isBinary | ❌ NotImplementedError | Requires `_stpy_isstrlbinary` |
| getObsSize | ✅ Derived from readBytes | |

### SFIToolkit (vendor: ~12 methods)

All via `execute()` — already working on all platforms.

### Missing (vendor: ~10 methods)

Pure Python — already working on all platforms.

---

## 11. Implementation Order & Dependencies

### Dependency Graph

```
Step 1: Design Document (THIS DOCUMENT)
  │
  ▼
Step 2a: Linux Implementation
  │
  ├── Phase A: Framework Extension (blocker for everything)
  │   ├── analyze_memory_layout()
  │   ├── generate_manifest()
  │   ├── diff_manifests()
  │   └── Manifest version 3
  │   │
  │   ▼
  ├── Phase B: Dispatch Fixes (blocker for Data + Macro + Scalar + VL)
  │   ├── Run framework: discover scalar table offsets
  │   ├── Run framework: discover macro hash table
  │   ├── Run framework: discover value label hash table
  │   ├── Run framework: discover var format table
  │   ├── Run framework: discover c(maxvar) location
  │   ├── Implement memory readers in _engine.py
  │   ├── Replace all hardcoded offsets with manifest entries
  │   ├── Fix call_string universal pattern (if needed)
  │   └── Re-generate Linux manifest
  │   │
  │   ▼
  ├── Phase C: Missing Classes (no blockers — execute()-based)
  │   ├── Frame (_bist_frame* dispatch — should work immediately)
  │   ├── Matrix (execute() — no dispatch needed)
  │   ├── Mata (execute() — no dispatch needed)
  │   ├── Characteristic (execute())
  │   ├── Datetime (pure Python)
  │   ├── Platform (pure Python)
  │   └── Preference (execute())
  │   │
  │   ▼
  ├── Phase D: Platform Strategy Pattern
  │   ├── Create _strategy.py with PlatformStrategy ABC
  │   ├── Move platform-specific code out of _core.py
  │   ├── Move platform-specific code out of _engine.py
  │   └── Register strategy at init time
  │   │
  │   ▼
  ├── Phase E: C Fast Path Expansion
  │   ├── Add remaining BIST slot IDs
  │   ├── Add C wrappers for all _bist_* functions
  │   └── Ensure x86_64 patches cover all functions
  │   │
  │   ▼
  └── Phase F: Linux Oracle + Testing
      ├── Re-generate Linux oracle.json
      ├── Add oracle tests for every method
      ├── Run full suite: unit + e2e + framework
      └── Zero skips/ignores (except _stpy_*)
  
Step 2b: Windows Implementation
  │
  ├── Phase G: PE Symbol Discovery
  │   ├── Run framework on libstata-se.dll
  │   ├── Complete _read_pe_syms()
  │   └── Generate Windows manifest
  │   │
  │   ▼
  ├── Phase H: Windows Dispatch
  │   ├── Resolve Microsoft x64 ABI differences
  │   ├── Adapt push+stack protocol for PE
  │   └── Test all dispatch functions
  │   │
  │   ▼
  ├── Phase I: Windows Memory Readers
  │   ├── Port memory readers (no /proc/self/mem)
  │   └── Verify against framework-discovered offsets
  │   │
  │   ▼
  ├── Phase J: Windows Missing Classes
  │   ├── Same as Phase C (execute()-based, platform independent)
  │   └── Test each class
  │   │
  │   ▼
  └── Phase K: Windows Oracle + Testing
      ├── Generate Windows oracle.json
      ├── Run all tests
      ├── Manifest diff vs Linux — zero unexpected diffs
      └── Zero skips/ignores

Step 3: Full Cross-Platform Testing
  │
  ├── Phase L: Unit tests on both platforms
  ├── Phase M: E2E oracle tests on both platforms
  ├── Phase N: Framework integration tests on both platforms
  ├── Phase O: Manifest diff — zero drifts
  └── Phase P: CI hardening
```

---

## 12. Risk Register

| Risk | Likelihood | Impact | Mitigation | When |
|------|-----------|--------|------------|------|
| x86_64 dispatch echo is by-design (identity stubs, no real dispatch) | Medium | Critical | Accept execute() fallback for reads where memory readers can't be built. Framework extension will confirm. | Phase B |
| Memory offsets differ between ELF and PE (different Stata build) | High | High | Per-platform manifests with diff tooling catch this automatically | Phase G |
| Windows PE COFF symbols are stripped | High | High | Use `.reloc` section + export table as fallback. Framework can find dispatch table by scanning for function pointer arrays | Phase G |
| Microsoft x64 ABI push function args differ from SysV | Medium | Medium | Already understood: rcx/rdx/r8/r9 vs rdi/rsi/rdx. Update CFUNCTYPE signatures | Phase H |
| Windows no `/proc/self/mem` — memory readers need different approach | High | Medium | Use ctypes `memmove` from known offsets (already works in _engine.py for ARM64) | Phase I |
| SSH latency makes Windows iteration slow | Medium | Low | Batch operations: send script, get results. Use automated test runner | Phase G-K |
| Stata version mismatch between Linux and Windows oracles | Medium | Medium | Version-check manifests; if values differ, investigate platform-specific formatting | Phase K |
| Framework extension takes longer than expected | Medium | Medium | Scope framework to minimum needed: memory-layout discovery. Push manifest diff/CI to Step 3 | Phase A |
| Segfault during ctypes-based dispatch (process crash, no recovery) | Low | High | Use subprocess isolation (CrashSafeProtocolTester) for all dispatch testing | Phase B |

---

*End of Step 1 Design Document. Next: Step 2a — begin framework extension for memory-layout discovery on Linux x86_64 (Docker).*
