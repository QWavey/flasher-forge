#!/usr/bin/env python3
"""Top-level launcher: ``python app.py`` starts the FlasherForge GUI.

This keeps the run command short; it is equivalent to ``python -m flasher_forge``.
"""
import sys

from flasher_forge.app import main

if __name__ == "__main__":
    sys.exit(main())
