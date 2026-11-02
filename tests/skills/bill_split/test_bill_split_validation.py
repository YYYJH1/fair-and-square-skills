"""Input validation: exit code 2 with the field named, and the odd inputs that are accepted."""

from __future__ import annotations

import copy
import io
import sys

import bill_split as bs
import fsq_core as fc
import pytest
from bs_testlib import dump_json, int_map


def base_expenses():
    return {
        "people": ["阿明", "小红", "大刘", "Coco"],
        "expenses": [
            {
                "id": "dinner-1",
                "what": "聚餐",
                "paid_by": {"阿明": 680},
                "items": [
                    {"name": "菜", "amount": 480, "everyone": True},
                    {"name": "酒", "amount": 160, "among": ["大刘", "Coco"]},
                ],
                "fees": [{"name": "服务费", "amount": 40, "split": "by_consumption"}],
                "discounts": [],
            }
        ],
    }


def base_order():
    return {
        "mode": "group_order",
        "id": "o-1",
        "items": [
            {"who": "a", "name": "x", "amount": 28, "packaging": 1},
            {"who": "b", "name": "y", "amount": 28, "packaging": 1},
            {"who": "c", "name": "z", "amount": 6, "packaging": 1},
        ],
        "fees": [{"name": "delivery", "amount": 5}],
        "coupons": [{"name": "tiers", "tiers": [[40, 10], [60, 18]]}],
        "paid_by": "a",
    }


def run_main(monkeypatch, capsys, data, *argv):
    text = data if isinstance(data, str) else dump_json(data)
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))
    with pytest.raises(SystemExit) as caught:
        fc.run_cli(bs.main, list(argv))
    captured = capsys.readouterr()
    return caught.value.code, captured.out, captured.err


def edit(base_factory, change):
    data = base_factory()
    change(data)
    return data


def expense(data):
    return data["expenses"][0]


