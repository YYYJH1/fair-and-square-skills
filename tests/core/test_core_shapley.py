"""The exact Shapley value from the worth of every group, checked against the definition as an
average over all orders, against the closed form of the airport game, and for its axioms."""

from __future__ import annotations

import itertools
from fractions import Fraction

import fsq_core as core
import pytest
from hypothesis import given
from hypothesis import strategies as st


def by_orders(n, worth):
    """The definition: the average over all n! orders of the worth each player adds."""
    total = [Fraction(0)] * n
    count = 0
    for order in itertools.permutations(range(n)):
        mask = 0
        for player in order:
            total[player] += worth[mask | 1 << player] - worth[mask]
            mask |= 1 << player
        count += 1
    return [value / count for value in total]


def airport(solo):
    """Worth of a group in the airport game: the dearest solo price among its members."""
    n = len(solo)
    return [0] + [max(solo[i] for i in range(n) if mask >> i & 1) for mask in range(1, 1 << n)]


def airport_closed_form(solo):
    """Littlechild and Owen: every stretch of road is shared by the riders still in the car."""
    n = len(solo)
    order = sorted(range(n), key=lambda i: (solo[i], i))
    share = [Fraction(0)] * n
    running = Fraction(0)
    previous = Fraction(0)
    for position, player in enumerate(order):
        running += Fraction(solo[player] - previous) / (n - position)
        previous = solo[player]
        share[player] = running
    return share


WORTHS = st.integers(min_value=3, max_value=4).flatmap(
    lambda n: st.tuples(
        st.just(n),
        st.lists(st.integers(min_value=-50, max_value=50), min_size=1 << n, max_size=1 << n).map(
            lambda values: [0] + values[1:]
        ),
    )
)


class TestAgainstTheDefinition:
    @given(WORTHS)
    def test_integer_worths_equal_the_average_over_all_orders(self, case):
        n, worth = case
        assert core.shapley_values(n, worth) == by_orders(n, worth)

    @given(st.integers(2, 5), st.data())
    def test_fraction_worths_equal_the_average_over_all_orders(self, n, data):
        worth = [Fraction(0)] + [
            Fraction(data.draw(st.integers(-30, 30)), data.draw(st.integers(1, 7)))
            for _ in range((1 << n) - 1)
        ]
        assert core.shapley_values(n, worth) == by_orders(n, worth)

    @given(st.lists(st.integers(0, 40), min_size=1, max_size=7))
    def test_the_airport_game_has_the_closed_form(self, solo):
        n = len(solo)
        assert core.shapley_values(n, airport(solo)) == airport_closed_form(solo)

    def test_the_hand_worked_threshold_example(self):
        # a coupon of 60 for an order of at least 300, with dishes of 150, 140 and 20
        dishes = [150, 140, 20]
        worth = [
            60 if sum(d for i, d in enumerate(dishes) if m >> i & 1) >= 300 else 0 for m in range(8)
        ]
        assert core.shapley_values(3, worth) == [20, 20, 20]

    def test_a_game_with_two_players_splits_the_gain_from_joining(self):
        # alone 4 and 6, together 14: each gets the solo worth plus half of the gain 4
        assert core.shapley_values(2, [0, 4, 6, 14]) == [6, 8]

    def test_the_results_are_fractions(self):
        values = core.shapley_values(3, [0, 0, 0, 0, 0, 0, 0, 1])
        assert values == [Fraction(1, 3)] * 3
        assert all(isinstance(value, Fraction) for value in values)


class TestAxioms:
    @given(WORTHS)
    def test_efficiency_the_values_add_up_to_the_worth_of_everyone(self, case):
        n, worth = case
        assert sum(core.shapley_values(n, worth)) == worth[-1] - worth[0]

    def test_efficiency_with_a_nonzero_empty_group(self):
        worth = [5, 7, 9, 20]
        assert sum(core.shapley_values(2, worth)) == worth[-1] - worth[0]

    @given(st.integers(0, 30), st.integers(0, 30), st.integers(0, 30))
    def test_symmetry_interchangeable_players_get_equal_values(self, a, b, c):
        # the worth depends only on how many of players 0 and 1 are present, and on player 2
        def worth(mask):
            return a * bin(mask & 3).count("1") ** 2 + b * (mask >> 2 & 1) + c

        values = core.shapley_values(3, [worth(mask) - c * (mask == 0) for mask in range(8)])
        assert values[0] == values[1]

    @given(WORTHS)
    def test_a_null_player_gets_nothing(self, case):
        n, worth = case
        bigger = list(worth) + list(worth)  # a new last player adds nothing to any group
        values = core.shapley_values(n + 1, bigger)
        assert values[-1] == 0
        assert values[:n] == core.shapley_values(n, worth)

    @given(WORTHS, WORTHS)
    def test_additivity_the_value_of_a_sum_of_games_is_the_sum_of_the_values(self, first, second):
        n = min(first[0], second[0])
        one = first[1][: 1 << n]
        two = second[1][: 1 << n]
        total = [x + y for x, y in zip(one, two)]
        expected = [x + y for x, y in zip(core.shapley_values(n, one), core.shapley_values(n, two))]
        assert core.shapley_values(n, total) == expected

    @given(WORTHS, st.randoms(use_true_random=False))
    def test_relabelling_the_players_relabels_the_values(self, case, rnd):
        n, worth = case
        perm = list(range(n))
        rnd.shuffle(perm)

        def relabel(mask):
            return sum(1 << perm[i] for i in range(n) if mask >> i & 1)

        moved = [0] * (1 << n)
        for mask in range(1 << n):
            moved[relabel(mask)] = worth[mask]
        original = core.shapley_values(n, worth)
        assert core.shapley_values(n, moved) == [original[perm.index(j)] for j in range(n)]


class TestEdges:
    def test_no_players(self):
        assert core.shapley_values(0, [0]) == []

    def test_one_player_gets_the_whole_worth(self):
        assert core.shapley_values(1, [0, 9]) == [9]

    def test_the_input_is_not_changed(self):
        worth = [0, 1, 2, 5]
        core.shapley_values(2, worth)
        assert worth == [0, 1, 2, 5]

    def test_sixteen_players_with_integer_worths_are_exact(self):
        n = 16
        worth = [0] * (1 << n)
        for mask in range(1, 1 << n):
            worth[mask] = 100 if bin(mask).count("1") >= 8 else 0
        values = core.shapley_values(n, worth)
        assert values == [Fraction(100, n)] * n

    @pytest.mark.parametrize("n", [-1, 21, True, 2.0, "2", None])
    def test_the_number_of_players_must_be_a_small_whole_number(self, n):
        with pytest.raises(ValueError):
            core.shapley_values(n, [0] * 4)

    @pytest.mark.parametrize("length", [0, 3, 5])
    def test_there_must_be_one_worth_per_group(self, length):
        with pytest.raises(ValueError, match="one entry for each of the 4 groups"):
            core.shapley_values(2, [0] * length)

    @pytest.mark.parametrize("bad", [0.5, True, "1", None, 1 + 2j])
    def test_worths_must_be_exact_numbers(self, bad):
        with pytest.raises(TypeError, match="ints or Fractions"):
            core.shapley_values(2, [0, bad, 1, 2])
