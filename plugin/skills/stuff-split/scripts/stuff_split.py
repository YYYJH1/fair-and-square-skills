"""Divide shared belongings among people by a rule the group picks first.

Everyone gives every item a private value (what it is worth to them, in money). The group
chooses one of three rules before anybody gives a number, and the choice is not changed after
the result. The items are indivisible, values add up over the items of a package, and every
item is given to somebody.

    envy_free   Every item goes to a person who values it most. Cash then makes the final worth
                (the value of one's items plus one's cash) the same for everybody, so nobody
                prefers another person's package plus that person's cash to their own.
    knaster     Knaster's sealed bids. Every item goes to a person who values it most, each
                person is first owed a fair share of their own total value (equal shares unless
                the group agreed on weights), and the surplus is shared in proportion to the
                shares. Nobody ends below their fair share, but somebody may envy somebody.
    max_nash    No money moves. The script tries every way of giving out the items (at most
                2,000,000 of them) and takes the one with the most people better off than
                nothing and then the largest product of their values: envy-free up to one item
                and Pareto efficient. With more allocations it takes turns instead and says so.

All arithmetic uses exact fractions. Cash is rounded to whole cents only at the end, so that it
adds up to zero.

Input is one JSON object on standard input (or --input FILE)::

    {"note": "optional one line",
     "people": ["Ann", "Bob", "Cy"],
     "items": ["fridge", "sofa"],
     "values": {"Ann": [30, 15], "Bob": [25, 10], "Cy": [35, 25]},
     "rules": {"method": "envy_free", "random_source": "optional public text",
               "weights": {"Ann": 2, "Bob": 1, "Cy": 1}}}

Only the standard library and the shared fsq_core module are used. Nothing is written to disk.
"""

from __future__ import annotations

import argparse
import itertools
import math
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

try:
    import fsq_core as fc
except ModuleNotFoundError:  # python -I, -P and PYTHONSAFEPATH leave the script folder off sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import fsq_core as fc

METHODS = ("envy_free", "knaster", "max_nash")
USED_ROUND_ROBIN = "round_robin"
RULE_NAME = "stuff_split_priority_v1"
MAX_PEOPLE = 12
MAX_ITEMS = 60
MAX_ALLOCATIONS = 2_000_000  # max_nash looks at all n**m allocations up to this many
MAX_WEIGHT = 1_000_000
TOP_FIELDS = ("note", "people", "items", "values", "rules")
RULE_FIELDS = ("method", "random_source", "weights")

EF1_NONE = "none"  # nothing to envy
EF1_HOLDS = "ef1"  # envies, and no longer envies once one item is set aside
EF1_FAILS = "fails"

fmt = fc.fmt_cents

# The recorded example: three roommates move out and share six things. Nobody pays anybody, so the
# numbers are points that only compare one person's items with each other.
DEMO_JSON = """{
  "note": "虚构示例：三个室友毕业搬家，分合租期间一起买的六件东西",
  "people": ["阿明", "小红", "大刘"],
  "items": ["冰箱", "洗衣机", "沙发", "电视", "微波炉", "书架"],
  "values": {
    "阿明": [30, 25, 15, 15, 10, 5],
    "小红": [25, 30, 10, 20, 5, 10],
    "大刘": [35, 10, 25, 10, 15, 5]
  },
  "rules": {"method": "max_nash"}
}"""

# One piano and three heirs. The two cash rules give different answers for the same numbers.
PIANO_JSON = """{
  "note": "虚构示例：甲、乙、丙三位继承人分一架钢琴",
  "people": ["甲", "乙", "丙"],
  "items": ["钢琴"],
  "values": {"甲": [0], "乙": [900], "丙": [890]},
  "rules": {"method": "knaster"}
}"""


# ---------------------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------------------


@dataclass
class Problem:
    """A validated input. Values are whole cents, exactly as the people gave them."""

    people: list[str]
    items: list[str]
    cents: dict[str, dict[str, int]]  # cents[person][item]
    method: str
    source: str | None = None
    weights: dict[str, Fraction] | None = None
    note: str | None = None


def _required(obj: dict[str, Any], key: str) -> Any:
    if key not in obj:
        raise fc.InputError(key, "is required")
    return obj[key]


def _read_weights(value: Any, people: list[str]) -> dict[str, Fraction]:
    obj = fc.require_object(value, "rules.weights")
    for name in obj:
        if name not in people:
            raise fc.InputError(f"rules.weights.{name}", "is not a person listed in people")
    weights: dict[str, Fraction] = {}
    for name in people:
        if name not in obj:
            raise fc.InputError(f"rules.weights.{name}", "is missing; list every person")
        weight = obj[name]
        if isinstance(weight, bool) or not isinstance(weight, (int, Fraction)):
            raise fc.InputError(f"rules.weights.{name}", "must be a positive number")
        if weight <= 0 or weight > MAX_WEIGHT:
            raise fc.InputError(
                f"rules.weights.{name}", f"must be greater than 0 and at most {MAX_WEIGHT}"
            )
        weights[name] = Fraction(weight)
    return weights


def parse_problem(data: Any) -> Problem:
    """Validate a parsed input object. Raises fc.InputError naming the field."""
    obj = fc.require_object(data, "input")
    fc.check_fields(obj, TOP_FIELDS, "")
    note = fc.one_line(obj["note"], "note") if "note" in obj else None
    people = fc.require_encodable_names(_required(obj, "people"), "people", 2, MAX_PEOPLE)
    items = fc.require_encodable_names(_required(obj, "items"), "items", 1, MAX_ITEMS)
    table = fc.require_object(_required(obj, "values"), "values")
    for name in table:
        if name not in people:
            raise fc.InputError(f"values.{name}", "is not a person listed in people")
    cents: dict[str, dict[str, int]] = {}
    for name in people:
        if name not in table:
            raise fc.InputError(f"values.{name}", "is missing; list every person")
        row = fc.require_list(table[name], f"values.{name}")
        if len(row) != len(items):
            raise fc.InputError(
                f"values.{name}",
                f"needs {len(items)} values, one per item in the order of items, got {len(row)}",
            )
        cents[name] = {
            item: fc.to_cents(fc.money(x, f"values.{name}[{k}]"))
            for k, (item, x) in enumerate(zip(items, row))
        }
    rules = fc.require_object(obj.get("rules", {}), "rules")
    fc.check_fields(rules, RULE_FIELDS, "rules")
    if "method" not in rules:
        raise fc.InputError(
            "rules.method",
            "is required: the group agrees on envy_free, knaster or max_nash before anyone "
            "gives numbers",
        )
    method = fc.require_choice(rules["method"], "rules.method", METHODS)
    source = None
    if "random_source" in rules:
        source = fc.require_source_text(rules["random_source"], "rules.random_source")
    weights = None
    if "weights" in rules:
        if method != "knaster":
            raise fc.InputError(
                "rules.weights",
                "only the knaster method uses weights; envy_free and max_nash treat everybody "
                "alike",
            )
        weights = _read_weights(rules["weights"], people)
    return Problem(people, items, cents, method, source, weights, note)


# ---------------------------------------------------------------------------------------
# Who comes first in a tie
# ---------------------------------------------------------------------------------------


@dataclass
class Priority:
    """The order that settles ties: sorted names, or a shuffle seeded by a public source."""

    order: list[str]
    method: str  # sorted_names or random_source
    seed_hex: str | None = None
    preimage: str | None = None


def priority_order(problem: Problem) -> Priority:
    """The tie-break order of the people: by name, or drawn from the public random source."""
    if problem.source is None:
        return Priority(sorted(problem.people), "sorted_names")
    drawn = fc.seeded_order(RULE_NAME, problem.people, len(problem.items), problem.source)
    return Priority(list(drawn.order), "random_source", drawn.seed_hex, drawn.preimage)


def rounding_key(problem: Problem) -> str:
    """The key that rotates exact ties between leftover cents, the same for any listing order."""
    return "stuff-split|" + fc.canonical_json(
        {"items": sorted(problem.items), "method": problem.method, "people": sorted(problem.people)}
    )


# ---------------------------------------------------------------------------------------
# Items to the people who value them most (envy_free and knaster)
# ---------------------------------------------------------------------------------------


@dataclass
class TopValuers:
    """Who gets each item when it goes to a person who values it most."""

    owner: dict[str, str]  # item -> person
    best: dict[str, int]  # item -> the highest value, in cents
    tops: dict[str, list[str]]  # item -> everybody with that value, in the order of priority
    tied: list[str]  # the items with more than one person at the top
    needs_order: list[str]  # the tied items that the number of items held did not settle


def assign_to_top_valuers(
    cents: dict[str, dict[str, int]], items: Sequence[str], priority: Sequence[str]
) -> TopValuers:
    """Give every item to a person who values it most.

    Items are taken in the order of their names. When several people value an item most, it goes
    to the one of them who holds the fewest items so far, and then to the one who comes first in
    the priority order, so a pile of equal items is spread over the people who tie for them.
    needs_order lists the items for which that second step was needed.
    """
    held = dict.fromkeys(priority, 0)
    rank = {name: index for index, name in enumerate(priority)}
    owner: dict[str, str] = {}
    best: dict[str, int] = {}
    tops: dict[str, list[str]] = {}
    tied: list[str] = []
    needs_order: list[str] = []
    for item in sorted(items):
        best[item] = max(cents[p][item] for p in priority)
        tops[item] = [p for p in priority if cents[p][item] == best[item]]
        if len(tops[item]) > 1:
            tied.append(item)
        fewest = min(held[p] for p in tops[item])
        candidates = [p for p in tops[item] if held[p] == fewest]
        if len(candidates) > 1:
            needs_order.append(item)
        pick = min(candidates, key=lambda p: rank[p])
        owner[item] = pick
        held[pick] += 1
    return TopValuers(owner, best, tops, tied, needs_order)


def bundles_of(
    owner: dict[str, str], people: Sequence[str], items: Sequence[str]
) -> dict[str, list[str]]:
    """The items of each person, in the order the items were listed."""
    return {p: [g for g in items if owner[g] == p] for p in people}


def package_value(cents: dict[str, dict[str, int]], person: str, package: Iterable[str]) -> int:
    """What a package of items is worth to a person, in cents."""
    return sum(cents[person][g] for g in package)


# ---------------------------------------------------------------------------------------
# max_nash: every allocation, or taking turns
# ---------------------------------------------------------------------------------------


@dataclass
class NashSearch:
    """The best of all allocations: who gets item j (indices into priority and sorted items)."""

    owner: tuple[int, ...]
    n_positive: int  # how many people get something worth more than nothing
    product: int  # the product of those values, in cents to the power n_positive
    n_optimal: int  # how many allocations reach that, before the tie-break
    evenness: int  # the sum of the squares of the numbers of items, smaller is more even
    n_best_even: int  # how many of those are the most even, so the order has to settle them