EXPENSE_ERRORS = [
    (
        "paid_by does not add up",
        lambda d: expense(d).update(paid_by={"阿明": 700}),
        "expenses[0].paid_by",
    ),
    (
        "payer not in people",
        lambda d: expense(d).update(paid_by={"赵六": 680}),
        "expenses[0].paid_by.赵六",
    ),
    (
        "payer amount zero",
        lambda d: expense(d).update(paid_by={"阿明": 680, "小红": 0}),
        "expenses[0].paid_by.小红",
    ),
    ("no payer", lambda d: expense(d).update(paid_by={}), "expenses[0].paid_by"),
    ("payer missing", lambda d: expense(d).pop("paid_by"), "expenses[0].paid_by"),
    (
        "exact does not add up",
        lambda d: expense(d)["items"].__setitem__(
            0, {"name": "菜", "amount": 480, "exact": {"阿明": 100, "小红": 100}}
        ),
        "expenses[0].items[0].exact",
    ),
    (
        "exact names a stranger",
        lambda d: expense(d)["items"].__setitem__(
            0, {"name": "菜", "amount": 480, "exact": {"赵六": 480}}
        ),
        "expenses[0].items[0].exact.赵六",
    ),
    (
        "exact together with among",
        lambda d: expense(d)["items"].__setitem__(
            0, {"name": "菜", "amount": 480, "among": ["阿明"], "exact": {"阿明": 480}}
        ),
        "expenses[0].items[0].among",
    ),
    (
        "among names a stranger",
        lambda d: expense(d)["items"][1].update(among=["大刘", "赵六"]),
        "expenses[0].items[1].among[1]",
    ),
    (
        "among is the string all",
        lambda d: expense(d)["items"][1].update(among="all"),
        "expenses[0].items[1].among",
    ),
    (
        "among repeats a name",
        lambda d: expense(d)["items"][1].update(among=["大刘", "大刘"]),
        "expenses[0].items[1].among[1]",
    ),
    (
        "among is empty",
        lambda d: expense(d)["items"][1].update(among=[]),
        "expenses[0].items[1].among",
    ),
    (
        "everyone is not a boolean",
        lambda d: expense(d)["items"][0].update(everyone="yes"),
        "expenses[0].items[0].everyone",
    ),
    (
        "everyone and among together",
        lambda d: expense(d)["items"][0].update(among=["阿明"]),
        "expenses[0].items[0].among",
    ),
    (
        "nobody says who shares",
        lambda d: expense(d)["items"][0].pop("everyone"),
        "expenses[0].items[0]",
    ),
    (
        "everyone false alone",
        lambda d: expense(d)["items"][0].update(everyone=False),
        "expenses[0].items[0]",
    ),
    (
        "weights names a non-sharer",
        lambda d: expense(d)["items"][1].update(weights={"阿明": 2}),
        "expenses[0].items[1].weights.阿明",
    ),
    (
        "weight zero",
        lambda d: expense(d)["items"][0].update(weights={"阿明": 0}),
        "expenses[0].items[0].weights.阿明",
    ),
    (
        "weight text",
        lambda d: expense(d)["items"][0].update(weights={"阿明": "2"}),
        "expenses[0].items[0].weights.阿明",
    ),
    (
        "misspelled field",
        lambda d: expense(d)["items"][0].update(weight={"阿明": 2}),
        "expenses[0].items[0].weight",
    ),
    ("misspelled expense field", lambda d: expense(d).update(discount=[]), "expenses[0].discount"),
    (
        "negative item",
        lambda d: expense(d)["items"][0].update(amount=-1),
        "expenses[0].items[0].amount",
    ),
    (
        "three decimals",
        lambda d: expense(d)["items"][0].update(amount="480.005"),
        "expenses[0].items[0].amount",
    ),
    (
        "amount is a boolean",
        lambda d: expense(d)["items"][0].update(amount=True),
        "expenses[0].items[0].amount",
    ),
    (
        "amount is words",
        lambda d: expense(d)["items"][0].update(amount="lots"),
        "expenses[0].items[0].amount",
    ),
    (
        "item without a name",
        lambda d: expense(d)["items"][0].pop("name"),
        "expenses[0].items[0].name",
    ),
    ("no items", lambda d: expense(d).update(items=[]), "expenses[0].items"),
    (
        "fee with an unknown split",
        lambda d: expense(d)["fees"][0].update(split="half"),
        "expenses[0].fees[0].split",
    ),
    (
        "fee exact does not add up",
        lambda d: expense(d)["fees"][0].update(split="exact", exact={"阿明": 1}),
        "expenses[0].fees[0].exact",
    ),
    (
        "fee exact without amounts",
        lambda d: expense(d)["fees"][0].update(split="exact"),
        "expenses[0].fees[0].exact",
    ),
    (
        "exact on a non-exact fee",
        lambda d: expense(d)["fees"][0].update(exact={"阿明": 40}),
        "expenses[0].fees[0].exact",
    ),
    (
        "negative fee",
        lambda d: expense(d)["fees"][0].update(amount=-5),
        "expenses[0].fees[0].amount",
    ),
    (
        "by_consumption with nothing consumed",
        lambda d: expense(d).update(
            items=[{"name": "free", "amount": 0, "everyone": True}],
            fees=[{"name": "fee", "amount": 5, "split": "by_consumption"}],
            paid_by={"阿明": 5},
        ),
        "expenses[0].fees[0].split",
    ),
    (
        "discount larger than the bill",
        lambda d: expense(d).update(
            discounts=[{"name": "coupon", "amount": 900, "split": "equal"}]
        ),
        "expenses[0].discounts",
    ),
    (
        "duplicate expense ids",
        lambda d: d["expenses"].append(copy.deepcopy(expense(d))),
        "expenses[1].id",
    ),
    ("no expenses", lambda d: d.update(expenses=[]), "expenses"),
    ("expenses missing", lambda d: d.pop("expenses"), "expenses"),
    ("one person only", lambda d: d.update(people=["阿明"]), "people"),
    ("people missing", lambda d: d.pop("people"), "people"),
    ("duplicate person", lambda d: d.update(people=["阿明", "阿明", "小红"]), "people[1]"),
    ("empty person name", lambda d: d.update(people=["", "阿明"]), "people[0]"),
    ("person name with a space", lambda d: d.update(people=[" 阿明", "小红"]), "people[0]"),
    ("unknown rule", lambda d: d.update(rules={"settle": "fast"}), "rules.settle"),
    ("unknown rule key", lambda d: d.update(rules={"round": "up"}), "rules.round"),
    ("unknown mode", lambda d: d.update(mode="rent"), "mode"),
    ("unknown top-level field", lambda d: d.update(note="x"), "note"),
    (
        "audit with an unknown baseline",
        lambda d: d.update(audit={"current": "half"}),
        "audit.current",
    ),
    (
        "audit amounts do not add up",
        lambda d: d.update(audit={"current": {"阿明": 100}}),
        "audit.current",
    ),
    (
        "audit amounts name a stranger",
        lambda d: d.update(audit={"current": {"赵六": 680}}),
        "audit.current.赵六",
    ),
    ("audit key misspelled", lambda d: d.update(audit={"now": "aa"}), "audit.now"),
]


