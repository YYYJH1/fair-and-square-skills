"""Property tests for bill-split, checked against independent reference solvers."""

from __future__ import annotations

import math
from fractions import Fraction

import bill_split as bs
import fsq_core as fc
import pytest
from bs_testlib import (
    PEOPLE_POOL,
    bfs_fewest_transfers,
    euros,
    group_order_reference,
    int_map,
    max_zero_sum_groups,
    reference_owed,
    reference_shapley,
)
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

SETTINGS = settings(
    deadline=None,
    max_examples=100,
    derandomize=True,
    database=None,
    suppress_health_check=list(HealthCheck),
)
HEAVY = settings(
    deadline=None,
    max_examples=60,
    derandomize=True,
    database=None,
    suppress_health_check=list(HealthCheck),
)


# --------------------------------------------------------------------------------------
# Strategies
# --------------------------------------------------------------------------------------


@st.composite
def split_cents(draw, total: int, parts: int) -> list[int]:
    """`total` cents cut into `parts` non-negative integers."""
    cuts = sorted(draw(st.lists(st.integers(0, total), min_size=parts - 1, max_size=parts - 1)))
    bounds = [0, *cuts, total]
    return [bounds[i + 1] - bounds[i] for i in range(parts)]


@st.composite
def subset(draw, names: list[str], min_size: int = 1, max_size: int | None = None) -> list[str]:
    size = draw(st.integers(min_size, max_size if max_size is not None else len(names)))
    return draw(st.permutations(names))[:size]


@st.composite
def exact_map(draw, names: list[str], cents: int) -> dict[str, Fraction]:
    who = draw(subset(names))
    return {p: euros(c) for p, c in zip(who, draw(split_cents(cents, len(who))))}


@st.composite
def ledgers(draw, max_people: int = 6, max_expenses: int = 4) -> dict:
    count = draw(st.integers(2, max_people))
    people = draw(st.permutations(PEOPLE_POOL))[:count]
    expenses = []
    for number in range(draw(st.integers(1, max_expenses))):
        items = []
        for index in range(draw(st.integers(1, 3))):
            cents = draw(st.integers(1, 30000))
            item = {"name": f"item{index}", "amount": euros(cents)}
            kind = draw(st.sampled_from(["everyone", "among", "weights", "exact"]))
            if kind == "everyone":
                item["everyone"] = True
            elif kind == "among":
                item["among"] = draw(subset(people))
            elif kind == "weights":
                item["among"] = draw(subset(people))
                chosen = draw(subset(item["among"]))
                weights = st.sampled_from(
                    [Fraction(1, 2), Fraction(1), Fraction(2), Fraction(3, 2)]
                )
                item["weights"] = {p: draw(weights) for p in chosen}
            else:
                item["exact"] = draw(exact_map(people, cents))
            items.append(item)
        bill = sum((item["amount"] for item in items), Fraction(0))
        fees = []
        for index in range(draw(st.integers(0, 2))):
            cents = draw(st.integers(0, 5000))
            split = draw(st.sampled_from(["by_consumption", "equal", "exact"]))
            fee = {"name": f"fee{index}", "amount": euros(cents), "split": split}
            if split == "exact":
                fee["exact"] = draw(exact_map(people, cents))
            fees.append(fee)
            bill += fee["amount"]
        discounts = []
        if draw(st.booleans()):
            cents = draw(st.integers(0, int(bill * 100)))
            split = draw(st.sampled_from(["by_consumption", "equal", "exact"]))
            discount = {"name": "voucher", "amount": euros(cents), "split": split}
            if split == "exact":
                discount["exact"] = draw(exact_map(people, cents))
            discounts.append(discount)
            bill -= discount["amount"]
        bill_cents = int(bill * 100)
        assume(bill_cents > 0)
        payers = draw(subset(people, 1, min(2, bill_cents)))
        extra = draw(split_cents(bill_cents - len(payers), len(payers)))
        paid_by = {p: euros(c + 1) for p, c in zip(payers, extra)}
        expenses.append(
            {
                "id": f"e{number}",
                "paid_by": paid_by,
                "items": items,
                "fees": fees,
                "discounts": discounts,
            }
        )
    return {"people": people, "expenses": expenses}


