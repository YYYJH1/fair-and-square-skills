"""General mode: group prices typed in, or a distance matrix with a tariff."""

from __future__ import annotations

import itertools
import json
from fractions import Fraction

import fsq_core as fc
import pytest
import ride_reference as ref
import ride_split as rs
from hypothesis import assume, given
from hypothesis import strategies as st
from ride_support import PROPERTY, run_json, subset_costs_data


def compute(data: dict, audit: bool = False):
    ride = rs.parse_ride(data, audit)
    return ride, rs.compute(ride)


def matrix_input(distances, base=10, per_unit=2, riders=None, **extra):
    n = len(distances) - 1
    data = {
        "mode": "general",
        "riders": riders or ["A", "B", "C", "D"][:n],
        "distance_matrix": distances,
        "tariff": {"base": base, "per_unit": per_unit},
    }
    data.update(extra)
    return data


@st.composite
def distance_matrices(draw, max_riders: int = 4):
    """Random (not necessarily symmetric) distance matrices with a zero diagonal."""
    n = draw(st.integers(2, max_riders))
    rows = []
    for a in range(n + 1):
        rows.append([0 if a == b else draw(st.integers(1, 30)) for b in range(n + 1)])
    return rows


class TestRoutes:
    @PROPERTY
    @given(distance_matrices())
    def test_route_enumeration_equals_the_independent_search(self, rows):
        n = len(rows) - 1
        distances = [[Fraction(v) for v in row] for row in rows]
        length, order = rs.route_table(distances, n)
        for mask in range(1, 1 << n):
            stops = [i + 1 for i in range(n) if mask >> i & 1]
            assert length[mask] == ref.shortest_open_route(distances, stops)
            walked = Fraction(0)
            here = 0
            for rider in order[mask]:
                walked += distances[here][rider + 1]
                here = rider + 1
            assert walked == length[mask]
            assert sorted(order[mask]) == [i for i in range(n) if mask >> i & 1]

    @PROPERTY
    @given(distance_matrices(), st.integers(1, 20), st.integers(0, 12))
    def test_group_prices_follow_the_tariff(self, rows, base, per_unit):
        n = len(rows) - 1
        ride = rs.parse_ride(matrix_input(rows, base, per_unit))
        distances = [[Fraction(v) for v in row] for row in rows]
        for mask in range(1, 1 << n):
            stops = [i + 1 for i in range(n) if mask >> i & 1]
            fare = base + per_unit * ref.shortest_open_route(distances, stops)
            assert ride.table[mask] == rs.round_cents(Fraction(fare))

    @PROPERTY
    @given(distance_matrices(), st.integers(1, 10), st.integers(1, 5))
    def test_shapley_over_routes_equals_the_permutation_average(self, rows, base, per_unit):
        n = len(rows) - 1
        ride, out = compute(matrix_input(rows, base, per_unit))
        distances = [[Fraction(v) for v in row] for row in rows]

        def price(group):
            if not group:
                return Fraction(0)
            stops = [i + 1 for i in group]
            return Fraction(base) + per_unit * ref.shortest_open_route(distances, stops)

        expected = ref.shapley_by_permutations(n, price)
        assert out.game.exact == expected
        assert sum(out.shapley.cents) == ride.total

    def test_decimal_distances_and_prices_are_exact(self):
        data = matrix_input(
            [[0, "3.2", "4.0"], ["3.2", 0, "1.1"], ["4.0", "1.1", 0]],
            base=7,
            per_unit="2.35",
            riders=["A", "B"],
        )
        ride = rs.parse_ride(data)
        assert ride.table[1] == 1452  # 7 + 2.35 * 3.2 = 14.52
        assert ride.table[2] == 1640  # 7 + 2.35 * 4.0 = 16.40
        # 7 + 2.35 * 4.3 = 17.105 exactly, and a half cent rounds up (a float gives 1710)
        assert ride.table[3] == 1711

    def test_minimum_fare(self):
        data = matrix_input([[0, 1, 2], [1, 0, 1], [2, 1, 0]], base=0, per_unit=2)
        data["tariff"]["minimum"] = 20
        ride = rs.parse_ride(data)
        assert ride.table[1:] == [2000, 2000, 2000]

    def test_the_cheapest_route_for_everybody_is_reported(self):
        rows = [[0, 2, 12, 11], [2, 0, 10, 9], [12, 10, 0, 5], [11, 9, 5, 0]]
        ride, _ = compute(matrix_input(rows, base=10, per_unit=Fraction(5, 2)))
        assert ride.route == [0, 2, 1]
        assert ride.route_length == 16
        md = run_json(matrix_input(rows, base=10, per_unit=2.5)).stdout
        assert "起点 → A → C → B，路程 16" in md


PARTIAL_PRICES = {"小周": 15, "阿杰": 40, "小周+阿杰": 40, "Mia": 37.5, "小周+Mia": 37.5}
FULL_PRICES = {**PARTIAL_PRICES, "阿杰+Mia": 50, "小周+阿杰+Mia": 50}
THREE_RIDERS = ["小周", "阿杰", "Mia"]


