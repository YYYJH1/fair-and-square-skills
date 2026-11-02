"""Property tests: the guarantees promised for ride-split, checked on random inputs."""

from __future__ import annotations

import itertools
from fractions import Fraction

import fsq_core as fc
import ride_reference as ref
import ride_split as rs
from hypothesis import assume, given
from hypothesis import strategies as st
from ride_support import (
    NAMES,
    PROPERTY,
    estimates_data,
    estimates_inputs,
    meter_data,
    meter_inputs,
    subset_costs_data,
)


def compute(data: dict, audit: bool = False):
    ride = rs.parse_ride(data, audit)
    return ride, rs.compute(ride)


def solo_costs(max_riders: int = 6):
    """Lists of solo prices in cents, small values so that ties are common."""
    return st.lists(st.integers(0, 60), min_size=1, max_size=max_riders)


@st.composite
def price_tables(draw, max_riders: int = 4):
    """A random game: n riders and the price in cents of every group (index = bit mask)."""
    n = draw(st.integers(2, max_riders))
    prices = [0] + [draw(st.integers(0, 400)) for _ in range((1 << n) - 1)]
    return n, prices


def mask_price(prices):
    """A price table indexed by bit mask, as a function of a tuple of rider indexes."""

    def price(group):
        return Fraction(prices[sum(1 << rider for rider in group)])

    return price


def airport_pricer(out, n):
    """The airport game of a computed ride, as a function of a tuple of rider indexes."""
    solo = [Fraction(out.game.alone[1 << i]) for i in range(n)]
    return lambda group: ref.airport_price(solo, group)


class TestEfficiency:
    """The shares add up to the fare to the cent, in every mode and for every split shown."""

    @PROPERTY
    @given(meter_inputs())
    def test_meter_shares_add_up(self, data):
        ride, out = compute(data)
        assert sum(out.shapley.cents) == ride.total
        for split in out.alternatives.values():
            assert sum(split.cents) == ride.total

    @PROPERTY
    @given(estimates_inputs())
    def test_estimates_shares_add_up(self, data):
        ride, out = compute(data)
        assert sum(out.shapley.cents) == ride.total
        for split in out.alternatives.values():
            assert sum(split.cents) == ride.total

    @PROPERTY
    @given(price_tables())
    def test_general_shares_add_up(self, table):
        _, prices = table
        assume(prices[-1] > 0)
        ride, out = compute(subset_costs_data(prices))
        assert sum(out.shapley.cents) == ride.total == prices[-1]
        for split in out.alternatives.values():
            assert sum(split.cents) == ride.total

    @PROPERTY
    @given(meter_inputs())
    def test_exact_shares_add_up_to_the_fare(self, data):
        ride, out = compute(data)
        assert sum(out.game.exact) == Fraction(ride.total, 100)


class TestClosedFormAgainstBruteForce:
    """The airport-game formula equals the Shapley value computed over all orders."""

    @PROPERTY
    @given(solo_costs())
    def test_closed_form_equals_permutation_shapley(self, costs):
        solo = [Fraction(c, 100) for c in costs]
        expected = ref.shapley_by_permutations(
            len(solo), lambda group: ref.airport_price(solo, group)
        )
        assert rs.airport_shapley(solo) == expected

    @PROPERTY
    @given(solo_costs(5))
    def test_the_scripts_own_helpers_agree_with_each_other(self, costs):
        solo = [Fraction(c) for c in costs]
        n = len(solo)
        table = [Fraction(0)] + [
            max(solo[i] for i in rs.bits(mask, n)) for mask in range(1, 1 << n)
        ]
        closed = rs.airport_shapley(solo)
        assert closed == fc.shapley_values(n, table)
        assert closed == rs.shapley_by_orders(n, table)

    @PROPERTY
    @given(price_tables())
    def test_subset_formula_equals_permutation_shapley(self, table):
        n, prices = table
        expected = ref.shapley_by_permutations(n, mask_price(prices))
        assert fc.shapley_values(n, [Fraction(p) for p in prices]) == expected


