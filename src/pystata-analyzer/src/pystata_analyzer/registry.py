"""PatternRegistry — knowledge base for Stata binary architectural patterns.

Three-tier registry:
1. **Hardcoded defaults** — known patterns loaded at construction
2. **Auto-detected** — patterns discovered during analysis (JSON)
3. **User-added** — patterns registered at runtime

All known architectural findings from CRACKED_CONVENTIONS.md,
X86_64_DISCOVERIES.md, and session analysis are embedded as hardcoded
defaults with full source docstrings.
"""

import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


# ═════════════════════════════════════════════════════════════════════
#  Pattern data model
# ═════════════════════════════════════════════════════════════════════

@dataclass
class PatternEntry:
    """A single pattern entry in the registry.

    Attributes
    ----------
    name : str
        Pattern name (e.g. ``"arg_ptr_protocol"``, ``"_bist_data"``).
    pattern_type : str
        One of ``"protocol"``, ``"address"``, ``"error_code"``,
        ``"entry_point"``, ``"pool_check"``, ``"convention"``.
    description : str
        Human-readable description of what this pattern captures.
    data : dict
        The pattern data itself (varies by type).
    source : str
        Origin: ``"hardcoded"``, ``"auto_detected"``, or ``"user_added"``.
    created_at : float
        Unix timestamp of when this entry was created.
    sha256 : str or None
        Binary SHA256 this pattern was discovered from (if auto-detected).
    manifest_version : int
        Version of the manifest format at creation time.
    tags : list[str]
        Freeform tags for searching/filtering.
    """
    name: str
    pattern_type: str
    description: str
    data: dict
    source: str = "user_added"
    created_at: float = field(default_factory=time.time)
    sha256: Optional[str] = None
    manifest_version: int = 2
    tags: list[str] = field(default_factory=list)


# ═════════════════════════════════════════════════════════════════════
#  Hardcoded defaults — ALL known architectural findings
# ═════════════════════════════════════════════════════════════════════

