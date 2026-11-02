"""Mutated inputs must give a result or an input error that names a field, never a crash."""

from __future__ import annotations

import copy
from fractions import Fraction

import bill_split as bs
import fsq_core as fc
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

SETTINGS = settings(
    deadline=None,
    max_examples=400,
    derandomize=True,
    database=None,
    suppress_health_check=list(HealthCheck),
)

LEDGER = {
    "people": ["阿明", "小红", "大刘", "Coco"],
    "expenses": [
        {
            "id": "dinner-1",
            "what": "聚餐",
            "paid_by": {"阿明": 600, "小红": 80},
            "items": [
                {"name": "菜", "amount": 480, "everyone": True},
                {"name": "酒", "amount": 160, "among": ["大刘", "Coco"], "weights": {"Coco": 2}},
                {"name": "票", "amount": 20, "exact": {"阿明": 15, "小红": 5}},
            ],
            "fees": [{"name": "服务费", "amount": 40, "split": "by_consumption"}],
            "discounts": [{"name": "券", "amount": 20, "split": "equal"}],
        }
    ],
    "rules": {"settle": "min_transfers"},
    "audit": {"current": "aa"},
}

ORDER = {
    "mode": "group_order",
    "id": "o-1",
    "items": [
        {"who": "a", "name": "x", "amount": 28, "packaging": 1},
        {"who": "b", "name": "y", "amount": 28, "packaging": 1},
        {"who": "c", "name": "z", "amount": 6, "packaging": 1},
    ],
    "fees": [{"name": "delivery", "amount": 5, "split": "proportional"}],
    "coupons": [
        {"name": "tiers", "tiers": [[40, 10], [60, 18]], "split": "shapley"},
        {"name": "packet", "amount": 3, "split": "equal"},
    ],
    "paid_by": {"a": 40, "b": 9},
    "audit": {"current": "proportional"},
}

REPLACEMENTS = [
    None,
    True,
    False,
    0,
    1,
    -1,
    2,
    10**13,
    Fraction(1, 3),
    Fraction(5, 2),
    Fraction(-7, 4),
    "",
    " ",
    "x",
    "all",
    "阿明",
    "小红",
    "a",
    [],
    [1],
    ["a"],
    ["阿明", "阿明"],
    {},
    {"a": 1},
    {"阿明": 1},
    {"阿明": Fraction(1, 2)},
    [[1, 2]],
    [[0, 0]],
    [[10, 20]],
]


def paths(value, prefix=()):
    """Every path (tuple of keys and indices) to a value inside value, including the root's children."""
    if isinstance(value, dict):
        for key, inner in value.items():
            yield (*prefix, key)
            yield from paths(inner, (*prefix, key))
    elif isinstance(value, list):
        for index, inner in enumerate(value):
            yield (*prefix, index)
            yield from paths(inner, (*prefix, index))


def mutate(base, draw_path, draw_kind, draw_value):
    data = copy.deepcopy(base)
    chosen = draw_path(list(paths(data)))
    parent = data
    for step in chosen[:-1]:
        parent = parent[step]
    key = chosen[-1]
    kind = draw_kind()
    if kind == "delete":
        if isinstance(parent, dict):
            del parent[key]
        else:
            parent.pop(key)
    elif kind == "replace":
        parent[key] = draw_value()
    else:
        if isinstance(parent, dict):
            parent[f"extra-{kind}"] = draw_value()
    return data


@st.composite
def mutated(draw, base):
    data = base
    for _ in range(draw(st.integers(1, 3))):
        data = mutate(
            data,
            lambda options: draw(st.sampled_from(options)),
            lambda: draw(st.sampled_from(["delete", "replace", "replace", "add"])),
            lambda: draw(st.sampled_from(REPLACEMENTS)),
        )
    return data


def outcome(data):
    try:
        result = bs.compute(data, audit=True)
    except fc.InputError as err:
        assert err.field, "an input error must name a field"
        return "error"
    for fmt in ("md", "dm", "group"):
        assert fc.render(result, fmt, False, "zh")
        assert fc.render(result, fmt, False, "en")
    assert fc.render_json(result)
    return "ok"


class TestMutatedInputs:
    @given(mutated(LEDGER))
    @SETTINGS
    def test_a_mutated_ledger_gives_a_result_or_an_input_error(self, data):
        outcome(data)

    @given(mutated(ORDER))
    @SETTINGS
    def test_a_mutated_order_gives_a_result_or_an_input_error(self, data):
        outcome(data)

    def test_the_unmutated_inputs_are_valid(self):
        assert outcome(LEDGER) == "ok" and outcome(ORDER) == "ok"

    def test_the_mutations_reach_both_outcomes(self):
        """Guard against a fuzz base that is already invalid, which would make the test vacuous."""
        seen = set()

        @given(mutated(LEDGER))
        @SETTINGS
        def probe(data):
            seen.add(outcome(data))

        probe()
        assert seen == {"ok", "error"}
