"""Reference code for the chore-split tests. It shares no code with the script.

The seed mapping is written out again from its specification (hashlib and json only). Picking
turn by turn is written as plain loops. Envy up to one chore is decided by trying every
integer cost that fits a ranking, which is slow but obviously right for the sizes the tests
use. The script instead compares the two bundles place by place, and the tests check that the
two agree.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from collections import Counter

RULE = "chore_pick_order_v1"
BIG = 10**6  # the cost of a chore that a person cannot do


def spec_seed(participants, n_slots, source, rule=RULE):
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


def reference_start_order(people, total_units, source):
    return spec_order(spec_seed(people, total_units, source), people)


def reference_week_order(base, week, rotate="shift"):
    """Week 1 is the base order. With rotation each week moves the first person to the back."""
    if rotate == "none":
        return list(base)
    order = list(base)
    for _ in range(week - 1):
        order = order[1:] + order[:1]
    return order


def reference_picks(order, rankings, units):
    """Turn by turn: the next person who still has a chore they can do takes the best one.

    Returns [(person, chore)] in time order. A person with nothing left to pick is skipped for
    good. rankings holds only the chores a person can do.
    """
    left = dict(units)
    out = []
    active = list(order)
    while any(left.values()):
        progressed = False
        for person in list(active):
            if not any(left.values()):
                break
            choice = next((c for c in rankings[person] if left[c] > 0), None)
            if choice is None:
                active.remove(person)
                continue
            left[choice] -= 1
            out.append((person, choice))
            progressed = True
        assert progressed
    return out


def monotone_costs(ranking, top=2):
    """Every integer cost from 0 to top that does not fall along the ranking (least disliked
    first), as a dict chore -> cost."""
    for values in itertools.product(range(top + 1), repeat=len(ranking)):
        if all(values[i] <= values[i + 1] for i in range(len(values) - 1)):
            yield dict(zip(ranking, values))


def bundle_cost(bundle, cost):
    """Cost of a Counter of chores. A chore without a cost is one the person cannot do."""
    return sum(units * cost.get(chore, BIG) for chore, units in bundle.items())


def envy_by_brute_force(own, other, ranking, top=2):
    """(envy-free, EF1) of one person's bundle against another, for ALL integer costs from 0 to
    top that fit the ranking. EF1 means: the person owns nothing, or some own chore can be set
    aside so that the rest costs no more than the other bundle."""
    free = True
    ef1 = True
    for cost in monotone_costs(ranking, top):
        mine = bundle_cost(own, cost)
        theirs = bundle_cost(other, cost)
        if mine > theirs:
            free = False
        if own:
            options = []
            for chore in own:
                rest = Counter(own)
                rest[chore] -= 1
                options.append(bundle_cost(+rest, cost))
            if min(options) > theirs:
                ef1 = False
    return free, ef1


def classify(own, other, ranking, top=2):
    """The status the script should give, from brute force alone."""
    if any(units and chore not in ranking for chore, units in other.items()):
        return "exempt"
    free, ef1 = envy_by_brute_force(own, other, ranking, top)
    if free:
        return "envy_free"
    return "ef1" if ef1 else "fails"