def search_max_nash(values: Sequence[Sequence[int]], n_people: int) -> NashSearch:
    """Look at every allocation and keep the best.

    values[j][p] is the value in cents of item j to person p. An allocation is better when more
    people get a positive total, then when the product of those totals is larger. Among
    allocations that tie exactly, the one that gives people the most even numbers of items wins
    (smallest sum of squares), and then the first one in lexicographic order of the owner list.
    """
    m = len(values)
    totals = [0] * n_people
    counts = [0] * n_people
    owner = [0] * m
    people = range(n_people)
    best_key = (-1, -1)
    # key, evenness, owner, how many reach the key, how many of those have this evenness
    state: list[Any] = [best_key, 0, (), 0, 0]

    def visit(j: int) -> None:
        row = values[j]
        for p in people:
            totals[p] += row[p]
            counts[p] += 1
            owner[j] = p
            if j + 1 < m:
                visit(j + 1)
            else:
                positive = 0
                product = 1
                for total in totals:
                    if total:
                        positive += 1
                        product *= total
                key = (positive, product)
                if key >= state[0]:
                    evenness = sum(c * c for c in counts)
                    if key > state[0]:
                        state[:] = [key, evenness, tuple(owner), 1, 1]
                    else:
                        state[3] += 1
                        if evenness < state[1]:
                            state[1], state[2], state[4] = evenness, tuple(owner), 1
                        elif evenness == state[1]:
                            state[4] += 1
            totals[p] -= row[p]
            counts[p] -= 1

    visit(0)
    (positive, product), evenness, best_owner, n_optimal, n_best_even = state
    return NashSearch(best_owner, positive, product, n_optimal, evenness, n_best_even)


def round_robin(
    cents: dict[str, dict[str, int]], items: Sequence[str], order: Sequence[str]
) -> list[tuple[str, str]]:
    """People take turns in the given order, each taking the remaining item they value most.

    A tie between items goes to the first of them in the order of their names. Returns the picks
    in the order they were made.
    """
    rank = {item: index for index, item in enumerate(sorted(items))}
    remaining = sorted(items)
    picks: list[tuple[str, str]] = []
    turn = 0
    while remaining:
        person = order[turn % len(order)]
        item = max(remaining, key=lambda g: (cents[person][g], -rank[g]))
        remaining.remove(item)
        picks.append((person, item))
        turn += 1
    return picks


@dataclass
class Ef1Step:
    """How one item set aside removes the envy of person i for person k."""

    item: str | None  # the item i values most in k's package
    item_value: int
    rest: int  # the value of k's package to i without that item
    status: str  # EF1_NONE, EF1_HOLDS or EF1_FAILS


def ef1_step(
    cents: dict[str, dict[str, int]],
    bundles: dict[str, list[str]],
    i: str,
    k: str,
) -> Ef1Step:
    """Check person i against person k's package. Ties between items go to the first listed."""
    own = package_value(cents, i, bundles[i])
    other = package_value(cents, i, bundles[k])
    if other <= own:
        return Ef1Step(None, 0, other, EF1_NONE)
    # max() keeps the first of equal items, and the package is in listing order.
    item = max(bundles[k], key=lambda g: cents[i][g])
    rest = other - cents[i][item]
    return Ef1Step(item, cents[i][item], rest, EF1_HOLDS if rest <= own else EF1_FAILS)


# ---------------------------------------------------------------------------------------
# Numbers shared by the output
# ---------------------------------------------------------------------------------------


def number_text(amount_cents: Fraction) -> str:
    """An amount given in cents, as a decimal in units ('-25.00') or a fraction ('-1/3')."""
    if amount_cents.denominator == 1:
        return fc.cents_str(int(amount_cents))
    units = amount_cents / 100
    return f"{units.numerator}/{units.denominator}"


def product_text(product: int, factors: int) -> str:
    """A product of `factors` amounts in cents, written in units (72000 for 45.00 * 40 * 40)."""
    if factors == 0:
        return "0"  # nobody gets anything worth more than nothing
    scale = 10 ** (2 * factors)
    whole, rest = divmod(product, scale)
    digits = str(rest).rjust(2 * factors, "0").rstrip("0")
    return str(whole) + ("." + digits if digits else "")


def floor_cents(amount_cents: Fraction) -> int:
    """An exact amount in cents, rounded down to whole cents."""
    return math.floor(amount_cents)


# ---------------------------------------------------------------------------------------
# Computation
# ---------------------------------------------------------------------------------------


@dataclass
class Outcome:
    """Everything computed from a Problem. Amounts without a unit are integer cents."""

    problem: Problem
    used: str  # envy_free, knaster, max_nash or round_robin
    priority: Priority
    was_tie: bool  # the priority order had to settle a tie somewhere
    owner: dict[str, str]  # item -> person
    bundles: dict[str, list[str]]  # person -> items, in the order the items were listed
    own: dict[str, int]  # the value of the person's own items to the person
    cash: dict[str, int]  # positive when received, zero for everybody when no money moves
    worth: dict[str, int]  # own value plus cash
    view: dict[str, dict[str, int]]  # view[i][k]: k's items as i values them, plus k's cash
    envy: dict[str, dict[str, int]]  # envy[i][k]: how much more k's package is worth to i
    max_envy: int
    ef1: dict[tuple[str, str], Ef1Step]  # for each envious pair when no money moves
    tops: TopValuers | None = None
    total_best: int = 0  # the highest value of every item, added up
    worth_exact: Fraction | None = None  # envy_free: total_best / n, in cents
    exact_cash: dict[str, Fraction] = field(default_factory=dict)  # in cents, before rounding
    shares: dict[str, Fraction] = field(default_factory=dict)  # knaster: each person's share
    fair_exact: dict[str, Fraction] = field(default_factory=dict)  # knaster: share * own total
    totals: dict[str, int] = field(default_factory=dict)  # a person's values added up
    surplus: Fraction = Fraction(0)  # knaster, in cents
    nash: NashSearch | None = None
    allocations: int = 0  # n ** m, for max_nash
    picks: list[tuple[str, str]] = field(default_factory=list)  # round_robin

    @property
    def money(self) -> bool:
        """True when the rule settles with cash."""
        return self.used in ("envy_free", "knaster")

    @property
    def fell_back(self) -> bool:
        """True when max_nash had too many allocations to look at and took turns instead."""
        return self.used == USED_ROUND_ROBIN


def round_envy_free(
    problem: Problem, bundles: dict[str, list[str]], exact_cash: dict[str, Fraction]
) -> dict[str, int]:
    """Round the exact cash to cents so that the largest envy is smallest and the total is zero.

    A person's package plays the part of a room and the cash paid for it the part of its rent, so
    the search of the core applies as it stands (rent-split uses it for rents).
    """
    people, cents = problem.people, problem.cents
    prices = {p: -exact_cash[p] / 100 for p in people}
    bids = {
        i: {k: Fraction(package_value(cents, i, bundles[k]), 100) for k in people} for i in people
    }
    paid = fc.round_min_envy(prices, 0, bids, {p: p for p in people}, rounding_key(problem))
    return {p: -paid[p] for p in people}


def shares_of(problem: Problem) -> dict[str, Fraction]:
    """Each person's share of the whole: equal, or in proportion to the agreed weights."""
    if problem.weights is None:
        return {p: Fraction(1, len(problem.people)) for p in problem.people}
    total = sum(problem.weights.values(), Fraction(0))
    return {p: problem.weights[p] / total for p in problem.people}


def compute(problem: Problem) -> Outcome:
    """Solve a validated problem: the allocation, the cash, the checks that follow from it."""
    people, items, cents = problem.people, problem.items, problem.cents
    n, m = len(people), len(items)
    priority = priority_order(problem)
    extra: dict[str, Any] = {}
    used = problem.method
    tops: TopValuers | None = None
    cash = dict.fromkeys(people, 0)
    if problem.method in ("envy_free", "knaster"):
        tops = assign_to_top_valuers(cents, items, priority.order)
        owner = tops.owner
        bundles = bundles_of(owner, people, items)
        got = {p: package_value(cents, p, bundles[p]) for p in people}
        total_best = sum(tops.best.values())
        was_tie = bool(tops.needs_order)
        extra.update(tops=tops, total_best=total_best)
        if problem.method == "envy_free":
            worth_exact = Fraction(total_best, n)
            exact_cash = {p: worth_exact - got[p] for p in people}
            cash = round_envy_free(problem, bundles, exact_cash)
            extra.update(worth_exact=worth_exact, exact_cash=exact_cash)
        else:
            shares = shares_of(problem)
            totals = {p: sum(cents[p].values()) for p in people}
            fair_exact = {p: shares[p] * totals[p] for p in people}
            surplus = total_best - sum(fair_exact.values(), Fraction(0))
            exact_cash = {p: fair_exact[p] + shares[p] * surplus - got[p] for p in people}
            units = {p: exact_cash[p] / 100 for p in people}
            cash = fc.round_shares(units, 0, rounding_key(problem))
            extra.update(
                shares=shares,
                totals=totals,
                fair_exact=fair_exact,
                surplus=surplus,
                exact_cash=exact_cash,
            )
    else:
        allocations = n**m
        extra["allocations"] = allocations
        if allocations <= MAX_ALLOCATIONS:
            order = priority.order
            names = sorted(items)
            values = [[cents[p][g] for p in order] for g in names]
            found = search_max_nash(values, n)
            owner = {g: order[found.owner[j]] for j, g in enumerate(names)}
            was_tie = found.n_best_even > 1
            extra["nash"] = found
        else:
            used = USED_ROUND_ROBIN
            picks = round_robin(cents, items, priority.order)
            owner = {g: p for p, g in picks}
            was_tie = False
            extra["picks"] = picks
        bundles = bundles_of(owner, people, items)
    own = {p: package_value(cents, p, bundles[p]) for p in people}
    view = {i: {k: package_value(cents, i, bundles[k]) + cash[k] for k in people} for i in people}
    worth = {p: view[p][p] for p in people}
    envy = {i: {k: view[i][k] - worth[i] for k in people if view[i][k] > worth[i]} for i in people}
    max_envy = max((gap for row in envy.values() for gap in row.values()), default=0)
    money = used in ("envy_free", "knaster")
    ef1 = {} if money else {(i, k): ef1_step(cents, bundles, i, k) for i in people for k in envy[i]}
    outcome = Outcome(
        problem=problem,
        used=used,
        priority=priority,
        was_tie=was_tie,
        owner=owner,
        bundles=bundles,
        own=own,
        cash=cash,
        worth=worth,
        view=view,
        envy=envy,
        max_envy=max_envy,
        ef1=ef1,
        **extra,
    )
    verify(outcome)
    return outcome


def verify(outcome: Outcome) -> None:
    """Raise AssertionError unless the result keeps the promises of its rule (a bug otherwise)."""
    p = outcome.problem
    people, cents = p.people, p.cents
    if sorted(outcome.owner) != sorted(p.items) or not set(outcome.owner.values()) <= set(people):
        raise AssertionError("every item must go to exactly one listed person")
    if sum(outcome.cash.values()) != 0:
        raise AssertionError("the cash does not add up to zero")
    if outcome.used == "envy_free":
        worth = outcome.worth_exact
        if worth is None or sum(outcome.exact_cash.values(), Fraction(0)) != 0:
            raise AssertionError("the exact cash does not add up to zero")
        for i in people:
            mine = package_value(cents, i, outcome.bundles[i]) + outcome.exact_cash[i]
            if mine != worth:
                raise AssertionError(f"{i} does not end with the common worth")
            for k in people:
                theirs = package_value(cents, i, outcome.bundles[k]) + outcome.exact_cash[k]
                if theirs > mine:
                    raise AssertionError(f"{i} envies {k} in exact arithmetic")
        if outcome.max_envy > 1:
            raise AssertionError("rounding left an envy of more than one cent")
    elif outcome.used == "knaster":
        if outcome.surplus < 0 or sum(outcome.exact_cash.values(), Fraction(0)) != 0:
            raise AssertionError("the surplus is negative or the exact cash is not zero-sum")
        for i in people:
            if outcome.worth[i] < floor_cents(outcome.fair_exact[i]):
                raise AssertionError(f"{i} ends below the fair share")
    for (i, k), step in outcome.ef1.items():
        if step.status != EF1_HOLDS:
            raise AssertionError(f"{i} still envies {k} with one item set aside")
    for k, rounded in outcome.cash.items():
        exact = outcome.exact_cash.get(k)
        if exact is not None and abs(Fraction(rounded) - exact) >= 1:
            raise AssertionError("cash moved by a cent or more in rounding")


