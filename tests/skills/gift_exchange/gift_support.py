"""Shared helpers of the gift-exchange tests: paths, running the script, input builders, the
recorded values and hypothesis strategies."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from hypothesis import HealthCheck, settings
from hypothesis import strategies as st

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_DIR = REPO_ROOT / "plugin" / "skills" / "gift-exchange"
SCRIPT = SKILL_DIR / "scripts" / "gift_exchange.py"
EXAMPLES = SKILL_DIR / "examples"
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

# The recorded example: six people, two couples, and Lao Wang gave to Yuki last year. One
# fictional published source. It has 96 legal plans, 40 of them single circles.
PEOPLE6 = ["阿明", "小红", "大刘", "Coco", "老王", "Yuki"]
SOURCE = "（虚构示例）2026-11-08 某公开开奖号码 03 11 19 24 33 + 02 07"
FORBIDDEN6 = [
    {"pair": ["阿明", "小红"]},
    {"pair": ["大刘", "Coco"]},
    {"giver": "老王", "receiver": "Yuki"},
]
BLOCKED6 = [
    ("阿明", "小红"),
    ("小红", "阿明"),
    ("大刘", "Coco"),
    ("Coco", "大刘"),
    ("老王", "Yuki"),
]
GOLDEN_COUNT = 96
GOLDEN_RING_COUNT = 40
GOLDEN_SEED = "1a00559810149576dff6f98ced86cddfee2b976104656ff33b57b66f87e005d9"
GOLDEN_NUMBER = 13
GOLDEN_PLAN = {
    "Coco": "Yuki",
    "Yuki": "小红",
    "大刘": "阿明",
    "小红": "老王",
    "老王": "Coco",
    "阿明": "大刘",
}
# The same people in one circle (examples/six_circle.json).
RING_SEED = "b9b77ae6d012ea2b3d34cf83a3e16f4ddf0beb0a6558f5fd5e4f019ca7f50ab0"
RING_NUMBER = 10
RING_CIRCLE = ["Coco", "Yuki", "阿明", "大刘", "老王", "小红"]
# Twelve people (examples/office_twelve.json), drawn by random proposals.
TWELVE_SEED = "ec9ea550dbcb77725a680520d95a3fdf53240880cd165a0b5f74ddfe4b385786"
TWELVE_ATTEMPTS = 2
TWELVE_PLAN = {
    "Coco": "阿杰",
    "Leo": "Coco",
    "Mia": "老王",
    "Nina": "Leo",
    "Yuki": "Nina",
    "大刘": "阿明",
    "小周": "小红",
    "小红": "Yuki",
    "小雨": "大刘",
    "老王": "Mia",
    "阿明": "小周",
    "阿杰": "小雨",
}

# Three people of whom two are a couple: no legal draw (Hall's condition fails).
THREE = ["甲", "乙", "丙"]
THREE_FORBIDDEN = [{"pair": ["甲", "乙"]}]

RULES = {
    "source_description": "fictional example: a public draw on a stated date, copied as shown",
    "deadline": "2026-11-07 20:00",
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


def run_json(data: dict, *args: str) -> subprocess.CompletedProcess:
    """Run the script on a JSON object given on standard input."""
    return run_script("--input", "-", *args, stdin=json.dumps(data, ensure_ascii=False))


def load_example(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------
# Input builders
# ---------------------------------------------------------------------------------------


def exchange_data(people, forbidden=(), mode="any", source=SOURCE, **extra) -> dict:
    data = {
        "mode": mode,
        "people": list(people),
        "forbidden": [dict(entry) for entry in forbidden],
        "random_source": source,
        "rules": dict(RULES),
    }
    data.update(extra)
    return data


def six_people(mode="any", source=SOURCE) -> dict:
    return exchange_data(PEOPLE6, FORBIDDEN6, mode, source)


def directions(entries) -> set:
    """The (giver, receiver) directions that a list of forbidden entries rules out."""
    found = set()
    for entry in entries:
        if "pair" in entry:
            first, second = entry["pair"]
            found |= {(first, second), (second, first)}
        else:
            found.add((entry["giver"], entry["receiver"]))
    return found


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
def cases(draw, min_people: int = 2, max_people: int = 6, most: float = 0.5):
    """(people, forbidden entries, source) with a random set of excluded directions.

    At most the given share of all directions is excluded, so small groups often have no legal
    plan and larger ones often do. The entries are one-way, so every direction is independent.
    """
    people = draw(name_lists(min_people, max_people))
    directions_ = [(a, b) for a in people for b in people if a != b]
    size = draw(st.integers(0, int(len(directions_) * most)))
    chosen = draw(st.lists(st.sampled_from(directions_), min_size=size, max_size=size, unique=True))
    forbidden = [{"giver": giver, "receiver": receiver} for giver, receiver in chosen]
    return people, forbidden, draw(SOURCES)
