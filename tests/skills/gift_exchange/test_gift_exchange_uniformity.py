"""Uniformity: every legal plan equally likely. Exact where it can be, a statistical check where
it cannot.

The statistical tests use fixed source texts, so they give the same answer on every run and never
flake. The thresholds are far in the tail (p about 0.001 on either side), so a failure means a
real bias, or a pattern that is too regular, and not bad luck. Where the exact argument is simple
it is made exactly: the shuffle reaches every permutation once, so the legal proposals are the
legal plans, each once for the way any and each n times for one circle.
"""

from __future__ import annotations

import collections
import dataclasses
import itertools
from unittest import mock

import fsq_core as fc
import gift_exchange as ge
from gift_reference import chi_square
from gift_support import exchange_data, six_people

# Critical values of the chi-square distribution on either side, from scipy:
CHI2_DF95 = (58.0, 143.4)  # 96 plans, one cell per plan: p about 0.001 on each side
CHI2_DF39 = (17.3, 72.1)  # 40 circles
ATTEMPTS_Z_LIMIT = 4.5  # a mean of geometric counts: |z| above this has probability below 1e-5


def drawn_plans(mode: str, label: str, how_many: int, rejection: bool) -> tuple:
    """(counts, all legal plans) after drawing the six-person example with how_many sources."""
    problem = ge.parse_problem(six_people(mode))
    plans = ge.list_plans(problem.allowed, mode == "ring")
    counts: collections.Counter = collections.Counter()
    with mock.patch.object(ge, "ENUMERATE_MAX", 1 if rejection else 9):
        for i in range(how_many):
            counts[ge.draw_plan(dataclasses.replace(problem, source=f"{label}-{i}")).plan] += 1
    assert set(counts) <= set(plans), "a plan outside the legal ones was drawn"
    return counts, plans


def check_uniform(counts, plans, how_many, limits) -> None:
    cells = [counts[plan] for plan in plans]
    assert min(cells) > 0, "some legal plan never came up"
    low, high = limits
    statistic = chi_square(cells, how_many / len(plans))
    assert low < statistic < high, f"chi-square {statistic:.1f} outside ({low}, {high})"


def test_the_96_plans_of_the_recorded_example_are_equally_likely():
    counts, plans = drawn_plans("any", "uniform-any", 9600, rejection=False)
    assert len(plans) == 96
    check_uniform(counts, plans, 9600, CHI2_DF95)


def test_the_40_circles_of_the_recorded_example_are_equally_likely():
    counts, plans = drawn_plans("ring", "uniform-ring", 4000, rejection=False)
    assert len(plans) == 40
    check_uniform(counts, plans, 4000, CHI2_DF39)


def test_proposals_give_each_of_the_96_plans_the_same_chance():
    counts, plans = drawn_plans("any", "reject-any", 9600, rejection=True)
    check_uniform(counts, plans, 9600, CHI2_DF95)


def test_proposals_give_each_of_the_40_circles_the_same_chance():
    counts, plans = drawn_plans("ring", "reject-ring", 4000, rejection=True)
    check_uniform(counts, plans, 4000, CHI2_DF39)


def mean_attempts(mode: str, how_many: int) -> float:
    people = [f"p{i:02d}" for i in range(12)]
    problem = ge.parse_problem(exchange_data(people, [], mode))
    total = 0
    for i in range(how_many):
        draw = ge.draw_plan(dataclasses.replace(problem, source=f"attempts-{mode}-{i}"))
        total += draw.attempts or 0
    return total / how_many


def test_a_random_permutation_of_twelve_is_a_derangement_with_probability_one_over_e():
    """The number of proposals up to the first derangement is geometric, with mean 1/p and
    p = D(12) / 12! = 176214841 / 479001600, which is 0.36788 (and 1/e is 0.36788 too)."""
    p = 176214841 / 479001600
    how_many = 600
    sd = ((1 - p) ** 0.5) / p
    z = (mean_attempts("any", how_many) - 1 / p) / (sd / how_many**0.5)
    assert abs(z) < ATTEMPTS_Z_LIMIT, f"z = {z:.2f}"


def test_a_random_arrangement_in_a_circle_is_always_one_circle():
    """Without exclusions every proposal of the way ring is a legal circle, so the first one is
    taken: the arrangement in a row is turned into a circle, and no proposal is wasted."""
    assert mean_attempts("ring", 300) == 1.0


# ---------------------------------------------------------------------------------------
# The exact argument: every proposal is reached by one choice sequence
# ---------------------------------------------------------------------------------------


class ScriptedStream:
    """A stand-in for SeedStream that returns chosen numbers instead of hash output."""

    def __init__(self, numbers):
        self.numbers = list(numbers)

    def below(self, n):
        value = self.numbers.pop(0)
        assert 0 <= value < n
        return value


def choice_sequences(n: int):
    """The choices Fisher-Yates makes: one number in [0, i] for i = n-1 down to 1."""
    return itertools.product(*(range(i + 1) for i in range(n - 1, 0, -1)))


def test_the_shuffle_reaches_every_permutation_by_exactly_one_choice_sequence():
    seen = collections.Counter(
        tuple(fc.shuffle(list(range(4)), ScriptedStream(choices)))
        for choices in choice_sequences(4)
    )
    assert len(seen) == 24 and set(seen.values()) == {1}


def legal_proposals(mode: str) -> collections.Counter:
    people = ["a", "b", "c", "d"]
    problem = ge.parse_problem(exchange_data(people, [{"pair": ["a", "b"]}], mode))
    allowed_sets = [frozenset(row) for row in problem.allowed]
    ring = mode == "ring"
    found: collections.Counter = collections.Counter()
    for choices in choice_sequences(4):
        proposal = fc.shuffle(list(range(4)), ScriptedStream(choices))
        if ge.is_legal(allowed_sets, proposal, ring):
            found[ge.plan_from_proposal(proposal, ring)] += 1
    assert set(found) == set(ge.list_plans(problem.allowed, ring))
    return found


def test_in_the_way_any_every_legal_plan_is_one_proposal_in_twenty_four():
    found = legal_proposals("any")
    assert len(found) > 1 and set(found.values()) == {1}


def test_in_the_way_ring_every_legal_circle_is_n_proposals_in_twenty_four():
    """A circle through four people can be written starting from any of them, so four rows of
    the shuffle stand for it."""
    found = legal_proposals("ring")
    assert len(found) >= 1 and set(found.values()) == {4}


def test_the_listing_method_draws_a_number_below_the_count_and_nothing_else():
    """Plan number k + 1 of the list is the plan, and k is the first uniform integer of the
    stream, so the plan is as uniform as that integer is."""
    problem = ge.parse_problem(six_people())
    draw = ge.draw_plan(problem)
    stream = fc.SeedStream(bytes.fromhex(draw.seed_hex))
    assert stream.below(96) + 1 == draw.number
    plans = ge.list_plans(problem.allowed, ring=False)
    assert plans[draw.number - 1] == draw.plan