ORDER_ERRORS = [
    ("unknown coupon split", lambda d: d["coupons"][0].update(split="half"), "coupons[0].split"),
    ("coupon with tiers and amount", lambda d: d["coupons"][0].update(amount=3), "coupons[0]"),
    ("coupon with neither", lambda d: d["coupons"][0].pop("tiers"), "coupons[0]"),
    (
        "reduction above the threshold",
        lambda d: d["coupons"][0].update(tiers=[[10, 20]]),
        "coupons[0].tiers[0][1]",
    ),
    ("empty tiers", lambda d: d["coupons"][0].update(tiers=[]), "coupons[0].tiers"),
    ("tier is not a pair", lambda d: d["coupons"][0].update(tiers=[[40]]), "coupons[0].tiers[0]"),
    ("threshold zero", lambda d: d["coupons"][0].update(tiers=[[0, 1]]), "coupons[0].tiers[0][0]"),
    (
        "flat coupon with an unknown split",
        lambda d: d.update(coupons=[{"name": "r", "amount": 3, "split": "half"}]),
        "coupons[0].split",
    ),
    ("paid_by does not add up", lambda d: d.update(paid_by={"a": 10}), "paid_by"),
    ("paid_by zero", lambda d: d.update(paid_by={"a": 49, "b": 0}), "paid_by.b"),
    ("paid_by empty", lambda d: d.update(paid_by={}), "paid_by"),
    ("fee negative", lambda d: d["fees"][0].update(amount=-1), "fees[0].amount"),
    ("fee split unknown", lambda d: d["fees"][0].update(split="shapley"), "fees[0].split"),
    ("who is empty", lambda d: d["items"][0].update(who=""), "items[0].who"),
    ("packaging negative", lambda d: d["items"][0].update(packaging=-1), "items[0].packaging"),
    (
        "packaging has three decimals",
        lambda d: d["items"][0].update(packaging="0.125"),
        "items[0].packaging",
    ),
    ("no items", lambda d: d.update(items=[]), "items"),
    ("item field misspelled", lambda d: d["items"][0].update(price=3), "items[0].price"),
    ("expenses field in an order", lambda d: d.update(expenses=[]), "expenses"),
    (
        "coupons take off more than the order",
        lambda d: d.update(coupons=[{"name": "r", "amount": 500}], paid_by="a"),
        "coupons",
    ),
    (
        "proportional fee on free dishes",
        lambda d: d.update(items=[{"who": "a", "name": "x", "amount": 0}], coupons=[], paid_by="a"),
        "fees[0].split",
    ),
    (
        "more than 16 people share a Shapley coupon",
        lambda d: d.update(
            items=[{"who": f"p{i}", "name": "x", "amount": 10} for i in range(17)],
            paid_by="p0",
        ),
        "coupons[0].split",
    ),
    ("audit baseline unknown", lambda d: d.update(audit={"current": "split"}), "audit.current"),
]

