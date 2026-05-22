"""Shared fixtures for e2e test modules.

Provides the module-scoped ``stata`` fixture that initialises a
Stata session once per module.
"""

from __future__ import annotations

import platform
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def stata():
    """Initialise Stata once and return engine.execute function."""
    from pystata_x import _config as cfg

    if not cfg.stinitialized:
        from pystata_x.sfi._engine import initialize
        try:
            initialize()
            from pystata_x.sfi._engine import _LIB
            _LIB.StataSO_Execute(b"sysuse auto, clear")
        except Exception:
            pytest.skip(f"Stata initialization failed on {sys.platform}")

    from pystata_x.sfi._engine import execute
    yield execute, None

    # NOTE: shutdown() is deliberately omitted here because it calls
    # dlclose(StataSO) which SIGSEGVs on x86_64 (fixed in _engine.py
    # but dlclose may still crash).  Python will unload the library
    # naturally when the process exits, so shutdown is unnecessary.
