"""Reference code for the gift-exchange tests. It shares no code with the script.

The seed mapping, the counter stream and the shuffle are written out again from their
specification (hashlib and json only). The legal plans are found by looking at every permutation,
Hall's condition by looking at every subset of givers, and the circles by following the gifts.
All of it is slow but obviously right for the sizes the tests use.
"""

from __future__ import annotations

import hashlib
import itertools
import json


def spec_seed(rule, participants, n_slots, source):
    """Seed exactly as the specification words it, written with the standard json module."""
    text = json.dumps(
        {"rule": rule, "participants": sorted(participants), "n_slots": n_slots, "source": source},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(text.encode("utf-8")).digest()


class SpecStream:
    """The counter stream: draw c is the first 8 bytes of SHA-256(seed + c), read big-endian."""

    def __init__(self, seed):
        self.seed = seed
        self.counter = 0

    def below(self, n):
        while True:
            block = hashlib.sha256(self.seed + self.counter.to_bytes(8, "big")).digest()
            self.counter += 1
            x = int.from_bytes(block[:8], "big")
            if x < 2**64 - (2**64 % n):
                return x % n

    def shuffled(self, n):
        """Fisher-Yates over 0 .. n-1, i from n-1 down to 1."""
        items = list(range(n))
        for i in range(n - 1, 0, -1):
            j = self.below(i + 1)
            items[i], items[j] = items[j], items[i]
        return items


# ---------------------------------------------------------------------------------------
# Legal plans by looking at every permutation
# ---------------------------------------------------------------------------------------


def blocked_indexes(names, blocked_names):
    """Directions as (giver, receiver) numbers over the names sorted by code point."""
    order = sorted(names)
    place = {name: i for i, name in enumerate(order)}
    return {(place[a], place[b]) for a, b in blocked_names}


def is_circle(plan):
    """True when following the gifts from person 0 visits everybody before coming back."""
    seen, person = set(), 0
    while person not in seen:
        seen.add(person)
        person = plan[person]
    return len(seen) == len(plan) and person == 0


def legal_plans(n, blocked, ring):
    """Every legal plan, in increasing order, by testing all n! permutations."""
    return [
        plan
        for plan in itertools.permutations(range(n))
        if all(plan[i] != i and (i, plan[i]) not in blocked for i in range(n))
        and (not ring or is_circle(plan))
    ]


def both_ways(pairs):
    """The directions that a list of unordered pairs of names forbids."""
    return {(a, b) for a, b in pairs} | {(b, a) for a, b in pairs}


# ---------------------------------------------------------------------------------------
# Hall's condition by looking at every subset of givers
# ---------------------------------------------------------------------------------------


def receivers_of(group, n, blocked):
    return {j for i in group for j in range(n) if j != i and (i, j) not in blocked}


def hall_violators(n, blocked):
    """Every non-empty group of givers who may give to fewer people than the group has."""
    found = []
    for size in range(1, n + 1):
        for group in itertools.combinations(range(n), size):
            if len(receivers_of(group, n, blocked)) < size:
                found.append(group)
    return found


def has_perfect_matching(n, blocked):
    """Hall's theorem, checked on every subset: a legal plan of the way any exists."""
    return not hall_violators(n, blocked)


# ---------------------------------------------------------------------------------------
# The draw, from the specification
# ---------------------------------------------------------------------------------------


def enumeration_draw(names, blocked_names, ring, source):
    """(plan, number, count) of the enumeration method, for up to nine people."""
    n = len(names)
    rule = f"gift_exchange_{'ring' if ring else 'any'}_enum_v1"
    plans = legal_plans(n, blocked_indexes(names, blocked_names), ring)
    stream = SpecStream(spec_seed(rule, names, n, source))
    index = stream.below(len(plans))
    return plans[index], index + 1, len(plans)


def rejection_draw(names, blocked_names, ring, source, max_attempts=20000):
    """(plan, attempts) of the rejection method, or None when no proposal is legal."""
    n = len(names)
    rule = f"gift_exchange_{'ring' if ring else 'any'}_reject_v1"
    blocked = blocked_indexes(names, blocked_names)
    stream = SpecStream(spec_seed(rule, names, n, source))
    for attempt in range(1, max_attempts + 1):
        s = stream.shuffled(n)
        if ring:
            plan = [0] * n
            for k in range(n):
                plan[s[k]] = s[(k + 1) % n]
        else:
            plan = list(s)
        if all(plan[i] != i and (i, plan[i]) not in blocked for i in range(n)):
            return tuple(plan), attempt
    return None


def chi_square(counts, expected):
    """Pearson's statistic of observed counts against one expected count per cell."""
    return sum((count - expected) ** 2 / expected for count in counts)