def shuffled(data: dict, rnd) -> dict:
    """The same ledger with people, expenses, items, fees and every mapping in another order."""

    def mix_dict(mapping: dict) -> dict:
        keys = list(mapping)
        rnd.shuffle(keys)
        return {key: mapping[key] for key in keys}

    def mix_list(values: list) -> list:
        values = list(values)
        rnd.shuffle(values)
        return values

    def mix_item(item: dict) -> dict:
        out = dict(item)
        for key in ("weights", "exact"):
            if key in out:
                out[key] = mix_dict(out[key])
        if "among" in out:
            out["among"] = mix_list(out["among"])
        return mix_dict(out)

    def mix_extra(extra: dict) -> dict:
        out = dict(extra)
        if "exact" in out:
            out["exact"] = mix_dict(out["exact"])
        return mix_dict(out)

    expenses = []
    for expense in data["expenses"]:
        expenses.append(
            mix_dict(
                {
                    "id": expense["id"],
                    "paid_by": mix_dict(expense["paid_by"]),
                    "items": mix_list([mix_item(i) for i in expense["items"]]),
                    "fees": mix_list([mix_extra(f) for f in expense["fees"]]),
                    "discounts": mix_list([mix_extra(d) for d in expense["discounts"]]),
                }
            )
        )
    return {"people": mix_list(data["people"]), "expenses": mix_list(expenses)}


# --------------------------------------------------------------------------------------
# Expenses
# --------------------------------------------------------------------------------------


class TestExpenseTotals:
    @given(ledgers())
    @SETTINGS
    def test_owed_adds_up_to_the_total_to_the_cent(self, data):
        out = bs.compute(data).result
        total = sum((sum(e["paid_by"].values()) for e in data["expenses"]), Fraction(0))
        assert sum(int_map(out["owed_cents"]).values()) == total * 100
        assert int(out["total_cents"]) == total * 100
        assert sum(int_map(out["paid_cents"]).values()) == total * 100

    @given(ledgers())
    @SETTINGS
    def test_each_expense_matches_exact_arithmetic_within_a_cent(self, data):
        result = bs.compute(data)
        for expense in data["expenses"]:
            exact = reference_owed(expense, data["people"])
            entry = result.certificate["expenses"][expense["id"]]
            got = int_map(entry["owed_cents"])
            assert set(got) == set(exact)
            assert sum(got.values()) == sum(expense["paid_by"].values()) * 100
            for person, value in exact.items():
                assert got[person] in (math.floor(value * 100), math.floor(value * 100) + 1)
            gave = sorted(p for p, v in got.items() if v > math.floor(exact[p] * 100))
            assert gave == sorted(entry["leftover_to"])
            assert int(entry["leftover_cents"]) == len(gave)

    @given(ledgers())
    @SETTINGS
    def test_the_parts_of_every_share_add_up_to_it(self, data):
        result = bs.compute(data)
        for expense in data["expenses"]:
            entry = result.certificate["expenses"][expense["id"]]
            for person, owed in entry["owed_cents"].items():
                assert sum(int(part["cents"][person]) for part in entry["parts"]) == int(owed)

    @given(ledgers())
    @SETTINGS
    def test_each_part_is_within_two_cents_of_its_exact_value(self, data):
        result = bs.compute(data)
        for expense in data["expenses"]:
            entry = result.certificate["expenses"][expense["id"]]
            plain = {"id": expense["id"], "items": expense["items"]}
            running = reference_owed(plain, data["people"])
            exact_parts = [running]
            for key in ("fees", "discounts"):
                for extra in expense[key]:
                    one = {**plain, key: [extra]}
                    with_extra = reference_owed(one, data["people"])
                    exact_parts.append(
                        {p: with_extra.get(p, 0) - running.get(p, 0) for p in with_extra}
                    )
            assert len(exact_parts) == len(entry["parts"])
            for exact, part in zip(exact_parts, entry["parts"]):
                for person, cents in part["cents"].items():
                    assert abs(int(cents) - exact.get(person, 0) * 100) < 2

    @given(ledgers())
    @SETTINGS
    def test_audit_against_equal_shares_is_consistent(self, data):
        calc = bs.compute_ledger(bs.parse_ledger(data), True)
        audit = calc.audit
        assert audit is not None and audit.label == "aa"
        assert sum(audit.current.values()) == calc.total_cents
        assert sum(audit.delta.values()) == 0
        assert max(audit.current.values()) - min(audit.current.values()) <= 1
        for person in data["people"]:
            assert audit.delta[person] == audit.current[person] - calc.owed[person]


