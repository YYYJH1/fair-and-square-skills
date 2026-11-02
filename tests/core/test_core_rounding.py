"""Largest-remainder rounding and the envy-minimising rounding for rent-like problems."""

from __future__ import annotations

import math
from fractions import Fraction
from itertools import combinations

import fsq_core as core
import pytest
from hypothesis import assume, given
from hypothesis import strategies as st
from rent_reference import as_mappings, is_envy_free, maximin_rents

NAMES = st.text(alphabet="abcdefgh阿明小红", min_size=1, max_size=3)
KEYS = st.text(max_size=12)


def exact_cents(shares: dict[str, Fraction]) -> dict[str, Fraction]:
    return {name: Fraction(value) * 100 for name, value in shares.items()}


@st.composite
def shares_with_total(draw):
    """Exact shares (currency units, any sign) that add up to a whole number of cents."""
    names = draw(st.lists(NAMES, min_size=1, max_size=8, unique=True))
    parts = [
        draw(st.fractions(min_value=-50, max_value=500, max_denominator=97)) for _ in names[:-1]
    ]
    total_cents = draw(st.integers(-5000, 50000))
    last = Fraction(total_cents, 100) - sum(parts, Fraction(0))
    shares = dict(zip(names, [*parts, last]))
    return shares, total_cents


class TestRoundShares:
    @given(shares_with_total(), KEYS)
    def test_total_is_exact_and_everyone_is_within_one_cent(self, case, key):
        shares, total_cents = case
        cents = core.round_shares(shares, total_cents, key)
        assert sum(cents.values()) == total_cents
        raw = exact_cents(shares)
        assert set(cents) == set(shares)
        for name, value in cents.items():
            assert isinstance(value, int)
            assert abs(value - raw[name]) < 1
            assert value in (math.floor(raw[name]), math.floor(raw[name]) + 1)

    @given(shares_with_total(), KEYS, st.randoms(use_true_random=False))
    def test_independent_of_input_order(self, case, key, rnd):
        shares, total_cents = case
        items = list(shares.items())
        rnd.shuffle(items)
        assert core.round_shares(dict(items), total_cents, key) == core.round_shares(
            shares, total_cents, key
        )

    @given(shares_with_total(), KEYS)
    def test_larger_remainders_never_lose_to_smaller_ones(self, case, key):
        shares, total_cents = case
        cents = core.round_shares(shares, total_cents, key)
        raw = exact_cents(shares)
        remainder = {name: raw[name] - math.floor(raw[name]) for name in raw}
        rounded_up = {name for name in raw if cents[name] > math.floor(raw[name])}
        for up in rounded_up:
            for down in set(raw) - rounded_up:
                assert remainder[up] >= remainder[down]

    def test_leftover_cent_rotates_over_30_bills(self):
        counts = {"小红": 0, "阿明": 0, "大刘": 0}
        for number in range(1, 31):
            cents = core.round_shares(
                {name: Fraction(100, 3) for name in counts}, 10000, f"expense-{number}"
            )
            assert sum(cents.values()) == 10000
            assert sorted(cents.values()) == [3333, 3333, 3334]
            for name, value in cents.items():
                counts[name] += value == 3334
        assert counts == {"小红": 10, "阿明": 10, "大刘": 10}

    def test_leftover_cent_is_not_always_the_first_name(self):
        winners = set()
        for number in range(40):
            cents = core.round_shares({n: Fraction(100, 3) for n in "abc"}, 10000, f"bill-{number}")
            winners.add(next(name for name, value in cents.items() if value == 3334))
        assert winners == {"a", "b", "c"}

    def test_same_key_same_answer(self):
        shares = {n: Fraction(100, 3) for n in "abc"}
        assert core.round_shares(shares, 10000, "k") == core.round_shares(shares, 10000, "k")

    def test_exact_values_pass_through(self):
        shares = {"a": Fraction(1275, 10), "b": Fraction(1275, 10), "c": Fraction(2125, 10)}
        assert core.round_shares(shares, 46750 - 8000 + 8000, "x") == {
            "a": 12750,
            "b": 12750,
            "c": 21250,
        }

    def test_negative_shares_use_floor(self):
        shares = {
            "a": Fraction(-32, 3),
            "b": Fraction(-32, 3),
            "c": Fraction(-32, 3) + 32 + Fraction(1, 1),
        }
        total = round(sum(shares.values()) * 100)
        cents = core.round_shares(shares, total, "x")
        assert sum(cents.values()) == total
        assert cents["a"] in (-1067, -1066)

    def test_output_is_sorted_by_name(self):
        cents = core.round_shares({"b": Fraction(1), "a": Fraction(2)}, 300, "x")
        assert list(cents) == ["a", "b"]

    def test_empty(self):
        assert core.round_shares({}, 0, "x") == {}
        with pytest.raises(ValueError):
            core.round_shares({}, 5, "x")

    def test_mismatched_total_is_refused(self):
        with pytest.raises(ValueError, match="add up to"):
            core.round_shares({"a": Fraction(1), "b": Fraction(1)}, 201, "x")

    @pytest.mark.parametrize("bad", [0.5, True, "1"])
    def test_floats_and_text_are_refused(self, bad):
        with pytest.raises(TypeError):
            core.round_shares({"a": bad}, 50, "x")

    def test_total_must_be_an_int(self):
        with pytest.raises(TypeError):
            core.round_shares({"a": Fraction(1)}, 100.0, "x")

    def test_cents_values_are_refused_as_shares(self):
        with pytest.raises(TypeError, match="already in cents"):
            core.round_shares({"a": core.Cents(100)}, 100, "x")


