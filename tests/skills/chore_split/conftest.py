"""Make the chore-split script importable as ``chore_split``, next to its own fsq_core copy."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "plugin" / "skills" / "chore-split" / "scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

# Importing the script must not leave __pycache__ folders inside the skill directory.
_previous = sys.dont_write_bytecode
sys.dont_write_bytecode = True
try:
    import chore_split  # noqa: F401
    import fsq_core  # noqa: F401
finally:
    sys.dont_write_bytecode = _previous
