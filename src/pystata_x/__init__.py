"""pystata-x: Independent drop-in replacement for StataCorp's pystata.

Fast Stata-Python bridge for headless / AI-agent use cases.

Key entry points
----------------
run(code, ...)     — Execute Stata commands (vendor-compatible, returns None)
execute(code, ...) — Execute Stata commands (fast, returns (output, rc) tuple)
config             — Config module (init, status, settings)
statasetup.config()— One-shot Stata initialisation (drop-in for ``stata_setup``)
"""

# SPDX-FileCopyrightText: 2025 Thomas Monk <t.d.monk@lse.ac.uk>
# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

from importlib.metadata import version as _metadata_version, PackageNotFoundError as _PackageNotFoundError

from pystata_x._core import run, execute, get_output, ExecuteResult
from pystata_x import _config as config

# Inject our sfi module so that 'from sfi import Macro, Data' works
# (Stata-agent and other pystata-compatible code uses this import pattern)
import sys as _sys
from pystata_x import sfi as _sfi
_sys.modules['sfi'] = _sfi

try:
    __version__ = _metadata_version("pystata-x")
except _PackageNotFoundError:
    __version__ = "0.0.0.dev0"

__author__ = "Thomas Monk"
