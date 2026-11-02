"""Golden numbers for bill-split: hand-checked examples that must come out exactly."""

from __future__ import annotations

import json
import random
from fractions import Fraction

import bill_split as bs
import fsq_core as fc
import pytest
from bs_testlib import EXAMPLES, int_map, run_script


def load_example(name: str):
    return fc.parse_input((EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))


def pairs(transfers) -> set[tuple[str, str, int]]:
    return {(t["from"], t["to"], int(t["cents"])) for t in transfers}


class TestDinner:
    """A table of four, 480 of food for everyone, 160 of wine for two, 40 service fee."""

    def test_itemised_amounts(self):
        out = bs.compute(load_example("dinner_680")).result
        assert int_map(out["owed_cents"]) == {
            "阿明": 12750,
            "小红": 12750,
            "大刘": 21250,
            "Coco": 21250,
        }
        assert int(out["total_cents"]) == 68000

    def test_transfers_are_the_fewest(self):
        out = bs.compute(load_example("dinner_680")).result
        assert out["exact_minimum"] is True
        assert pairs(out["transfers"]) == {
            ("小红", "阿明", 12750),
            ("大刘", "阿明", 21250),
            ("Coco", "阿明", 21250),
        }

    def test_audit_against_equal_shares(self):
        out = bs.compute(load_example("audit_aa"), audit=True).result["audit"]
        assert out["baseline"] == "aa"
        deltas = {p: int(v["delta_cents"]) for p, v in out["per_person"].items()}
        assert deltas == {"阿明": 4250, "小红": 4250, "大刘": -4250, "Coco": -4250}
        assert {int(v["current_cents"]) for v in out["per_person"].values()} == {17000}
        assert out["pays_more_now"] == ["小红", "阿明"]

    def test_audit_text_says_who_overpays(self):
        result = bs.compute(load_example("audit_aa"), audit=True)
        md = fc.render(result, "md")
        assert "多掏 42.50" in md and "少掏 42.50" in md
        group = fc.render(result, "group")
        assert "阿明多掏 42.50" in group and "大刘少掏 42.50" in group


class TestTransfers:
    def test_trip_counts_16_11_5_5(self):
        out = bs.compute(load_example("trip_five_bills")).result
        assert out["transfer_counts"] == {"separate": 16, "pairwise": 11, "greedy": 5, "fewest": 5}
        assert int_map(out["net_cents"]) == {
            "阿明": 71000,
            "小红": 20000,
            "大刘": -16000,
            "Coco": -22000,
            "老王": -28000,
            "Yuki": -25000,
        }
        assert len(out["transfers"]) == 5 and out["exact_minimum"] is True

    def test_trip_text_mentions_the_comparison(self):
        md = fc.render(bs.compute(load_example("trip_five_bills")), "md")
        assert "16 笔" in md and "11 笔" in md and "最少 5 笔" in md

    def test_greedy_needs_four_where_three_are_enough(self):
        net = {"甲": 7000, "乙": 5000, "丙": -5000, "丁": -4000, "戊": -3000}
        assert set(bs.greedy_transfers(net)) == {
            ("丙", "甲", 5000),
            ("丁", "乙", 4000),
            ("戊", "甲", 2000),
            ("戊", "乙", 1000),
        }
        assert bs.fewest_transfers(net) == [
            ("丁", "甲", 4000),
            ("丙", "乙", 5000),
            ("戊", "甲", 3000),
        ]

    def test_greedy_uses_an_extra_transfer_in_11_3_percent_of_random_cases(self):
        """20000 random settlements of 4 to 8 people with balances in multiples of 10.

        The stream of random.Random(3) gave the same 2252 cases on CPython 3.9, 3.10, 3.12 and
        3.13 when this test was written. The assertion on the share is the one that matters.
        """
        rng = random.Random(3)
        total = more = 0
        for _ in range(20000):
            people = rng.randint(4, 8)
            values = [rng.randint(-20, 20) * 10 for _ in range(people - 1)]
            values.append(-sum(values))
            if not any(values):
                continue
            net = {f"p{i}": v for i, v in enumerate(values)}
            total += 1
            more += len(bs.greedy_transfers(net)) > len(bs.fewest_transfers(net))
        assert 0.10 < more / total < 0.126
        assert (total, more) == (20000, 2252)

    def test_the_same_through_an_input_file(self):
        out = bs.compute(load_example("fewest_transfers")).result
        assert int_map(out["net_cents"]) == {
            "甲": 7000,
            "乙": 5000,
            "丙": -5000,
            "丁": -4000,
            "戊": -3000,
        }
        assert pairs(out["transfers"]) == {
            ("丙", "乙", 5000),
            ("丁", "甲", 4000),
            ("戊", "甲", 3000),
        }
        assert out["transfer_counts"]["greedy"] == 4 and out["transfer_counts"]["fewest"] == 3

    def test_greedy_rule_can_be_chosen_and_says_so(self):
        data = load_example("fewest_transfers")
        data["rules"] = {"settle": "greedy"}
        out = bs.compute(data).result
        assert out["exact_minimum"] is False and len(out["transfers"]) == 4
        assert "greedy_chosen" in {note["code"] for note in out["notes"]}


