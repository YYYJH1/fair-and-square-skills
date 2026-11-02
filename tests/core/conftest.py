"""Make core/fsq_core.py importable as ``fsq_core`` and fix the hypothesis profile."""

from __future__ import annotations

import sys
from pathlib import Path

from hypothesis import settings

REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_DIR = REPO_ROOT / "core"

if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

# Reproducible runs: examples are derived from the test, no example database is written.
settings.register_profile("fsq", deadline=None, max_examples=100, derandomize=True, database=None)
settings.load_profile("fsq")