class TestApportion:
    @given(
        st.dictionaries(NAMES, st.integers(0, 1000), min_size=1, max_size=8),
        st.integers(0, 10**7),
        KEYS,
    )
    def test_proportional_split_adds_up_and_stays_close(self, weights, total_cents, key):
        assume(sum(weights.values()) > 0)
        cents = core.apportion(total_cents, {n: Fraction(w) for n, w in weights.items()}, key)
        assert sum(cents.values()) == total_cents
        weight_sum = sum(weights.values())
        for name, weight in weights.items():
            assert abs(cents[name] - Fraction(total_cents * weight, weight_sum)) < 1

    def test_bad_weights(self):
        with pytest.raises(ValueError):
            core.apportion(100, {"a": Fraction(0)}, "x")
        with pytest.raises(ValueError):
            core.apportion(100, {"a": Fraction(-1), "b": Fraction(2)}, "x")
        with pytest.raises(TypeError):
            core.apportion(100, {"a": 0.5}, "x")

    def test_golden_values_of_the_worked_examples(self):
        # worked example: 63 yuan in proportion to meter readings 14/26/41/63
        riders = ["小周", "阿杰", "Mia", "老陈"]
        meter = [14, 26, 41, 63]
        cents = core.apportion(6300, {r: Fraction(m) for r, m in zip(riders, meter)}, "ride-1")
        assert [cents[r] for r in riders] == [613, 1137, 1794, 2756]
        # worked example: a coupon of 60 split in proportion to 150/140/20
        cents = core.apportion(
            6000, {"甲": Fraction(150), "乙": Fraction(140), "丙": Fraction(20)}, "coupon-1"
        )
        assert (cents["甲"], cents["乙"], cents["丙"]) == (2903, 2710, 387)

    def test_group_order_shapley_shares_golden(self):
        # worked example: exact payments 2068/93, 2068/93, 421/93 yuan; the spare cent goes to 阿明
        shares = {"阿明": Fraction(2068, 93), "小红": Fraction(2068, 93), "Coco": Fraction(421, 93)}
        cents = core.round_shares(shares, 4900, "waimai-1")
        assert cents == {"Coco": 453, "小红": 2223, "阿明": 2224}