# ---------------------------------------------------------------------------------------
# Texts (zh is the default, en says the same)
# ---------------------------------------------------------------------------------------

TEXT: dict[str, dict[str, Any]] = {
    "zh": {
        "sep": "、",
        "end": "。",
        "arrow": " → ",
        "nothing": "（没有东西）",
        "title": "分家当结果（{method}）：{people} 人分 {things}",
        "things_one": "{items} 件东西",
        "things_many": "{items} 件东西",
        "envying_one": "{k} 人",
        "envying_many": "{k} 人",
        "m_envy_free": "无嫉妒加转账",
        "m_knaster": "Knaster 暗标法",
        "m_max_nash": "不转钱，最大纳什福利",
        "m_round_robin": "不转钱，轮流挑",
        "rule_envy_free": (
            "每件东西给最看重它的人，再用现金把每个人最后得到的（东西加现金）调成一样多，"
            "这样没有人羡慕别人那一份（envy_free）"
        ),
        "rule_knaster_equal": (
            "每件东西给最看重它的人，每个人先得到自己全部估值的 1/{n}，多出来的盈余平分（knaster）"
        ),
        "rule_knaster_weighted": (
            "每件东西给最看重它的人，每个人先得到按权重算出的份额（{weights}），"
            "多出来的盈余按份额分（knaster）"
        ),
        "rule_max_nash": (
            "不转钱，在所有分法里选让更多人分到东西、各人所得估值乘积最大的一种，"
            "保证去掉一件东西后没有人羡慕，也没有别的分法能让每个人都不吃亏而有人更好（max_nash）"
        ),
        "n_rule": "分法（事先定好，结果出来后不再改）：{rule}。",
        "n_note": "备注：{note}",
        "cash_in": "收到 {amount}",
        "cash_out": "付出 {amount}",
        "cash_none": "没有往来",
        "t1_cap": "谁拿什么",
        "t1_hdr_money": [
            "人",
            "拿到的东西",
            "按本人估值",
            "现金（收为正，付为负）",
            "最后合计（估值 + 现金）",
        ],
        "t1_hdr_plain": ["人", "拿到的东西", "按本人估值", "全部东西按本人估值合计"],
        "t_total": "合计",
        "t_person": "人",
        "t2_cap_money": (
            "羡慕表（按本人估值：列出的那个人拿到的东西的估值，加上他的现金。"
            "带 * 的是本人那一份，数越大越划算）"
        ),
        "t2_cap_plain": (
            "羡慕表（按本人估值：列出的那个人拿到的东西的估值，带 * 的是本人那一份，数越大越划算）"
        ),
        "t2_cash_row": "现金",
        "t3_cap": "每件东西的最高估值",
        "t3_hdr": ["东西", "最高估值", "估值最高的人", "拿到的人"],
        "t4_cap": "Knaster 的计算（表中的金额只在显示时取整到分，现金是对精确值一次取整得到的）",
        "t4_hdr": [
            "人",
            "份额",
            "公平份额（向下取到分）",
            "拿到的东西值",
            "分到的盈余",
            "最后合计",
            "现金",
        ],
        "t5_cap": "去掉一件东西后的核对（只列出羡慕别人的人）",
        "t5_hdr": [
            "谁",
            "羡慕谁",
            "自己那份",
            "对方那份",
            "对方那份里最看重的一件",
            "去掉这件后对方那份",
            "结论",
        ],
        "ef1_ok": "去掉后不羡慕",
        "ef1_fail": "去掉后仍羡慕（EF1 不成立）",
        "t6_cap": "轮流挑的过程",
        "t6_hdr": ["轮", "谁挑了什么（按挑选顺序）"],
        "t6_pick": "{person}：{item}",
        "n_ef_exact": (
            "结果：每件东西都给了最看重它的人。所有东西的最高估值加起来是 {total}，"
            "除以 {n} 个人，每个人最后得到的（东西加现金）都是 {worth}。"
        ),
        "n_ef_round": (
            "结果：每件东西都给了最看重它的人。所有东西的最高估值加起来是 {total}，"
            "每个人最后得到的（东西加现金）精确值都是它的 1/{n}，取整到分后是 {low} 或 {high}。"
        ),
        "n_envy_zero": (
            "取整到分后，没有人羡慕任何人（最大羡慕 0.00）。现金只向下或向上取到分，总额恰好是 0。"
        ),
        "n_envy_some": (
            "取整到分后，最大羡慕是 {amount}：精确值下没有人羡慕，这是取整造成的，最多差 0.01。"
            "现金只向下或向上取到分，总额恰好是 0。"
        ),
        "n_kn_basis_equal": "全部东西按本人估值合计的 1/{n}",
        "n_kn_basis_weighted": "全部东西按本人估值合计，乘以按权重算出的份额",
        "n_kn_result": (
            "结果：每件东西都给了最看重它的人，最高估值加起来是 {total}。"
            "每个人先得到公平份额（{basis}），公平份额加起来约 {fair}，"
            "多出来的盈余约 {surplus} 按份额分给大家（这两个数只在显示时取整到分）。"
            "现金只向下或向上取到分，总额恰好是 0。"
        ),
        "n_kn_envy_none": "Knaster 不保证没有人羡慕。本次没有人羡慕别人那一份。",
        "n_kn_envy_some": (
            "Knaster 不保证没有人羡慕。本次有 {envying}按自己的估值羡慕别人那一份（见羡慕表），"
            "最大的羡慕是 {amount}。"
        ),
        "n_nash_result": (
            "结果：逐一核对了全部 {allocations} 种分法，选出让更多人分到东西、"
            "各人所得估值乘积最大的一种（{positive} 人所得大于 0，乘积 {product}）。"
        ),
        "n_nash_envy_none": "按各人自己的估值，没有人羡慕别人那一份。",
        "n_nash_envy_some": (
            "有 {envying}按自己的估值羡慕别人那一份（见羡慕表）。每一处羡慕，去掉对方那份里的一件东西"
            "就没有了（见下表）。这是去掉一件后不羡慕（EF1），不是完全没有人羡慕。"
        ),
        "n_rr_fallback": (
            "东西太多：{people} 个人分 {items} 件东西有 {allocations} 种分法，"
            "超过逐一核对的上限 {limit}，所以改用轮流挑，没有用最大纳什福利。"
            "轮流挑只保证去掉一件东西后没有人羡慕（EF1），不保证帕累托有效。挑选顺序：{order}。"
        ),
        "n_rr_envy_none": "按各人自己的估值，没有人羡慕别人那一份。",
        "n_rr_envy_some": (
            "有 {envying}按自己的估值羡慕别人那一份（见羡慕表）。每一处羡慕，去掉对方那份里的一件东西"
            "就没有了（见下表）。"
        ),
        "n_order_names": "挑选顺序按姓名排序，偏向名字靠前的人。想避免，下次在规则消息里写一个公开随机源。",
        "n_order_seed": "挑选顺序来自规则里的公开随机源。种子（SHA-256）：{seed}。算法见 fsq_core 的 SEED_SPEC。",
        "n_tie_money_seed": (
            "有几件东西的最高估值并列{items}。并列时先给手里东西最少的人，再按优先顺序，"
            "优先顺序来自规则里的公开随机源。种子（SHA-256）：{seed}。算法见 fsq_core 的 SEED_SPEC。"
            "这只决定谁拿东西、谁收付现金，每个人最后的合计不变。"
        ),
        "n_tie_money_names": (
            "有几件东西的最高估值并列{items}。并列时先给手里东西最少的人，再按姓名排序，"
            "偏向名字靠前的人。想避免，下次在规则消息里写一个公开随机源。"
            "这只决定谁拿东西、谁收付现金，每个人最后的合计不变。"
        ),
        "n_tie_nash_seed": (
            "有 {count} 种分法的纳什福利并列最大。先选各人拿到的东西件数最平均的，"
            "还并列就按优先顺序选第一种，优先顺序来自规则里的公开随机源。"
            "种子（SHA-256）：{seed}。算法见 fsq_core 的 SEED_SPEC。"
        ),
        "n_tie_nash_names": (
            "有 {count} 种分法的纳什福利并列最大。先选各人拿到的东西件数最平均的，"
            "还并列就按姓名排序选第一种，偏向名字靠前的人。想避免，下次在规则消息里写一个公开随机源。"
        ),
        "tie_items": "（{items}）",
        "n_tie_money_spread": (
            "有几件东西的最高估值并列{items}。并列时先给手里东西最少的人，这一步就分出了结果，"
            "用不到优先顺序。这只决定谁拿东西、谁收付现金，每个人最后的合计不变。"
        ),
        "n_tie_nash_even": (
            "有 {count} 种分法的纳什福利并列最大。其中各人拿到的东西件数最平均的只有一种，"
            "选了它，用不到优先顺序。"
        ),
        "n_seed_unused": "规则里给了公开随机源，但这次没有用到它。",
        "n_nobody": (
            "没有人想要：{items}（每个人的估值都是 0）。它们按上面的并列规则分给了某人，"
            "要不要留下，由大家另行商量。"
        ),
        "n_one_liners": "每人一句话（只发给本人，不要贴到群里）：",
        "n_one_liner": "- {name}：{text}",
        "d_items": "拿到 {pkg}，值 {own}；现金：{cash}",
        "d_none": "没有拿到东西；现金：{cash}",
        "cert_ef": (
            "按你的估值，你的合计是 {worth}（{detail}）。换成别人任何一份（那份东西按你的估值，"
            "加上那个人的现金），你得到的都不会比 {worth} 更多，所以你不羡慕任何人"
        ),
        "cert_ef_round": (
            "按你的估值，你的合计是 {worth}（{detail}）。精确值下换成别人任何一份都不会更多。"
            "取整到分后，{who}那份（东西加现金）比你的多 {amount}，这是取整造成的"
        ),
        "cert_kn": (
            "按你的估值，你的公平份额是 {fair}（你给全部东西的估值合计 {total}，乘以你的份额 {share}，"
            "向下取到分）。你的合计是 {worth}（{detail}），不少于它"
        ),
        "cert_kn_envy_none": "按你的估值，没有人那一份（东西加现金）比你的多",
        "cert_kn_envy_some": (
            "按你的估值，{who}那一份（东西加现金）值 {theirs}，比你的 {worth} 多 {amount}，"
            "所以你羡慕{who}。Knaster 不保证没有人羡慕"
        ),
        "cert_plain_none": "按你的估值，没有人那一份比你的 {own} 多，你不羡慕任何人",
        "cert_plain_envy": (
            "按你的估值，{who}那份值 {theirs}，比你的 {own} 多 {amount}。去掉那份里你最看重的"
            "{item}（值 {value}）后只剩 {rest}，不比你的多，所以去掉一件后你不羡慕{who}"
        ),
        "cert_plain_fail": (
            "按你的估值，{who}那份值 {theirs}，比你的 {own} 多 {amount}，去掉一件后仍然羡慕"
        ),
        "cert_plain_rest": "其余的人那一份都不比你的多",
        "cert_join": "；",
        "dm_head": "{name}，这是只给你的分家当结果，别人看不到你的估值。",
        "dm_fallback": (
            "注意：东西太多，没法逐一核对全部分法，这次改用轮流挑，没有用最大纳什福利。"
            "轮流挑只保证去掉一件东西后没有人羡慕（EF1），不保证帕累托有效。"
        ),
        "dm_pkg": "你拿到：{pkg}，按你的估值共 {own}。",
        "dm_pkg_none": "你没有拿到东西。",
        "dm_cash": "现金：{cash}。你的合计（东西的估值 + 现金）是 {worth}。",
        "dm_table_money": (
            "你的核对表（每人一行：他拿到的东西按你的估值是多少，加上他的现金，带 * 的是你自己的）："
        ),
        "dm_table_plain": "你的核对表（每人一行：他拿到的东西按你的估值是多少，带 * 的是你自己的）：",
        "dm_row_money": "  {owner}：{pkg}，估值 {value}，现金 {cash}，合计 {total}{star}",
        "dm_row_plain": "  {owner}：{pkg}，估值 {value}{star}",
        "g_person_money": "{name} 拿 {pkg}，现金：{cash}",
        "g_person_plain": "{name} 拿 {pkg}",
        "g_person_money_none": "{name} 没有拿到东西，现金：{cash}",
        "g_person_plain_none": "{name} 没有拿到东西",
        "g_cash_total": "现金合计 {sum}。",
        "g_ef_exact": (
            "保证：按各人私下报的估值，每个人最后得到的（东西加现金）都是 {worth}，"
            "没有人想把自己的一份换成别人的一份（取整到分后最多差 {amount}）。"
            "每个人会收到一条只含自己数字的私信，可以自己核对。"
        ),
        "g_ef_range": (
            "保证：按各人私下报的估值，每个人最后得到的（东西加现金）在 {low} 和 {high} 之间，"
            "只差取整到分的零头，没有人想把自己的一份换成别人的一份（取整到分后最多差 {amount}）。"
            "每个人会收到一条只含自己数字的私信，可以自己核对。"
        ),
        "g_kn": (
            "保证：每个人最后得到的不少于自己的公平份额（向下取到分）。{envy}"
            "每个人会收到一条只含自己数字的私信，可以自己核对。"
        ),
        "g_kn_envy_none": "不保证没有人羡慕，本次没有人羡慕别人那一份。",
        "g_kn_envy_some": "不保证没有人羡慕，本次有 {envying}按自己的估值羡慕别人那一份。",
        "g_nash": (
            "保证：去掉一件东西之后，没有人羡慕别人那一份（EF1）；没有别的分法能让每个人都不吃亏、"
            "其中有人更好（帕累托有效）。{envy}每个人会收到一条只含自己数字的私信，可以自己核对。"
        ),
        "g_nash_envy_none": "本次没有人羡慕别人那一份。",
        "g_nash_envy_some": (
            "不保证完全没有人羡慕，本次有 {envying}按自己的估值羡慕别人那一份，去掉一件就不羡慕了。"
        ),
        "g_rr": (
            "东西太多（{people} 人分 {items} 件有 {allocations} 种分法，超过上限 {limit}），"
            "没法逐一核对，改用轮流挑，挑选顺序：{order}。保证：去掉一件东西之后，"
            "没有人羡慕别人那一份（EF1）。不保证帕累托有效。{envy}"
            "每个人会收到一条只含自己数字的私信，可以自己核对。"
        ),
        "g_rr_envy_none": "本次没有人羡慕别人那一份。",
        "g_rr_envy_some": "本次有 {envying}按自己的估值羡慕别人那一份，去掉一件就不羡慕了。",
        "nm_additive": (
            "估值按件相加：两件东西合起来比分开更值钱（比如电视和电视柜）时，请把它们当成一件来报。"
        ),
        "nm_budget": "有人一时拿不出现金的情形：脚本不看预算，也不处理分期。",
        "nm_whole": "东西都按整件、按大家共有处理：不处理拆开、卖掉或扔掉。",
        "nm_strategy": "防策略：三种分法都不能防止有人谎报估值。",
        "s_title": "钢琴的例子：同一组估值，两种有现金的分法",
        "s_hdr": [
            "人",
            "钢琴",
            "Knaster：现金",
            "Knaster：合计",
            "无嫉妒加转账：现金",
            "无嫉妒加转账：合计",
        ],
        "s_has": "拿到",
        "s_hasnt": "没拿到",
        "s_note": (
            "同一组估值，两种有现金的分法。Knaster 里，{envier}按自己的估值，看{target}那一份"
            "（东西加现金）值 {view}，比自己的 {worth} 多 {gap}，所以羡慕{target}。"
            "无嫉妒加转账里，每个人的合计都是 {equal}，没有人羡慕。"
            "两种分法各有取舍：Knaster 让每个人先拿到自己的公平份额，再按份额分盈余，"
            "但可能有人羡慕；无嫉妒加转账保证没有人羡慕，但盈余不一定平分，"
            "有人拿到的比 Knaster 里少（{lower}）。"
            "看完结果再表决的话，{kn}会选 Knaster，{ef}会选无嫉妒加转账，"
            "所以分法必须在收估值之前定好。"
        ),
        "s_lower": "{name}在 Knaster 里是 {a}，这里是 {b}",
    },
    "en": {
        "sep": ", ",
        "end": ".",
        "arrow": " -> ",
        "nothing": "(no items)",
        "title": "Stuff split result ({method}): {people} people share {things}",
        "things_one": "{items} item",
        "things_many": "{items} items",
        "envying_one": "{k} person envies",
        "envying_many": "{k} people envy",
        "m_envy_free": "envy-free with cash",
        "m_knaster": "Knaster's sealed bids",
        "m_max_nash": "no cash, maximum Nash welfare",
        "m_round_robin": "no cash, taking turns",
        "rule_envy_free": (
            "every item goes to a person who values it most, and cash then makes everybody's "
            "final worth (the value of their items plus their cash) the same, so nobody envies "
            "anybody's package (envy_free)"
        ),
        "rule_knaster_equal": (
            "every item goes to a person who values it most, everybody is first owed 1/{n} of "
            "their own total value, and the surplus is shared equally (knaster)"
        ),
        "rule_knaster_weighted": (
            "every item goes to a person who values it most, everybody is first owed the share "
            "given by the agreed weights ({weights}) of their own total value, and the surplus "
            "is shared in proportion to the shares (knaster)"
        ),
        "rule_max_nash": (
            "no money moves, and the allocation taken is the one that gives something to the "
            "most people and then has the largest product of the values people receive. It "
            "leaves nobody envious once one item is set aside, and no other allocation is at "
            "least as good for everybody and better for somebody (max_nash)"
        ),
        "n_rule": "Rule (fixed in advance, not changed after the result): {rule}.",
        "n_note": "Note: {note}",
        "cash_in": "receives {amount}",
        "cash_out": "pays {amount}",
        "cash_none": "none",
        "t1_cap": "Who gets what",
        "t1_hdr_money": [
            "Person",
            "Items",
            "Value to the person",
            "Cash (received is positive)",
            "Final worth (value + cash)",
        ],
        "t1_hdr_plain": [
            "Person",
            "Items",
            "Value to the person",
            "All items, by the person's values",
        ],
        "t_total": "Total",
        "t_person": "Person",
        "t2_cap_money": (
            "Envy table (by the row person's values: the value of the listed person's items plus "
            "that person's cash. The package marked * is the row person's own, a larger number "
            "is a better deal)"
        ),
        "t2_cap_plain": (
            "Envy table (by the row person's values: the value of the listed person's items. "
            "The package marked * is the row person's own, a larger number is a better deal)"
        ),
        "t2_cash_row": "Cash",
        "t3_cap": "The highest value of each item",
        "t3_hdr": ["Item", "Highest value", "People with it", "Gets it"],
        "t4_cap": (
            "Knaster's computation (amounts in this table are rounded to the cent for display "
            "only, while the cash is rounded once from the exact values)"
        ),
        "t4_hdr": [
            "Person",
            "Share",
            "Fair share (rounded down to the cent)",
            "Value of the items received",
            "Surplus received",
            "Final worth",
            "Cash",
        ],
        "t5_cap": "Check with one item set aside (only the people who envy somebody)",
        "t5_hdr": [
            "Person",
            "Envies",
            "Own package",
            "Their package",
            "Item valued most in it",
            "Their package without it",
            "Result",
        ],
        "ef1_ok": "no envy once it is set aside",
        "ef1_fail": "still envious (EF1 fails)",
        "t6_cap": "How the turns went",
        "t6_hdr": ["Round", "Who took what (in picking order)"],
        "t6_pick": "{person}: {item}",
        "n_ef_exact": (
            "Result: every item went to a person who values it most. The highest values add up "
            "to {total}. Divided among the {n} people, that is {worth}, which is what each "
            "person ends with (items plus cash)."
        ),
        "n_ef_round": (
            "Result: every item went to a person who values it most. The highest values add up "
            "to {total}, and each person's final worth (items plus cash) is exactly 1/{n} of it. "
            "After rounding to the cent it is {low} or {high}."
        ),
        "n_envy_zero": (
            "After rounding to the cent, nobody envies anybody (largest envy 0.00). Each cash "
            "amount is rounded only down or up to the cent, and the total is exactly 0."
        ),
        "n_envy_some": (
            "After rounding to the cent, the largest envy is {amount}. There is no envy at the "
            "exact values, so this is caused by rounding and is at most 0.01. Each cash amount "
            "is rounded only down or up to the cent, and the total is exactly 0."
        ),
        "n_kn_basis_equal": "1/{n} of the person's total value of all items",
        "n_kn_basis_weighted": (
            "the person's total value of all items times the share given by the weights"
        ),
        "n_kn_result": (
            "Result: every item went to a person who values it most, and the highest values add "
            "up to {total}. Everybody is first owed a fair share ({basis}). The fair shares add "
            "up to about {fair}, and the surplus of about {surplus} is shared in proportion to "
            "the shares (these two figures are rounded to the cent for display only). Each cash "
            "amount is rounded only down or up to the cent, and the total is exactly 0."
        ),
        "n_kn_envy_none": (
            "Knaster does not promise that nobody envies anybody. This time nobody envies "
            "another person's package."
        ),
        "n_kn_envy_some": (
            "Knaster does not promise that nobody envies anybody. This time {envying} "
            "another person's package by their own values (see the envy table), by {amount} "
            "at most."
        ),
        "n_nash_result": (
            "Result: all {allocations} allocations were checked one by one, and the one was "
            "taken that gives something to most people and then has the largest product of the "
            "values people receive ({positive} people receive more than nothing, product "
            "{product})."
        ),
        "n_nash_envy_none": "By everybody's own values, nobody envies another person's package.",
        "n_nash_envy_some": (
            "{envying} another person's package by their own values (see the envy table). "
            "Every such envy disappears once one item is set aside from the package (see the "
            "table below). This is envy-free up to one item (EF1), not freedom from all envy."
        ),
        "n_rr_fallback": (
            "Too many items: {people} people sharing {items} items have {allocations} "
            "allocations, above the limit of {limit} that can be checked one by one. The "
            "script took turns instead and did not use maximum Nash welfare. Taking turns "
            "only promises that nobody envies anybody once one item is set aside (EF1), and "
            "does not promise Pareto efficiency. Picking order: {order}."
        ),
        "n_rr_envy_none": "By everybody's own values, nobody envies another person's package.",
        "n_rr_envy_some": (
            "{envying} another person's package by their own values (see the envy table). "
            "Every such envy disappears once one item is set aside from the package (see the "
            "table below)."
        ),
        "n_order_names": (
            "The picking order is the names in sorted order, which favors names that sort first. "
            "To avoid that, put a public random source in the rules message next time."
        ),
        "n_order_seed": (
            "The picking order comes from the public random source in the rules. Seed "
            "(SHA-256): {seed}. The algorithm is SEED_SPEC in fsq_core."
        ),
        "n_tie_money_seed": (
            "Several items have a highest value that more than one person shares{items}. "
            "Such an item goes to the sharer who holds the fewest items so far, and then to the "
            "one who comes first in the priority order, which comes from the public random "
            "source in the rules. Seed (SHA-256): {seed}. The algorithm is SEED_SPEC in "
            "fsq_core. This only decides who holds the item and who pays or receives cash, and "
            "every person's final worth stays the same."
        ),
        "n_tie_money_names": (
            "Several items have a highest value that more than one person shares{items}. "
            "Such an item goes to the sharer who holds the fewest items so far, and then to the "
            "one whose name sorts first, which favors names that sort first. To avoid that, put "
            "a public random source in the rules message next time. This only decides who "
            "holds the item and who pays or receives cash, and every person's final worth "
            "stays the same."
        ),
        "n_tie_nash_seed": (
            "{count} allocations tie for the largest Nash welfare. The one is taken in which "
            "people hold the most even numbers of items, and if several still tie, the first "
            "one in the priority order, which comes from the public random source in the rules. "
            "Seed (SHA-256): {seed}. The algorithm is SEED_SPEC in fsq_core."
        ),
        "n_tie_nash_names": (
            "{count} allocations tie for the largest Nash welfare. The one is taken in which "
            "people hold the most even numbers of items, and if several still tie, the first "
            "one when the names are sorted, which favors names that sort first. To avoid that, "
            "put a public random source in the rules message next time."
        ),
        "tie_items": " ({items})",
        "n_tie_money_spread": (
            "Several items have a highest value that more than one person shares{items}. "
            "Such an item goes to the sharer who holds the fewest items so far, which settled "
            "every one of them, so no priority order was needed. This only decides who holds "
            "the item and who pays or receives cash, and every person's final worth stays the "
            "same."
        ),
        "n_tie_nash_even": (
            "{count} allocations tie for the largest Nash welfare. Exactly one of them gives "
            "people the most even numbers of items, and it was taken, so no priority order "
            "was needed."
        ),
        "n_seed_unused": (
            "The rules name a public random source, but it was not needed this time."
        ),
        "n_nobody": (
            "Nobody wants {items} (everybody's value is 0). They were given out by the tie "
            "rule above, and the group can decide separately whether to keep them."
        ),
        "n_one_liners": "One line per person (send it to that person only, not to the group):",
        "n_one_liner": "- {name}: {text}",
        "d_items": "you hold {pkg}, worth {own} to you; cash: {cash}",
        "d_none": "you hold no items; cash: {cash}",
        "cert_ef": (
            "By your values, your final worth is {worth} ({detail}). If you swapped for any other "
            "person's package (that package as you value it, plus that person's cash), you would "
            "get no more than {worth}, so you envy nobody"
        ),
        "cert_ef_round": (
            "By your values, your final worth is {worth} ({detail}). At the exact values no "
            "swap would give you more. After rounding to the cent, the package of {who} (items "
            "plus cash) is {amount} more than yours, which comes from rounding"
        ),
        "cert_kn": (
            "By your values, your fair share is {fair} (your values of all items add up to "
            "{total}, times your share {share}, rounded down to the cent). Your final worth is "
            "{worth} ({detail}), which is not less"
        ),
        "cert_kn_envy_none": (
            "By your values, nobody's package (items plus cash) is worth more than yours"
        ),
        "cert_kn_envy_some": (
            "By your values, the package of {who} (items plus cash) is worth {theirs}, which "
            "is {amount} more than your {worth}, so you envy {who}. Knaster does not promise "
            "that nobody envies anybody"
        ),
        "cert_plain_none": (
            "By your values, nobody's package is worth more than your {own}, so you envy nobody"
        ),
        "cert_plain_envy": (
            "By your values, the package of {who} is worth {theirs}, which is {amount} more "
            "than your {own}. Without {item}, the item in it you value most (worth {value}), "
            "it is worth {rest} and no more than yours, so you do not envy {who} once one item "
            "is set aside"
        ),
        "cert_plain_fail": (
            "By your values, the package of {who} is worth {theirs}, which is {amount} more "
            "than your {own}, and you still envy it with one item set aside"
        ),
        "cert_plain_rest": "Every other package is worth no more than yours",
        "cert_join": ". ",
        "dm_head": "{name}, this is your own result. Nobody else can see your values.",
        "dm_fallback": (
            "Important: there were too many items to check every allocation, so this time the script "
            "took turns and did not use maximum Nash welfare. Taking turns only promises that "
            "nobody envies anybody once one item is set aside (EF1), and does not promise "
            "Pareto efficiency."
        ),
        "dm_pkg": "You get: {pkg}, worth {own} by your values.",
        "dm_pkg_none": "You get no items.",
        "dm_cash": "Cash: {cash}. Your final worth (value of the items + cash) is {worth}.",
        "dm_table_money": (
            "Your check table (one row per person: what their items are worth by your values, "
            "plus their cash, and the row marked * is your own):"
        ),
        "dm_table_plain": (
            "Your check table (one row per person: what their items are worth by your values, "
            "and the row marked * is your own):"
        ),
        "dm_row_money": "  {owner}: {pkg}, value {value}, cash {cash}, total {total}{star}",
        "dm_row_plain": "  {owner}: {pkg}, value {value}{star}",
        "g_person_money": "{name} gets {pkg}, cash: {cash}",
        "g_person_plain": "{name} gets {pkg}",
        "g_person_money_none": "{name} gets no items, cash: {cash}",
        "g_person_plain_none": "{name} gets no items",
        "g_cash_total": "The cash adds up to {sum}.",
        "g_ef_exact": (
            "Guarantee: by the values each person gave in private, everybody's final worth (items "
            "plus cash) is {worth}, and nobody wants to swap their package for another person's "
            "(after rounding to the cent the difference is at most {amount}). Everybody gets a "
            "private message with only their own numbers, so each person can check it."
        ),
        "g_ef_range": (
            "Guarantee: by the values each person gave in private, everybody's final worth (items "
            "plus cash) is between {low} and {high}, which differ only by rounding to the cent, "
            "and nobody wants to swap their package for another person's (after rounding to the "
            "cent the difference is at most {amount}). Everybody gets a private message with "
            "only their own numbers, so each person can check it."
        ),
        "g_kn": (
            "Guarantee: everybody ends with at least their own fair share (rounded down to the "
            "cent). {envy} Everybody gets a private message with only their own numbers, so each "
            "person can check it."
        ),
        "g_kn_envy_none": "Nobody is promised freedom from envy, and this time nobody envies anybody.",
        "g_kn_envy_some": (
            "Nobody is promised freedom from envy, and this time {envying} another "
            "person's package by their own values."
        ),
        "g_nash": (
            "Guarantee: once one item is set aside, nobody envies another person's package "
            "(EF1), and no other allocation is at least as good for everybody and better for "
            "somebody (Pareto efficient). {envy} Everybody gets a private message with only "
            "their own numbers, so each person can check it."
        ),
        "g_nash_envy_none": "This time nobody envies another person's package.",
        "g_nash_envy_some": (
            "Freedom from all envy is not promised, and this time {envying} another "
            "person's package by their own values, which goes away once one item is set aside."
        ),
        "g_rr": (
            "Too many items ({people} people sharing {items} items have {allocations} "
            "allocations, above the limit of {limit}), so they could not be checked one by one "
            "and the script took turns instead. Picking order: {order}. Guarantee: once one "
            "item is set aside, nobody envies another person's package (EF1). Pareto efficiency "
            "is not promised. {envy} Everybody gets a private message with only their own "
            "numbers, so each person can check it."
        ),
        "g_rr_envy_none": "This time nobody envies another person's package.",
        "g_rr_envy_some": (
            "This time {envying} another person's package by their own values, which goes "
            "away once one item is set aside."
        ),
        "nm_additive": (
            "Values that add up: when two items are worth more together than apart (a TV and "
            "its stand), please enter them as one item."
        ),
        "nm_budget": (
            "People who cannot come up with the cash for now: the script does not look at "
            "budgets and does not handle instalments."
        ),
        "nm_whole": (
            "Items are treated as whole and as shared by everybody: no splitting, selling or "
            "throwing away."
        ),
        "nm_strategy": (
            "Strategy-proofness: none of the three rules stops somebody from misreporting their "
            "values."
        ),
        "s_title": "The piano example: the same values under two rules with cash",
        "s_hdr": [
            "Person",
            "Piano",
            "Knaster: cash",
            "Knaster: final worth",
            "Envy-free: cash",
            "Envy-free: final worth",
        ],
        "s_has": "gets it",
        "s_hasnt": "does not",
        "s_note": (
            "The same values under two rules with cash. Under Knaster, {envier} values the "
            "package of {target} (items plus cash) at {view}, which is {gap} more than their own "
            "{worth}, so {envier} envies {target}. Under envy-free with cash, everybody's final "
            "worth is {equal} and nobody envies anybody. The two rules are a trade-off. Knaster "
            "gives everybody their fair share first and then shares the surplus in proportion "
            "to the shares, but somebody may envy somebody. Envy-free with cash promises that "
            "nobody envies anybody, but the surplus is not necessarily shared equally, and "
            "somebody gets less than under Knaster ({lower}). If the group voted after seeing "
            "the results, {kn} would choose Knaster and {ef} would choose envy-free with cash, "
            "so the rule has to be fixed before the values are collected."
        ),
        "s_lower": "{name} has {a} under Knaster and {b} here",
    },
}


