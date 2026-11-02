"""Put tests/ on sys.path, so that test modules in the subfolders can import the shared helper
theory_doc, which reads docs/THEORY.md. Also switch terminal colors off for every process that a
test starts: Python 3.14 colors the --help text of argparse when FORCE_COLOR is set, and the escape
codes would split the option names that the tests look for."""

from __future__ import annotations

import os
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent

if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

os.environ.pop("FORCE_COLOR", None)
os.environ["NO_COLOR"] = "1"
os.environ["PYTHON_COLORS"] = "0"
