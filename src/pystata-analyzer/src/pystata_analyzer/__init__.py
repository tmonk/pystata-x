"""pystata-analyzer — Standalone Stata binary analysis framework.

A comprehensive, living analysis framework with:
- ``StataBinary`` — core binary analysis engine
- ``Framework`` — unified orchestration pipeline
- ``PatternRegistry`` — knowledge base of architectural patterns
- ``Plugin`` — extensible plugin system with lifecycle hooks
- ``ELFReader`` — pure-ctypes ELF section reader
- CLI: ``python -m pystata_analyzer <path> [flags]``

Quick start::

    from pystata_analyzer import Framework
    fw = Framework("/path/to/libstata.so", auto_analyze=True)
    print(fw.report(format="markdown"))
    fw.generate_report("output/")
"""

from pystata_analyzer.elf import ELFReader
from pystata_analyzer.binary import StataBinary
from pystata_analyzer.helpers import HAS_CAPSTONE
from pystata_analyzer.registry import PatternRegistry, PatternEntry, REGISTRY_VERSION
from pystata_analyzer.plugin import (
    Plugin,
    analyze_hook,
    report_hook,
    BUILTIN_PLUGINS,
    ErrorCodeMapper,
    EntryPointDetector,
    ProtocolClassifier,
    PoolHeaderScanner,
    ManifestManager,
    DocstringExtractor,
)
from pystata_analyzer.framework import Framework
from pystata_analyzer.live_protocol import (
    EngineConnection,
    ProtocolAutoTester,
    LiveProtocolValidatorPlugin,
)

__all__ = [
    "ELFReader",
    "StataBinary",
    "HAS_CAPSTONE",
    "PatternRegistry",
    "PatternEntry",
    "REGISTRY_VERSION",
    "Plugin",
    "analyze_hook",
    "report_hook",
    "BUILTIN_PLUGINS",
    "ErrorCodeMapper",
    "EntryPointDetector",
    "ProtocolClassifier",
    "PoolHeaderScanner",
    "ManifestManager",
    "DocstringExtractor",
    "Framework",
    "EngineConnection",
    "ProtocolAutoTester",
    "LiveProtocolValidatorPlugin",
]