class TestTakeoutGroupOrder:
    """Three dishes, packaging 1 each, delivery 5 and a red packet 3 by dish price, tiers 40-10, 60-18."""

    def test_payments_and_trap_check(self):
        out = bs.compute(load_example("group_order_takeout")).result
        assert int_map(out["pay_cents"]) == {"阿明": 2224, "小红": 2223, "Coco": 453}
        assert int(out["total_cents"]) == 4900
        assert int_map(out["alone_cents"]) == {"阿明": 3400, "小红": 3400, "Coco": 1200}
        assert out["trap_check"] is True and out["pays_more_than_alone"] == []

    def test_coupon_shares_are_the_shapley_value(self):
        result = bs.compute(load_example("group_order_takeout"))
        assert result.certificate["shapley"] == {
            "满减": {"阿明": "23/3", "小红": "23/3", "Coco": "8/3"}
        }
        assert int(result.result["coupon_reductions"]["满减"]) == 1800
        coupon = next(p for p in result.certificate["parts"] if p["name"] == "满减")
        cents = int_map(coupon["cents"])
        assert sum(cents.values()) == -1800
        for person, exact in (
            ("阿明", Fraction(2300, 3)),
            ("小红", Fraction(2300, 3)),
            ("Coco", Fraction(800, 3)),
        ):
            assert abs(-cents[person] - exact) < 1

    def test_parts_add_up_to_what_each_person_pays(self):
        result = bs.compute(load_example("group_order_takeout"))
        for person, pay in int_map(result.result["pay_cents"]).items():
            assert sum(int(part["cents"][person]) for part in result.certificate["parts"]) == pay

    def test_proportional_split_for_comparison(self):
        audit = bs.compute(load_example("group_order_takeout"), audit=True).result["audit"]
        assert audit["baseline"] == "proportional"
        assert {p: int(v["current_cents"]) for p, v in audit["per_person"].items()} == {
            "阿明": 2178,
            "小红": 2177,
            "Coco": 545,
        }


class TestCouponHook:
    """Spend 300 and take 60 off: orders of 150, 140 and 20."""

    def test_shapley_makes_the_small_order_free(self):
        out = bs.compute(load_example("group_order_coupon")).result
        assert int_map(out["pay_cents"]) == {"甲": 13000, "乙": 12000, "丙": 0}
        assert int_map(out["coupon_share"]) == {"甲": 2000, "乙": 2000, "丙": 2000}
        assert int_map(out["alone_cents"]) == {"甲": 15000, "乙": 14000, "丙": 2000}

    def test_proportional_split_is_29_03_27_10_3_87(self):
        audit = bs.compute(load_example("group_order_coupon"), audit=True).result["audit"]
        per = audit["per_person"]
        assert {p: int(v["current_discount"]) for p, v in per.items()} == {
            "甲": 2903,
            "乙": 2710,
            "丙": 387,
        }
        assert {p: int(v["target_discount"]) for p, v in per.items()} == {
            "甲": 2000,
            "乙": 2000,
            "丙": 2000,
        }
        assert {p: int(v["current_cents"]) for p, v in per.items()} == {
            "甲": 12097,
            "乙": 11290,
            "丙": 1613,
        }

    def test_without_the_small_order_nothing_is_saved(self):
        data = load_example("group_order_coupon")
        data["items"] = data["items"][:2]
        out = bs.compute(data).result
        assert int(out["coupon_reductions"]["满300减60"]) == 0
        assert int_map(out["pay_cents"]) == {"甲": 15000, "乙": 14000}
        assert [note["code"] for note in out["notes"]] == ["tier_not_reached"]


