"""Cross-checks of the exact shortest-path solution against linear programming (scipy).

The script solves the rent division in exact fractions without a solver. These tests solve the
same problems with scipy's HiGHS and compare: the maximin value, the question whether a split
without negative rent exists at all, and the leximin utilities.
"""

from __future__ import annotations

from fractions import Fraction

import pytest
from hypothesis import given
from rent_split_lp import lp_leximin, lp_maximin
from rent_split_strategies import SETTINGS, bid_matrices
from rent_split_support import load_script

rs = load_script()
fc = rs.fc

TOLERANCE = 1e-6  # in units of the total rent


def solve(rows, total, rule):
    return rs.solve_exact([[Fraction(x) for x in row] for row in rows], Fraction(total), rule)


def squared_weight_cases(count, seed):
    """Spread-out bids (squares of random weights), which often force a negative rent."""
    stream = fc.SeedStream(fc.make_seed("rent-lp-sweep", [seed], count, "lp"))
    total = 100_000
    for _ in range(count):
        n = 2 + stream.below(5)
        rows = []
        for _person in range(n):
            weights = [stream.below(41) ** 2 for _ in range(n)]
            if not sum(weights):
                weights = [1] * n
            row = [total * w // sum(weights) for w in weights]
            row[0] += total - sum(row)
            rows.append(row)
        yield rows, total


def check_against_lp(rows, total):
    n = len(rows)
    allow = solve(rows, total, "allow")
    lp_value = lp_maximin(rows, total, allow.room_of, non_negative=False)
    assert lp_value is not None
    assert abs(float(min(allow.utilities)) / total - lp_value) <= TOLERANCE

    spliddit = solve(rows, total, "spliddit")
    lp_nonneg = lp_maximin(rows, total, spliddit.room_of, non_negative=True)
    if spliddit.applied == rs.APPLIED_FALLBACK:
        assert lp_nonneg is None  # the LP agrees that no split without negative rent exists
        return "infeasible"
    assert lp_nonneg is not None
    assert abs(float(min(spliddit.utilities)) / total - lp_nonneg) <= TOLERANCE
    lex = lp_leximin(rows, total, spliddit.room_of)
    assert lex is not None
    exact = [float(u) / total for u in spliddit.utilities]
    assert max(abs(a - b) for a, b in zip(exact, lex)) <= TOLERANCE
    assert len(exact) == n
    return "negative" if min(allow.rents) < 0 else "plain"


@SETTINGS
@given(bid_matrices(max_people=5))
def test_maximin_leximin_and_feasibility_match_the_linear_programs(case):
    rows, total = case
    check_against_lp(rows, total)


def test_a_seeded_sweep_covers_plain_negative_and_infeasible_cases():
    seen = {"plain": 0, "negative": 0, "infeasible": 0}
    for rows, total in squared_weight_cases(150, "sweep"):
        seen[check_against_lp(rows, total)] += 1
    assert all(count >= 3 for count in seen.values()), seen


def test_the_closet_that_nobody_values_has_no_split_without_negative_rent():
    rows = [[0, 2, 0, 4], [0, 3, 3, 0], [0, 1, 0, 5], [0, 0, 5, 1]]
    allow = solve(rows, 6, "allow")
    assert allow.rents == [Fraction(-7, 4), Fraction(5, 4), Fraction(13, 4), Fraction(13, 4)]
    assert lp_maximin(rows, 6, allow.room_of, non_negative=True) is None
    assert solve(rows, 6, "spliddit").applied == rs.APPLIED_FALLBACK
    with pytest.raises(fc.NoSolution):
        solve(rows, 6, "forbid")


def test_leximin_differs_from_plain_maximin_when_a_rent_would_be_negative():
    rows = [[48, 10, 2], [10, 48, 2], [29, 29, 2]]
    total = 60
    allow = solve(rows, total, "allow")
    spliddit = solve(rows, total, "spliddit")
    assert min(allow.rents) < 0 <= min(spliddit.rents)
    assert spliddit.utilities != allow.utilities
    assert sum(spliddit.rents) == sum(allow.rents) == total