class TestAuditWithAmounts:
    @given(ledgers(), st.randoms(use_true_random=False))
    @SETTINGS
    def test_explicit_current_amounts_are_compared_person_by_person(self, data, rnd):
        total_cents = int(sum(sum(e["paid_by"].values()) for e in data["expenses"]) * 100)
        people = data["people"]
        cuts = sorted(rnd.randint(0, total_cents) for _ in range(len(people) - 1))
        bounds = [0, *cuts, total_cents]
        current = {p: euros(bounds[i + 1] - bounds[i]) for i, p in enumerate(people)}
        data = {**data, "audit": {"current": current}}
        calc = bs.compute_ledger(bs.parse_ledger(data), True)
        audit = calc.audit
        assert audit is not None and audit.label == "custom"
        assert sum(audit.current.values()) == total_cents and sum(audit.delta.values()) == 0
        for person in people:
            assert audit.current[person] == current[person] * 100
            assert audit.delta[person] == audit.current[person] - calc.owed[person]


class TestSettlement:
    @given(ledgers())
    @SETTINGS
    def test_balances_sum_to_zero_and_the_transfers_clear_them(self, data):
        out = bs.compute(data).result
        net = int_map(out["net_cents"])
        assert sum(net.values()) == 0
        balance = dict(net)
        for transfer in out["transfers"]:
            debtor, creditor, cents = transfer["from"], transfer["to"], int(transfer["cents"])
            assert cents > 0 and net[debtor] < 0 < net[creditor]
            balance[debtor] += cents
            balance[creditor] -= cents
        assert all(value == 0 for value in balance.values())
        assert bs.settle(balance, "min_transfers").transfers == []
        nonzero = sum(1 for value in net.values() if value)
        assert len(out["transfers"]) <= max(nonzero - 1, 0)

    @given(ledgers())
    @SETTINGS
    def test_nobody_both_pays_and_receives(self, data):
        transfers = bs.compute(data).result["transfers"]
        senders = {t["from"] for t in transfers}
        receivers = {t["to"] for t in transfers}
        assert not senders & receivers

    @given(ledgers())
    @SETTINGS
    def test_after_one_transfer_the_minimum_drops_by_exactly_one(self, data):
        out = bs.compute(data).result
        assume(out["transfers"])
        net = int_map(out["net_cents"])
        first = out["transfers"][0]
        net[first["from"]] += int(first["cents"])
        net[first["to"]] -= int(first["cents"])
        assert len(bs.fewest_transfers(net)) == len(out["transfers"]) - 1

    @given(st.lists(st.integers(-9, 9), min_size=1, max_size=7))
    @SETTINGS
    def test_the_dp_count_equals_the_brute_force_minimum(self, raw):
        values = [*raw, -sum(raw)]
        nonzero = [v for v in values if v]
        net = {f"p{i}": v for i, v in enumerate(nonzero)}
        plan = bs.fewest_transfers(net)
        assert len(plan) == len(nonzero) - max_zero_sum_groups(nonzero)
        balance = dict(net)
        for debtor, creditor, cents in plan:
            balance[debtor] += cents
            balance[creditor] -= cents
        assert not any(balance.values())

    @given(st.lists(st.integers(-3, 3), min_size=1, max_size=4))
    @settings(deadline=None, max_examples=60, derandomize=True, database=None)
    def test_the_dp_count_equals_a_search_over_all_transfers(self, raw):
        values = [*raw, -sum(raw)]
        nonzero = [v for v in values if v]
        net = {f"p{i}": v for i, v in enumerate(nonzero)}
        assert len(bs.fewest_transfers(net)) == bfs_fewest_transfers(nonzero)

    @given(st.lists(st.integers(-40, 40), min_size=1, max_size=9))
    @SETTINGS
    def test_greedy_is_never_fewer_than_the_dp_and_at_most_n_minus_1(self, raw):
        values = [*raw, -sum(raw)]
        nonzero = [v for v in values if v]
        net = {f"p{i}": v for i, v in enumerate(nonzero)}
        greedy = bs.greedy_transfers(net)
        assert len(bs.fewest_transfers(net)) <= len(greedy) <= max(len(nonzero) - 1, 0)
        balance = dict(net)
        for debtor, creditor, cents in greedy:
            balance[debtor] += cents
            balance[creditor] -= cents
        assert not any(balance.values())

    @given(st.lists(st.integers(-9, 9), min_size=1, max_size=7), st.randoms(use_true_random=False))
    @SETTINGS
    def test_the_transfers_do_not_depend_on_the_order_of_the_balances(self, raw, rnd):
        values = [*raw, -sum(raw)]
        items = [(f"p{i}", v) for i, v in enumerate(values)]
        shuffled_items = list(items)
        rnd.shuffle(shuffled_items)
        assert bs.fewest_transfers(dict(items)) == bs.fewest_transfers(dict(shuffled_items))
        assert bs.greedy_transfers(dict(items)) == bs.greedy_transfers(dict(shuffled_items))

    @given(st.lists(st.integers(-5, 5), min_size=1, max_size=15))
    @HEAVY
    def test_the_group_split_adds_up_and_each_group_is_minimal(self, raw):
        values = [v for v in [*raw, -sum(raw)] if v]
        assume(values)
        groups = bs.zero_sum_groups(values)
        assert sorted(i for g in groups for i in g) == list(range(len(values)))
        for group in groups:
            assert sum(values[i] for i in group) == 0
            if len(group) <= 8:
                assert max_zero_sum_groups([values[i] for i in group]) == 1


