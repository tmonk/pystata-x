"""pystata-analyzer — Standalone Stata binary analysis framework.

StataBinary is the main entry point for all analysis.  It loads an ELF
or Mach-O Stata shared library, discovers the dispatch table, st_* name
table, push functions, and provides methods for deep protocol analysis
of individual dispatch functions.

Quick start:

    from pystata_analyzer import StataBinary
    ana = StataBinary("/path/to/libstata.so")
    ana.analyze()
    print(ana.report())
    ana.analyze_dispatch_fn("_bist_nobs")
"""

from pystata_analyzer.elf import ELFReader
from pystata_analyzer.binary import StataBinary
from pystata_analyzer.helpers import HAS_CAPSTONE

__all__ = [
    "ELFReader",
    "StataBinary",
    "HAS_CAPSTONE",
]