def say(lang: str, key: str, **values: Any) -> str:
    """Fill the text template of this key (see fsq_core.fill_text for the Latin-name spacing)."""
    return fc.fill_text(lang, TEXT[lang][key], **values)


def envying(lang: str, count: int) -> str:
    """The people who envy somebody, with the verb in English: 1 person envies, 2 people envy."""
    return say(lang, "envying_one" if count == 1 else "envying_many", k=count)


def joined(lang: str, items: Iterable[str]) -> str:
    """Names joined with the separator of the language."""
    return TEXT[lang]["sep"].join(items)


def plus(cents: int) -> str:
    """An amount of cash for a table cell: received is positive and written with a sign."""
    return "+" + fmt(cents) if cents > 0 else fmt(cents)


def cash_text(lang: str, cents: int) -> str:
    """Cash in words: received, paid or none."""
    key = "cash_in" if cents > 0 else "cash_out" if cents < 0 else "cash_none"
    return say(lang, key, amount=fmt(abs(cents)))


def package_text(lang: str, items: Sequence[str]) -> str:
    """The items of a package, or a word for nothing."""
    return joined(lang, items) if items else TEXT[lang]["nothing"]


def share_text(share: Fraction) -> str:
    """A share such as 1/3 or 1/2."""
    return f"{share.numerator}/{share.denominator}"