class TestSubsetCostsLayouts:
    """The compact object layout and the list layout mean the same thing."""

    def test_object_layout_equals_list_layout(self):
        as_object = {"mode": "general", "riders": THREE_RIDERS, "subset_costs": FULL_PRICES}
        as_list = {
            "mode": "general",
            "riders": THREE_RIDERS,
            "subset_costs": [
                {"riders": key.split("+"), "cost": cost} for key, cost in FULL_PRICES.items()
            ],
        }
        first = run_json(as_object, "--json")
        second = run_json(as_list, "--json")
        assert first.returncode == 0 and second.returncode == 0, first.stderr + second.stderr
        assert json.loads(first.stdout)["result"] == json.loads(second.stdout)["result"]

    def test_spaces_around_the_plus_and_the_order_of_names_do_not_matter(self):
        keys = {"小周": 15, "阿杰": 40, "阿杰 + 小周": 40, "Mia": 37.5, "Mia+小周": 37.5}
        keys.update({"Mia + 阿杰": 50, "阿杰+Mia+小周": 50})
        ride = rs.parse_ride({"mode": "general", "riders": THREE_RIDERS, "subset_costs": keys})
        assert ride.table[1:] == [1500, 4000, 4000, 3750, 3750, 5000, 5000]

    @pytest.mark.parametrize(
        ("change", "field"),
        [
            ({"小周+Z": 5}, "subset_costs.小周+Z"),
            ({"小周+": 5}, "subset_costs.小周+"),
            ({"小周+小周": 5}, "subset_costs.小周+小周"),
            ({"阿杰+小周": 40}, "subset_costs.阿杰+小周"),
            ({"阿杰": -1}, "subset_costs.阿杰"),
            ({"阿杰": 40.005}, "subset_costs.阿杰"),
        ],
    )
    def test_bad_entries_name_their_key(self, change, field):
        with pytest.raises(fc.InputError) as caught:
            rs.parse_ride(
                {
                    "mode": "general",
                    "riders": THREE_RIDERS,
                    "subset_costs": {**FULL_PRICES, **change},
                }
            )
        assert field in caught.value.field

    def test_a_missing_group_is_named(self):
        with pytest.raises(fc.InputError) as caught:
            rs.parse_ride(
                {"mode": "general", "riders": THREE_RIDERS, "subset_costs": PARTIAL_PRICES}
            )
        assert caught.value.field == "subset_costs"
        assert "2 groups" in caught.value.message


class TestScaling:
    def test_all_group_prices_are_scaled_to_the_paid_total(self):
        prices = [0, 1000, 1500, 1500, 1500, 2000, 1500, 2500]
        data = subset_costs_data(prices, ["A", "B", "C"], actual_total=Fraction(2750, 100))
        ride, out = compute(data)
        assert ride.model_total == 2500 and ride.total == 2750
        assert ride.scale == Fraction(11, 10)
        assert out.game.alone[1] == 1100 and out.game.alone[7] == 2750
        assert sum(out.shapley.cents) == 2750

    def test_no_scaling_when_the_totals_agree(self):
        prices = [0, 1000, 1500, 1500, 1500, 2000, 1500, 2500]
        data = subset_costs_data(prices, ["A", "B", "C"], actual_total=25)
        ride, _ = compute(data)
        assert ride.scale == 1

    def test_the_scaling_is_reported(self):
        prices = [0, 1000, 1500, 1500, 1500, 2000, 1500, 2500]
        data = subset_costs_data(prices, ["A", "B", "C"], actual_total=Fraction(2750, 100))
        md = run_json(data).stdout
        assert "27.50" in md and "25.00" in md and "11/10" in md


