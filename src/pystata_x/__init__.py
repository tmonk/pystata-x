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

from pystata_x._core import run, execute, get_output
from pystata_x import _config as config

__version__ = "0.2.0"
__author__ = "Thomas Monk"