RAW_ERRORS = [
    ("not JSON", "{", "input"),
    ("NaN", '{"people": NaN}', "input"),
    ("top level is a list", "[1, 2]", "input"),
    ("duplicate key", '{"people": ["a", "b"], "people": ["a", "b"]}', "input"),
    (
        "0.295 is not a whole number of cents",
        (
            '{"people":["a","b"],"expenses":[{"paid_by":{"a":0.295},'
            '"items":[{"name":"x","amount":0.295,"everyone":true}]}]}'
        ),
        "expenses[0].paid_by.a",
    ),
]


class TestExpenseErrors:
    @pytest.mark.parametrize(
        ("why", "change", "field"), EXPENSE_ERRORS, ids=[c[0] for c in EXPENSE_ERRORS]
    )
    def test_exit_2_and_the_field_is_named(self, monkeypatch, capsys, why, change, field):
        code, out, err = run_main(monkeypatch, capsys, edit(base_expenses, change))
        assert code == 2, err
        assert out == ""
        assert f'field "{field}"' in err, err

    def test_the_base_input_is_valid(self, monkeypatch, capsys):
        code, out, err = run_main(monkeypatch, capsys, base_expenses(), "--format", "group")
        assert code == 0 and "127.50" in out and err == ""


class TestOrderErrors:
    @pytest.mark.parametrize(
        ("why", "change", "field"), ORDER_ERRORS, ids=[c[0] for c in ORDER_ERRORS]
    )
    def test_exit_2_and_the_field_is_named(self, monkeypatch, capsys, why, change, field):
        code, out, err = run_main(monkeypatch, capsys, edit(base_order, change))
        assert code == 2, err
        assert out == ""
        assert f'field "{field}"' in err, err

    def test_the_base_order_is_valid(self, monkeypatch, capsys):
        code, out, err = run_main(monkeypatch, capsys, base_order(), "--format", "group")
        assert code == 0 and "52.00" in out and err == ""


# A name that cannot be written as UTF-8 must be refused at the input, not when the result is
# printed, and the same way in every output format (some formats never print the name).
SURROGATE_EXPENSE_ERRORS = [
    ("person", lambda d: d["people"].__setitem__(1, "小红\ud800"), "people[1]"),
    ("expense id", lambda d: expense(d).update(id="dinner\ud800"), "expenses[0].id"),
    ("expense description", lambda d: expense(d).update(what="聚餐\ud800"), "expenses[0].what"),
    (
        "item name",
        lambda d: expense(d)["items"][0].update(name="菜\ud800"),
        "expenses[0].items[0].name",
    ),
    (
        "fee name",
        lambda d: expense(d)["fees"][0].update(name="服务费\ud800"),
        "expenses[0].fees[0].name",
    ),
    (
        "discount name",
        lambda d: expense(d).update(
            discounts=[{"name": "券\ud800", "amount": 10, "split": "equal"}],
            paid_by={"阿明": 670},
        ),
        "expenses[0].discounts[0].name",
    ),
]

SURROGATE_ORDER_ERRORS = [
    ("order id", lambda d: d.update(id="o\ud800"), "id"),
    ("buyer", lambda d: d["items"][1].update(who="b\ud800"), "items[1].who"),
    ("dish name", lambda d: d["items"][0].update(name="x\ud800"), "items[0].name"),
    ("fee name", lambda d: d["fees"][0].update(name="delivery\ud800"), "fees[0].name"),
    ("coupon name", lambda d: d["coupons"][0].update(name="tiers\ud800"), "coupons[0].name"),
    ("payer", lambda d: d.update(paid_by="a\ud800"), "paid_by"),
]

OUTPUT_CHOICES = [["--format", "md"], ["--format", "dm"], ["--format", "group"], ["--json"]]