class TestOrderIndependence:
    @given(ledgers(), st.randoms(use_true_random=False))
    @HEAVY
    def test_the_result_does_not_depend_on_the_order_of_the_input(self, data, rnd):
        other = shuffled(data, rnd)
        first, second = bs.compute(data), bs.compute(other)
        for key in (
            "total_cents",
            "owed_cents",
            "paid_cents",
            "net_cents",
            "transfers",
            "exact_minimum",
            "transfer_counts",
        ):
            assert first.result[key] == second.result[key], key
        assert sorted(map(repr, first.result["notes"])) == sorted(map(repr, second.result["notes"]))
        for expense in data["expenses"]:
            a = first.certificate["expenses"][expense["id"]]
            b = second.certificate["expenses"][expense["id"]]
            for key in ("owed_cents", "paid_cents", "leftover_to", "leftover_cents"):
                assert a[key] == b[key], key

    @given(ledgers())
    @HEAVY
    def test_the_same_input_gives_the_same_bytes(self, data):
        assert fc.render_json(bs.compute(data)) == fc.render_json(bs.compute(data))
        assert fc.render(bs.compute(data), "md") == fc.render(bs.compute(data), "md")


# --------------------------------------------------------------------------------------
# Shapley value
# --------------------------------------------------------------------------------------


@st.composite
def tier_lists(draw, top: int = 20000) -> list[tuple[int, int]]:
    tiers = []
    for _ in range(draw(st.integers(1, 3))):
        threshold = draw(st.integers(1, top))
        tiers.append((threshold, draw(st.integers(1, threshold))))
    return tiers


@st.composite
def dish_totals(draw, max_people: int = 6) -> dict[str, int]:
    names = draw(subset(PEOPLE_POOL, 1, max_people))
    return {name: draw(st.integers(0, 12000)) for name in names}


def worth(tiers, total: int) -> int:
    return max([cut for gate, cut in tiers if total >= gate], default=0)