class TestRoundHalfUp:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (Fraction(5, 2), 3),
            (Fraction(-5, 2), -2),
            (Fraction(1, 2), 1),
            (Fraction(-1, 2), 0),
            (Fraction(7, 3), 2),
            (Fraction(8, 3), 3),
            (Fraction(-7, 3), -2),
            (Fraction(-8, 3), -3),
            (0, 0),
            (7, 7),
            (-7, -7),
            (Fraction(10, 5), 2),
        ],
    )
    def test_nearest_integer_with_halves_going_up(self, value, expected):
        assert core.round_half_up(value) == expected
        assert type(core.round_half_up(value)) is int

    @given(st.fractions(min_value=-1000, max_value=1000, max_denominator=50))
    def test_the_result_is_within_half_and_ties_go_up(self, value):
        result = core.round_half_up(value)
        assert -Fraction(1, 2) < result - value <= Fraction(1, 2)

    @given(st.integers(-(10**6), 10**6))
    def test_whole_numbers_are_unchanged(self, value):
        assert core.round_half_up(value) == value

    @pytest.mark.parametrize("bad", [2.5, True, "2", None])
    def test_only_exact_numbers_are_accepted(self, bad):
        with pytest.raises(TypeError):
            core.round_half_up(bad)


class TestFnv:
    @pytest.mark.parametrize(
        ("text", "value"),
        [("", 0x811C9DC5), ("a", 0xE40C292C), ("foobar", 0xBF9CF968)],
    )
    def test_known_vectors(self, text, value):
        assert core.fnv1a32(text) == value

    def test_hashes_utf8_bytes(self):
        assert 0 <= core.fnv1a32("阿明") < 2**32
        assert core.fnv1a32("阿明") != core.fnv1a32("小红")


# --- rent-like rounding -----------------------------------------------------------------

ROOMS4 = ["主卧带卫", "南次卧", "北次卧", "小书房"]
PEOPLE4 = ["阿明", "小红", "大刘", "Coco"]
BIDS4 = [
    [3000, 2200, 1600, 1200],
    [2600, 2500, 1700, 1200],
    [3400, 2000, 1500, 1100],
    [2400, 2300, 2000, 1300],
]


def named(bids, people, rooms):
    return {p: {r: Fraction(b) for r, b in zip(rooms, row)} for p, row in zip(people, bids)}


class TestRoundMinEnvyThreePersonExample:
    """skills_demo_numbers: three people, a closet nobody wants, rent 6000."""

    ROOMS = ("大主卧", "朝南卧", "储物间改的小间")
    PEOPLE = ("甲", "乙", "丙")
    BIDS = ((4800, 1000, 200), (1000, 4800, 200), (2900, 2900, 200))

    def setup_method(self):
        self.bids = named(self.BIDS, self.PEOPLE, self.ROOMS)
        self.assignment = dict(zip(self.PEOPLE, self.ROOMS))
        room_of, rents = maximin_rents(
            [[Fraction(b) for b in row] for row in self.BIDS], Fraction(6000)
        )
        self.prices = {room: rents[room_of[i]] for i, room in enumerate(self.ROOMS)}

    def test_reference_prices(self):
        assert self.prices == {
            "大主卧": Fraction(10600, 3),
            "朝南卧": Fraction(10600, 3),
            "储物间改的小间": Fraction(-3200, 3),
        }

    def test_each_possible_extra_cent_and_its_envy(self):
        lower = {room: math.floor(price * 100) for room, price in self.prices.items()}
        assert sum(lower.values()) == 600000 - 1
        envy = {}
        for room in self.ROOMS:
            cents = dict(lower)
            cents[room] += 1
            envy[room] = core.max_envy_cents(self.bids, self.assignment, cents)
        assert envy == {"大主卧": 1, "朝南卧": 1, "储物间改的小间": 0}

    def test_min_envy_rounding_gives_zero_where_naive_gives_one(self):
        # the naive largest-remainder rounding breaks ties by room index
        naive = {room: math.floor(price * 100) for room, price in self.prices.items()}
        naive["大主卧"] += 1
        assert core.max_envy_cents(self.bids, self.assignment, naive) == 1
        for key in ("rent-1", "x", "", "2026-11"):
            cents = core.round_min_envy(self.prices, 600000, self.bids, self.assignment, key)
            assert sum(cents.values()) == 600000
            assert cents == {"大主卧": 353333, "朝南卧": 353333, "储物间改的小间": -106666}
            assert core.max_envy_cents(self.bids, self.assignment, cents) == 0
            assert core.fmt_cents(cents["储物间改的小间"]) == "-1,066.66"


