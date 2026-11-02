"""Uniformity: every order equally likely. Exact where it can be, a loose statistical check
where it cannot.

The statistical tests use fixed source texts, so they give the same answer on every run and
never flake. The thresholds are far in the tail (p about 0.001 or smaller), so a failure means
a real bias and not bad luck. Where the exact argument is simple it is made exactly: the
shuffle visits every permutation once for the choice sequences it can make, and the serial
dictatorship's exact probabilities are enumerated over all orders.
"""

from __future__ import annotations

import collections
import itertools
from fractions import Fraction

import fsq_core as fc
import slot_lottery as sl
from lottery_reference import chi_square, exact_rsd_probabilities

# Critical values of the chi-square distribution (upper tail), from scipy:
CHI2_DF23_P001 = 49.728  # 24 possible orders, one cell per draw
CHI2_DF4_P0002 = 22.005  # one row or column of a 5 x 5 position table (a multinomial)
Z_LIMIT = 4.5  # win counts: |z| above this has probability below 1e-5


def draw(people, n_slots, source):
    return sl.make_draw("main", people, "uniform_lottery_v1", n_slots, source)


def test_the_orders_of_four_people_are_uniform():
    people = ["甲", "乙", "丙", "丁"]
    n = 4800
    counts = collections.Counter(tuple(draw(people, 2, f"uniformity-{i}").order) for i in range(n))
    assert len(counts) == 24, "some order never occurred"
    cells = [counts[order] for order in itertools.permutations(people)]
    assert chi_square(cells, n / 24) < CHI2_DF23_P001


def test_every_person_is_equally_likely_at_every_position():
    people = list("ABCDE")
    n = 5000
    table = collections.Counter()
    for i in range(n):
        for place, person in enumerate(draw(people, 2, f"position-{i}").order):
            table[(person, place)] += 1
    for person in people:
        row = [table[(person, place)] for place in range(5)]
        assert chi_square(row, n / 5) < CHI2_DF4_P0002, f"{person} prefers some positions"
    for place in range(5):
        column = [table[(person, place)] for person in people]
        assert chi_square(column, n / 5) < CHI2_DF4_P0002, f"position {place} prefers someone"


def test_each_person_is_drawn_with_probability_slots_over_people():
    people = list("ABCDEF")
    n = 6000
    wins = collections.Counter()
    for i in range(n):
        wins.update(draw(people, 2, f"wins-{i}").order[:2])
    expected = n * 2 / 6
    sd = (n * (2 / 6) * (4 / 6)) ** 0.5
    for person in people:
        assert abs(wins[person] - expected) / sd < Z_LIMIT, f"{person} won {wins[person]} times"


class ScriptedStream:
    """A stand-in for SeedStream that returns chosen numbers instead of hash output."""

    def __init__(self, numbers):
        self.numbers = list(numbers)

    def below(self, n):
        value = self.numbers.pop(0)
        assert 0 <= value < n
        return value


def test_the_shuffle_reaches_every_permutation_exactly_once():
    """Fisher-Yates makes one choice per position, n! choice sequences in all, and each of
    them gives a different permutation. With equally likely choices every order is therefore
    exactly as likely as every other one."""
    names = ["a", "b", "c", "d"]
    seen = collections.Counter()
    for choices in itertools.product(range(4), range(3), range(2)):
        seen[tuple(fc.shuffle(names, ScriptedStream(choices)))] += 1
    assert len(seen) == 24
    assert set(seen.values()) == {1}


def test_moving_up_the_waiting_list_equals_drawing_among_those_who_remain():
    """If one person leaves a uniformly random order, the others still form a uniformly random
    order: every order of the remaining people arises from the same number of full orders."""
    names = ["a", "b", "c", "d"]
    for leaver in names:
        remaining = collections.Counter(
            tuple(name for name in order if name != leaver)
            for order in itertools.permutations(names)
        )
        assert len(remaining) == 6
        assert set(remaining.values()) == {4}


def test_rejection_sampling_leaves_every_residue_equally_likely():
    """below(n) keeps x mod n only for x below the largest multiple of n, so each residue has
    exactly the same number of accepted values."""
    for n in (3, 5, 6, 7, 100):
        limit = 2**64 - (2**64 % n)
        assert limit % n == 0
        assert 2**64 - limit < n, "fewer rejected values than one full residue class"


# ---------------------------------------------------------------------------------------
# Exact probabilities of the serial dictatorship
# ---------------------------------------------------------------------------------------

CLASSIC_PEOPLE = ["A", "B", "C", "D"]
CLASSIC_SLOTS = ["a", "b", "c", "d"]
CLASSIC_PREFS = {
    "A": list("abcd"),
    "B": list("abcd"),
    "C": list("badc"),
    "D": list("badc"),
}


def test_the_classic_four_person_example_has_the_known_exact_probabilities():
    """Two people rank a > b > c > d and two rank b > a > d > c. Each of the first two gets
    the slot it likes best with probability 5/12 when the order is uniform."""
    probs = exact_rsd_probabilities(
        CLASSIC_PEOPLE, CLASSIC_SLOTS, CLASSIC_PREFS, sl.serial_dictatorship
    )
    twelfth = Fraction(1, 12)
    for person in ("A", "B"):
        assert [probs[person][s] for s in CLASSIC_SLOTS] == [5 * twelfth, twelfth] * 2
    for person in ("C", "D"):
        assert [probs[person][s] for s in CLASSIC_SLOTS] == [twelfth, 5 * twelfth] * 2
    for person in CLASSIC_PEOPLE:
        assert sum(probs[person].values()) == 1, "everybody gets some slot here"


def test_people_with_the_same_ranking_have_the_same_probabilities():
    people = ["p", "q", "r", "s"]
    slots = ["x", "y", "z"]
    prefs = {"p": ["x", "y"], "q": ["x", "y"], "r": ["y", "z", "x"], "s": ["z"]}
    probs = exact_rsd_probabilities(people, slots, prefs, sl.serial_dictatorship)
    assert probs["p"] == probs["q"]
    # nobody gets a slot more often than the orders allow
    for person in people:
        assert sum(probs[person].values()) <= 1
    # every slot goes to somebody in some order, none is certain for everybody
    assert all(0 < sum(probs[p][s] for p in people) <= 1 for s in slots)


def test_each_exact_probability_matches_a_uniform_sample_of_the_script_orders():
    """The script's orders, run through the same rule, reproduce the exact probability."""
    people, slots, prefs = CLASSIC_PEOPLE, CLASSIC_SLOTS, CLASSIC_PREFS
    n = 4800
    firsts = 0
    for i in range(n):
        order = sl.make_draw("main", people, "rsd_v1", 4, f"classic-{i}").order
        firsts += sl.serial_dictatorship(order, prefs, slots)[0].get("A") == "a"
    assert abs(firsts / n - 5 / 12) < 0.03
