"""Helpers for the bill-split tests: paths, a CLI runner and independent reference solvers.

The reference solvers below do not use the script's own code. They exist so that the property
tests compare the script with a second, plainly written implementation.
"""

from __future__ import annotations

import itertools
import json
import math
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any

SKILL_DIR = Path(__file__).resolve().parents[3] / "plugin" / "skills" / "bill-split"
SCRIPT = SKILL_DIR / "scripts" / "bill_split.py"
EXAMPLES = SKILL_DIR / "examples"

PEOPLE_POOL = ["阿明", "小红", "大刘", "Coco", "老王", "Yuki", "小周", "Mia"]


# --------------------------------------------------------------------------------------
# Running the script
# --------------------------------------------------------------------------------------


def run_script(
    *args: str, text: str | None = None, cwd: Path | None = None
) -> subprocess.CompletedProcess:
    """Run the script like the contract tests do: no site-packages, no bytecode files."""
    return subprocess.run(
        [sys.executable, "-B", "-S", str(SCRIPT), *args],
        input=text if text is not None else "",
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )


def dump_json(value: Any) -> str:
    """JSON text in which a Fraction (a multiple of 0.01) becomes a plain decimal number."""
    if isinstance(value, Fraction):
        cents = value * 100
        assert cents.denominator == 1, value
        sign = "-" if cents < 0 else ""
        whole, part = divmod(abs(cents.numerator), 100)
        return f"{sign}{whole}.{part:02d}"
    if isinstance(value, dict):
        return (
            "{"
            + ",".join(
                f"{json.dumps(k, ensure_ascii=False)}:{dump_json(v)}" for k, v in value.items()
            )
            + "}"
        )
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(dump_json(v) for v in value) + "]"
    return json.dumps(value, ensure_ascii=False)


def euros(cents: int) -> Fraction:
    return Fraction(cents, 100)


def int_map(mapping: dict) -> dict[str, int]:
    """A result mapping of Cents values as plain ints."""
    return {key: int(value) for key, value in mapping.items()}


# --------------------------------------------------------------------------------------
# Reference solvers
# --------------------------------------------------------------------------------------


def reference_owed(expense: dict[str, Any], people: list[str]) -> dict[str, Fraction]:
    """Exact amount each person owes for one expense, from plain definitions."""
    share: dict[str, Fraction] = {}
    for item in expense["items"]:
        amount = Fraction(item["amount"])
        if "exact" in item:
            parts = {p: Fraction(v) for p, v in item["exact"].items()}
        else:
            who = people if item.get("everyone") else item["among"]
            weight = {p: Fraction(item.get("weights", {}).get(p, 1)) for p in who}
            total_weight = sum(weight.values())
            parts = {p: amount * weight[p] / total_weight for p in who}
        for p, v in parts.items():
            share[p] = share.get(p, Fraction(0)) + v
    consumed = dict(share)
    sharers = sorted(consumed)
    for sign, extras in ((1, expense.get("fees", [])), (-1, expense.get("discounts", []))):
        for extra in extras:
            amount = Fraction(extra["amount"])
            split = extra.get("split", "by_consumption")
            if split == "exact":
                parts = {p: Fraction(v) for p, v in extra["exact"].items()}
            elif split == "equal":
                parts = {p: amount / len(sharers) for p in sharers}
            else:
                total = sum(consumed.values())
                parts = {p: amount * consumed[p] / total for p in sharers} if total else {}
            for p, v in parts.items():
                share[p] = share.get(p, Fraction(0)) + sign * v
    return share


def reference_shapley(amounts: dict[str, int], tiers: list[tuple[int, int]]) -> dict[str, Fraction]:
    """Shapley value by averaging marginal contributions over all orders of the people."""
    names = sorted(amounts)

    def worth(total: int) -> int:
        return max([cut for gate, cut in tiers if total >= gate], default=0)

    value = {name: Fraction(0) for name in names}
    orders = list(itertools.permutations(names))
    for order in orders:
        running = 0
        for name in order:
            before = worth(running)
            running += amounts[name]
            value[name] += worth(running) - before
    return {name: value[name] / len(orders) for name in names}


def max_zero_sum_groups(values: list[int]) -> int:
    """Largest number of zero-sum groups, by recursion over subsets that contain the lowest bit."""
    count = len(values)
    sums = [0] * (1 << count)
    for mask in range(1, 1 << count):
        sums[mask] = sum(values[i] for i in range(count) if mask >> i & 1)
    cache = {0: 0}

    def best(mask: int) -> int:
        if mask in cache:
            return cache[mask]
        low = mask & -mask
        top = 0
        sub = mask
        while sub:
            if sub & low and sums[sub] == 0:
                top = max(top, 1 + best(mask ^ sub))
            sub = (sub - 1) & mask
        cache[mask] = top
        return top

    return best((1 << count) - 1)


def bfs_fewest_transfers(values: list[int]) -> int:
    """Fewest transfers by breadth-first search over balance vectors (tiny inputs only)."""
    start = tuple(values)
    if not any(start):
        return 0
    seen = {start}
    frontier = [start]
    steps = 0
    while frontier:
        steps += 1
        following = []
        for state in frontier:
            for debtor, owed in enumerate(state):
                if owed >= 0:
                    continue
                for creditor, due in enumerate(state):
                    if due <= 0:
                        continue
                    for amount in range(1, min(-owed, due) + 1):
                        moved = list(state)
                        moved[debtor] += amount
                        moved[creditor] -= amount
                        key = tuple(moved)
                        if not any(key):
                            return steps
                        if key not in seen:
                            seen.add(key)
                            following.append(key)
        frontier = following
    raise AssertionError("no settlement found")


def group_order_reference(order: dict[str, Any]) -> dict[str, Fraction]:
    """Exact amount each buyer pays in a group order (rule split), from plain definitions."""
    buyers: list[str] = []
    dish: dict[str, Fraction] = {}
    pack: dict[str, Fraction] = {}
    for item in order["items"]:
        who = item["who"]
        if who not in dish:
            buyers.append(who)
            dish[who] = Fraction(0)
            pack[who] = Fraction(0)
        dish[who] += Fraction(item["amount"])
        pack[who] += Fraction(item.get("packaging", 0))
    subtotal = sum(dish.values())
    pay = {p: dish[p] + pack[p] for p in buyers}
    for fee in order.get("fees", []):
        amount = Fraction(fee["amount"])
        for p in buyers:
            if fee.get("split", "proportional") == "equal":
                pay[p] += amount / len(buyers)
            else:
                pay[p] += amount * dish[p] / subtotal
    cents = {p: int(dish[p] * 100) for p in buyers}
    for coupon in order.get("coupons", []):
        if "tiers" in coupon:
            tiers = [(int(Fraction(a) * 100), int(Fraction(b) * 100)) for a, b in coupon["tiers"]]
            if coupon.get("split", "shapley") == "shapley":
                for p, v in reference_shapley(cents, tiers).items():
                    pay[p] -= v / 100
            else:
                cut = max([r for t, r in tiers if int(subtotal * 100) >= t], default=0)
                for p in buyers:
                    pay[p] -= Fraction(cut, 100) * dish[p] / subtotal
        else:
            amount = Fraction(coupon["amount"])
            for p in buyers:
                if coupon.get("split", "proportional") in ("equal", "shapley"):
                    pay[p] -= amount / len(buyers)
                else:
                    pay[p] -= amount * dish[p] / subtotal
    return pay


def floor_cents(value: Fraction) -> int:
    return math.floor(value * 100)
