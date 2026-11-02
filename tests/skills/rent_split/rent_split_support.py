"""Helpers shared by the rent-split tests: loading the script, running it, and input builders.

The tests import the script as a module for speed and also run it as a program (with ``-B -S``,
so that no third-party package can sneak in) to check the command line.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from types import ModuleType
from typing import Any

REPO = Path(__file__).resolve().parents[3]
SKILL = REPO / "plugin" / "skills" / "rent-split"
SCRIPT = SKILL / "scripts" / "rent_split.py"
EXAMPLES = SKILL / "examples"
SKILL_MD = SKILL / "SKILL.md"
GOLDEN = Path(__file__).resolve().parent / "golden"

FOUR_PEOPLE = ["阿明", "小红", "大刘", "Coco"]
FOUR_ROOMS = ["主卧带卫", "南次卧", "北次卧", "小书房"]
FOUR_BIDS = {
    "阿明": [3000, 2200, 1600, 1200],
    "小红": [2600, 2500, 1700, 1200],
    "大刘": [3400, 2000, 1500, 1100],
    "Coco": [2400, 2300, 2000, 1300],
}
# The same example with Latin letters only, so that every word of the output comes from the
# script and none from the data.
ASCII_PEOPLE = ["Ann", "Bob", "Cy", "Dee"]
ASCII_ROOMS = ["Main", "South", "North", "Study"]
ASCII_BIDS = dict(zip(ASCII_PEOPLE, FOUR_BIDS.values()))
STORAGE_ROOMS = ["大主卧", "朝南卧", "储物间改的小间"]
STORAGE_BIDS = {"甲": [4800, 1000, 200], "乙": [1000, 4800, 200], "丙": [2900, 2900, 200]}

# Nobody values the first room at anything, so someone has to be paid to live there and no
# envy-free split without a negative rent exists. Bids are whole units, the total rent is 6000.
NO_NON_NEGATIVE_BIDS = {
    "甲": [0, 2000, 0, 4000],
    "乙": [0, 3000, 3000, 0],
    "丙": [0, 1000, 0, 5000],
    "丁": [0, 0, 5000, 1000],
}
NO_NON_NEGATIVE_ROOMS = ["储物间", "东卧", "西卧", "南卧"]


def load_script() -> ModuleType:
    """Import rent_split.py from the skill folder, next to its own copy of the shared core."""
    scripts_dir = str(SCRIPT.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("rent_split_under_test", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up here
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True  # keep __pycache__ folders out of the skill directory
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def run_script(
    *args: str, stdin: str = "", cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the script as a program without site-packages and without writing bytecode."""
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-B", "-S", str(SCRIPT), *args],
        input=stdin,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )


def run_script_bytes(*args: str, stdin: bytes) -> subprocess.CompletedProcess[bytes]:
    """Like run_script, for standard input that is not valid text."""
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-B", "-S", str(SCRIPT), *args],
        input=stdin,
        env=env,
        capture_output=True,
        timeout=120,
        check=False,
    )


def make_input(
    total: Any,
    rooms: list[str],
    bids: dict[str, list[Any]],
    rule: str = "spliddit",
    **extra: Any,
) -> dict[str, Any]:
    """The input object of the script, built from Python values."""
    data: dict[str, Any] = {
        "total_rent": total,
        "rooms": list(rooms),
        "bids": {name: list(row) for name, row in bids.items()},
        "rules": {"negative_rent": rule},
    }
    for key, value in extra.items():
        if key == "random_source":
            data["rules"]["random_source"] = value
        else:
            data[key] = value
    return data


def four_roommates(rule: str = "spliddit", **extra: Any) -> dict[str, Any]:
    return make_input(8000, FOUR_ROOMS, FOUR_BIDS, rule, **extra)


def ascii_roommates(rule: str = "spliddit", **extra: Any) -> dict[str, Any]:
    """The four roommates with ASCII names, with the audit block of the equal split."""
    audit = {
        "assignment": dict(zip(ASCII_PEOPLE, ["Study", "South", "Main", "North"])),
        "rent": dict.fromkeys(ASCII_PEOPLE, 2000),
    }
    return make_input(8000, ASCII_ROOMS, ASCII_BIDS, rule, audit=audit, **extra)


def storage_room(rule: str = "spliddit") -> dict[str, Any]:
    return make_input(6000, STORAGE_ROOMS, STORAGE_BIDS, rule)


def matrix_input(
    rows: list[list[int]], total_cents: int, rule: str = "spliddit", **extra: Any
) -> dict[str, Any]:
    """An input with people p0.. and rooms r0.. from a matrix of bids in cents."""
    n = len(rows)
    rooms = [f"r{k}" for k in range(n)]
    bids = {f"p{i}": [Fraction(x, 100) for x in row] for i, row in enumerate(rows)}
    return make_input(Fraction(total_cents, 100), rooms, bids, rule, **extra)


def dumps(data: Any) -> str:
    """JSON text of an input that may hold Fractions (written as decimal strings like "12.34")."""

    def default(value: Any) -> Any:
        if isinstance(value, Fraction):
            cents = value * 100
            assert cents.denominator == 1
            whole, part = divmod(abs(int(cents)), 100)
            return f"{'-' if cents < 0 else ''}{whole}.{part:02d}"
        raise TypeError(type(value))

    return json.dumps(data, ensure_ascii=False, default=default)


def exact_rents(module: ModuleType, rows: list[list[int]], total: int, rule: str) -> Any:
    """The exact solution of a matrix of integer bids whose rows add up to total."""
    return module.solve_exact([[Fraction(x) for x in row] for row in rows], Fraction(total), rule)
