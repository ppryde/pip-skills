"""Make the shared helpers (and, through them, the hook module) importable from any cwd."""
from __future__ import annotations

import sys
from pathlib import Path

HERE = str(Path(__file__).resolve().parent)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