class TestRoundMinEnvyFourPersonExample:
    def setup_method(self):
        self.bids = named(BIDS4, PEOPLE4, ROOMS4)
        matrix = [[Fraction(b) for b in row] for row in BIDS4]
        self.room_of, rents = maximin_rents(matrix, Fraction(8000))
        self.prices = {room: rents[k] for k, room in enumerate(ROOMS4)}
        self.assignment = {p: ROOMS4[self.room_of[i]] for i, p in enumerate(PEOPLE4)}

    def test_reference_solution(self):
        assert self.assignment == {
            "阿明": "小书房",
            "小红": "南次卧",
            "大刘": "主卧带卫",
            "Coco": "北次卧",
        }
        assert self.prices == {"主卧带卫": 3150, "南次卧": 2250, "北次卧": 1650, "小书房": 950}

    def test_rounding_keeps_exact_prices(self):
        cents = core.round_min_envy(self.prices, 800000, self.bids, self.assignment, "k")
        assert cents == {"主卧带卫": 315000, "南次卧": 225000, "北次卧": 165000, "小书房": 95000}
        assert core.max_envy_cents(self.bids, self.assignment, cents) == 0

    def test_envy_table_matches_the_recorded_table(self):
        cents = core.round_min_envy(self.prices, 800000, self.bids, self.assignment, "k")
        table = core.surplus_table_cents(self.bids, cents)
        expected = {  # recorded table, values in yuan, rooms in ROOMS4 order
            "阿明": [-150, -50, -50, 250],
            "小红": [-550, 250, 50, 250],
            "大刘": [250, -250, -150, 150],
            "Coco": [-750, 50, 350, 350],
        }
        for person, row in expected.items():
            assert [table[person][room] for room in ROOMS4] == [v * 100 for v in row]


def brute_force_min_envy(prices, total_cents, bids, assignment):
    """Smallest max envy over every way of rounding each item down or up to the cent."""
    lower = {item: math.floor(price * 100) for item, price in prices.items()}
    fractional = [item for item, price in prices.items() if price * 100 != lower[item]]
    leftover = total_cents - sum(lower.values())
    best = None
    for up in combinations(fractional, leftover):
        cents = {item: lower[item] + (item in up) for item in prices}
        envy = core.max_envy_cents(bids, assignment, cents)
        best = envy if best is None else min(best, envy)
    return lower, fractional, leftover, best


@st.composite
def rent_problems(draw):
    n = draw(st.integers(2, 5))
    bids = [[Fraction(draw(st.integers(0, 300000)), 100) for _ in range(n)] for _ in range(n)]
    total = Fraction(draw(st.integers(1, 1000000)), 100)
    return bids, total


