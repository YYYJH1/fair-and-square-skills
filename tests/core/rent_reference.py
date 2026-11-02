"""Exact reference solver for envy-free rent division, used only to build test inputs.

It is the closed form of Gal, Mash, Procaccia and Zick (maximin, rents may be negative):
take the assignment with the largest total bid, then shortest paths on the envy graph.
The core's rounding functions need exact envy-free prices to be tested on realistic input.
"""

from __future__ import annotations

from fractions import Fraction
from itertools import permutations


def maximin_rents(
    bids: list[list[Fraction]], total: Fraction
) -> tuple[tuple[int, ...], list[Fraction]]:
    """Return (room of each person, exact rent of each room) for bids[person][room]."""
    n = len(bids)
    room_of = max(permutations(range(n)), key=lambda perm: sum(bids[i][perm[i]] for i in range(n)))
    dist = [
        [Fraction(0) if i == k else bids[k][room_of[k]] - bids[i][room_of[k]] for k in range(n)]
        for i in range(n)
    ]
    for mid in range(n):
        for i in range(n):
            for k in range(n):
                dist[i][k] = min(dist[i][k], dist[i][mid] + dist[mid][k])
    lows = [-min(row) for row in dist]
    surplus = sum(bids[i][room_of[i]] for i in range(n)) - total
    level = (surplus - sum(lows)) / n
    rents = [Fraction(0)] * n
    for i in range(n):
        rents[room_of[i]] = bids[i][room_of[i]] - (level + lows[i])
    return room_of, rents


def as_mappings(
    bids: list[list[Fraction]], room_of: tuple[int, ...], rents: list[Fraction]
) -> tuple[dict[str, dict[str, Fraction]], dict[str, str], dict[str, Fraction]]:
    """Convert matrices to the dict form of the core: bids, assignment, prices.

    People are named p0, p1, ... and rooms r0, r1, ... by index.
    """
    n = len(bids)
    bid_map = {f"p{i}": {f"r{k}": bids[i][k] for k in range(n)} for i in range(n)}
    assignment = {f"p{i}": f"r{room_of[i]}" for i in range(n)}
    prices = {f"r{k}": rents[k] for k in range(n)}
    return bid_map, assignment, prices


def is_envy_free(
    bids: list[list[Fraction]], room_of: tuple[int, ...], rents: list[Fraction]
) -> bool:
    """True if nobody prefers another room at the given exact rents."""
    n = len(bids)
    return all(
        bids[i][k] - rents[k] <= bids[i][room_of[i]] - rents[room_of[i]]
        for i in range(n)
        for k in range(n)
    )