class TestUnpairedSurrogates:
    @staticmethod
    def check(monkeypatch, capsys, data, argv, field):
        code, out, err = run_main(monkeypatch, capsys, data, *argv)
        assert code == 2, err
        assert out == ""
        assert err == (
            f'error: invalid input, field "{field}": '
            "contains an invalid character (unpaired surrogate)\n"
        )

    @pytest.mark.parametrize("argv", OUTPUT_CHOICES, ids=[" ".join(c) for c in OUTPUT_CHOICES])
    @pytest.mark.parametrize(
        ("why", "change", "field"),
        SURROGATE_EXPENSE_ERRORS,
        ids=[c[0] for c in SURROGATE_EXPENSE_ERRORS],
    )
    def test_a_bill_is_refused_in_every_output_format(
        self, monkeypatch, capsys, why, change, field, argv
    ):
        self.check(monkeypatch, capsys, edit(base_expenses, change), argv, field)

    @pytest.mark.parametrize("argv", OUTPUT_CHOICES, ids=[" ".join(c) for c in OUTPUT_CHOICES])
    @pytest.mark.parametrize(
        ("why", "change", "field"),
        SURROGATE_ORDER_ERRORS,
        ids=[c[0] for c in SURROGATE_ORDER_ERRORS],
    )
    def test_a_group_order_is_refused_in_every_output_format(
        self, monkeypatch, capsys, why, change, field, argv
    ):
        self.check(monkeypatch, capsys, edit(base_order, change), argv, field)

    def test_the_name_in_a_payer_key_is_refused_too(self):
        order = base_order()
        order["paid_by"] = {"a\ud800": 52}
        with pytest.raises(fc.InputError) as caught:
            bs.parse_order(order)
        assert caught.value.field == "paid_by.a\ud800"
        assert caught.value.message == "contains an invalid character (unpaired surrogate)"

    def test_a_payer_key_that_is_not_among_the_people_is_a_stranger(self):
        """A payer key with an unpaired surrogate is refused as a stranger: it is not in people."""
        data = base_expenses()
        expense(data)["paid_by"] = {"阿明\ud800": 680}
        with pytest.raises(fc.InputError) as caught:
            bs.parse_ledger(data)
        assert caught.value.field == "expenses[0].paid_by.阿明\ud800"
        assert caught.value.message.endswith("is not in people")


class TestRawErrors:
    @pytest.mark.parametrize(("why", "text", "field"), RAW_ERRORS, ids=[c[0] for c in RAW_ERRORS])
    def test_exit_2_and_the_field_is_named(self, monkeypatch, capsys, why, text, field):
        code, _out, err = run_main(monkeypatch, capsys, text)
        assert code == 2, err
        assert f'field "{field}"' in err, err

    def test_a_missing_file_is_an_input_error(self, monkeypatch, capsys):
        with pytest.raises(SystemExit) as caught:
            fc.run_cli(bs.main, ["--input", "/nonexistent/bill.json"])
        assert caught.value.code == 2
        assert 'field "input"' in capsys.readouterr().err