class TestDecimals:
    @pytest.mark.parametrize(
        "text",
        [
            (
                '{"people":["a","b"],"expenses":[{"paid_by":{"a":0.29},'
                '"items":[{"name":"x","amount":0.29,"everyone":true}]}]}'
            ),
            (
                '{"people":["a","b"],"expenses":[{"paid_by":{"a":"0.29"},'
                '"items":[{"name":"x","amount":"0.29","everyone":true}]}]}'
            ),
        ],
    )
    def test_029_is_29_cents(self, text):
        out = bs.compute(fc.parse_input(text)).result
        assert int(out["total_cents"]) == 29
        assert sorted(int_map(out["owed_cents"]).values()) == [14, 15]

    def test_the_binary_float_trap_does_not_lose_a_cent(self):
        # 0.29 as a float times 100 is 28.999999999999996, which floors to 28 cents.
        text = (
            '{"mode":"group_order","items":[{"who":"a","name":"x","amount":0.29}],'
            '"fees":[{"name":"f","amount":0.29,"split":"equal"}]}'
        )
        out = bs.compute(fc.parse_input(text)).result
        assert int_map(out["pay_cents"]) == {"a": 58}


class TestLeftoverCent:
    def test_the_extra_cent_rotates_over_30_bills(self):
        people = ["A", "B", "C"]
        expenses = [
            {
                "id": f"expense-{number}",
                "paid_by": {"A": 100},
                "items": [{"name": "x", "amount": 100, "everyone": True}],
            }
            for number in range(1, 31)
        ]
        calc = bs.compute_ledger(bs.parse_ledger({"people": people, "expenses": expenses}), False)
        lucky = {name: 0 for name in people}
        for expense in calc.expenses:
            assert sum(expense.owed_cents.values()) == 10000
            for name, cents in expense.owed_cents.items():
                lucky[name] += cents == 3334
        assert sorted(lucky.values()) == [10, 10, 10]

    def test_the_certificate_names_who_got_the_cent(self):
        data = {
            "people": ["A", "B", "C"],
            "expenses": [
                {
                    "id": "bill-7",
                    "paid_by": {"A": 100},
                    "items": [{"name": "x", "amount": 100, "everyone": True}],
                }
            ],
        }
        result = bs.compute(data)
        entry = result.certificate["expenses"]["bill-7"]
        assert int(entry["leftover_cents"]) == 1 and len(entry["leftover_to"]) == 1
        winner = entry["leftover_to"][0]
        assert int(entry["owed_cents"][winner]) == 3334


class TestCommandLine:
    def test_json_envelope_has_the_five_standard_keys(self):
        done = run_script("--input", str(EXAMPLES / "dinner_680.json"), "--json")
        assert done.returncode == 0, done.stderr
        envelope = json.loads(done.stdout)
        assert sorted(envelope) == [
            "certificate",
            "inputs_echo",
            "not_modeled",
            "reproduce",
            "result",
        ]
        assert envelope["result"]["owed_cents"] == {
            "Coco": "212.50",
            "大刘": "212.50",
            "小红": "127.50",
            "阿明": "127.50",
        }
        assert envelope["result"]["transfers"][0] == {
            "cents": "212.50",
            "from": "Coco",
            "to": "阿明",
        }

    def test_standard_input_works(self):
        text = (EXAMPLES / "dinner_680.json").read_text(encoding="utf-8")
        done = run_script("--format", "group", text=text)
        assert done.returncode == 0, done.stderr
        assert "阿明 127.50" in done.stdout
