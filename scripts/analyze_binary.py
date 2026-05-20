#!/usr/bin/env python3
"""analyze_binary — Thin CLI wrapper around pystata_x.sfi._analyzer.

All binary analysis logic lives in _analyzer.py (the living framework).
This script is just a convenient entry point.

Usage:
    python scripts/analyze_binary.py <path> [--report|--verify|--cache|--diff|--dispatch|--health|--json]

See `python -m pystata_x.sfi._analyzer --help` for details.
"""
import sys
import os

# Ensure the package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Delegate entirely to the framework
from pystata_x.sfi._analyzer import main

if __name__ == "__main__":
    main()