def rule_text(problem: Problem, lang: str) -> str:
    """The agreed rule in one sentence (the rule the group chose, also when turns replaced it)."""
    if problem.method == "knaster":
        if problem.weights is None:
            return say(lang, "rule_knaster_equal", n=len(problem.people))
        shares = shares_of(problem)
        weights = joined(lang, [f"{name} {share_text(shares[name])}" for name in problem.people])
        return say(lang, "rule_knaster_weighted", weights=weights)
    return say(lang, "rule_" + problem.method)


def order_text(outcome: Outcome, lang: str) -> str:
    """The tie-break or picking order of the people."""
    return TEXT[lang]["arrow"].join(outcome.priority.order)


def envious(outcome: Outcome) -> list[str]:
    """The people who envy somebody, in the order they were listed."""
    return [name for name in outcome.problem.people if outcome.envy[name]]


def detail_text(outcome: Outcome, name: str, lang: str) -> str:
    """The parts of a person's final worth: the items, what they are worth, and the cash."""
    cash = cash_text(lang, outcome.cash[name])
    items = outcome.bundles[name]
    if not items:
        return say(lang, "d_none", cash=cash)
    return say(
        lang,
        "d_items",
        pkg=package_text(lang, items),
        own=fmt(outcome.own[name]),
        cash=cash,
    )