class TestShapley:
    @given(dish_totals(), tier_lists())
    @SETTINGS
    def test_agrees_with_averaging_over_all_orders(self, amounts, tiers):
        assert bs.shapley_tier_shares(amounts, tiers) == reference_shapley(amounts, tiers)

    @given(dish_totals(), tier_lists())
    @SETTINGS
    def test_efficiency_shares_add_up_to_the_reduction(self, amounts, tiers):
        shares = bs.shapley_tier_shares(amounts, tiers)
        assert sum(shares.values()) == worth(tiers, sum(amounts.values()))

    @given(dish_totals(), tier_lists())
    @SETTINGS
    def test_symmetry_equal_dishes_get_equal_shares(self, amounts, tiers):
        shares = bs.shapley_tier_shares(amounts, tiers)
        for a in amounts:
            for b in amounts:
                if amounts[a] == amounts[b]:
                    assert shares[a] == shares[b]

    @given(dish_totals(), tier_lists())
    @SETTINGS
    def test_nobody_gets_a_negative_share_and_nobody_gets_more_than_the_reduction(
        self, amounts, tiers
    ):
        shares = bs.shapley_tier_shares(amounts, tiers)
        whole = worth(tiers, sum(amounts.values()))
        assert all(0 <= v <= whole for v in shares.values())

    @given(dish_totals(max_people=5), tier_lists())
    @SETTINGS
    def test_a_person_with_no_dishes_gets_nothing(self, amounts, tiers):
        shares = bs.shapley_tier_shares({**amounts, "nothing": 0}, tiers)
        assert shares["nothing"] == 0

    @given(dish_totals(max_people=5), tier_lists())
    @SETTINGS
    def test_adding_a_person_with_no_dishes_changes_nobody_else(self, amounts, tiers):
        assert {**bs.shapley_tier_shares({**amounts, "nothing": 0}, tiers)} == {
            **bs.shapley_tier_shares(amounts, tiers),
            "nothing": 0,
        }

    @given(dish_totals(), st.randoms(use_true_random=False), tier_lists())
    @SETTINGS
    def test_does_not_depend_on_the_order_of_the_people(self, amounts, rnd, tiers):
        items = list(amounts.items())
        rnd.shuffle(items)
        assert bs.shapley_tier_shares(dict(items), tiers) == bs.shapley_tier_shares(amounts, tiers)

    @given(
        st.lists(st.integers(0, 300), min_size=1, max_size=10),
        st.lists(st.integers(1, 1200), min_size=1, max_size=3),
        st.randoms(use_true_random=False),
    )
    @HEAVY
    def test_agrees_with_an_independent_counting_algorithm_for_larger_groups(
        self, dishes, gates, rnd
    ):
        """Count the groups of the other people by size and total instead of listing them."""
        tiers = [(gate, rnd.randint(1, gate)) for gate in gates]
        amounts = {f"p{i:02d}": cents for i, cents in enumerate(dishes)}
        count = len(dishes)
        expected = {}
        for index, mine in enumerate(dishes):
            others = dishes[:index] + dishes[index + 1 :]
            table = {(0, 0): 1}
            for cents in others:
                grown = dict(table)
                for (size, total), ways in table.items():
                    key = (size + 1, total + cents)
                    grown[key] = grown.get(key, 0) + ways
                table = grown
            value = Fraction(0)
            for (size, total), ways in table.items():
                weight = Fraction(
                    math.factorial(size) * math.factorial(count - size - 1), math.factorial(count)
                )
                value += weight * ways * (worth(tiers, total + mine) - worth(tiers, total))
            expected[f"p{index:02d}"] = value
        assert bs.shapley_tier_shares(amounts, tiers) == expected

    def test_the_hand_computed_example(self):
        shares = bs.shapley_tier_shares(
            {"a": 2800, "b": 2800, "c": 600}, [(4000, 1000), (6000, 1800)]
        )
        assert shares == {"a": Fraction(2300, 3), "b": Fraction(2300, 3), "c": Fraction(800, 3)}

    def test_the_largest_group_is_exact_and_quick(self):
        amounts = {f"p{i:02d}": 1000 + 137 * i for i in range(16)}
        tiers = [(5000, 300), (12000, 900), (20000, 2000)]
        shares = bs.shapley_tier_shares(amounts, tiers)
        assert sum(shares.values()) == worth(tiers, sum(amounts.values()))

    def test_more_than_16_people_are_refused(self):
        with pytest.raises(ValueError):
            bs.shapley_tier_shares({f"p{i:02d}": 100 for i in range(17)}, [(100, 10)])