def _hardcoded_defaults() -> list[PatternEntry]:
    """Return all hardcoded default patterns.

    Every finding in CRACKED_CONVENTIONS.md, X86_64_DISCOVERIES.md,
    and session analysis is represented here.
    """
    now = time.time()
    return [
        # ── Address patterns ──────────────────────────────────────
        PatternEntry(
            name="arg_ptr",
            pattern_type="address",
            description="ARG_PTR — push-function stack-pointer at .bss 0x500C6A0. "
                        "Push functions (_pushdbl, _pushint, _pushstr) store tsmat "
                        "pointers here and advance by 8 per push. _save_sp() reads "
                        "from here. Also known as _STACK_PTR_OFFSET in the manifest.",
            data={"vaddr": 0x500C6A0, "size": 8, "purpose": "push+stack argument ptr"},
            source="hardcoded", created_at=now, tags=["address", "core"],
        ),
        PatternEntry(
            name="sp_global",
            pattern_type="address",
            description="SP_global — checker/SP-resetting thunk target at .bss 0x500C638. "
                        "SP-resetting dispatch thunks (e.g. _bist_nobs) write a data-"
                        "descriptor address here. Implementation functions often ignore "
                        "it and read from ARG_PTR instead.",
            data={"vaddr": 0x500C638, "size": 8, "purpose": "SP-resetting thunk target"},
            source="hardcoded", created_at=now, tags=["address", "core"],
        ),
        PatternEntry(
            name="err_addr",
            pattern_type="address",
            description="Error-code global at .bss 0x500C698. Stata stores integer "
                        "error codes (rc) here. Values like 0xce4 (3300) mean "
                        "conformability error, 0xcea (3306) means index out of bounds.",
            data={"vaddr": 0x500C698, "size": 4, "purpose": "Stata error code global"},
            source="hardcoded", created_at=now, tags=["address", "error"],
        ),
        # ── tsmat / pool mechanics ────────────────────────────────
        PatternEntry(
            name="tsmat_data_embedded",
            pattern_type="convention",
            description="tsmat data is EMBEDDED at offset 0 of the struct. "
                        "tsmat[0] holds the double value (or GSO string pointer "
                        "for string tsmat). There is NO separate data buffer. "
                        "This differs from the ARM64 convention where data is "
                        "at a separate pointer.",
            data={"data_offset": 0, "type": "embedded double/GSO ptr"},
            source="hardcoded", created_at=now, tags=["tsmat", "core"],
        ),
        PatternEntry(
            name="pool_header_check",
            pattern_type="pool_check",
            description="Pool-header check: tsmat[-0x94] == 0x2b verifies the tsmat "
                        "was pool-allocated. The sentinel 0x2b is at a negative offset "
                        "from the tsmat struct pointer, in the pool allocation header. "
                        "Functions that receive a raw tsmat run this check before access.",
            data={"sentinel_offset": -0x94, "sentinel_value": 0x2b, "type": "pool_header"},
            source="hardcoded", created_at=now, tags=["tsmat", "pool", "core"],
        ),
        PatternEntry(
            name="patch_last_tsmat",
            pattern_type="convention",
            description="_patch_last_tsmat() fixes the pool-header self-pointer: "
                        "sets tsmat[-0x10] = tsmat after each pool_alloc call. "
                        "Without this fix, tsmat[-0x10] points to the pool free-list "
                        "instead of the tsmat itself, causing crashes on access.",
            data={"fix_offset": -0x10, "fix_type": "self_pointer"},
            source="hardcoded", created_at=now, tags=["tsmat", "pool"],
        ),
        # ── Protocol patterns ─────────────────────────────────────
        PatternEntry(
            name="protocol_push_stack",
            pattern_type="protocol",
            description="Standard push+stack protocol: arguments are pushed via "
                        "_pushdbl/_pushint/_pushstr which allocate tsmat structs "
                        "and update ARG_PTR. The dispatch implementation reads from "
                        "these tsmat structs by indexing backward from ARG_PTR. "
                        "This is the PRIMARY protocol for all data-access functions.",
            data={"type": "push_stack", "uses_arg_ptr": True, "push_fns_required": True},
            source="hardcoded", created_at=now, tags=["protocol", "core"],
        ),
        PatternEntry(
            name="protocol_sp_reset",
            pattern_type="protocol",
            description="SP-resetting protocol: the dispatch thunk writes a data-"
                        "descriptor address into SP_global (0x500C638). The implementation "
                        "reads from a global C struct, not from push+stack. No push "
                        "function calls. Used by _bist_nobs, _bist_nvar, and similar "
                        "0-arg/1-arg scalar-return functions.",
            data={"type": "sp_reset", "uses_sp_global": True, "push_fns_required": False},
            source="hardcoded", created_at=now, tags=["protocol", "core"],
        ),
        PatternEntry(
            name="protocol_internal_global",
            pattern_type="protocol",
            description="Internal-global protocol: the implementation reads from "
                        "a global struct that the thunk sets up from Stata internals, "
                        "not from ARG_PTR. Used by _bist_store write path and "
                        "_bist_sdata. The caller must have gone through a type-checking "
                        "dispatch thunk first.",
            data={"type": "internal_global", "uses_arg_ptr": False,
                  "uses_sp_global": False, "push_fns_required": False},
            source="hardcoded", created_at=now, tags=["protocol", "core"],
        ),
        PatternEntry(
            name="protocol_string_return",
            pattern_type="protocol",
            description="String-return protocol: similar to push+stack but the "
                        "return value is a GSO string pointer stored in a tsmat, "
                        "read via call_string(). Used by _bist_macroexpand, _bist_dir.",
            data={"type": "string_return", "uses_arg_ptr": True, "return_type": "gso_string"},
            source="hardcoded", created_at=now, tags=["protocol", "string"],
        ),
        # ── Multi-entry dispatch ──────────────────────────────────
        PatternEntry(
            name="dispatch_87_multi_entry",
            pattern_type="entry_point",
            description="Dispatch[87] serves BOTH _bist_data (read) AND _bist_store "
                        "(write) on x86_64 — unlike ARM64 where they are separate "
                        "functions. Three sub-entry points: 0x826494 (read, esi=0), "
                        "0x8264b8 (read, esi=1), 0x8264dc (write, 6-push prologue).",
            data={"dispatch_index": 87, "function": "_bist_data/_bist_store",
                  "entries": [{"vaddr": 0x826494, "mode": "read", "edi": 2},
                              {"vaddr": 0x8264b8, "mode": "read_alt", "edi": 2},
                              {"vaddr": 0x8264dc, "mode": "write", "edi": "3+"}]},
            source="hardcoded", created_at=now, tags=["dispatch", "multi_entry"],
        ),
        # ── Known function patterns ───────────────────────────────
        PatternEntry(
            name="_bist_global",
            pattern_type="protocol",
            description="_bist_global handles single-arg reads only via push+stack. "
                        "The write path (edi != 1) reads from a global struct that "
                        "the thunk sets up from Stata internal state, not from ARG_PTR. "
                        "Cannot be used for macro writes from external code. "
                        "Argument is a GSO string (macro name) via call_string.",
            data={"dispatch_index": 1314, "read_ok": True,
                  "write_ok": False, "arg_type": "gso_string"},
            source="hardcoded", created_at=now, tags=["function", "read_only"],
        ),
        PatternEntry(
            name="_bist_putglobal",
            pattern_type="convention",
            description="_bist_putglobal has NO dispatch entry on x86_64. "
                        "No st_putglobal in the st_* name table. The function exists "
                        "in the ARM64 binary (Mach-O symbol table) but is stripped "
                        "from x86_64 ELF. Macro writes need a different approach.",
            data={"x86_64": "not_found", "arm64": "exists_at_0x1cff60"},
            source="hardcoded", created_at=now, tags=["function", "missing"],
        ),
        PatternEntry(
            name="_bist_macroexpand",
            pattern_type="protocol",
            description="_bist_macroexpand works reliably for reading macros via "
                        "call_string protocol. It is the ONLY dispatch-path method "
                        "that returns string values from Stata's macro system.",
            data={"dispatch_index": 549, "protocol": "string_return",
                  "works": True, "read_type": "macro_value"},
            source="hardcoded", created_at=now, tags=["function", "string", "macro"],
        ),
        # ── Error code maps ──────────────────────────────────────
        PatternEntry(
            name="error_code_3300",
            pattern_type="error_code",
            description="Error 3300 (0xCE4): conformability error. Set when the "
                        "number of arguments or their types don't match what the "
                        "dispatch function expects. Common in write-path failures.",
            data={"code": 3300, "hex": 0xCE4, "meaning": "conformability error"},
            source="hardcoded", created_at=now, tags=["error", "common"],
        ),
        PatternEntry(
            name="error_code_3306",
            pattern_type="error_code",
            description="Error 3306 (0xCEA): index out of bounds. Set when "
                        "obs or var index exceeds valid range. Common in read-path "
                        "failures with wrong argument count.",
            data={"code": 3306, "hex": 0xCEA, "meaning": "index out of bounds"},
            source="hardcoded", created_at=now, tags=["error", "bounds"],
        ),
        PatternEntry(
            name="error_code_3302",
            pattern_type="error_code",
            description="Error 3302 (0xCE6): type mismatch. Set when the pushed "
                        "argument type (double vs int vs string) doesn't match the "
                        "expected tsmat type.",
            data={"code": 3302, "hex": 0xCE6, "meaning": "type mismatch"},
            source="hardcoded", created_at=now, tags=["error", "type"],
        ),
        # ── Write-path bugs ──────────────────────────────────────
        PatternEntry(
            name="bist_store_write_bug",
            pattern_type="convention",
            description="_bist_store write-path bug: at 0x8264dc + edi=3, rax "
                        "is zeroed by 'mov eax, 0' at 0x826553 before 'test rax, rax' "
                        "at 0x8266c9, so the obs check fails with error 3300. "
                        "The 3-arg entry expects the caller to have gone through "
                        "the type checker at dispatch[86] first. Additionally, "
                        "the store helper at 0x8253ab reads from the wrong tsmat — "
                        "it copies from VAR tsmat instead of VAL tsmat content.",
            data={"fault": "rax zeroed before obs check",
                  "rax_zero_at": 0x826553, "test_rax_at": 0x8266c9,
                  "error_thrown": "3300 via 0x8268a1",
                  "root_cause": "wrong tsmat source in store helper"},
            source="hardcoded", created_at=now, tags=["bug", "write_path"],
        ),
    ]


