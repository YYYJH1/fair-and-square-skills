"""Shared helpers of the slot-lottery tests: paths, running the script, input builders and
hypothesis strategies."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from hypothesis import HealthCheck, settings
from hypothesis import strategies as st

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_DIR = REPO_ROOT / "plugin" / "skills" / "slot-lottery"
SCRIPT = SKILL_DIR / "scripts" / "slot_lottery.py"
EXAMPLES = SKILL_DIR / "examples"
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

# The recorded example: eight people, three slots, one fictional published source. Seed prefix
# 15b9c53a44270857eb442863 and the order below were first recorded on Python 3.10, 3.12 and 3.13.
PEOPLE8 = ["阿明", "小红", "大刘", "Coco", "老王", "Yuki", "小周", "Mia"]
SOURCE = "（虚构示例）2026-11-08 某公开开奖号码 03 11 19 24 33 + 02 07"
GOLDEN_SEED_PREFIX = "15b9c53a44270857eb442863"
GOLDEN_SEED = "15b9c53a44270857eb44286382b897216eaecc0dcf18eb49260f7442cdf87710"
GOLDEN_ORDER = ["Yuki", "小周", "大刘", "Coco", "小红", "阿明", "Mia", "老王"]
GOLDEN_WINNERS = ["Yuki", "小周", "大刘"]
GOLDEN_WAITING = ["Coco", "小红", "阿明", "Mia", "老王"]

# Six people choosing among four holiday weeks (the shifts example).
PEOPLE6 = ["阿明", "小红", "大刘", "Coco", "老王", "Yuki"]
WEEKS = ["国庆后一周", "春节前一周", "五一", "端午"]
RSD_ORDER = ["阿明", "大刘", "Yuki", "Coco", "老王", "小红"]
RSD_SEED = "eb68f25b704cc0b16d81364aa5b5857fb68694f339256eb8cd86851266aedd1c"
RSD_ALLOCATION = {"阿明": "春节前一周", "大刘": "国庆后一周", "Yuki": "端午", "Coco": "五一"}
RSD_PREFS = {
    "阿明": ["春节前一周", "国庆后一周", "五一", "端午"],
    "小红": ["春节前一周", "五一", "国庆后一周", "端午"],
    "大刘": ["国庆后一周", "春节前一周", "端午", "五一"],
    "Coco": ["春节前一周", "国庆后一周", "端午", "五一"],
    "老王": ["五一", "春节前一周", "国庆后一周", "端午"],
    "Yuki": ["春节前一周", "端午", "五一", "国庆后一周"],
}

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


def lottery_data(people, n_slots, source=SOURCE, **extra) -> dict:
    data = {
        "mode": "lottery",
        "people": list(people),
        "n_slots": n_slots,
        "random_source": source,
        "rules": dict(RULES),
    }
    data.update(extra)
    return data


def rsd_data(people, slots, prefs, source=SOURCE, no_ranking="forfeit", **extra) -> dict:
    data = {
        "mode": "rsd",
        "people": list(people),
        "slot_names": list(slots),
        "prefs": {person: list(ranking) for person, ranking in prefs.items()},
        "random_source": source,
        "rules": dict(RULES, no_ranking=no_ranking),
    }
    data.update(extra)
    return data


def ps_data(
    people, slots, prefs, source=SOURCE, no_ranking="forfeit", capacities=None, **extra
) -> dict:
    """An input for rules.method ps: the rsd input with the method chosen and the seats given."""
    data = rsd_data(people, slots, prefs, source, no_ranking)
    data["rules"]["method"] = "ps"
    if capacities is not None:
        data["capacities"] = dict(capacities)
    data.update(extra)
    return data


def da_data(
    people,
    slots,
    prefs,
    source=SOURCE,
    no_ranking="forfeit",
    capacities=None,
    priorities=None,
    **extra,
) -> dict:
    """An input for rules.method da: seats and priority tiers are optional."""
    data = rsd_data(people, slots, prefs, source, no_ranking)
    data["rules"]["method"] = "da"
    if capacities is not None:
        data["capacities"] = dict(capacities)
    if priorities is not None:
        data["priorities"] = {
            slot: [list(tier) for tier in tiers] for slot, tiers in priorities.items()
        }
    data.update(extra)
    return data


def code_for(person: str, salt: str = "") -> str:
    """A fixed, obviously fake reveal code (32 hex characters) for tests."""
    return hashlib.sha256(f"test-code-{salt}-{person}".encode()).hexdigest()[:32]


def reveal_data(
    people,
    revealing=None,
    n_slots=2,
    non_reveal="forfeit",
    tampered=(),
    committing=None,
    mode="lottery",
    salt="",
    slots=None,
    prefs=None,
    no_ranking="forfeit",
    **extra,
) -> dict:
    """A commit-reveal input. Everybody in `committing` (default: everybody) commits, those in
    `revealing` (default: everybody who committed) reveal, and `tampered` reveal a wrong code.
    For mode rsd give `slots` and `prefs` too."""
    import slot_lottery as sl

    committing = list(people) if committing is None else list(committing)
    revealing = committing if revealing is None else list(revealing)
    made = {p: sl.make_commitment(p, code_for(p, salt)) for p in people}
    reveals = [
        {"name": p, "reveal": code_for(p, "wrong" + salt) if p in tampered else made[p][1]}
        for p in revealing
    ]
    data = {
        "mode": mode,
        "people": list(people),
        "commit_reveal": {
            "commitments": [{"name": p, "commitment": made[p][0]} for p in committing],
            "reveals": reveals,
        },
        "rules": {"deadline": RULES["deadline"], "non_reveal": non_reveal},
    }
    if mode == "lottery":
        data["n_slots"] = n_slots
    else:
        data["slot_names"] = list(slots)
        data["prefs"] = {person: list(ranking) for person, ranking in prefs.items()}
        data["rules"]["no_ranking"] = no_ranking
    data.update(extra)
    return data


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
def lottery_inputs(draw, max_people: int = 8):
    people = draw(name_lists(2, max_people))
    return lottery_data(people, draw(st.integers(1, max_people + 2)), draw(SOURCES))


@st.composite
def rsd_cases(draw, max_people: int = 5, max_slots: int = 4, everybody_ranks: bool = True):
    """(people, slots, prefs, source) with partial rankings and possibly an empty ranking."""
    people = draw(name_lists(2, max_people))
    slots = draw(name_lists(1, max_slots))
    ranked = people
    if not everybody_ranks:
        ranked = draw(st.lists(st.sampled_from(people), min_size=1, unique=True))
    prefs = {
        person: draw(st.lists(st.sampled_from(slots), unique=True, max_size=len(slots)))
        for person in ranked
    }
    return people, slots, prefs, draw(SOURCES)


@st.composite
def matching_cases(
    draw,
    max_people: int = 5,
    max_slots: int = 4,
    max_capacity: int = 2,
    with_priorities: bool = False,
    everybody_ranks: bool = True,
):
    """(people, slots, prefs, capacities, priorities, source) with partial rankings, empty
    rankings, seats and (if asked) priority tiers. Tiers are lists of lists of names."""
    people = draw(name_lists(2, max_people))
    slots = draw(name_lists(1, max_slots))
    ranked = people
    if not everybody_ranks:
        ranked = draw(st.lists(st.sampled_from(people), min_size=1, unique=True))
    prefs = {
        person: draw(st.lists(st.sampled_from(slots), unique=True, max_size=len(slots)))
        for person in ranked
    }
    capacities = {slot: draw(st.integers(1, max_capacity)) for slot in slots}
    priorities = {}
    if with_priorities:
        for slot in slots:
            if draw(st.booleans()):
                eligible = draw(st.lists(st.sampled_from(people), min_size=1, unique=True))
                levels = {person: draw(st.integers(0, 2)) for person in eligible}
                tiers = [
                    sorted(p for p in eligible if levels[p] == level)
                    for level in range(3)
                    if any(levels[p] == level for p in eligible)
                ]
                priorities[slot] = tiers
    return people, slots, prefs, capacities, priorities, draw(SOURCES)
