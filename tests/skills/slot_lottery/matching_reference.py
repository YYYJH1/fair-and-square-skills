"""Reference code for the probabilistic serial and deferred acceptance tests.

Nothing here imports the script. The eating algorithm is written again in another style, the
properties that the script claims are checked from their definitions (stochastic dominance, the
linear program for ordinal efficiency, blocking pairs, a search over all assignments), and
deferred acceptance is run a second time on a market in which every seat is its own college.
"""

from __future__ import annotations

import itertools
from fractions import Fraction

# ---------------------------------------------------------------------------------------
# Probabilistic serial, written as a plain simulation of the eating
# ---------------------------------------------------------------------------------------


def eat(people, prefs, capacity):
    """chances[person][slot or None] by simulating the eating, in exact fractions.

    A different layout from the script: the supply left of every slot is a dictionary, and at
    every stage each person's slot is looked up from scratch on their list.
    """
    supply = {slot: Fraction(seats) for slot, seats in capacity.items()}
    chances = {p: {slot: Fraction(0) for slot in [*capacity, None]} for p in people}
    clock = Fraction(0)
    while clock < 1:
        choice = {}
        for p in people:
            choice[p] = next((s for s in prefs[p] if supply[s] > 0), None)
        crowd = {}
        for p, slot in choice.items():
            if slot is not None:
                crowd.setdefault(slot, []).append(p)
        step = 1 - clock
        for slot, eaters in crowd.items():
            step = min(step, supply[slot] / len(eaters))
        for p, slot in choice.items():
            chances[p][slot] += step
        for slot, eaters in crowd.items():
            supply[slot] -= step * len(eaters)
        clock += step
    return chances


# ---------------------------------------------------------------------------------------
# Properties from their definitions
# ---------------------------------------------------------------------------------------


def prefix_sums(ranking, row):
    """Cumulative chances along a ranking, then 'no slot', then the slots it does not list."""
    order = [*ranking, None]
    total = Fraction(0)
    sums = []
    for slot in order:
        total += row[slot]
        sums.append(total)
    return sums


def dominates(ranking, mine, theirs):
    """True when the lottery `mine` is at least as good as `theirs` at every prefix."""
    return all(a >= b for a, b in zip(prefix_sums(ranking, mine), prefix_sums(ranking, theirs)))


def strictly_dominates(ranking, mine, theirs):
    return dominates(ranking, mine, theirs) and prefix_sums(ranking, mine) != prefix_sums(
        ranking, theirs
    )


def envy_pairs(people, prefs, chances):
    """Ordered pairs (i, j) such that i does not stochastically dominate j by i's ranking."""
    return [
        (i, j)
        for i in people
        for j in people
        if i != j and not dominates(prefs[i], chances[i], chances[j])
    ]


def ordinal_gain(people, slots, prefs, capacity, chances):
    """The largest total improvement of cumulative chances over `chances`, by linear programming.

    Variables are a second table of chances with the same row sums and the same capacities, and
    the constraint is that no person gets a smaller cumulative chance at any prefix of their
    ranking. The chances are ordinally efficient exactly when the best total improvement is zero.
    Needs scipy, which is a development dependency of the tests only.
    """
    import numpy as np
    from scipy.optimize import linprog

    objects = [*slots, None]
    index = {(p, o): k for k, (p, o) in enumerate((p, o) for p in people for o in objects)}
    size = len(index)
    equal_rows, equal_values = [], []
    for p in people:
        row = np.zeros(size)
        for o in objects:
            row[index[(p, o)]] = 1
        equal_rows.append(row)
        equal_values.append(1.0)
    upper_rows, upper_values = [], []
    for s in slots:
        row = np.zeros(size)
        for p in people:
            row[index[(p, s)]] = 1
        upper_rows.append(row)
        upper_values.append(float(capacity[s]))
    cost = np.zeros(size)
    base = 0.0
    for p in people:
        order = [*prefs[p], None, *[s for s in slots if s not in prefs[p]]]
        total = Fraction(0)
        row = np.zeros(size)
        for o in order:
            total += chances[p][o]
            row[index[(p, o)]] = 1
            upper_rows.append(-row.copy())
            upper_values.append(-float(total))
            cost -= row
            base += float(total)
    found = linprog(
        cost,
        A_ub=np.array(upper_rows),
        b_ub=np.array(upper_values),
        A_eq=np.array(equal_rows),
        b_eq=np.array(equal_values),
        bounds=(0, None),
        method="highs",
    )
    assert found.status == 0, found
    return -found.fun - base


def expected_utility(ranking, row, utilities):
    """Expected utility of a lottery, where utilities[k] belongs to the k-th slot of the ranking
    and 'no slot' (and any slot that is not listed) is worth 0."""
    return sum(
        (utilities[k] * row[slot] for k, slot in enumerate(ranking)),
        Fraction(0),
    )


def utilities_for_prefix(length, size, gap=10**6):
    """Strictly decreasing utilities for a ranking of `size` slots in which the first `length`
    slots are worth `gap` more than the others. 'No slot' is worth 0, below all of them."""
    return [Fraction((gap if k < length else 0) + size - k) for k in range(size)]


# ---------------------------------------------------------------------------------------
# Exact lotteries of the random serial dictatorship, by enumeration of all orders
# ---------------------------------------------------------------------------------------


def serial_dictatorship_chances(people, slots, prefs):
    """chances[person][slot or None] of random serial dictatorship with one seat per slot."""
    orders = list(itertools.permutations(people))
    chances = {p: {slot: Fraction(0) for slot in [*slots, None]} for p in people}
    for order in orders:
        free = set(slots)
        for p in order:
            pick = next((s for s in prefs[p] if s in free), None)
            if pick is not None:
                free.discard(pick)
            chances[p][pick] += Fraction(1, len(orders))
    return chances