class TestCoreOfGeneralGames:
    def test_the_detour_example_is_in_the_core(self):
        data = matrix_input(
            [[0, 2, 12, 11], [2, 0, 10, 9], [12, 10, 0, 5], [11, 9, 5, 0]],
            base=10,
            per_unit=2.5,
            riders=["小周", "阿杰", "Mia"],
        )
        _, out = compute(data)
        assert [fc.fmt_cents(c) for c in out.shapley.cents] == ["5.00", "23.75", "21.25"]
        assert out.shapley.violations == []

    def test_three_directions_have_an_empty_core(self):
        prices = [0, 1000, 1000, 3000, 1000, 3000, 3000, 5000]
        ride, out = compute(subset_costs_data(prices, ["A", "B", "C"]))
        assert out.core_empty is True
        assert len(out.shapley.violations) == 6
        assert len(out.alternatives["equal"].violations) == 6
        assert ride.total == 5000

    def test_a_proportional_split_is_not_offered_when_nobody_has_a_solo_price(self):
        prices = [0, 0, 0, 1000]
        _, out = compute(subset_costs_data(prices, ["A", "B"]))
        assert "proportional" not in out.alternatives
        md = run_json(subset_costs_data(prices, ["A", "B"])).stdout
        assert "按单独打车价比例没有定义" in md

    @PROPERTY
    @given(st.integers(2, 4), st.data())
    def test_emptiness_agrees_with_an_independent_linear_program(self, n, draw):
        scipy_optimize = pytest.importorskip("scipy.optimize")
        prices = [0] + [draw.draw(st.integers(0, 40)) for _ in range((1 << n) - 1)]
        assume(prices[-1] > 0)
        groups = list(range(1, 1 << n))
        # least core: minimise e subject to x(S) - c(S) <= e for every proper group, x(N) = c(N)
        proper = [mask for mask in groups if mask != (1 << n) - 1]
        a_ub = [[1.0 if mask >> i & 1 else 0.0 for i in range(n)] + [-1.0] for mask in proper]
        b_ub = [float(prices[mask]) for mask in proper]
        a_eq = [[1.0] * n + [0.0]]
        b_eq = [float(prices[-1])]
        result = scipy_optimize.linprog(
            c=[0.0] * n + [1.0],
            A_ub=a_ub,
            b_ub=b_ub,
            A_eq=a_eq,
            b_eq=b_eq,
            bounds=[(None, None)] * (n + 1),
            method="highs",
        )
        assert result.status == 0
        assert rs.core_is_empty(n, prices) == (result.fun > 1e-7)

    @PROPERTY
    @given(st.integers(2, 4), st.data())
    def test_packing_value_agrees_with_an_independent_linear_program(self, n, draw):
        scipy_optimize = pytest.importorskip("scipy.optimize")
        gains = {mask: draw.draw(st.integers(-20, 30)) for mask in range(1, 1 << n)}
        a_ub = [[1.0 if mask >> i & 1 else 0.0 for mask in gains] for i in range(n)]
        result = scipy_optimize.linprog(
            c=[-float(g) for g in gains.values()],
            A_ub=a_ub,
            b_ub=[1.0] * n,
            bounds=[(0, None)] * len(gains),
            method="highs",
        )
        assert result.status == 0
        assert float(rs.packing_lp_value(n, gains)) == pytest.approx(-result.fun, abs=1e-7)

    @PROPERTY
    @given(st.integers(2, 5), st.data())
    def test_shapley_in_the_core_means_the_core_is_not_empty(self, n, draw):
        prices = [0] + [draw.draw(st.integers(0, 30)) for _ in range((1 << n) - 1)]
        assume(prices[-1] > 0)
        shapley = fc.shapley_values(n, [Fraction(p) for p in prices])
        inside = all(
            sum(shapley[i] for i in rs.bits(mask, n)) <= prices[mask] for mask in range(1, 1 << n)
        )
        if inside:
            assert not rs.core_is_empty(n, prices)

    def test_an_empty_core_has_no_core_point_by_brute_force(self):
        prices = [0, 1, 1, 3, 1, 3, 3, 5]
        assert rs.core_is_empty(3, prices)
        solo_sum = prices[1] + prices[2] + prices[4]
        assert solo_sum < prices[7], "every rider alone is cheaper than the shared ride"
        for x in itertools.product(range(-5, 11), repeat=2):
            third = prices[7] - sum(x)
            paid = [*x, third]
            assert any(
                sum(paid[i] for i in rs.bits(mask, 3)) > prices[mask] for mask in range(1, 7)
            )


class TestGeneralOutput:
    def test_json_carries_the_route_and_the_group_prices(self):
        rows = [[0, 2, 12, 11], [2, 0, 10, 9], [12, 10, 0, 5], [11, 9, 5, 0]]
        done = run_json(
            matrix_input(rows, base=10, per_unit=2.5, riders=["小周", "阿杰", "Mia"]), "--json"
        )
        parsed = json.loads(done.stdout)
        assert parsed["result"]["route"] == ["小周", "Mia", "阿杰"]
        assert parsed["result"]["route_length"] == "16"
        assert parsed["result"]["core_is_empty"] is None
        prices = {
            tuple(entry["riders"]): entry["cost"] for entry in parsed["inputs_echo"]["subset_costs"]
        }
        assert prices[("小周",)] == "15.00" and prices[("阿杰", "Mia")] == "50.00"
        assert parsed["inputs_echo"]["tariff"]["per_unit"] == "2.5"

    def test_md_lists_every_group_price_up_to_four_riders(self):
        four = [[0, 1, 2, 3, 4], [1, 0, 1, 2, 3], [2, 1, 0, 1, 2], [3, 2, 1, 0, 1], [4, 3, 2, 1, 0]]
        md = run_json(matrix_input(four)).stdout
        assert md.count("\n| ") > 15
        assert "每种乘车组合单独打一辆车的价" in md
        five = [[0 if a == b else abs(a - b) for b in range(6)] for a in range(6)]
        md5 = run_json(matrix_input(five, riders=list("ABCDE"))).stdout
        assert "每种乘车组合单独打一辆车的价" not in md5
