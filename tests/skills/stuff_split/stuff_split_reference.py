"""Plain reference computations for the stuff-split tests.

They work on a matrix ``values[p][j]`` of integer cents (person p, item j) and an owner list
``owner[j]`` (the person who gets item j). They are written from the definitions and share no
code with the script, so a test that compares the two checks one against the other.
"""

from __future__ import annotations

import itertools
import math
from fractions import Fraction


def n_people(values):
    return len(values)


def n_items(values):
    return len(values[0])


def highest(values):
    """The highest value of each item."""
    return [max(values[p][j] for p in range(len(values))) for j in range(len(values[0]))]


def welfare(values):
    """The largest total value any way of giving out the items can reach."""
    return sum(highest(values))


def top_valuers(values):
    """For each item, the people who value it most."""
    best = highest(values)
    return [[p for p in range(len(values)) if values[p][j] == best[j]] for j in range(len(best))]


def own_value(values, owner, p):
    """What person p's own items are worth to p."""
    return sum(values[p][j] for j in range(len(owner)) if owner[j] == p)


def package_value(values, owner, i, k):
    """What the items of person k are worth to person i."""
    return sum(values[i][j] for j in range(len(owner)) if owner[j] == k)


def all_owners(values):
    return itertools.product(range(len(values)), repeat=len(values[0]))


def all_top_valuer_owners(values):
    """Every owner list in which each item goes to a person who values it most."""
    return itertools.product(*top_valuers(values))


def envy_free_exact_cash(values, owner):
    """Exact cash in cents: everybody ends with welfare / n."""
    n = len(values)
    return [Fraction(welfare(values), n) - own_value(values, owner, p) for p in range(n)]


def knaster_exact(values, owner, weights=None):
    """Exact (fair share, surplus, cash) of Knaster's procedure, all in cents."""
    n = len(values)
    weights = weights or [Fraction(1)] * n
    shares = [Fraction(w) / sum(Fraction(x) for x in weights) for w in weights]
    fair = [shares[p] * sum(values[p]) for p in range(n)]
    surplus = welfare(values) - sum(fair)
    cash = [fair[p] + shares[p] * surplus - own_value(values, owner, p) for p in range(n)]
    return fair, surplus, cash


def exact_envy(values, owner, cash):
    """The largest envy over all pairs, for exact or integer cash."""
    n = len(values)
    worst = 0
    for i in range(n):
        mine = own_value(values, owner, i) + cash[i]
        for k in range(n):
            theirs = package_value(values, owner, i, k) + cash[k]
            worst = max(worst, theirs - mine)
    return worst


def best_nash_key(values):
    """The best (people with something, product of their values) over all allocations."""
    n, m = len(values), len(values[0])
    best = (-1, -1)
    for owner in itertools.product(range(n), repeat=m):
        totals = [own_value(values, owner, p) for p in range(n)]
        positive = [x for x in totals if x]
        best = max(best, (len(positive), math.prod(positive)))
    return best


def nash_key(values, owner):
    totals = [own_value(values, owner, p) for p in range(len(values))]
    positive = [x for x in totals if x]
    return (len(positive), math.prod(positive))


def optimal_nash_owners(values):
    """Every owner list that reaches the best key, in lexicographic order."""
    best = best_nash_key(values)
    return [owner for owner in all_owners(values) if nash_key(values, owner) == best]


def is_ef1(values, owner):
    """True if, for every pair, setting aside one item of the other's package removes the envy."""
    n, m = len(values), len(values[0])
    for i in range(n):
        mine = own_value(values, owner, i)
        for k in range(n):
            if k == i:
                continue
            package = [j for j in range(m) if owner[j] == k]
            theirs = sum(values[i][j] for j in package)
            if theirs > mine and not any(theirs - values[i][j] <= mine for j in package):
                return False
    return True


def is_envy_free(values, owner):
    n = len(values)
    return all(
        package_value(values, owner, i, k) <= own_value(values, owner, i)
        for i in range(n)
        for k in range(n)
    )


def is_pareto_efficient(values, owner):
    """True if no other allocation is at least as good for everybody and better for somebody."""
    n = len(values)
    mine = [own_value(values, owner, p) for p in range(n)]
    for other in all_owners(values):
        theirs = [own_value(values, other, p) for p in range(n)]
        if all(a >= b for a, b in zip(theirs, mine)) and theirs != mine:
            return False
    return True


def largest_smallest_worth(values):
    """The largest smallest final worth over all allocations and all zero-sum cash.

    For one allocation the worths add up to the total value of the allocation, so the smallest
    worth cannot exceed the average, and cash can always move the worths to the average.
    """
    n = len(values)
    return max(
        Fraction(sum(own_value(values, owner, p) for p in range(n)), n)
        for owner in all_owners(values)
    )


def round_robin_owner(values, order):
    """People take turns in the given order, each taking the item they value most (first on ties).

    Returns the owner list. Items are tried in index order, which the caller makes the order of
    the item names.
    """
    n, m = len(values), len(values[0])
    left = list(range(m))
    owner = [None] * m
    turn = 0
    while left:
        p = order[turn % n]
        pick = max(left, key=lambda j: (values[p][j], -j))
        owner[pick] = p
        left.remove(pick)
        turn += 1
    return owner
