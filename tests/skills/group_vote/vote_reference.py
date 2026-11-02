"""Plain reference implementations of the counting rules, written for the tests only.

They follow the definitions in the skill's documentation and work on expanded ballots (one
ranking per person, as lists of option names), with simple loops and no merging, so they share
no code with the script. A tie that the order would have to break raises ReferenceTie when no
order is given. Where the order breaks a tie, the option that comes first in it wins, and the
option that comes last in it is the one eliminated.
"""

from __future__ import annotations

import itertools
from fractions import Fraction


class ReferenceTie(Exception):
    """A tie that needs the random order, and there is none."""

    def __init__(self, tied):
        super().__init__(f"tie between {tied}")
        self.tied = sorted(tied)


def expand(lines):
    """[(count, ranking)] to one ranking per person."""
    return [list(ranking) for count, ranking in lines for _ in range(count)]


def restrict(ballots, alive):
    """Remove the options that are out of the race from every ballot, dropping empty ones."""
    kept = [[o for o in ballot if o in alive] for ballot in ballots]
    return [ballot for ballot in kept if ballot]


def favoured(tied, order):
    tied = list(tied)
    if len(tied) == 1:
        return tied[0]
    if order is None:
        raise ReferenceTie(tied)
    return min(tied, key=order.index)


def prefers(ballot, a, b):
    """True if the ballot puts a above b: a ranked option beats an unranked one."""
    if a not in ballot:
        return False
    return b not in ballot or ballot.index(a) < ballot.index(b)


def pairwise(ballots, alive):
    return {
        (a, b): sum(prefers(r, a, b) for r in ballots) for a, b in itertools.permutations(alive, 2)
    }


def plurality(ballots, alive, order):
    score = {o: sum(1 for r in ballots if r[0] == o) for o in alive}
    top = max(score.values())
    return favoured([o for o in alive if score[o] == top], order)


def runoff(ballots, alive, order):
    first = {o: sum(1 for r in ballots if r[0] == o) for o in alive}
    total = sum(first.values())
    top = max(first.values())
    if 2 * top > total:
        return next(o for o in alive if first[o] == top)
    counts = sorted(first.values(), reverse=True)
    if len(counts) > 2 and counts[1] == counts[2] and order is None:
        raise ReferenceTie([o for o in alive if first[o] == counts[1]])
    if order is None:
        x, y = sorted(alive, key=lambda o: (-first[o], alive.index(o)))[:2]
    else:
        x, y = sorted(alive, key=lambda o: (-first[o], order.index(o)))[:2]
    votes = {x: 0, y: 0}
    for ballot in ballots:
        if prefers(ballot, x, y):
            votes[x] += 1
        elif prefers(ballot, y, x):
            votes[y] += 1
    if votes[x] != votes[y]:
        return x if votes[x] > votes[y] else y
    return favoured([x, y], order)


def irv(ballots, alive, order):
    remaining = list(alive)
    while True:
        counts = {o: 0 for o in remaining}
        for ballot in ballots:
            for option in ballot:
                if option in counts:
                    counts[option] += 1
                    break
        continuing = sum(counts.values())
        top = max(counts.values())
        if 2 * top > continuing or len(remaining) == 1:
            return next(o for o in remaining if counts[o] == top)
        low = min(counts.values())
        lowest = [o for o in remaining if counts[o] == low]
        if low == 0:
            remaining = [o for o in remaining if counts[o] > 0]
        elif len(lowest) == 1:
            remaining.remove(lowest[0])
        elif order is None:
            raise ReferenceTie(lowest)
        else:
            remaining.remove(max(lowest, key=order.index))


def borda_scores(ballots, alive):
    """Exact Borda points; options a ballot leaves out share the points that are left."""
    m = len(alive)
    score = {o: Fraction(0) for o in alive}
    for ballot in ballots:
        for place, option in enumerate(ballot):
            score[option] += m - 1 - place
        left_out = [o for o in alive if o not in ballot]
        for option in left_out:
            score[option] += Fraction(len(left_out) - 1, 2)
    return score


def borda(ballots, alive, order):
    score = borda_scores(ballots, alive)
    top = max(score.values())
    return favoured([o for o in alive if score[o] == top], order)


def condorcet_winner(ballots, alive):
    d = pairwise(ballots, alive)
    for a in alive:
        if all(d[a, b] > d[b, a] for b in alive if b != a):
            return a
    return None


def schulze_set(ballots, alive):
    """Potential winners by enumerating every simple path (independent of Floyd-Warshall)."""
    d = pairwise(ballots, alive)
    strength = {}
    for a, b in itertools.permutations(alive, 2):
        others = [o for o in alive if o not in (a, b)]
        best = 0
        for size in range(len(others) + 1):
            for middle in itertools.permutations(others, size):
                path = [a, *middle, b]
                links = list(zip(path, path[1:]))
                if all(d[x, y] > d[y, x] for x, y in links):
                    best = max(best, min(d[x, y] for x, y in links))
        strength[a, b] = best
    return [a for a in alive if all(strength[a, b] >= strength[b, a] for b in alive if b != a)]


def schulze(ballots, alive, order):
    return favoured(schulze_set(ballots, alive), order)


def kemeny_rankings(ballots, alive):
    """(best score, every ranking that reaches it), by trying all orders."""
    d = pairwise(ballots, alive)
    best, found = -1, []
    for ranking in itertools.permutations(alive):
        score = sum(
            d[ranking[i], ranking[j]]
            for i in range(len(ranking))
            for j in range(i + 1, len(ranking))
        )
        if score > best:
            best, found = score, [list(ranking)]
        elif score == best:
            found.append(list(ranking))
    return best, found


def kemeny_pick(ballots, alive, order):
    """The optimal ranking that a top-down use of the order selects, and the best score."""
    best, found = kemeny_rankings(ballots, alive)
    if len(found) > 1 and order is None:
        raise ReferenceTie(sorted({r[0] for r in found}))
    ranking = min(found, key=lambda r: [order.index(o) for o in r]) if order else found[0]
    return best, ranking


def approval(approvals, alive, order):
    score = {o: sum(1 for ballot in approvals if o in ballot) for o in alive}
    top = max(score.values())
    return favoured([o for o in alive if score[o] == top], order)


def has_cycle(ballots, alive):
    """True if the 'beats' graph (more ballots put a above b) contains a directed cycle."""
    d = pairwise(ballots, alive)
    beats = {a: [b for b in alive if b != a and d[a, b] > d[b, a]] for a in alive}
    state = {}

    def visit(node):
        state[node] = 1
        for nxt in beats[node]:
            if state.get(nxt) == 1:
                return True
            if nxt not in state and visit(nxt):
                return True
        state[node] = 2
        return False

    return any(a not in state and visit(a) for a in alive)


RULES = {
    "plurality": plurality,
    "runoff": runoff,
    "irv": irv,
    "borda": borda,
    "condorcet": lambda ballots, alive, order: schulze(ballots, alive, order),
    "schulze": schulze,
}
