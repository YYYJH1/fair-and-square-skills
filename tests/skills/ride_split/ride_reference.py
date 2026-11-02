"""Independent reference implementations, used only to check the ride-split script.

They avoid the script's bit-mask tricks on purpose: groups are plain tuples of rider indexes
and every Shapley value is an average over all orders.
"""

from __future__ import annotations

import itertools
from fractions import Fraction


def airport_price(solo, group):
    """Price of a group in the airport game: the dearest solo price among its members."""
    return max((solo[i] for i in group), default=Fraction(0))


def shapley_by_permutations(n, price):
    """Shapley value of a game price(group), by averaging over all n! orders of arrival."""
    total = [Fraction(0)] * n
    orders = 0
    for order in itertools.permutations(range(n)):
        arrived = []
        for rider in order:
            before = price(tuple(sorted(arrived)))
            arrived.append(rider)
            total[rider] += price(tuple(sorted(arrived))) - before
        orders += 1
    return [value / orders for value in total]


def violations_by_enumeration(n, price, paid):
    """The set of groups (sorted tuples) whose members pay more together than price(group)."""
    found = set()
    for size in range(1, n + 1):
        for group in itertools.combinations(range(n), size):
            if sum(paid[i] for i in group) > price(group):
                found.add(group)
    return found


def core_is_nonempty_for_two_or_three(n, price):
    """Core of a cost game with 2 or 3 players, from the classical inequalities.

    Two players: c(12) <= c(1) + c(2). Three players: the same for every partition, and
    2 c(123) <= c(12) + c(13) + c(23) for the balanced collection of the three pairs.
    """
    everyone = tuple(range(n))
    if n == 2:
        return price(everyone) <= price((0,)) + price((1,))
    pairs = [(0, 1), (0, 2), (1, 2)]
    if price(everyone) > sum(price((i,)) for i in range(3)):
        return False
    for i in range(3):
        rest = tuple(j for j in range(3) if j != i)
        if price(everyone) > price((i,)) + price(rest):
            return False
    return 2 * price(everyone) <= sum(price(pair) for pair in pairs)


def shortest_open_route(distances, stops):
    """Length of the shortest route from point 0 through all `stops` (indexes into distances)."""
    best = None
    for order in itertools.permutations(stops):
        length = Fraction(0)
        here = 0
        for stop in order:
            length += distances[here][stop]
            here = stop
        if best is None or length < best:
            best = length
    return best
