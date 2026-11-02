"""Shared helpers of the group-vote tests: paths, running the script, input builders, strategies."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from hypothesis import HealthCheck, settings
from hypothesis import strategies as st

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_DIR = REPO_ROOT / "plugin" / "skills" / "group-vote"
SCRIPT = SKILL_DIR / "scripts" / "group_vote.py"
EXAMPLES = SKILL_DIR / "examples"
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

# The 27-ballot profile of the demo: five rules, five different winners.
DEMO_OPTIONS = ["密室逃脱", "爬山", "剧本杀", "火锅", "KTV"]
DEMO_LINES = [
    (8, ["密室逃脱", "爬山", "KTV", "火锅", "剧本杀"]),
    (6, ["火锅", "KTV", "剧本杀", "爬山", "密室逃脱"]),
    (4, ["KTV", "火锅", "密室逃脱", "爬山", "剧本杀"]),
    (2, ["爬山", "剧本杀", "火锅", "密室逃脱", "KTV"]),
    (7, ["剧本杀", "爬山", "KTV", "火锅", "密室逃脱"]),
]
SOURCE = "（虚构示例）2026-11-08 某公开开奖号码 03 11 19 24 33 + 02 07"

POOL = ["火锅", "爬山", "KTV", "剧本杀", "密室逃脱", "烧烤", "日料"]
RANKED_METHODS = ["plurality", "runoff", "irv", "borda", "condorcet", "schulze", "kemeny"]

PROPERTY = settings(
    deadline=None,
    max_examples=120,
    derandomize=True,
    database=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)


def run_script(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    """Run the script the way the contract tests do: no site-packages, no bytecode files."""
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-B", "-S", str(SCRIPT), *args],
        input=stdin if stdin is not None else "",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=120,
        check=False,
    )


def run_json(data: dict, *args: str) -> subprocess.CompletedProcess:
    """Run the script on a JSON object given on standard input."""
    return run_script("--input", "-", *args, stdin=json.dumps(data, ensure_ascii=False))


def make_input(
    options,
    lines,
    method: str = "condorcet",
    *,
    partial: str | None = None,
    source: str | None = SOURCE,
    **extra,
) -> dict:
    """An input object from (count, ranking) lines."""
    rules: dict = {"method": method}
    if partial is not None:
        rules["partial"] = partial
    if source is not None:
        rules["tie_break"] = {"random_source": source}
    data = {
        "options": list(options),
        "ballots": [{"count": count, "ranking": list(ranking)} for count, ranking in lines],
        "rules": rules,
    }
    data.update(extra)
    return data


def demo_input(method: str = "condorcet", **kwargs) -> dict:
    return make_input(DEMO_OPTIONS, DEMO_LINES, method, **kwargs)


@st.composite
def option_lists(draw, min_size: int = 2, max_size: int = 5):
    """Distinct option names in an arbitrary order (the order must not matter)."""
    size = draw(st.integers(min_size, max_size))
    return list(draw(st.permutations(POOL)))[:size]


@st.composite
def ranked_profiles(draw, max_options: int = 5, partial: bool = False, max_lines: int = 6):
    """(options, lines): a random ranked profile with small counts. Partial ballots on request."""
    options = draw(option_lists(2, max_options))
    lines = []
    for _ in range(draw(st.integers(1, max_lines))):
        length = draw(st.integers(1, len(options))) if partial else len(options)
        ranking = list(draw(st.permutations(options)))[:length]
        lines.append((draw(st.integers(1, 4)), ranking))
    return options, lines


def input_for(options, lines, method, partial: bool = False, source: str | None = SOURCE):
    return make_input(
        options, lines, method, partial="tie_last" if partial else None, source=source
    )
