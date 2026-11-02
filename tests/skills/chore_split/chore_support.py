"""Shared helpers of the chore-split tests: paths, running the script, input builders and
hypothesis strategies."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from hypothesis import HealthCheck, settings
from hypothesis import strategies as st

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_DIR = REPO_ROOT / "plugin" / "skills" / "chore-split"
SCRIPT = SKILL_DIR / "scripts" / "chore_split.py"
EXAMPLES = SKILL_DIR / "examples"
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

# The recorded example: three roommates, six chores, one week, one fictional published source.
SOURCE = "（虚构示例）2026-11-08 某公开开奖号码 03 11 19 24 33 + 02 07"
GOLDEN_SEED = "6944c304e73fa353e0d827408cc1f48fd3a8684494793fc65a25fa07a39f46a1"
PEOPLE3 = ["阿明", "小红", "大刘"]
CHORES6 = ["洗碗", "倒垃圾", "拖地", "刷厕所", "做饭", "擦窗"]
RANKINGS3 = {
    "阿明": ["倒垃圾", "做饭", "拖地", "擦窗", "洗碗", "刷厕所"],
    "小红": ["倒垃圾", "洗碗", "擦窗", "拖地", "刷厕所", "做饭"],
    "大刘": ["拖地", "倒垃圾", "做饭", "刷厕所", "洗碗", "擦窗"],
}
# The scores the recorded example was first computed with. The rankings above are the ones these
# scores imply (ties do not occur). Lower is less disliked.
RECORDED_SCORES = {
    "阿明": {"洗碗": 6, "倒垃圾": 1, "拖地": 4, "刷厕所": 9, "做饭": 2, "擦窗": 5},
    "小红": {"洗碗": 3, "倒垃圾": 2, "拖地": 5, "刷厕所": 8, "做饭": 9, "擦窗": 4},
    "大刘": {"洗碗": 7, "倒垃圾": 3, "拖地": 2, "刷厕所": 6, "做饭": 5, "擦窗": 8},
}
RECORDED_PICKS = [
    ("阿明", "倒垃圾"),
    ("小红", "洗碗"),
    ("大刘", "拖地"),
    ("阿明", "做饭"),
    ("小红", "擦窗"),
    ("大刘", "刷厕所"),
]
RECORDED_BUNDLES = {
    "阿明": ["倒垃圾", "做饭"],
    "小红": ["洗碗", "擦窗"],
    "大刘": ["拖地", "刷厕所"],
}

PROPERTY = settings(
    deadline=None,
    max_examples=120,
    derandomize=True,
    database=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)


# ---------------------------------------------------------------------------------------
# Running the script
# ---------------------------------------------------------------------------------------


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


def run_script_bytes(*args: str, stdin: bytes) -> subprocess.CompletedProcess:
    """Like run_script, for standard input that is not valid text."""
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-B", "-S", str(SCRIPT), *args],
        input=stdin,
        capture_output=True,
        env=env,
        timeout=120,
        check=False,
    )


def run_json(data: dict, *args: str) -> subprocess.CompletedProcess:
    """Run the script on a JSON object given on standard input."""
    return run_script("--input", "-", *args, stdin=json.dumps(data, ensure_ascii=False))


def load_example(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------
# Input builders
# ---------------------------------------------------------------------------------------


def chore_data(
    people,
    chores,
    rankings,
    units=None,
    cannot=None,
    weeks=1,
    source=SOURCE,
    rotate=None,
    **extra,
) -> dict:
    """An input object. chores are names, units maps a name to its units (default 1)."""
    units = units or {}
    listed = [{"name": c, "units": units[c]} if c in units else c for c in chores]
    data = {
        "people": list(people),
        "chores": listed,
        "rankings": {person: list(ranking) for person, ranking in rankings.items()},
        "weeks": weeks,
        "rules": {"random_source": source},
    }
    if rotate is not None:
        data["rules"]["rotate"] = rotate
    if cannot:
        data["cannot"] = {person: list(c) for person, c in cannot.items()}
    data.update(extra)
    return data


def recorded_data(**extra) -> dict:
    return chore_data(PEOPLE3, CHORES6, RANKINGS3, source=SOURCE, **extra)


# ---------------------------------------------------------------------------------------
# Plan B (bundle_pay): input builders
# ---------------------------------------------------------------------------------------

BUNDLE_SOURCE = "（虚构示例）2026-11-15 某公开开奖号码 05 12 18 26 31 + 03 09"
# What each person wants per week for doing the chore once, in the order of CHORES6. The recorded
# example of plan B: two cheapest splits (total 135), every person ends at -45.00 a week.
PRICE3 = {
    "阿明": [30, 5, 20, 60, 40, 25],
    "小红": [20, 10, 25, 50, 70, 20],
    "大刘": [35, 15, 10, 40, 30, 45],
}
# The case in which the cheapest split is not the best one for the worst-off person. Rows are
# 阿明, 小红 and 大刘, columns are CHORES6, every person takes two chores.
HARD3 = {
    "阿明": [28, 29, 5, 20, 9, 18],
    "小红": [13, 9, 4, 3, 26, 2],
    "大刘": [2, 26, 24, 27, 1, 13],
}


def bundle_data(
    people,
    chores,
    costs,
    caps,
    units=None,
    cannot=None,
    source=None,
    description=None,
    **extra,
) -> dict:
    """An input object of plan bundle_pay. costs maps a person to {chore: cost}."""
    units = units or {}
    listed = [{"name": c, "units": units[c]} if c in units else c for c in chores]
    rules = {"plan": "bundle_pay"}
    if source is not None:
        rules["random_source"] = source
    if description is not None:
        rules["source_description"] = description
    data = {
        "people": list(people),
        "chores": listed,
        "costs": {person: dict(row) for person, row in costs.items()},
        "caps": dict(caps),
        "rules": rules,
    }
    if cannot:
        data["cannot"] = {person: list(c) for person, c in cannot.items()}
    data.update(extra)
    return data


def table_costs(table, chores=CHORES6) -> dict:
    """costs from {person: [cost per chore, in the order of chores]}."""
    return {person: dict(zip(chores, row)) for person, row in table.items()}


def price_data(table=PRICE3, cap=2, **extra) -> dict:
    """Three roommates, six chores, the same cap for everybody."""
    return bundle_data(PEOPLE3, CHORES6, table_costs(table), {p: cap for p in PEOPLE3}, **extra)


# ---------------------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------------------

# Names are any text without surrogates, without leading or trailing white space.
CHARACTERS = st.characters(blacklist_categories=("Cs",))
NAMES = st.text(CHARACTERS, min_size=1, max_size=5).filter(lambda s: s == s.strip() and s != "")
SOURCES = st.text(CHARACTERS, min_size=1, max_size=30).filter(lambda s: s.strip() != "")


def name_lists(min_size: int, max_size: int):
    return st.lists(NAMES, min_size=min_size, max_size=max_size, unique=True)


@st.composite
def chore_cases(
    draw,
    max_people: int = 4,
    max_chores: int = 5,
    max_units: int = 2,
    with_cannot: bool = False,
    max_weeks: int = 3,
):
    """A valid input object. With with_cannot, people may have chores they cannot do, but every
    chore can still be done by somebody."""
    people = draw(name_lists(2, max_people))
    chores = draw(name_lists(1, max_chores))
    units = {c: draw(st.integers(1, max_units)) for c in chores}
    cannot = {person: [] for person in people}
    if with_cannot:
        for person in people:
            cannot[person] = draw(
                st.lists(st.sampled_from(chores), unique=True, max_size=len(chores))
            )
        for chore in chores:
            if all(chore in cannot[person] for person in people):
                cannot[draw(st.sampled_from(people))].remove(chore)
    rankings = {
        person: draw(st.permutations([c for c in chores if c not in cannot[person]]))
        for person in people
    }
    return chore_data(
        people,
        chores,
        rankings,
        units=units,
        cannot={person: c for person, c in cannot.items() if c},
        weeks=draw(st.integers(1, max_weeks)),
        source=draw(SOURCES),
        rotate=draw(st.sampled_from([None, "shift", "none"])),
    )
