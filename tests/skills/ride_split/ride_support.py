"""Shared helpers of the ride-split tests: paths, running the script, small input builders."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

from hypothesis import HealthCheck, settings
from hypothesis import strategies as st

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_DIR = REPO_ROOT / "plugin" / "skills" / "ride-split"
SCRIPT = SKILL_DIR / "scripts" / "ride_split.py"
EXAMPLES = SKILL_DIR / "examples"
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

RIDERS = ["小周", "阿杰", "Mia", "老陈"]
NAMES = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L"]

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


def _amount_text(value):
    """JSON text for the exact amounts the builders produce (whole cents become '14.00')."""
    if isinstance(value, Fraction):
        cents = value * 100
        if cents.denominator != 1:
            raise TypeError(f"{value} is not a whole number of cents")
        whole, part = divmod(cents.numerator, 100)
        return f"{whole}.{part:02d}"
    raise TypeError(f"cannot write {type(value).__name__}")


def to_json(data: dict) -> str:
    """JSON text of an input object; Fractions become decimal strings the script accepts."""
    return json.dumps(data, ensure_ascii=False, default=_amount_text)


def run_json(data: dict, *args: str) -> subprocess.CompletedProcess:
    """Run the script on a JSON object given on standard input."""
    return run_script("--input", "-", *args, stdin=to_json(data))


def meter_data(readings, riders=None, **extra) -> dict:
    """A meter-mode input; readings are cents."""
    riders = riders or NAMES[: len(readings)]
    data = {
        "mode": "meter",
        "riders": list(riders),
        "meter_at_dropoff": [Fraction(c, 100) for c in readings],
    }
    data.update(extra)
    return data


def estimates_data(estimates, total_cents, riders=None, **extra) -> dict:
    """An estimates-mode input; estimates and total are cents."""
    riders = riders or NAMES[: len(estimates)]
    data = {
        "mode": "estimates",
        "riders": list(riders),
        "solo_estimate": [Fraction(c, 100) for c in estimates],
        "actual_total": Fraction(total_cents, 100),
    }
    data.update(extra)
    return data


def subset_costs_data(prices, riders=None, **extra) -> dict:
    """A general-mode input from prices[mask] in cents (mask 1 .. 2**n - 1)."""
    n = (len(prices) - 1).bit_length()
    riders = riders or NAMES[:n]
    entries = [
        {
            "riders": [riders[i] for i in range(n) if mask >> i & 1],
            "cost": Fraction(prices[mask], 100),
        }
        for mask in range(1, 1 << n)
    ]
    data = {"mode": "general", "riders": list(riders), "subset_costs": entries}
    data.update(extra)
    return data


@st.composite
def distinct_names(draw, n: int):
    """n distinct rider names in an arbitrary order (the order decides tie-breaks)."""
    return draw(st.permutations(NAMES))[:n]


@st.composite
def meter_inputs(draw, max_riders: int = 8):
    """Random meter-mode inputs in cents: non-decreasing readings, a positive last one."""
    n = draw(st.integers(2, max_riders))
    top = draw(st.sampled_from([5, 40, 500, 20000]))
    cents = sorted(draw(st.lists(st.integers(0, top), min_size=n, max_size=n)))
    if cents[-1] == 0:
        cents[-1] = 1
    names = draw(distinct_names(n))
    ride_id = draw(st.sampled_from(["ride-1", "a", "airport-9", "旅"]))
    return meter_data(cents, names, ride_id=ride_id)


@st.composite
def estimates_inputs(draw, max_riders: int = 8):
    """Random estimates-mode inputs: any order, at least one positive estimate."""
    n = draw(st.integers(2, max_riders))
    top = draw(st.sampled_from([5, 40, 500, 20000]))
    cents = draw(st.lists(st.integers(0, top), min_size=n, max_size=n))
    if max(cents) == 0:
        cents[0] = 1
    total = draw(st.integers(1, 30000))
    names = draw(distinct_names(n))
    ride_id = draw(st.sampled_from(["ride-1", "a", "airport-9", "旅"]))
    return estimates_data(cents, total, names, ride_id=ride_id)