class TestSymmetry:
    """Interchangeable riders pay the same."""

    @PROPERTY
    @given(solo_costs(7))
    def test_equal_solo_prices_give_equal_exact_shares(self, costs):
        shares = rs.airport_shapley([Fraction(c) for c in costs])
        for i, j in itertools.combinations(range(len(costs)), 2):
            if costs[i] == costs[j]:
                assert shares[i] == shares[j]

    @PROPERTY
    @given(estimates_inputs())
    def test_equal_estimates_differ_by_at_most_one_cent(self, data):
        ride, out = compute(data)
        for i, j in itertools.combinations(range(ride.n), 2):
            if ride.given[i] == ride.given[j]:
                assert abs(out.shapley.cents[i] - out.shapley.cents[j]) <= 1

    @PROPERTY
    @given(meter_inputs())
    def test_exact_shares_never_fall_along_the_drop_off_order(self, data):
        _, out = compute(data)
        assert out.game.exact == sorted(out.game.exact)

    @PROPERTY
    @given(price_tables(), st.data())
    def test_relabelling_the_riders_relabels_the_shares(self, table, draw):
        n, prices = table
        order = draw.draw(st.permutations(range(n)))
        relabelled = [0] * (1 << n)
        for mask in range(1, 1 << n):
            image = sum(1 << order[i] for i in range(n) if mask >> i & 1)
            relabelled[image] = prices[mask]
        before = fc.shapley_values(n, [Fraction(p) for p in prices])
        after = fc.shapley_values(n, [Fraction(p) for p in relabelled])
        assert [after[order[i]] for i in range(n)] == before

    @PROPERTY
    @given(estimates_inputs(), st.data())
    def test_estimates_do_not_depend_on_the_order_of_the_list(self, data, draw):
        order = draw.draw(st.permutations(range(len(data["riders"]))))
        shuffled = {
            **data,
            "riders": [data["riders"][i] for i in order],
            "solo_estimate": [data["solo_estimate"][i] for i in order],
        }
        ride, out = compute(data)
        ride2, out2 = compute(shuffled)
        assert dict(zip(ride.riders, out.shapley.cents)) == dict(
            zip(ride2.riders, out2.shapley.cents)
        )


class TestNullPlayer:
    """A rider who adds nothing to the fare pays nothing."""

    @PROPERTY
    @given(estimates_inputs(), st.data())
    def test_a_zero_estimate_pays_nothing(self, data, draw):
        index = draw.draw(st.integers(0, len(data["riders"]) - 1))
        estimates = list(data["solo_estimate"])
        estimates[index] = Fraction(0)
        assume(max(estimates) > 0)
        _, out = compute({**data, "solo_estimate": estimates})
        assert out.game.exact[index] == 0
        assert out.shapley.cents[index] == 0

    @PROPERTY
    @given(st.integers(1, 3), st.lists(st.integers(1, 5000), min_size=1, max_size=5))
    def test_zero_readings_at_the_start_pay_nothing(self, zeros, rest):
        readings = [0] * zeros + sorted(rest)
        _, out = compute(meter_data(readings))
        assert out.shapley.cents[:zeros] == [0] * zeros
        assert all(cents >= 0 for cents in out.shapley.cents)

    @PROPERTY
    @given(price_tables(3), st.integers(0, 3))
    def test_a_rider_who_never_changes_the_price_pays_nothing(self, table, where):
        n, prices = table
        assume(prices[-1] > 0)
        dummy = where % (n + 1)
        # a new rider at position `dummy`: every group costs what it costs without that rider
        bigger = [0] * (1 << (n + 1))
        for mask in range(1, 1 << (n + 1)):
            below = mask & ((1 << dummy) - 1)
            above = mask >> (dummy + 1)
            bigger[mask] = prices[below | (above << dummy)]
        shares = fc.shapley_values(n + 1, [Fraction(p) for p in bigger])
        assert shares[dummy] == 0
        _, out = compute(subset_costs_data(bigger))
        assert out.shapley.cents[dummy] == 0


class TestAdditivity:
    """The share for two fares added together is the sum of the shares for each."""

    @PROPERTY
    @given(price_tables(4), st.data())
    def test_shapley_is_additive(self, table, draw):
        n, first = table
        second = [0] + [draw.draw(st.integers(0, 400)) for _ in range((1 << n) - 1)]
        total = [a + b for a, b in zip(first, second)]
        one = fc.shapley_values(n, [Fraction(p) for p in first])
        two = fc.shapley_values(n, [Fraction(p) for p in second])
        both = fc.shapley_values(n, [Fraction(p) for p in total])
        assert both == [a + b for a, b in zip(one, two)]

    @PROPERTY
    @given(solo_costs(5), solo_costs(5))
    def test_two_airport_games_added_together(self, first, second):
        n = min(len(first), len(second))
        first, second = first[:n], second[:n]
        both = [Fraction(0)] + [
            max(first[i] for i in rs.bits(mask, n)) + max(second[i] for i in rs.bits(mask, n))
            for mask in range(1, 1 << n)
        ]
        parts = [
            a + b
            for a, b in zip(
                rs.airport_shapley([Fraction(c) for c in first]),
                rs.airport_shapley([Fraction(c) for c in second]),
            )
        ]
        assert fc.shapley_values(n, both) == parts


