"""stata-fast: Optimised pystata fork.

Fast Stata-Python bridge — drop-in accelerator for StataCorp's pystata.

Key entry points
----------------
run(code, ...)     — Execute Stata commands, return (output, rc)
config             — Config module (init, status, settings)
statasetup.config()— One-shot Stata initialisation (drop-in for ``stata_setup``)
"""

# SPDX-FileCopyrightText: 2025 Thomas Monk <t.d.monk@lse.ac.uk>
# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

from stata_fast._core import run, get_output
from stata_fast import _config as config

__version__ = "0.2.0"
__author__ = "Thomas Monk"