# ---------------------------------------------------------------------------------------
# Deferred acceptance on a market in which every seat is a college of its own
# ---------------------------------------------------------------------------------------


def gale_shapley_by_seats(people, prefs, capacity, key):
    """Men-proposing Gale-Shapley after a college with q seats is split into q colleges.

    Every seat of a slot ranks the people exactly as the slot does (key(slot, person), smaller is
    better, None means unacceptable), and a person lists the seats of each slot in a row where the
    slot stood. Returns {person: slot} for the people who get a seat.
    """
    seats = [(slot, k) for slot in sorted(capacity) for k in range(capacity[slot])]
    lists = {p: [(slot, k) for slot in prefs[p] for k in range(capacity[slot])] for p in people}
    nxt = {p: 0 for p in people}
    holder = {}
    free = list(people)
    while free:
        p = free.pop()
        while nxt[p] < len(lists[p]):
            seat = lists[p][nxt[p]]
            nxt[p] += 1
            if key(seat[0], p) is None:
                continue
            current = holder.get(seat)
            if current is None:
                holder[seat] = p
                break
            if key(seat[0], p) < key(seat[0], current):
                holder[seat] = p
                free.append(current)
                break
    assert set(holder) <= set(seats)
    return {p: seat[0] for seat, p in holder.items()}


def rank_of(prefs, person, slot):
    """How bad a slot is for a person: its place in their ranking, worst when nothing."""
    ranking = prefs[person]
    return ranking.index(slot) if slot in ranking else len(ranking)


def feasible_assignments(people, slots, capacity, prefs, key):
    """Every way to give each person at most one slot that they list and that accepts them,
    with at most capacity[slot] people in a slot."""
    options = [[None] + [s for s in prefs[p] if key(s, p) is not None] for p in people]
    for combo in itertools.product(*options):
        used = {}
        for slot in combo:
            if slot is not None:
                used[slot] = used.get(slot, 0) + 1
        if all(count <= capacity[slot] for slot, count in used.items()):
            yield dict(zip(people, combo))


def blocking_pairs_by_definition(people, slots, capacity, prefs, key, assignment):
    """(person, slot) pairs that block: the person lists the slot above their result (or has no
    result), the slot accepts them, and it has a free seat or holds somebody it likes less."""
    holders = {s: [p for p in people if assignment[p] == s] for s in slots}
    found = []
    for p in people:
        got = assignment[p]
        for s in prefs[p]:
            if got is not None and rank_of(prefs, p, s) >= rank_of(prefs, p, got):
                continue
            if key(s, p) is None:
                continue
            if len(holders[s]) < capacity[s] or any(key(s, q) > key(s, p) for q in holders[s]):
                found.append((p, s))
    return found


def stable_assignments(people, slots, capacity, prefs, key):
    return [
        a
        for a in feasible_assignments(people, slots, capacity, prefs, key)
        if not blocking_pairs_by_definition(people, slots, capacity, prefs, key, a)
    ]


def pareto_improvement(people, slots, capacity, prefs, assignment):
    """An assignment that nobody dislikes and somebody likes better than `assignment`, ignoring
    the priorities of the slots (every listed slot accepts everybody), or None."""

    def anyone(slot, person):
        return (0, 0)  # a key under which no slot turns anybody away

    for other in feasible_assignments(people, slots, capacity, prefs, anyone):
        better = [rank_of(prefs, p, other[p]) - rank_of(prefs, p, assignment[p]) for p in people]
        if all(delta <= 0 for delta in better) and any(delta < 0 for delta in better):
            return other
    return None


def reference_key(priorities, order):
    """key(slot, person) as the documentation words it: (tier, place in the lottery order),
    smaller is better, None for a person whom a slot with a priority list does not list."""
    place = {p: i for i, p in enumerate(order, 1)}

    def key(slot, person):
        if slot not in priorities:
            return (0, place[person])
        for level, tier in enumerate(priorities[slot]):
            if person in tier:
                return (level, place[person])
        return None

    return key


def replay_rounds(people, prefs, capacity, key, rounds):
    """Replay the printed rounds with plain rules and return {slot: holders}, or raise.

    Round r: everybody who is not on hold and still has a slot left to try applies to the next
    one on their list. Each slot keeps the best capacity[slot] of those it held and those who
    applied, dropping everybody it does not accept, and turns the others away.
    """
    held = {slot: [] for slot in capacity}
    nxt = {p: 0 for p in people}
    on_hold = set()
    turned = []
    for number, entry in enumerate(rounds, 1):
        assert entry["round"] == number
        expected = {
            p: prefs[p][nxt[p]] for p in people if p not in on_hold and nxt[p] < len(prefs[p])
        }
        assert entry["proposals"] == dict(sorted(expected.items())), number
        turned = []
        for slot in sorted({s for s in expected.values()}):
            pool = held[slot] + [p for p, s in expected.items() if s == slot]
            kept = sorted((p for p in pool if key(slot, p) is not None), key=lambda p: key(slot, p))
            kept = kept[: capacity[slot]]
            for p in sorted(pool):
                if p not in kept:
                    why = "ineligible" if key(slot, p) is None else "outranked"
                    turned.append({"person": p, "slot": slot, "reason": why})
            held[slot] = kept
        assert entry["rejections"] == turned, number
        on_hold = {p for holders in held.values() for p in holders}
        for item in turned:
            nxt[item["person"]] += 1
        assert entry["holds"] == {s: sorted(h) for s, h in sorted(held.items()) if h}, number
    for item in turned:
        assert nxt[item["person"]] >= len(prefs[item["person"]]), (
            "somebody could have applied again"
        )
    return held
