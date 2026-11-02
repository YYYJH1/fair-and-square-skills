"""Helpers shared by the stuff-split tests: paths, running the script, and input builders.

The tests import the script as a module for speed and also run it as a program (with ``-B -S``,
so that no third-party package can sneak in) to check the command line.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
SKILL = REPO / "plugin" / "skills" / "stuff-split"
SCRIPT = SKILL / "scripts" / "stuff_split.py"
EXAMPLES = SKILL / "examples"
SKILL_MD = SKILL / "SKILL.md"
GOLDEN = Path(__file__).resolve().parent / "golden"

METHODS = ("envy_free", "knaster", "max_nash")

# The recorded example: three roommates move out and share six things (points, no money).
ROOMMATES = ["阿明", "小红", "大刘"]
STUFF = ["冰箱", "洗衣机", "沙发", "电视", "微波炉", "书架"]
ROOMMATE_VALUES = {
    "阿明": [30, 25, 15, 15, 10, 5],
    "小红": [25, 30, 10, 20, 5, 10],
    "大刘": [35, 10, 25, 10, 15, 5],
}
# One piano and three heirs.
HEIRS = ["甲", "乙", "丙"]
PIANO_VALUES = {"甲": [0], "乙": [900], "丙": [890]}
# The fictional published source of the examples.
SOURCE = "（虚构示例）2026-11-08 某公开开奖号码 03 11 19 24 33 + 02 07"


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


def make_input(
    people: list[str],
    items: list[str],
    values: dict[str, list[Any]],
    method: str,
    **rules: Any,
) -> dict[str, Any]:
    """The input object of the script, built from Python values."""
    return {
        "people": list(people),
        "items": list(items),
        "values": {name: list(row) for name, row in values.items()},
        "rules": {"method": method, **rules},
    }


def roommates(method: str = "max_nash", **rules: Any) -> dict[str, Any]:
    return make_input(ROOMMATES, STUFF, ROOMMATE_VALUES, method, **rules)


def piano(method: str = "knaster", **rules: Any) -> dict[str, Any]:
    return make_input(HEIRS, ["钢琴"], PIANO_VALUES, method, **rules)


def matrix_input(rows_cents: list[list[int]], method: str, **rules: Any) -> dict[str, Any]:
    """An input with people p0.. and items g0.. from a matrix of values in cents."""
    people = [f"p{i}" for i in range(len(rows_cents))]
    items = [f"g{j}" for j in range(len(rows_cents[0]))]
    values = {name: [Fraction(x, 100) for x in row] for name, row in zip(people, rows_cents)}
    return make_input(people, items, values, method, **rules)


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


def example(name: str) -> dict[str, Any]:
    return json.loads((EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))