class TestOddButValidInputs:
    """Inputs that look wrong but are fine, or fine but worth a note."""

    def test_a_person_named_all_is_just_a_person(self):
        data = {
            "people": ["all", "bob"],
            "expenses": [
                {
                    "paid_by": {"bob": 30},
                    "items": [
                        {"name": "shared", "amount": 20, "everyone": True},
                        {"name": "mine", "amount": 10, "among": ["all"]},
                    ],
                }
            ],
        }
        out = bs.compute(data).result
        assert int_map(out["owed_cents"]) == {"all": 2000, "bob": 1000}

    def test_everyone_includes_the_person_named_all(self):
        data = {
            "people": ["all", "bob", "cy"],
            "expenses": [
                {
                    "paid_by": {"cy": 30},
                    "items": [{"name": "shared", "amount": 30, "everyone": True}],
                }
            ],
        }
        assert int_map(bs.compute(data).result["owed_cents"]) == {
            "all": 1000,
            "bob": 1000,
            "cy": 1000,
        }

    def test_a_zero_yuan_item_is_only_a_note(self):
        data = base_expenses()
        expense(data)["items"].append(
            {"name": "complimentary water", "amount": 0, "everyone": True}
        )
        out = bs.compute(data).result
        assert [n["code"] for n in out["notes"]] == ["zero_item"]
        assert int_map(out["owed_cents"])["阿明"] == 12750

    def test_a_payer_who_shares_nothing_is_only_a_note(self):
        data = base_expenses()
        data["people"].append("老王")
        expense(data)["paid_by"] = {"老王": 680}
        expense(data)["items"][0] = {"name": "菜", "amount": 480, "among": data["people"][:4]}
        out = bs.compute(data).result
        assert {"code": "payer_not_sharing", "expense": "dinner-1", "person": "老王"} in out[
            "notes"
        ]
        assert int_map(out["net_cents"])["老王"] == 68000

    def test_two_people_can_pay_one_expense(self):
        data = base_expenses()
        expense(data)["paid_by"] = {"阿明": 400, "小红": 280}
        out = bs.compute(data).result
        assert int_map(out["paid_cents"]) == {"阿明": 40000, "小红": 28000, "大刘": 0, "Coco": 0}
        assert sum(int_map(out["net_cents"]).values()) == 0
        assert int_map(out["net_cents"])["阿明"] == 40000 - 12750

    def test_a_child_eats_half_a_portion(self):
        data = {
            "people": ["mum", "dad", "kid"],
            "expenses": [
                {
                    "paid_by": {"mum": 100},
                    "items": [
                        {"name": "dinner", "amount": 100, "everyone": True, "weights": {"kid": 0.5}}
                    ],
                }
            ],
        }
        calc = bs.compute_ledger(bs.parse_ledger(fc.parse_input(dump_json(data))), False)
        assert calc.owed == {"mum": 4000, "dad": 4000, "kid": 2000}

    def test_decimal_weights_come_out_of_json_text(self):
        text = (
            '{"people":["a","b"],"expenses":[{"paid_by":{"a":90},'
            '"items":[{"name":"x","amount":90,"everyone":true,"weights":{"b":0.5}}]}]}'
        )
        calc = bs.compute_ledger(bs.parse_ledger(fc.parse_input(text)), False)
        assert calc.owed == {"a": 6000, "b": 3000}

    def test_a_discount_is_shared_by_consumption(self):
        data = base_expenses()
        expense(data)["fees"] = []
        expense(data)["discounts"] = [{"name": "voucher", "amount": 64, "split": "by_consumption"}]
        expense(data)["paid_by"] = {"阿明": 576}
        out = bs.compute(data).result
        assert int_map(out["owed_cents"]) == {
            "阿明": 10800,
            "小红": 10800,
            "大刘": 18000,
            "Coco": 18000,
        }

    def test_an_equal_discount_can_make_a_share_negative(self):
        data = {
            "people": ["a", "b"],
            "expenses": [
                {
                    "paid_by": {"a": 8},
                    "items": [
                        {"name": "big", "amount": 10, "among": ["a"]},
                        {"name": "small", "amount": 0.5, "among": ["b"]},
                    ],
                    "discounts": [{"name": "voucher", "amount": 2.5, "split": "equal"}],
                }
            ],
        }
        out = bs.compute(data).result
        assert int_map(out["owed_cents"]) == {"a": 875, "b": -75}
        assert [n["code"] for n in out["notes"]] == ["negative_share"]

    def test_more_than_16_balances_fall_back_to_greedy_and_say_so(self):
        people = [f"p{i:02d}" for i in range(17)]
        expenses = [
            {
                "id": f"e{i}",
                "paid_by": {p: 10 + i},
                "items": [{"name": "x", "amount": 10 + i, "everyone": True}],
            }
            for i, p in enumerate(people)
        ]
        out = bs.compute({"people": people, "expenses": expenses}).result
        assert out["exact_minimum"] is False and out["transfer_counts"]["fewest"] is None
        assert [n["code"] for n in out["notes"]] == ["greedy_fallback"]
        assert len(out["transfers"]) <= 16

    def test_exactly_16_balances_are_searched_exactly(self):
        people = [f"p{i:02d}" for i in range(16)]
        expenses = [
            {
                "id": f"e{i}",
                "paid_by": {p: 10 + i},
                "items": [{"name": "x", "amount": 10 + i, "everyone": True}],
            }
            for i, p in enumerate(people)
        ]
        out = bs.compute({"people": people, "expenses": expenses}).result
        assert out["exact_minimum"] is True and out["transfer_counts"]["fewest"] == len(
            out["transfers"]
        )

    def test_everyone_even_means_no_transfers(self):
        data = {
            "people": ["a", "b"],
            "expenses": [
                {
                    "id": "1",
                    "paid_by": {"a": 10},
                    "items": [{"name": "x", "amount": 10, "everyone": True}],
                },
                {
                    "id": "2",
                    "paid_by": {"b": 10},
                    "items": [{"name": "x", "amount": 10, "everyone": True}],
                },
            ],
        }
        result = bs.compute(data)
        assert result.result["transfers"] == []
        assert "不需要转账" in fc.render(result, "md")
        assert "no transfers needed" in fc.render(bs.compute(data, lang="en"), "group")

    def test_a_negative_shapley_payer_is_reported(self):
        order = {
            "mode": "group_order",
            "items": [
                {"who": "big", "name": "x", "amount": 99},
                {"who": "small", "name": "y", "amount": 1},
            ],
            "coupons": [{"name": "deal", "tiers": [[100, 90]]}],
            "paid_by": "big",
        }
        out = bs.compute(order).result
        assert int_map(out["pay_cents"]) == {"big": 5400, "small": -4400}
        assert [n["code"] for n in out["notes"]] == ["negative_payer"]
        assert out["transfers"] == [{"from": "big", "to": "small", "cents": fc.Cents(4400)}]

    def test_a_payer_who_ordered_nothing_gets_money_back(self):
        order = base_order()
        order["paid_by"] = "pay-for-all"
        out = bs.compute(order).result
        assert out["net_cents"]["pay-for-all"] == 5200
        assert {n["code"] for n in out["notes"]} == {"payer_outside"}

    def test_no_payer_means_no_transfers_in_a_group_order(self):
        order = base_order()
        del order["paid_by"]
        out = bs.compute(order).result
        assert "transfers" not in out and int(out["total_cents"]) == 5200

    def test_a_single_buyer_gets_the_whole_coupon(self):
        order = {
            "mode": "group_order",
            "items": [{"who": "solo", "name": "x", "amount": 70}],
            "coupons": [{"name": "deal", "tiers": [[60, 18]]}],
        }
        assert int_map(bs.compute(order).result["pay_cents"]) == {"solo": 5200}

    def test_the_highest_tier_reached_applies_once(self):
        order = {
            "mode": "group_order",
            "items": [{"who": "a", "name": "x", "amount": 100}],
            "coupons": [{"name": "deal", "tiers": [[100, 20], [50, 8], [30, 3]]}],
        }
        assert int_map(bs.compute(order).result["pay_cents"]) == {"a": 8000}

    def test_by_consumption_is_accepted_for_order_fees_and_flat_coupons_as_proportional(self):
        order = base_order()
        order["fees"] = [{"name": "delivery", "amount": 5, "split": "by_consumption"}]
        order["coupons"] = [{"name": "packet", "amount": 3, "split": "by_consumption"}]
        order["paid_by"] = "a"
        spelled = bs.compute(order).result
        order["fees"][0]["split"] = "proportional"
        order["coupons"][0]["split"] = "proportional"
        assert bs.compute(order).result["pay_cents"] == spelled["pay_cents"]
        assert bs.compute(order).inputs_echo["fees"][0]["split"] == "proportional"

    def test_a_flat_coupon_shared_by_shapley_value_is_shared_equally(self):
        order = base_order()
        order["coupons"] = [{"name": "packet", "amount": 3, "split": "shapley"}]
        order["paid_by"] = "a"
        shapley = bs.compute(order).result
        order["coupons"][0]["split"] = "equal"
        assert bs.compute(order).result["pay_cents"] == shapley["pay_cents"]
        assert sorted(int_map(shapley["coupon_share"]).values()) == [100, 100, 100]

    def test_equal_is_another_name_of_aa_in_an_audit(self):
        data = base_expenses()
        data["audit"] = {"current": "equal"}
        calc = bs.compute_ledger(bs.parse_ledger(data), True)
        assert calc.audit is not None and calc.audit.label == "aa"
        assert bs.compute(data).inputs_echo["audit"] == {"current": "aa"}
        order = base_order()
        order["audit"] = {"current": "equal"}
        assert bs.compute(order, audit=True).result["audit"]["baseline"] == "aa"