class TestCore:
    """The airport-game split is in the core, also after rounding to cents."""

    @PROPERTY
    @given(meter_inputs())
    def test_every_meter_result_is_in_the_core(self, data):
        ride, out = compute(data)
        assert out.shapley.violations == []
        found = ref.violations_by_enumeration(
            ride.n, airport_pricer(out, ride.n), out.shapley.cents
        )
        assert found == set()

    @PROPERTY
    @given(estimates_inputs())
    def test_every_estimates_result_is_in_the_core(self, data):
        ride, out = compute(data)
        assert out.shapley.violations == []
        found = ref.violations_by_enumeration(
            ride.n, airport_pricer(out, ride.n), out.shapley.cents
        )
        assert found == set()

    @PROPERTY
    @given(price_tables(5), st.data())
    def test_core_check_agrees_with_exhaustive_enumeration(self, table, draw):
        n, prices = table
        paid = [draw.draw(st.integers(0, 300)) for _ in range(n)]
        found = rs.core_violations(n, prices, paid)
        assert {item.members for item in found} == ref.violations_by_enumeration(
            n, mask_price(prices), paid
        )
        for item in found:
            assert item.paid == sum(paid[i] for i in item.members)
            assert item.alone == prices[sum(1 << i for i in item.members)]
            assert item.excess > 0

    @PROPERTY
    @given(meter_inputs(7))
    def test_the_alternatives_core_checks_agree_with_enumeration(self, data):
        ride, out = compute(data)
        price = airport_pricer(out, ride.n)
        for split in out.alternatives.values():
            expected = ref.violations_by_enumeration(ride.n, price, split.cents)
            assert {item.members for item in split.violations} == expected

    @PROPERTY
    @given(price_tables(3))
    def test_core_emptiness_agrees_with_the_classical_inequalities(self, table):
        n, prices = table
        expected = ref.core_is_nonempty_for_two_or_three(n, mask_price(prices))
        assert rs.core_is_empty(n, prices) == (not expected)


class TestScaling:
    """The estimates are scaled to the paid total without changing who pays more."""

    @PROPERTY
    @given(estimates_inputs())
    def test_a_dearer_estimate_never_pays_less(self, data):
        ride, out = compute(data)
        for i, j in itertools.permutations(range(ride.n), 2):
            if ride.given[i] < ride.given[j]:
                assert out.shapley.cents[i] <= out.shapley.cents[j]

    @PROPERTY
    @given(estimates_inputs(), st.integers(2, 9))
    def test_the_unit_of_the_estimates_does_not_matter(self, data, factor):
        _, out = compute(data)
        bigger = {**data, "solo_estimate": [value * factor for value in data["solo_estimate"]]}
        _, again = compute(bigger)
        assert again.shapley.cents == out.shapley.cents
        assert again.alternatives["equal"].cents == out.alternatives["equal"].cents

    @PROPERTY
    @given(meter_inputs())
    def test_estimates_equal_to_the_readings_reproduce_the_meter_result(self, data):
        ride, out = compute(data)
        as_estimates = estimates_data(
            [int(value * 100) for value in data["meter_at_dropoff"]],
            ride.total,
            data["riders"],
            ride_id=data["ride_id"],
        )
        _, same = compute(as_estimates)
        assert same.shapley.cents == out.shapley.cents


class TestAuditSums:
    @PROPERTY
    @given(meter_inputs(6), st.data())
    def test_differences_to_the_fair_split_add_up_to_zero(self, data, draw):
        ride, _ = compute(data)
        cuts = sorted(draw.draw(st.integers(0, ride.total)) for _ in range(ride.n - 1))
        paid = [b - a for a, b in zip([0] + cuts, cuts + [ride.total])]
        audited = {
            **data,
            "audit": {"current": {n: Fraction(c, 100) for n, c in zip(data["riders"], paid)}},
        }
        _, out2 = compute(audited, audit=True)
        assert out2.current.cents == paid
        assert sum(c - f for c, f in zip(out2.current.cents, out2.shapley.cents)) == 0


def test_the_name_pool_is_long_enough_for_the_largest_ride():
    assert len(NAMES) >= rs.MAX_RIDERS_CLOSED_FORM