class TestRoundMinEnvyProperties:
    @given(rent_problems(), KEYS)
    def test_exact_search_matches_brute_force_and_bounds_envy_by_one_cent(self, problem, key):
        bids, total = problem
        room_of, rents = maximin_rents(bids, total)
        assert sum(rents) == total
        assert is_envy_free(bids, room_of, rents)
        bid_map, assignment, prices = as_mappings(bids, room_of, rents)
        total_cents = round(total * 100)
        cents = core.round_min_envy(prices, total_cents, bid_map, assignment, key)

        assert sum(cents.values()) == total_cents
        for item, price in prices.items():
            assert abs(cents[item] - price * 100) < 1
        envy = core.max_envy_cents(bid_map, assignment, cents)
        assert envy <= 1
        *_, best = brute_force_min_envy(prices, total_cents, bid_map, assignment)
        assert envy == (0 if best is None else best)

        naive = core.round_shares(prices, total_cents, key)
        naive_envy = core.max_envy_cents(bid_map, assignment, naive)
        assert envy <= naive_envy
        if envy == naive_envy:
            assert cents == naive  # ties go to the largest-remainder rounding

    @given(st.integers(2, 6), KEYS)
    def test_all_options_tie_means_largest_remainder_with_rotation(self, n, key):
        # everyone is indifferent between the rooms and the prices are exactly equal
        rooms = [f"r{k}" for k in range(n)]
        people = [f"p{k}" for k in range(n)]
        bids = {p: {r: Fraction(0) for r in rooms} for p in people}
        assignment = dict(zip(people, rooms))
        total_cents = 100 * n + 1  # n equal prices of 1 + 1/n cents
        prices = {r: Fraction(total_cents, 100 * n) for r in rooms}
        cents = core.round_min_envy(prices, total_cents, bids, assignment, key)
        assert sum(cents.values()) == total_cents
        # one room pays one cent more; every choice leaves someone envying by one cent
        assert core.max_envy_cents(bids, assignment, cents) == 1
        assert cents == core.round_shares(prices, total_cents, key)

    @given(st.integers(9, 11), st.randoms(use_true_random=False), KEYS)
    def test_many_items_use_swap_search_and_never_lose_to_largest_remainder(self, n, rnd, key):
        assert n > core.EXACT_SEARCH_MAX_ITEMS
        rooms = [f"r{k}" for k in range(n)]
        people = [f"p{k}" for k in range(n)]
        bids = {p: {r: Fraction(rnd.randint(0, 100000), 100) for r in rooms} for p in people}
        assignment = dict(zip(people, rooms))
        parts = [
            Fraction(rnd.randint(0, 9999), 100) + Fraction(rnd.randint(0, 6), 7)
            for _ in range(n - 1)
        ]
        total_cents = round(sum(parts) * 100) + 12345
        prices = {r: part for r, part in zip(rooms, parts)}
        prices[rooms[-1]] = Fraction(total_cents, 100) - sum(parts, Fraction(0))
        cents = core.round_min_envy(prices, total_cents, bids, assignment, key)
        assert sum(cents.values()) == total_cents
        for item, price in prices.items():
            assert abs(cents[item] - price * 100) < 1
        naive = core.round_shares(prices, total_cents, key)
        assert core.max_envy_cents(bids, assignment, cents) <= core.max_envy_cents(
            bids, assignment, naive
        )

    def test_nothing_to_round(self):
        assert core.round_min_envy({}, 0, {}, {}, "k") == {}

    def test_cents_values_are_refused_as_prices(self):
        bids = {"a": {"x": Fraction(5)}}
        with pytest.raises(TypeError, match="already in cents"):
            core.round_min_envy({"x": core.Cents(500)}, 500, bids, {"a": "x"}, "k")

    def test_no_fractional_items_returns_floors(self):
        bids = {
            "a": {"x": Fraction(5), "y": Fraction(3)},
            "b": {"x": Fraction(2), "y": Fraction(4)},
        }
        cents = core.round_min_envy(
            {"x": Fraction(3), "y": Fraction(2)}, 500, bids, {"a": "x", "b": "y"}, "k"
        )
        assert cents == {"x": 300, "y": 200}

    def test_input_checks(self):
        bids = {
            "a": {"x": Fraction(5), "y": Fraction(3)},
            "b": {"x": Fraction(2), "y": Fraction(4)},
        }
        prices = {"x": Fraction(3), "y": Fraction(2)}
        with pytest.raises(ValueError, match="add up to"):
            core.round_min_envy(prices, 501, bids, {"a": "x", "b": "y"}, "k")
        with pytest.raises(ValueError, match="same people"):
            core.round_min_envy(prices, 500, bids, {"a": "x"}, "k")
        with pytest.raises(ValueError, match="unknown item"):
            core.round_min_envy(prices, 500, bids, {"a": "x", "b": "z"}, "k")
        with pytest.raises(ValueError, match="no bid"):
            core.round_min_envy(
                prices, 500, {"a": {"x": Fraction(1)}, "b": bids["b"]}, {"a": "x", "b": "y"}, "k"
            )
        with pytest.raises(ValueError, match="whole number of cents"):
            core.round_min_envy(
                prices,
                500,
                {"a": {"x": Fraction(1, 3), "y": Fraction(1)}, "b": bids["b"]},
                {"a": "x", "b": "y"},
                "k",
            )
