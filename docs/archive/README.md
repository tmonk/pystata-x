# Archived Documentation

These documents are preserved for historical reference but are **superseded** by newer analysis or plans.

| File | Dated | Replaced By | Reason for Archive |
|------|-------|-------------|-------------------|
| `SFI_OVERHAUL_ANALYSIS.md` | 2026-05-21 | `docs/APPROACH.md` | Comprehensive analysis with phased 6-week roadmap. The analysis sections (architecture, performance, reliability) remain useful reference, but the phased plan is superseded by the actual implementation. |
| `REMAINING_GAPS.md` | 2026-05-21 | `docs/APPROACH.md` §8 | Listed x86_64 gaps. All gaps have been resolved or explicitly frozen. |
| `bi_st_re_report.md` | 2026-05-19 | `docs/CRACKED_CONVENTIONS.md` | Final report on `_bi_st_*` reverse engineering. Key findings (pushstr-first convention, type=-3 tsmat) are now in the authoritative calling convention reference. |
| `bi_st_analysis.md` | 2026-05-19 | `docs/CRACKED_CONVENTIONS.md` | Side-by-side disassembly of `_bi_st_strlpart` vs `_bist_data`. Superseded by the complete tsmat structure doc. |
| `SFI_CROSS_PLATFORM_DESIGN.md` | 2026-05-22 | `docs/APPROACH.md` | Pre-implementation design document for the cross-platform SFI overhaul. Superseded by the actual implementation results and the frozen approach documented in APPROACH.md. |
| `STEP2A_COMPLETION.md` | 2026-05-21 | `docs/APPROACH.md` | Step 2a completion report from an earlier phase. The status (dispatch function fixes, missing classes) is now outdated — see APPROACH.md §4-7 for the final state. |

### Still Current (not archived)

| File | Purpose |
|------|---------|
| `CRACKED_CONVENTIONS.md` | Complete tsmat structure, push+stack protocol, calling convention reference (architecture still accurate) |
| `X86_64_DISCOVERIES.md` | x86_64-specific technical discoveries — updated 2026-05-22 to reflect final state after 3 call_string fixes + per-class runner |
| `BENCHMARKING.md` | Benchmarking methodology and results (macOS ARM64 focus — still accurate) |
| `APPROACH.md` | **Authoritative comprehensive approach document** — the single source of truth for architecture, decisions, and current status |