def certificate_line(outcome: Outcome, name: str, lang: str = "zh") -> str:
    """The certificate of one person in the person's own numbers (a few clauses, one sentence)."""
    o, p = outcome, outcome.problem
    others = [k for k in p.people if k != name]
    if o.used == "envy_free":
        better = [k for k in others if o.view[name][k] > o.worth[name]]
        if better:
            gap = max(o.view[name][k] - o.worth[name] for k in better)
            who = joined(lang, [k for k in better if o.view[name][k] - o.worth[name] == gap])
            head = say(
                lang,
                "cert_ef_round",
                worth=fmt(o.worth[name]),
                detail=detail_text(o, name, lang),
                who=who,
                amount=fmt(gap),
            )
        else:
            head = say(lang, "cert_ef", worth=fmt(o.worth[name]), detail=detail_text(o, name, lang))
        return head + TEXT[lang]["end"]
    if o.used == "knaster":
        share = shares_of(p)[name]
        head = say(
            lang,
            "cert_kn",
            fair=fmt(floor_cents(o.fair_exact[name])),
            total=fmt(o.totals[name]),
            share=share_text(share),
            worth=fmt(o.worth[name]),
            detail=detail_text(o, name, lang),
        )
        if o.envy[name]:
            gap = max(o.envy[name].values())
            target = [k for k in others if o.envy[name].get(k) == gap]
            tail = say(
                lang,
                "cert_kn_envy_some",
                who=joined(lang, target),
                theirs=fmt(o.worth[name] + gap),
                worth=fmt(o.worth[name]),
                amount=fmt(gap),
            )
        else:
            tail = TEXT[lang]["cert_kn_envy_none"]
        return head + TEXT[lang]["cert_join"] + tail + TEXT[lang]["end"]
    # No money moves: the check is envy up to one item.
    if not o.envy[name]:
        return say(lang, "cert_plain_none", own=fmt(o.own[name])) + TEXT[lang]["end"]
    clauses = []
    for k in others:
        if k not in o.envy[name]:
            continue
        step = o.ef1[(name, k)]
        values = {
            "who": k,
            "theirs": fmt(o.view[name][k]),
            "own": fmt(o.own[name]),
            "amount": fmt(o.envy[name][k]),
        }
        if step.status == EF1_HOLDS:
            clauses.append(
                say(
                    lang,
                    "cert_plain_envy",
                    item=step.item,
                    value=fmt(step.item_value),
                    rest=fmt(step.rest),
                    **values,
                )
            )
        else:
            clauses.append(say(lang, "cert_plain_fail", **values))
    if len(clauses) < len(others):
        clauses.append(TEXT[lang]["cert_plain_rest"])
    return TEXT[lang]["cert_join"].join(clauses) + TEXT[lang]["end"]


# ---------------------------------------------------------------------------------------
# Tables, notes, messages
# ---------------------------------------------------------------------------------------