# ═════════════════════════════════════════════════════════════════════
#  Registry class
# ═════════════════════════════════════════════════════════════════════

class PatternRegistry:
    """Three-tier knowledge base of Stata architectural patterns.

    Tiers (checked in order, first match wins):
    1. **Hardcoded defaults** — baked into the code at construction.
    2. **Auto-detected** — loaded from versioned JSON registry files.
    3. **User-added** — registered programmatically at runtime.

    Usage::

        reg = PatternRegistry()
        reg.add("my_pattern", {"key": "value"}, pattern_type="protocol")
        entry = reg.lookup("my_pattern")
        reg.save("/tmp/registry.json")
        reg2 = PatternRegistry.load("/tmp/registry.json")
    """

    def __init__(self, auto_load_defaults: bool = True):
        self._tiers: dict[str, list[PatternEntry]] = {
            "hardcoded": [],
            "auto_detected": [],
            "user_added": [],
        }
        self._by_name: dict[str, PatternEntry] = {}
        if auto_load_defaults:
            self._load_hardcoded_defaults()

    # ── Loading ─────────────────────────────────────────────────

    def _load_hardcoded_defaults(self) -> None:
        """Embed all known architectural findings."""
        for entry in _hardcoded_defaults():
            self._tiers["hardcoded"].append(entry)
            self._by_name[entry.name] = entry

    def load(self, path: str, tier: str = "auto_detected") -> int:
        """Load patterns from a JSON file into *tier*.

        Returns the number of entries loaded.
        """
        if tier not in self._tiers:
            raise ValueError(f"Unknown tier: {tier!r}, choose from {list(self._tiers)}")
        with open(path) as f:
            raw = json.load(f)
        count = 0
        for item in raw:
            entry = PatternEntry(**item)
            self._tiers[tier].append(entry)
            self._by_name[entry.name] = entry
            count += 1
        return count

    # ── CRUD ────────────────────────────────────────────────────

    def add(self, name: str, data: dict, *,
            pattern_type: str = "protocol",
            description: str = "",
            source: str = "user_added",
            sha256: Optional[str] = None,
            tags: Optional[list[str]] = None) -> PatternEntry:
        """Register a new pattern.

        If *name* already exists (in any tier), it is overwritten in
        the tier matching *source*.
        """
        entry = PatternEntry(
            name=name,
            pattern_type=pattern_type,
            description=description or f"Pattern: {name}",
            data=data,
            source=source,
            sha256=sha256,
            tags=tags or [],
        )
        # Remove existing from target tier
        tier = source if source in self._tiers else "user_added"
        self._tiers[tier] = [e for e in self._tiers[tier]
                              if e.name != name]
        self._tiers[tier].append(entry)
        self._by_name[name] = entry
        return entry

    def lookup(self, name: str) -> Optional[PatternEntry]:
        """Find a pattern by name (tier order: hardcoded → auto → user)."""
        return self._by_name.get(name)

    def lookup_by_type(self, pattern_type: str) -> list[PatternEntry]:
        """Get all patterns matching *pattern_type*."""
        results = []
        for entry in self._by_name.values():
            if entry.pattern_type == pattern_type:
                results.append(entry)
        return results

    def remove(self, name: str) -> bool:
        """Remove a pattern from all tiers. Returns True if found."""
        found = name in self._by_name
        for tier in self._tiers.values():
            tier[:] = [e for e in tier if e.name != name]
        self._by_name.pop(name, None)
        return found

    def list(self, source: Optional[str] = None,
             pattern_type: Optional[str] = None) -> list[PatternEntry]:
        """List patterns, optionally filtered by *source* and/or *pattern_type*."""
        results = []
        for entry in self._by_name.values():
            if source and entry.source != source:
                continue
            if pattern_type and entry.pattern_type != pattern_type:
                continue
            results.append(entry)
        return results

    # ── Persistence ─────────────────────────────────────────────

    def save(self, path: str, tier: str = "auto_detected") -> str:
        """Save patterns from *tier* to a JSON file.

        Returns the path written.
        """
        entries = []
        for entry in self._tiers.get(tier, []):
            d = {
                "name": entry.name,
                "pattern_type": entry.pattern_type,
                "description": entry.description,
                "data": entry.data,
                "source": entry.source,
                "created_at": entry.created_at,
                "sha256": entry.sha256,
                "manifest_version": entry.manifest_version,
                "tags": entry.tags,
            }
            entries.append(d)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump(entries, f, indent=2)
        return path

    @classmethod
    def from_file(cls, path: str, tier: str = "auto_detected",
                  merge_defaults: bool = True) -> "PatternRegistry":
        """Load from JSON, optionally with hardcoded defaults merged."""
        reg = cls(auto_load_defaults=merge_defaults)
        reg.load(path, tier=tier)
        return reg

    # ── Auto-detection helpers ──────────────────────────────────

    def register_detected(self, name: str, data: dict,
                          sha256: str, **kwargs) -> PatternEntry:
        """Register an auto-detected pattern (tier: auto_detected)."""
        return self.add(name, data, source="auto_detected",
                        sha256=sha256, **kwargs)

    # ── Reporting ───────────────────────────────────────────────

    def stats(self) -> dict[str, int]:
        """Count of patterns per tier."""
        return {
            "hardcoded": len(self._tiers["hardcoded"]),
            "auto_detected": len(self._tiers["auto_detected"]),
            "user_added": len(self._tiers["user_added"]),
            "total": len(self._by_name),
        }

    def __repr__(self) -> str:
        s = self.stats()
        return (f"<PatternRegistry hardcoded={s['hardcoded']} "
                f"auto={s['auto_detected']} user={s['user_added']}>")


# ═════════════════════════════════════════════════════════════════════
#  Current version
# ═════════════════════════════════════════════════════════════════════

REGISTRY_VERSION = 2
