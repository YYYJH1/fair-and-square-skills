"""Reference code for the slot-lottery tests. It shares no code with the script.

The seed mapping is written out again from its specification (hashlib and json only). Serial
dictatorship, Pareto efficiency and strategy-proofness are checked by plain exhaustive search
over all assignments, which is slow but obviously right for the small sizes the tests use.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from fractions import Fraction


def spec_seed(rule, participants, n_slots, source):
    """Seed exactly as the specification words it, written with the standard json module."""
    text = json.dumps(
        {"rule": rule, "participants": sorted(participants), "n_slots": n_slots, "source": source},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(text.encode("utf-8")).digest()


def spec_order(seed, names):
    """Counter stream, rejection sampling and Fisher-Yates, reimplemented from the spec."""
    counter = 0

    def uniform_below(n):
        nonlocal counter
        while True:
            block = hashlib.sha256(seed + counter.to_bytes(8, "big")).digest()
            counter += 1
            x = int.from_bytes(block[:8], "big")
            if x < 2**64 - (2**64 % n):
                return x % n

    items = sorted(names)
    for i in range(len(items) - 1, 0, -1):
        j = uniform_below(i + 1)
        items[i], items[j] = items[j], items[i]
    return items


def reference_order(rule, participants, n_slots, source):
    return spec_order(spec_seed(rule, participants, n_slots, source), participants)


# ---------------------------------------------------------------------------------------
# Exhaustive checks of the serial dictatorship
# ---------------------------------------------------------------------------------------


def value(prefs, person, slot):
    """How bad a slot is for a person: its place in their ranking, worst when nothing."""
    ranking = prefs[person]
    if slot is None or slot not in ranking:
        return len(ranking)
    return ranking.index(slot)


def feasible_assignments(people, slots, prefs):
    """Every way to give each person at most one acceptable slot, each slot to one person."""
    options = [[None] + [slot for slot in slots if slot in prefs[p]] for p in people]
    for combo in itertools.product(*options):
        taken = [slot for slot in combo if slot is not None]
        if len(taken) == len(set(taken)):
            yield dict(zip(people, combo))


def lexicographic_best(order, prefs, slots):
    """Serial dictatorship by brute force: the feasible assignment that is best for the first
    person, then (among those) best for the second, and so on."""
    best = min(
        feasible_assignments(order, slots, prefs),
        key=lambda assignment: tuple(value(prefs, p, assignment[p]) for p in order),
    )
    return {person: slot for person, slot in best.items() if slot is not None}


def pareto_improvements(allocation, people, slots, prefs):
    """Feasible assignments that nobody dislikes and somebody likes better."""
    mine = {p: value(prefs, p, allocation.get(p)) for p in people}
    found = []
    for other in feasible_assignments(people, slots, prefs):
        theirs = {p: value(prefs, p, other[p]) for p in people}
        if all(theirs[p] <= mine[p] for p in people) and any(theirs[p] < mine[p] for p in people):
            found.append(other)
    return found


def all_reports(slots):
    """Every ranking a person could report: any ordered sub-list of the slots."""
    for size in range(len(slots) + 1):
        yield from (list(report) for report in itertools.permutations(slots, size))


# ---------------------------------------------------------------------------------------
# Exact probabilities and statistics
# ---------------------------------------------------------------------------------------


def exact_rsd_probabilities(people, slots, prefs, serial_dictatorship):
    """P(person gets slot) when all orders of the people are equally likely."""
    counts = {p: {slot: 0 for slot in slots} for p in people}
    orders = list(itertools.permutations(people))
    for order in orders:
        allocation = serial_dictatorship(list(order), prefs, slots)[0]
        for person, slot in allocation.items():
            counts[person][slot] += 1
    return {p: {s: Fraction(n, len(orders)) for s, n in row.items()} for p, row in counts.items()}


def chi_square(counts, expected):
    """Pearson's statistic of observed counts against one expected count per cell."""
    return sum((count - expected) ** 2 / expected for count in counts)