def _tables(outcome: Outcome, lang: str) -> list[fc.Table]:
    t, o, p = TEXT[lang], outcome, outcome.problem
    tables: list[fc.Table] = []
    rows = []
    for name in p.people:
        row = [name, package_text(lang, o.bundles[name]), fmt(o.own[name])]
        if o.money:
            row += [plus(o.cash[name]), fmt(o.worth[name])]
        else:
            row += [fmt(sum(p.cents[name].values()))]
        rows.append(row)
    total = [t["t_total"], "", fmt(sum(o.own.values()))]
    if o.money:
        total += [fmt(sum(o.cash.values())), fmt(sum(o.worth.values()))]
    else:
        total += [""]
    rows.append(total)
    header = t["t1_hdr_money"] if o.money else t["t1_hdr_plain"]
    tables.append(fc.Table(list(header), rows, t["t1_cap"]))

    envy_rows = []
    for i in p.people:
        cells = [fmt(o.view[i][k]) + ("*" if k == i else "") for k in p.people]
        envy_rows.append([i, *cells])
    if o.money:
        envy_rows.append([t["t2_cash_row"], *[plus(o.cash[k]) for k in p.people]])
    caption = t["t2_cap_money"] if o.money else t["t2_cap_plain"]
    tables.append(fc.Table([t["t_person"], *p.people], envy_rows, caption))

    if o.tops is not None:
        tops_rows = [
            [
                g,
                fmt(o.tops.best[g]),
                joined(lang, [k for k in p.people if k in o.tops.tops[g]]),
                o.owner[g],
            ]
            for g in p.items
        ]
        tops_rows.append([t["t_total"], fmt(o.total_best), "", ""])
        tables.append(fc.Table(list(t["t3_hdr"]), tops_rows, t["t3_cap"]))
    if o.used == "knaster":
        shares = shares_of(p)
        rows = []
        for name in p.people:
            mine = shares[name] * o.surplus
            rows.append(
                [
                    name,
                    share_text(shares[name]),
                    fmt(floor_cents(o.fair_exact[name])),
                    fmt(o.own[name]),
                    fmt(fc.round_half_up(mine)),
                    fmt(o.worth[name]),
                    plus(o.cash[name]),
                ]
            )
        tables.append(fc.Table(list(t["t4_hdr"]), rows, t["t4_cap"]))
    if not o.money and o.ef1:
        rows = []
        for i in p.people:
            for k in p.people:
                if (i, k) not in o.ef1:
                    continue
                step = o.ef1[(i, k)]
                rows.append(
                    [
                        i,
                        k,
                        fmt(o.own[i]),
                        fmt(o.view[i][k]),
                        f"{step.item} ({fmt(step.item_value)})",
                        fmt(step.rest),
                        t["ef1_ok"] if step.status == EF1_HOLDS else t["ef1_fail"],
                    ]
                )
        tables.append(fc.Table(list(t["t5_hdr"]), rows, t["t5_cap"]))
    if o.fell_back:
        n = len(p.people)
        rows = []
        for start in range(0, len(o.picks), n):
            turn = [
                say(lang, "t6_pick", person=person, item=item)
                for person, item in o.picks[start : start + n]
            ]
            rows.append([str(start // n + 1), t["arrow"].join(turn)])
        tables.append(fc.Table(list(t["t6_hdr"]), rows, t["t6_cap"]))
    return tables


def _envy_note(outcome: Outcome, lang: str) -> str:
    """The sentence on who envies whom, for the rules that do not promise freedom from it."""
    count = len(envious(outcome))
    amount = fmt(outcome.max_envy)
    who_envies = envying(lang, count)
    if outcome.used == "knaster":
        if count:
            return say(lang, "n_kn_envy_some", envying=who_envies, amount=amount)
        return TEXT[lang]["n_kn_envy_none"]
    key = "n_rr_envy" if outcome.fell_back else "n_nash_envy"
    if count:
        return say(lang, key + "_some", envying=who_envies)
    return TEXT[lang][key + "_none"]


def _tie_notes(outcome: Outcome, lang: str, show_items: bool = True) -> list[str]:
    """Notes on how ties were broken, or that the random source was not needed.

    The group summary leaves out which items tied, because that says something about the values.
    """
    o, p = outcome, outcome.problem
    seed = o.priority.seed_hex
    if o.fell_back:
        return []
    notes = []
    if o.used == "max_nash":
        assert o.nash is not None
        if o.nash.n_optimal > 1:
            if o.was_tie:
                key = "n_tie_nash_seed" if seed else "n_tie_nash_names"
            else:
                key = "n_tie_nash_even"
            notes.append(say(lang, key, count=o.nash.n_optimal, seed=seed or ""))
    elif o.tops is not None and o.tops.tied:
        if o.was_tie:
            key = "n_tie_money_seed" if seed else "n_tie_money_names"
        else:
            key = "n_tie_money_spread"
        clause = ""
        if show_items:
            clause = say(
                lang, "tie_items", items=joined(lang, [g for g in p.items if g in o.tops.tied])
            )
        notes.append(say(lang, key, items=clause, seed=seed or ""))
    if seed and not o.was_tie:
        notes.append(TEXT[lang]["n_seed_unused"])
    return notes


def _notes(outcome: Outcome, lang: str) -> list[str]:
    o, p = outcome, outcome.problem
    n = len(p.people)
    notes = []
    if p.note:
        notes.append(say(lang, "n_note", note=p.note))
    notes.append(say(lang, "n_rule", rule=rule_text(p, lang)))
    if o.used == "envy_free":
        if o.total_best % n == 0:
            notes.append(
                say(
                    lang,
                    "n_ef_exact",
                    total=fmt(o.total_best),
                    n=n,
                    worth=fmt(o.total_best // n),
                )
            )
        else:
            low = o.total_best // n
            notes.append(
                say(
                    lang,
                    "n_ef_round",
                    total=fmt(o.total_best),
                    n=n,
                    low=fmt(low),
                    high=fmt(low + 1),
                )
            )
        if o.max_envy == 0:
            notes.append(TEXT[lang]["n_envy_zero"])
        else:
            notes.append(say(lang, "n_envy_some", amount=fmt(o.max_envy)))
    elif o.used == "knaster":
        basis_key = "n_kn_basis_equal" if p.weights is None else "n_kn_basis_weighted"
        fair_sum = sum(o.fair_exact.values(), Fraction(0))
        notes.append(
            say(
                lang,
                "n_kn_result",
                total=fmt(o.total_best),
                basis=say(lang, basis_key, n=n),
                fair=fmt(fc.round_half_up(fair_sum)),
                surplus=fmt(fc.round_half_up(o.surplus)),
            )
        )
        notes.append(_envy_note(o, lang))
    elif o.used == "max_nash":
        assert o.nash is not None
        notes.append(
            say(
                lang,
                "n_nash_result",
                allocations=f"{o.allocations:,}",
                positive=o.nash.n_positive,
                product=product_text(o.nash.product, o.nash.n_positive),
            )
        )
        notes.append(_envy_note(o, lang))
    else:
        if o.priority.seed_hex is None:
            how = TEXT[lang]["n_order_names"]
        else:
            how = say(lang, "n_order_seed", seed=o.priority.seed_hex)
        notes.append(
            say(
                lang,
                "n_rr_fallback",
                people=n,
                items=len(p.items),
                allocations=f"{o.allocations:,}",
                limit=f"{MAX_ALLOCATIONS:,}",
                order=order_text(o, lang),
            )
        )
        notes.append(how)
        notes.append(_envy_note(o, lang))
    notes.extend(_tie_notes(o, lang))
    if o.tops is not None:
        nobody = [g for g in p.items if o.tops.best[g] == 0]
    else:
        nobody = [g for g in p.items if all(p.cents[k][g] == 0 for k in p.people)]
    if nobody:
        notes.append(say(lang, "n_nobody", items=joined(lang, nobody)))
    lines = [
        say(lang, "n_one_liner", name=name, text=certificate_line(o, name, lang))
        for name in p.people
    ]
    notes.append(say(lang, "n_one_liners") + "\n\n" + "\n".join(lines))
    return notes


def _person_lines(outcome: Outcome, name: str, lang: str) -> list[str]:
    """The private message of one person: their own numbers and the public result."""
    t, o, p = TEXT[lang], outcome, outcome.problem
    lines = [say(lang, "dm_head", name=name), say(lang, "n_rule", rule=rule_text(p, lang))]
    if o.fell_back:
        lines.append(t["dm_fallback"])
    if o.bundles[name]:
        lines.append(
            say(
                lang,
                "dm_pkg",
                pkg=package_text(lang, o.bundles[name]),
                own=fmt(o.own[name]),
            )
        )
    else:
        lines.append(t["dm_pkg_none"])
    if o.money:
        lines.append(
            say(lang, "dm_cash", cash=cash_text(lang, o.cash[name]), worth=fmt(o.worth[name]))
        )
    lines.append(certificate_line(o, name, lang))
    lines.append(t["dm_table_money"] if o.money else t["dm_table_plain"])
    for owner in p.people:
        star = " *" if owner == name else ""
        pkg = package_text(lang, o.bundles[owner])
        value = package_value(p.cents, name, o.bundles[owner])
        if o.money:
            lines.append(
                say(
                    lang,
                    "dm_row_money",
                    owner=owner,
                    pkg=pkg,
                    value=fmt(value),
                    cash=plus(o.cash[owner]),
                    total=fmt(o.view[name][owner]),
                    star=star,
                )
            )
        else:
            lines.append(
                say(lang, "dm_row_plain", owner=owner, pkg=pkg, value=fmt(value), star=star)
            )
    return lines


def _group_lines(outcome: Outcome, lang: str) -> list[str]:
    """The summary for the group chat: who gets what, and the guarantee. No private values."""
    o, p = outcome, outcome.problem
    n = len(p.people)
    lines = []
    if p.note:
        lines.append(say(lang, "n_note", note=p.note))
    lines.append(say(lang, "n_rule", rule=rule_text(p, lang)))
    for name in p.people:
        key = "g_person_money" if o.money else "g_person_plain"
        if not o.bundles[name]:
            key += "_none"
        lines.append(
            say(
                lang,
                key,
                name=name,
                pkg=package_text(lang, o.bundles[name]),
                cash=cash_text(lang, o.cash[name]),
            )
        )
    if o.money:
        lines.append(say(lang, "g_cash_total", sum=fmt(sum(o.cash.values()))))
    count = len(envious(o))
    who_envies = envying(lang, count)
    if o.used == "envy_free":
        if o.total_best % n == 0:
            lines.append(
                say(
                    lang,
                    "g_ef_exact",
                    worth=fmt(o.total_best // n),
                    amount=fmt(o.max_envy),
                )
            )
        else:
            low = o.total_best // n
            lines.append(
                say(
                    lang,
                    "g_ef_range",
                    low=fmt(low),
                    high=fmt(low + 1),
                    amount=fmt(o.max_envy),
                )
            )
    elif o.used == "knaster":
        envy = (
            say(lang, "g_kn_envy_some", envying=who_envies)
            if count
            else TEXT[lang]["g_kn_envy_none"]
        )
        lines.append(say(lang, "g_kn", envy=envy))
    elif o.used == "max_nash":
        envy = (
            say(lang, "g_nash_envy_some", envying=who_envies)
            if count
            else TEXT[lang]["g_nash_envy_none"]
        )
        lines.append(say(lang, "g_nash", envy=envy))
    else:
        envy = (
            say(lang, "g_rr_envy_some", envying=who_envies)
            if count
            else TEXT[lang]["g_rr_envy_none"]
        )
        lines.append(
            say(
                lang,
                "g_rr",
                people=n,
                items=len(p.items),
                allocations=f"{o.allocations:,}",
                limit=f"{MAX_ALLOCATIONS:,}",
                order=order_text(o, lang),
                envy=envy,
            )
        )
    if o.fell_back:
        if o.priority.seed_hex is None:
            lines.append(TEXT[lang]["n_order_names"])
        else:
            lines.append(say(lang, "n_order_seed", seed=o.priority.seed_hex))
    else:
        lines.extend(_tie_notes(o, lang, show_items=False))
    return lines


def not_modeled(outcome: Outcome, lang: str = "zh") -> list[str]:
    """What the result does not cover, one sentence each."""
    keys = ["nm_additive"]
    if outcome.problem.method != "max_nash":
        keys.append("nm_budget")
    keys += ["nm_whole", "nm_strategy"]
    return [TEXT[lang][key] for key in keys]


# ---------------------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------------------


def _ef1_json(outcome: Outcome) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for (i, k), step in outcome.ef1.items():
        out.setdefault(i, {})[k] = {
            "own_cents": fc.Cents(outcome.own[i]),
            "theirs_cents": fc.Cents(outcome.view[i][k]),
            "set_aside_item": step.item,
            "set_aside_value_cents": fc.Cents(step.item_value),
            "rest_cents": fc.Cents(step.rest),
            "holds": step.status == EF1_HOLDS,
        }
    return out


def _recompute_json(outcome: Outcome) -> dict[str, Any]:
    """What anyone needs to redo the computation from the values in inputs_echo."""
    o, p = outcome, outcome.problem
    if o.tops is not None:
        base: dict[str, Any] = {
            "best_value_cents": {g: fc.Cents(o.tops.best[g]) for g in p.items},
            "top_valuers": {g: [k for k in p.people if k in o.tops.tops[g]] for g in p.items},
            "total_best_cents": fc.Cents(o.total_best),
            "cash_exact": {k: number_text(o.exact_cash[k]) for k in p.people},
        }
        if o.used == "envy_free":
            assert o.worth_exact is not None
            base["worth_exact"] = number_text(o.worth_exact)
        else:
            base.update(
                {
                    "shares": {k: share_text(o.shares[k]) for k in p.people},
                    "total_value_cents": {k: fc.Cents(o.totals[k]) for k in p.people},
                    "fair_share_exact": {k: number_text(o.fair_exact[k]) for k in p.people},
                    "surplus_exact": number_text(o.surplus),
                    "worth_exact": {
                        k: number_text(o.fair_exact[k] + o.shares[k] * o.surplus) for k in p.people
                    },
                }
            )
        return base
    base = {
        "allocations": str(o.allocations),
        "limit": str(MAX_ALLOCATIONS),
        "ef1": _ef1_json(o),
    }
    if o.nash is not None:
        base.update(
            {
                "people_with_positive_value": o.nash.n_positive,
                "product_cents": str(o.nash.product),
                "product": product_text(o.nash.product, o.nash.n_positive),
                "optimal_allocations": o.nash.n_optimal,
                "evenness": o.nash.evenness,
            }
        )
    else:
        base["picks"] = [[person, item] for person, item in o.picks]
    return base


def _json_parts(
    outcome: Outcome, lang: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    o, p = outcome, outcome.problem
    rules: dict[str, Any] = {"method": p.method}
    if p.source is not None:
        rules["random_source"] = p.source
    if p.weights is not None:
        rules["weights"] = {k: str(w) for k, w in p.weights.items()}
    echo: dict[str, Any] = {
        "people": list(p.people),
        "items": list(p.items),
        "values": {k: {g: fc.Cents(p.cents[k][g]) for g in p.items} for k in p.people},
        "rules": rules,
    }
    if p.note:
        echo["note"] = p.note
    result: dict[str, Any] = {
        "method": p.method,
        "method_used": o.used,
        "fell_back": o.fell_back,
        "money_moves": o.money,
        "allocation": {k: list(o.bundles[k]) for k in p.people},
        "owner": {g: o.owner[g] for g in p.items},
        "own_value_cents": {k: fc.Cents(o.own[k]) for k in p.people},
        "max_envy_cents": fc.Cents(o.max_envy),
        "envious_people": len(envious(o)),
        "tie_break": {
            "was_tie": o.was_tie,
            "method": o.priority.method,
            "order": list(o.priority.order),
            "seed_hex": o.priority.seed_hex,
            "preimage": o.priority.preimage,
        },
    }
    if o.money:
        result["cash_cents"] = {k: fc.Cents(o.cash[k]) for k in p.people}
        result["worth_cents"] = {k: fc.Cents(o.worth[k]) for k in p.people}
    certificate: dict[str, Any] = {
        "envy_table": {i: {k: fc.Cents(o.view[i][k]) for k in p.people} for i in p.people},
        "one_liner": {k: certificate_line(o, k, lang) for k in p.people},
        "recompute": _recompute_json(o),
    }
    return echo, result, certificate


def reproduce_command(args: argparse.Namespace) -> str:
    parts = ["python3", "scripts/stuff_split.py"]
    parts += ["--demo"] if args.demo else ["--input", "-"]
    parts += ["--json"] if args.json else ["--format", args.format]
    if args.lang != "zh":
        parts += ["--lang", args.lang]
    return " ".join(parts)


def build_result(outcome: Outcome, lang: str = "zh", reproduce: str = "") -> fc.Result:
    """Turn an Outcome into the Result the core writes out."""
    if lang not in TEXT:
        raise ValueError(f"lang must be one of {', '.join(TEXT)}")
    p = outcome.problem
    echo, result, certificate = _json_parts(outcome, lang)
    method = TEXT[lang]["m_" + outcome.used]
    things = say(lang, "things_one" if len(p.items) == 1 else "things_many", items=len(p.items))
    return fc.Result(
        title=say(lang, "title", method=method, people=len(p.people), things=things),
        inputs_echo=echo,
        result=result,
        certificate=certificate,
        not_modeled=not_modeled(outcome, lang),
        reproduce=reproduce,
        tables=_tables(outcome, lang),
        notes=_notes(outcome, lang),
        person_lines={name: _person_lines(outcome, name, lang) for name in p.people},
        group_lines=_group_lines(outcome, lang),
    )


def analyse(data: Any, lang: str = "zh", reproduce: str = "") -> fc.Result:
    """Validate parsed input, solve it and build the Result (the whole pipeline)."""
    return build_result(compute(parse_problem(data)), lang, reproduce)


# ---------------------------------------------------------------------------------------
# Demo and self-test
# ---------------------------------------------------------------------------------------


def piano_comparison(lang: str = "zh") -> fc.Result:
    """The piano example under Knaster and under envy_free, side by side."""
    t = TEXT[lang]
    base = fc.parse_input(PIANO_JSON)
    kn = compute(parse_problem({**base, "rules": {"method": "knaster"}}))
    ef = compute(parse_problem({**base, "rules": {"method": "envy_free"}}))
    people = kn.problem.people
    rows = [
        [
            name,
            t["s_has"] if kn.bundles[name] else t["s_hasnt"],
            plus(kn.cash[name]),
            fmt(kn.worth[name]),
            plus(ef.cash[name]),
            fmt(ef.worth[name]),
        ]
        for name in people
    ]
    envier = next(name for name in people if kn.envy[name])
    gap = max(kn.envy[envier].values())
    target = next(k for k, g in kn.envy[envier].items() if g == gap)
    equal = {fmt(w) for w in ef.worth.values()}
    if len(equal) != 1:
        raise AssertionError("envy_free must leave everybody with the same worth here")
    lower = [
        say(lang, "s_lower", name=k, a=fmt(kn.worth[k]), b=fmt(ef.worth[k]))
        for k in people
        if ef.worth[k] < kn.worth[k]
    ]
    note = say(
        lang,
        "s_note",
        envier=envier,
        target=target,
        view=fmt(kn.view[envier][target]),
        worth=fmt(kn.worth[envier]),
        gap=fmt(gap),
        equal=equal.pop(),
        lower=t["cert_join"].join(lower),
        kn=joined(lang, [k for k in people if kn.worth[k] > ef.worth[k]]),
        ef=joined(lang, [k for k in people if ef.worth[k] > kn.worth[k]]),
    )
    return fc.Result(title=t["s_title"], tables=[fc.Table(list(t["s_hdr"]), rows)], notes=[note])


def run_demo(args: argparse.Namespace) -> int:
    """--demo: the roommates example; md output adds the piano example."""
    result = analyse(fc.read_object(args, DEMO_JSON), args.lang, reproduce_command(args))
    if args.json or args.format != "md":
        fc.emit(result, args, lang=args.lang)
        return 0
    sys.stdout.write(
        fc.render_md(result, args.lang)
        + "\n"
        + fc.render_md(piano_comparison(args.lang), args.lang)
    )
    return 0


def reference_best_key(values: Sequence[Sequence[int]], n: int, m: int) -> tuple[int, int]:
    """The best (people with something, product) over all allocations, written plainly."""
    best = (-1, -1)
    for owner in itertools.product(range(n), repeat=m):
        totals = [0] * n
        for j, who in enumerate(owner):
            totals[who] += values[j][who]
        positive = [x for x in totals if x]
        best = max(best, (len(positive), math.prod(positive)))
    return best


def selftest_checks() -> list[tuple[str, Callable[[], None]]]:
    """Named checks of the stuff logic for --selftest (the core adds its own)."""

    def solve(data: Any, method: str) -> Outcome:
        return compute(
            parse_problem({**data, "rules": {**data.get("rules", {}), "method": method}})
        )

    def random_data(stream: fc.SeedStream, people: int, items: int) -> dict[str, Any]:
        top = (1, 3, 10)[stream.below(3)]
        names = [f"p{i}" for i in range(people)]
        goods = [f"g{j}" for j in range(items)]
        return {
            "people": names,
            "items": goods,
            "values": {
                name: [stream.below(top + 1) * (1 + stream.below(3)) for _ in goods]
                for name in names
            },
        }

    def piano() -> None:
        data = fc.parse_input(PIANO_JSON)
        kn = solve(data, "knaster")
        fc.expect(kn.cash == {"甲": 10111, "乙": -49889, "丙": 39778}, f"knaster {kn.cash}")
        fc.expect(kn.envy["甲"] == {"丙": 29667}, f"knaster envy {kn.envy['甲']}")
        ef = solve(data, "envy_free")
        fc.expect(ef.cash == {"甲": 30000, "乙": -60000, "丙": 30000}, f"envy_free {ef.cash}")
        fc.expect(set(ef.worth.values()) == {30000} and ef.max_envy == 0, "equal worth")

    def roommates() -> None:
        out = solve(fc.parse_input(DEMO_JSON), "max_nash")
        fc.expect(out.bundles["阿明"] == ["冰箱", "电视"], f"阿明 {out.bundles['阿明']}")
        fc.expect(out.bundles["小红"] == ["洗衣机", "书架"], f"小红 {out.bundles['小红']}")
        fc.expect(out.bundles["大刘"] == ["沙发", "微波炉"], f"大刘 {out.bundles['大刘']}")
        fc.expect(out.own == {"阿明": 4500, "小红": 4000, "大刘": 4000}, f"values {out.own}")
        fc.expect(set(out.envy["小红"]) == {"阿明"} and not out.envy["阿明"], "who envies whom")
        fc.expect(all(s.status == EF1_HOLDS for s in out.ef1.values()), "EF1")

    def money_rules_on_random_cases() -> None:
        stream = fc.SeedStream(fc.make_seed("stuff_split_selftest", ["money"], 60, "selftest"))
        for _ in range(60):
            data = random_data(stream, 2 + stream.below(4), 1 + stream.below(6))
            for method in ("envy_free", "knaster"):
                out = solve(data, method)  # compute() checks the promises of the rule
                fc.expect(sum(out.cash.values()) == 0, "cash adds up to zero")
                best = sum(
                    max(row[j] for row in data["values"].values()) * 100
                    for j in range(len(data["items"]))
                )
                fc.expect(out.total_best == best, "every item goes to a top valuer")
            ef = solve(data, "envy_free")
            fc.expect(
                max(ef.worth.values()) - min(ef.worth.values()) <= 1, "worths differ by a cent"
            )

    def nash_against_a_plain_search() -> None:
        stream = fc.SeedStream(fc.make_seed("stuff_split_selftest", ["nash"], 40, "selftest"))
        for _ in range(40):
            n, m = 2 + stream.below(3), 1 + stream.below(5)
            data = random_data(stream, n, m)
            out = solve(data, "max_nash")
            names = sorted(data["items"])
            order = out.priority.order
            values = [
                [data["values"][p][data["items"].index(g)] * 100 for p in order] for g in names
            ]
            fc.expect(out.nash is not None, "searched")
            key = (out.nash.n_positive, out.nash.product)
            fc.expect(key == reference_best_key(values, n, m), f"best key {key}")
            mine = [out.own[p] for p in data["people"]]
            for other in itertools.product(range(n), repeat=m):
                totals = [0] * n
                for j, who in enumerate(other):
                    totals[who] += data["values"][data["people"][who]][
                        data["items"].index(names[j])
                    ]
                theirs = [x * 100 for x in totals]
                better = all(a >= b for a, b in zip(theirs, mine)) and theirs != mine
                fc.expect(not better, "Pareto efficiency")

    def taking_turns_is_ef1() -> None:
        stream = fc.SeedStream(fc.make_seed("stuff_split_selftest", ["turns"], 40, "selftest"))
        for _ in range(40):
            data = random_data(stream, 2 + stream.below(4), 1 + stream.below(12))
            problem = parse_problem({**data, "rules": {"method": "max_nash"}})
            picks = round_robin(problem.cents, problem.items, sorted(problem.people))
            owner = {g: p for p, g in picks}
            bundles = bundles_of(owner, problem.people, problem.items)
            for i in problem.people:
                for k in problem.people:
                    step = ef1_step(problem.cents, bundles, i, k)
                    fc.expect(step.status != EF1_FAILS, "turns are EF1")

    def too_many_items_take_turns() -> None:
        names = ["p0", "p1", "p2"]
        goods = [f"g{j:02d}" for j in range(14)]
        values = {p: [(7 * i + 3 * j) % 11 + 1 for j in range(14)] for i, p in enumerate(names)}
        out = solve({"people": names, "items": goods, "values": values}, "max_nash")
        fc.expect(out.fell_back and out.allocations == 3**14, "3 people and 14 items take turns")
        fc.expect(out.allocations > MAX_ALLOCATIONS, "above the limit")

    def weights_change_the_shares() -> None:
        data = fc.parse_input(PIANO_JSON)
        data["rules"] = {"method": "knaster", "weights": {"甲": 2, "乙": 1, "丙": 1}}
        out = compute(parse_problem(data))
        fc.expect(out.shares["甲"] == Fraction(1, 2), "a weight of 2 out of 4 is a share of 1/2")
        fc.expect(sum(out.cash.values()) == 0 and out.surplus > 0, "cash and surplus")

    def listing_order_is_irrelevant() -> None:
        data = fc.parse_input(DEMO_JSON)
        for method in METHODS:
            first = solve(data, method)
            mixed = {
                "people": list(reversed(data["people"])),
                "items": list(reversed(data["items"])),
                "values": {
                    name: list(reversed(data["values"][name])) for name in reversed(data["people"])
                },
            }
            second = solve(mixed, method)
            fc.expect(first.owner == second.owner and first.cash == second.cash, method)

    def bad_input_names_the_field() -> None:
        cases = [
            ("values.阿明[0]", lambda d: d["values"]["阿明"].__setitem__(0, -1)),
            ("values.阿明", lambda d: d["values"]["阿明"].pop()),
            ("rules.method", lambda d: d["rules"].pop("method")),
            ("rules.weights", lambda d: d["rules"].update(weights={})),
            ("zzz", lambda d: d.update(zzz=1)),
        ]
        for field_name, change in cases:
            data = fc.parse_input(DEMO_JSON)
            change(data)
            try:
                parse_problem(data)
            except fc.InputError as err:
                fc.expect(err.field.startswith(field_name), f"{field_name}: {err.field}")
            else:
                raise AssertionError(f"accepted a bad input at {field_name}")

    def texts_match() -> None:
        fc.expect(set(TEXT["zh"]) == set(TEXT["en"]), "zh and en text keys differ")

    def every_output_renders() -> None:
        data = fc.parse_input(DEMO_JSON)
        for method in METHODS:
            for lang in fc.LANGS:
                result = build_result(solve(data, method), lang)
                for fmt_name in fc.FORMATS:
                    fc.expect(bool(fc.render(result, fmt_name, False, lang)), f"{fmt_name} {lang}")
                fc.expect(bool(fc.render(result, "md", True, lang)), f"json {lang}")
        for lang in fc.LANGS:
            fc.expect(bool(fc.render_md(piano_comparison(lang), lang)), f"piano {lang}")

    return [
        ("stuff: piano under knaster and envy_free", piano),
        ("stuff: roommates under max_nash", roommates),
        ("stuff: envy_free and knaster on random cases", money_rules_on_random_cases),
        ("stuff: max_nash against a plain search, Pareto efficiency", nash_against_a_plain_search),
        ("stuff: taking turns is EF1", taking_turns_is_ef1),
        ("stuff: too many items take turns", too_many_items_take_turns),
        ("stuff: weights change the shares", weights_change_the_shares),
        ("stuff: listing order is irrelevant", listing_order_is_irrelevant),
        ("stuff: bad input names the field", bad_input_names_the_field),
        ("stuff: zh and en texts have the same keys", texts_match),
        ("stuff: every output renders", every_output_renders),
    ]


# ---------------------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stuff_split.py",
        description=(
            "Divide shared belongings by a rule the group picked first. Reads one JSON object "
            "(people, items, values, rules and an optional note) from standard input or "
            "--input FILE and prints tables, private messages or a group summary, in Chinese "
            "by default or in English with --lang en. rules.method is envy_free (every item to "
            "a person who values it most, cash makes everybody's final worth equal), knaster "
            "(Knaster's sealed bids, optional rules.weights for unequal shares) or max_nash "
            "(no cash, the most people better off and then the largest product of values, "
            "which is envy-free up to one item and Pareto efficient, and takes turns when "
            "there are more than 2,000,000 allocations to try)."
        ),
        epilog=(
            "values: person to a list with one value per item, in the order of items, with at "
            "most two decimals. rules.random_source (optional): public text that only settles "
            "ties. "
        )
        + fc.exit_codes_epilog(),
    )
    fc.standard_args(parser)
    fc.add_lang_option(parser, "JSON keys and names do not change")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    fc.exclusive_modes(args, "--demo", "--selftest")
    if args.selftest:
        return fc.run_selftest(selftest_checks())
    if args.demo:
        return run_demo(args)
    data = fc.read_object(args)
    fc.emit(analyse(data, args.lang, reproduce_command(args)), args, lang=args.lang)
    return 0


if __name__ == "__main__":
    fc.run_cli(main)
