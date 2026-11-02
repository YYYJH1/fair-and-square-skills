"""Reference code for the plan B tests of chore-split. It shares no code with the script.

Splits are found by trying every way to give out the units. The money is checked with a linear
program (scipy) and with plain loops over all pairs of people. The module name has no test
prefix on purpose, so that pytest does not collect it.
"""

from __future__ import annotations

import itertools
from collections import Counter
from fractions import Fraction

from chore_support import bundle_data
from hypothesis import strategies as st
from scipy.optimize import linprog


def unit_list(chores) -> list:
    """Chore names with repeats, in the order of the names. chores is {name: units}."""
    return [name for name in sorted(chores) for _ in range(chores[name])]


def owner_tuples(people, units, caps, can):
    """Every way to give each unit to a person who can do it, within the caps.

    people is the order of the tie rule. Each tuple has the owner of every unit."""
    for owners in itertools.product(people, repeat=len(units)):
        counts = Counter(owners)
        if any(counts[p] > caps[p] for p in people):
            continue
        if any(chore not in can[o] for chore, o in zip(units, owners)):
            continue
        yield owners


def split_of(people, units, owners) -> frozenset:
    """A split as a set of (person, sorted chores): swapping equal units changes nothing."""
    return frozenset((p, tuple(sorted(c for c, o in zip(units, owners) if o == p))) for p in people)


def cheapest_by_brute_force(people, chores, costs, caps):
    """(smallest total cost, the first cheapest split in the order of people, number of cheapest
    splits), or None when no way to give out the units exists.

    The first split is the one whose owners, read in the order of the units, come first in the
    order of people. chores is {name: units}, costs is {person: {chore: cost}}."""
    units = unit_list(chores)
    can = {p: set(costs[p]) for p in people}
    rank = {p: i for i, p in enumerate(people)}
    best_cost = None
    best: list = []
    for owners in owner_tuples(people, units, caps, can):
        cost = sum(costs[o][c] for c, o in zip(units, owners))
        if best_cost is None or cost < best_cost:
            best_cost, best = cost, [owners]
        elif cost == best_cost:
            best.append(owners)
    if best_cost is None:
        return None
    first = min(best, key=lambda owners: [rank[o] for o in owners])
    return (
        best_cost,
        split_of(people, units, first),
        len({split_of(people, units, o) for o in best}),
    )


def cost_to(person, bundle, costs, caps):
    """What a bundle (a list of chores) costs the person, or None if they cannot take it."""
    if len(bundle) > caps[person] or any(c not in costs[person] for c in bundle):
        return None
    return sum(costs[person][c] for c in bundle)


def reference_cost_table(split, costs, caps):
    """{person: {holder: cost of the holder's bundle to the person, or None}}.

    split is a set of (holder, chores) pairs, as made by split_of."""
    bundles = {holder: list(chores) for holder, chores in split}
    return {p: {h: cost_to(p, bundles[h], costs, caps) for h in bundles} for p in bundles}


def lp_best_worst_off(table):
    """The largest possible smallest net among payments that add up to zero and leave nobody
    envying a bundle they can take, by linear programming. table is {person: {holder: cost}}.

    The net of a person is the payment they receive minus the cost of their own bundle."""
    people = sorted(table)
    n = len(people)
    # variables: the payments t_0 .. t_{n-1}, then m. Maximise m.
    objective = [0.0] * n + [-1.0]
    upper, bound = [], []
    for i, p in enumerate(people):
        row = [0.0] * (n + 1)
        row[n], row[i] = 1.0, -1.0  # m <= t_i - cost_ii
        upper.append(row)
        bound.append(-table[p][p])
        for k, h in enumerate(people):
            if k != i and table[p][h] is not None:
                row = [0.0] * (n + 1)  # t_k - cost_ik <= t_i - cost_ii
                row[k], row[i] = 1.0, -1.0
                upper.append(row)
                bound.append(table[p][h] - table[p][p])
    result = linprog(
        objective,
        A_ub=upper,
        b_ub=bound,
        A_eq=[[1.0] * n + [0.0]],
        b_eq=[0.0],
        bounds=[(None, None)] * (n + 1),
        method="highs",
    )
    assert result.status == 0, result.message
    return -result.fun


def exact_envy(table, payments):
    """The largest envy, as a Fraction, over all pairs the person can take: how much more a
    person would get by taking the holder's bundle and payment than by keeping their own."""
    worst = Fraction(0)
    for p, row in table.items():
        own = payments[p] - row[p]
        for holder, cost in row.items():
            if cost is not None and holder != p:
                worst = max(worst, payments[holder] - cost - own)
    return worst


# ---------------------------------------------------------------------------------------
# Random cases
# ---------------------------------------------------------------------------------------

SMALL_NAMES = ["p0", "p1", "p2", "p3", "p4", "p5"]
SMALL_CHORES = ["c0", "c1", "c2"]


@st.composite
def bundle_cases(
    draw,
    max_people=4,
    max_chores=3,
    max_units=2,
    top_cost=6,
    with_cannot=True,
    uniform_cap=False,
    always_feasible=False,
):
    """A valid input object of plan bundle_pay, small enough to try every split.

    Without always_feasible, the caps may be too small, or the cannot lists too long, for any
    way to give out the chores to exist."""
    people = SMALL_NAMES[: draw(st.integers(2, max_people))]
    chores = SMALL_CHORES[: draw(st.integers(1, max_chores))]
    units = {c: draw(st.integers(1, max_units)) for c in chores}
    total = sum(units.values())
    cannot = {p: [] for p in people}
    if with_cannot:
        for p in people:
            cannot[p] = draw(st.lists(st.sampled_from(chores), unique=True, max_size=len(chores)))
        for c in chores:
            if all(c in cannot[p] for p in people):
                cannot[draw(st.sampled_from(people))].remove(c)
    if uniform_cap:
        cap = draw(st.integers(-(-total // len(people)), total))
        caps = {p: cap for p in people}
    elif always_feasible:
        caps = {p: total for p in people}
    else:
        caps = {p: draw(st.integers(0, total)) for p in people}
    costs = {
        p: {c: draw(st.integers(0, top_cost)) for c in chores if c not in cannot[p]} for p in people
    }
    return bundle_data(
        people,
        chores,
        costs,
        caps,
        units={c: u for c, u in units.items() if u > 1},
        cannot={p: c for p, c in cannot.items() if c},
    )