# --------------------------------------------------------------------------------------
# Group orders
# --------------------------------------------------------------------------------------


@st.composite
def orders(draw, max_people: int = 5, solo_discounts: bool = True) -> dict:
    buyers = draw(subset(PEOPLE_POOL, 1, max_people))
    items = []
    for person in buyers:
        for index in range(draw(st.integers(1, 2))):
            items.append(
                {
                    "who": person,
                    "name": f"dish{index}",
                    "amount": euros(draw(st.integers(100, 8000))),
                    "packaging": euros(draw(st.integers(0, 300))),
                }
            )
    dish = {}
    for item in items:
        dish[item["who"]] = dish.get(item["who"], Fraction(0)) + item["amount"]
    subtotal_cents = int(sum(dish.values()) * 100)
    biggest = int(max(dish.values()) * 100)
    fees = [
        {
            "name": f"fee{index}",
            "amount": euros(draw(st.integers(0, 1500))),
            "split": draw(st.sampled_from(["proportional", "equal"])),
        }
        for index in range(draw(st.integers(0, 2)))
    ]
    coupons = []
    if draw(st.booleans()):
        low = 1 if solo_discounts else biggest + 1
        assume(low <= max(subtotal_cents, low))
        tiers = []
        for _ in range(draw(st.integers(1, 3))):
            threshold = draw(st.integers(low, max(subtotal_cents, low) + 3000))
            tiers.append([euros(threshold), euros(draw(st.integers(1, max(threshold // 2, 1))))])
        coupons.append(
            {
                "name": "tiers",
                "tiers": tiers,
                "split": draw(st.sampled_from(["shapley", "proportional"])),
            }
        )
    if draw(st.booleans()):
        coupons.append(
            {
                "name": "packet",
                "amount": euros(draw(st.integers(0, subtotal_cents // 4))),
                "split": draw(
                    st.sampled_from(["proportional", "equal", "shapley", "by_consumption"])
                ),
            }
        )
    return {"mode": "group_order", "id": "o", "items": items, "fees": fees, "coupons": coupons}


def alone_reference(order: dict) -> dict[str, int]:
    dish: dict[str, int] = {}
    pack: dict[str, int] = {}
    for item in order["items"]:
        dish[item["who"]] = dish.get(item["who"], 0) + int(item["amount"] * 100)
        pack[item["who"]] = pack.get(item["who"], 0) + int(item["packaging"] * 100)
    fees = sum(int(fee["amount"] * 100) for fee in order["fees"])
    out = {}
    for person, cents in dish.items():
        cut = 0
        for coupon in order["coupons"]:
            if "tiers" in coupon:
                cut += max(
                    [int(r * 100) for t, r in coupon["tiers"] if cents >= int(t * 100)], default=0
                )
        out[person] = cents + pack[person] + fees - cut
    return out


def compute_or_skip(order: dict, audit: bool = False) -> fc.Result:
    try:
        return bs.compute(order, audit=audit)
    except fc.InputError:
        assume(False)
        raise


class TestGroupOrder:
    @given(orders())
    @HEAVY
    def test_payments_add_up_and_match_exact_arithmetic(self, order):
        result = compute_or_skip(order)
        exact = group_order_reference(order)
        pay = int_map(result.result["pay_cents"])
        assert set(pay) == set(exact)
        assert sum(pay.values()) == sum(exact.values()) * 100 == int(result.result["total_cents"])
        for person, value in exact.items():
            assert pay[person] in (math.floor(value * 100), math.floor(value * 100) + 1)

    @given(orders())
    @HEAVY
    def test_the_coupon_shares_add_up_to_the_reductions(self, order):
        result = compute_or_skip(order)
        discount = int_map(result.result["coupon_share"])
        assert sum(discount.values()) == sum(
            int(v) for v in result.result["coupon_reductions"].values()
        )

    @given(orders())
    @HEAVY
    def test_the_parts_add_up_to_what_each_person_pays(self, order):
        result = compute_or_skip(order)
        for person, pay in result.result["pay_cents"].items():
            assert sum(int(p["cents"][person]) for p in result.certificate["parts"]) == int(pay)

    @given(orders())
    @HEAVY
    def test_the_trap_check_is_exactly_pay_not_above_alone(self, order):
        result = compute_or_skip(order)
        alone = alone_reference(order)
        assert int_map(result.result["alone_cents"]) == alone
        pay = int_map(result.result["pay_cents"])
        violators = sorted(p for p in pay if pay[p] > alone[p])
        assert result.result["pays_more_than_alone"] == violators
        assert result.result["trap_check"] is (not violators)
        md = fc.render(result, "md")
        assert ("凑单陷阱检查：通过" in md) is (not violators)

    @given(orders(solo_discounts=False))
    @HEAVY
    def test_nobody_pays_more_than_alone_when_nobody_reaches_a_tier_alone(self, order):
        result = compute_or_skip(order)
        alone = alone_reference(order)
        dish = {}
        for item in order["items"]:
            dish[item["who"]] = dish.get(item["who"], 0) + int(item["amount"] * 100)
        for coupon in order["coupons"]:
            if "tiers" in coupon:
                assume(all(dish[p] < int(t * 100) for p in dish for t, _ in coupon["tiers"]))
        pay = int_map(result.result["pay_cents"])
        assert all(pay[p] <= alone[p] for p in pay)
        assert result.result["trap_check"] is True

    @given(orders(), st.randoms(use_true_random=False))
    @HEAVY
    def test_the_result_does_not_depend_on_the_order_of_the_input(self, order, rnd):
        other = dict(order)
        other["items"] = list(order["items"])
        rnd.shuffle(other["items"])
        other["items"] = [
            dict(sorted(item.items(), key=lambda kv: rnd.random())) for item in other["items"]
        ]
        a, b = compute_or_skip(order), compute_or_skip(other)
        for key in ("pay_cents", "alone_cents", "coupon_share", "trap_check", "total_cents"):
            assert a.result[key] == b.result[key], key

    @given(orders())
    @HEAVY
    def test_audit_against_equal_shares_is_consistent(self, order):
        order = dict(order)
        order["audit"] = {"current": "aa"}
        result = compute_or_skip(order, audit=True)
        audit = result.result["audit"]
        current = {p: int(v["current_cents"]) for p, v in audit["per_person"].items()}
        assert sum(current.values()) == int(result.result["total_cents"])
        assert max(current.values()) - min(current.values()) <= 1
        pay = int_map(result.result["pay_cents"])
        for person, entry in audit["per_person"].items():
            assert int(entry["delta_cents"]) == current[person] - pay[person]

    @given(orders())
    @HEAVY
    def test_audit_against_proportional_shares_is_consistent(self, order):
        result = compute_or_skip(order, audit=True)
        audit = result.result["audit"]
        assert audit["baseline"] == "proportional"
        current = {p: int(v["current_cents"]) for p, v in audit["per_person"].items()}
        assert sum(current.values()) == int(result.result["total_cents"])
        assert sum(int(v["delta_cents"]) for v in audit["per_person"].values()) == 0

    def test_three_full_orders_waste_a_coupon_and_the_check_says_so(self):
        order = {
            "mode": "group_order",
            "items": [{"who": w, "name": "x", "amount": 100} for w in ("a", "b", "c")],
            "fees": [{"name": "delivery", "amount": 5}],
            "coupons": [{"name": "deal", "tiers": [[100, 20]]}],
        }
        result = bs.compute(order)
        assert int_map(result.result["pay_cents"]) == {"a": 9500, "b": 9500, "c": 9500}
        assert int_map(result.result["alone_cents"]) == {"a": 8500, "b": 8500, "c": 8500}
        assert result.result["trap_check"] is False
        assert result.result["pays_more_than_alone"] == ["a", "b", "c"]
        md = fc.render(result, "md")
        assert "没有通过" in md and "a（拼单 95.00，单点 85.00）" in md
        assert "未通过" in fc.render(result, "group")
        assert "pays_more_than_alone" in fc.render_json(result)
        assert "FAILED" in fc.render(bs.compute(order, lang="en"), "md")
