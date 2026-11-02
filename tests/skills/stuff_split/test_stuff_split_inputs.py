"""The stuff-split script as a program: options, exit codes and what it does with bad input.

Every run uses ``python -B -S``, so the script must work without any installed package.
"""

from __future__ import annotations

import json
import re

import pytest
from stuff_split_support import (
    ROOMMATE_VALUES,
    ROOMMATES,
    STUFF,
    dumps,
    make_input,
    piano,
    roommates,
    run_script,
)


def run_json(data, *args):
    return run_script("--input", "-", *args, stdin=dumps(data))


# --------------------------------------------------------------------------------------
# Options and help
# --------------------------------------------------------------------------------------


def test_help_lists_every_option():
    done = run_script("--help")
    assert done.returncode == 0
    for option in (
        "--input",
        "--delete-input",
        "--format",
        "--json",
        "--demo",
        "--selftest",
        "--lang",
    ):
        assert re.search(rf"(?<![\w-]){re.escape(option)}(?![\w-])", done.stdout), option
    for needed in ("Exit code 0 means success", "envy_free", "knaster", "max_nash", "2,000,000"):
        assert needed in " ".join(done.stdout.split()), needed


def test_selftest_passes_and_says_so():
    done = run_script("--selftest")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "0 failed" in done.stdout
    assert "ok   stuff: piano under knaster and envy_free" in done.stdout


def test_running_without_input_is_an_input_error():
    done = run_script()
    assert done.returncode == 2
    assert 'field "input"' in done.stderr


def test_demo_and_selftest_together_are_refused():
    done = run_script("--demo", "--selftest")
    assert done.returncode == 2
    assert 'field "options"' in done.stderr


def test_an_unknown_format_is_a_usage_error():
    done = run_script("--format", "html", "--demo")
    assert done.returncode == 2
    assert "invalid choice" in done.stderr


# --------------------------------------------------------------------------------------
# Exit code 2: invalid input names the field
# --------------------------------------------------------------------------------------


def bad(change, method="max_nash"):
    data = roommates(method)
    change(data)
    return data


def many_people(count):
    names = [f"p{i}" for i in range(count)]
    return make_input(names, ["g"], {name: [1] for name in names}, "max_nash")


INVALID = [
    ("no people", lambda d: d.pop("people"), "people"),
    ("one person", lambda d: d.update(people=["阿明"], values={"阿明": [1] * 6}), "people"),
    ("thirteen people", lambda d: d.update(many_people(13)), "people"),
    ("people not a list", lambda d: d.update(people="阿明"), "people"),
    ("duplicate person", lambda d: d.update(people=["阿明", "阿明", "大刘"]), "people[1]"),
    ("a name with a space", lambda d: d["people"].__setitem__(0, " 阿明"), "people[0]"),
    ("a name that is not text", lambda d: d["people"].__setitem__(0, 7), "people[0]"),
    ("no items", lambda d: d.pop("items"), "items"),
    (
        "an empty item list",
        lambda d: d.update(items=[], values={n: [] for n in ROOMMATES}),
        "items",
    ),
    ("sixty-one items", lambda d: d.update(items=[f"g{i}" for i in range(61)]), "items"),
    ("duplicate item", lambda d: d["items"].__setitem__(1, "冰箱"), "items[1]"),
    ("no values", lambda d: d.pop("values"), "values"),
    ("values not an object", lambda d: d.update(values=[1, 2]), "values"),
    ("a person who is not listed", lambda d: d["values"].update({"路人": [1] * 6}), "values.路人"),
    ("a person without values", lambda d: d["values"].pop("大刘"), "values.大刘"),
    ("too few values", lambda d: d["values"]["阿明"].pop(), "values.阿明"),
    ("too many values", lambda d: d["values"]["阿明"].append(1), "values.阿明"),
    ("values not a list", lambda d: d["values"].update({"阿明": 5}), "values.阿明"),
    ("a negative value", lambda d: d["values"]["阿明"].__setitem__(2, -1), "values.阿明[2]"),
    (
        "a value with three decimals",
        lambda d: d["values"]["小红"].__setitem__(0, 1.005),
        "values.小红[0]",
    ),
    ("a value that is true", lambda d: d["values"]["小红"].__setitem__(1, True), "values.小红[1]"),
    (
        "a value that is not a number",
        lambda d: d["values"]["大刘"].__setitem__(0, "lots"),
        "values.大刘[0]",
    ),
    ("a value that is NaN", lambda d: d["values"]["大刘"].__setitem__(0, "nan"), "values.大刘[0]"),
    (
        "a value that is too large",
        lambda d: d["values"]["大刘"].__setitem__(0, 10**13),
        "values.大刘[0]",
    ),
    ("no rules", lambda d: d.pop("rules"), "rules.method"),
    ("no method", lambda d: d["rules"].clear(), "rules.method"),
    ("a method that does not exist", lambda d: d["rules"].update(method="auto"), "rules.method"),
    ("an unknown field", lambda d: d.update(price=1), "price"),
    ("an unknown rule field", lambda d: d["rules"].update(tie="x"), "rules.tie"),
    ("a blank source", lambda d: d["rules"].update(random_source="  "), "rules.random_source"),
    (
        "a source that is not text",
        lambda d: d["rules"].update(random_source=5),
        "rules.random_source",
    ),
    ("a note with a line break", lambda d: d.update(note="a\nb"), "note"),
    ("a note that is too long", lambda d: d.update(note="x" * 301), "note"),
    ("a note that is not text", lambda d: d.update(note=3), "note"),
]


@pytest.mark.parametrize(("label", "change", "field"), INVALID, ids=[row[0] for row in INVALID])
def test_invalid_input_exits_2_and_names_the_field(label, change, field):
    data = roommates()
    change(data)
    done = run_json(data)
    assert done.returncode == 2, done.stdout
    assert done.stdout == ""
    assert done.stderr.startswith(f'error: invalid input, field "{field}"'), done.stderr


WEIGHT_ERRORS = [
    ("a person is missing", {"甲": 1, "乙": 1}, "rules.weights.丙"),
    ("a person who is not listed", {"甲": 1, "乙": 1, "丙": 1, "丁": 1}, "rules.weights.丁"),
    ("a weight of zero", {"甲": 1, "乙": 0, "丙": 1}, "rules.weights.乙"),
    ("a negative weight", {"甲": 1, "乙": -2, "丙": 1}, "rules.weights.乙"),
    ("a weight that is true", {"甲": 1, "乙": True, "丙": 1}, "rules.weights.乙"),
    ("a weight that is text", {"甲": 1, "乙": "2", "丙": 1}, "rules.weights.乙"),
    ("a weight that is too large", {"甲": 1, "乙": 1_000_001, "丙": 1}, "rules.weights.乙"),
]


@pytest.mark.parametrize(
    ("label", "weights", "field"), WEIGHT_ERRORS, ids=[w[0] for w in WEIGHT_ERRORS]
)
def test_bad_weights_name_the_person(label, weights, field):
    done = run_json(piano("knaster", weights=weights))
    assert done.returncode == 2
    assert done.stderr.startswith(f'error: invalid input, field "{field}"'), done.stderr


def test_weights_that_are_not_an_object_are_refused():
    done = run_json(piano("knaster", weights=[1, 1, 1]))
    assert done.returncode == 2 and 'field "rules.weights"' in done.stderr


def test_weights_with_another_method_are_refused_and_say_why():
    done = run_json(piano("envy_free", weights={"甲": 1, "乙": 1, "丙": 1}))
    assert done.returncode == 2
    assert 'field "rules.weights"' in done.stderr and "only the knaster method" in done.stderr


def test_input_that_is_not_json_is_an_input_error():
    done = run_script("--input", "-", stdin="{not json")
    assert done.returncode == 2 and 'field "input"' in done.stderr


def test_input_that_is_not_an_object_is_an_input_error():
    done = run_script("--input", "-", stdin="[1, 2]")
    assert done.returncode == 2 and 'field "input"' in done.stderr


# --------------------------------------------------------------------------------------
# Odd but valid inputs
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["envy_free", "knaster", "max_nash"])
def test_values_may_be_numbers_or_decimal_strings_and_are_exact(method):
    as_numbers = make_input(["a", "b"], ["x", "y"], {"a": [0.29, 1], "b": [0.1, 2.5]}, method)
    as_strings = make_input(
        ["a", "b"], ["x", "y"], {"a": ["0.29", "1"], "b": ["0.10", "2.50"]}, method
    )
    first, second = run_json(as_numbers, "--json"), run_json(as_strings, "--json")
    assert first.returncode == second.returncode == 0, first.stderr
    assert first.stdout == second.stdout
    echo = json.loads(first.stdout)["inputs_echo"]["values"]
    assert echo["a"]["x"] == "0.29" and echo["b"]["x"] == "0.10"  # 0.29 is 29 cents, not 28.999


@pytest.mark.parametrize("method", ["envy_free", "knaster", "max_nash"])
def test_every_value_zero_still_gives_a_result(method):
    data = make_input(["a", "b"], ["x"], {"a": [0], "b": [0]}, method)
    done = run_json(data, "--format", "group", "--lang", "en")
    assert done.returncode == 0, done.stderr


@pytest.mark.parametrize("method", ["envy_free", "knaster", "max_nash"])
def test_one_item_and_two_people_work_in_every_format(method):
    data = make_input(["a", "b"], ["x"], {"a": [5], "b": [3]}, method)
    for flags in (["--format", "md"], ["--format", "dm"], ["--format", "group"], ["--json"]):
        for lang in ("zh", "en"):
            done = run_json(data, *flags, "--lang", lang)
            assert done.returncode == 0 and done.stdout, (flags, lang, done.stderr)


@pytest.mark.parametrize("method", ["envy_free", "knaster", "max_nash"])
def test_the_largest_sizes_are_accepted(method):
    names = [f"p{i:02d}" for i in range(12)]
    goods = [f"g{j:02d}" for j in range(60)]
    values = {name: [(7 * i + 3 * j) % 17 for j in range(60)] for i, name in enumerate(names)}
    done = run_json(make_input(names, goods, values, method), "--format", "group")
    assert done.returncode == 0, done.stderr


def test_a_note_is_shown_in_the_outputs_and_kept_in_the_json():
    data = piano("envy_free")
    data["note"] = "虚构示例：测试用"
    for flags in (["--format", "md"], ["--format", "group"]):
        assert "虚构示例：测试用" in run_json(data, *flags).stdout
    assert json.loads(run_json(data, "--json").stdout)["inputs_echo"]["note"] == "虚构示例：测试用"
    assert "note" not in json.loads(run_json(piano("envy_free"), "--json").stdout)["inputs_echo"]


@pytest.mark.parametrize("method", ["envy_free", "knaster", "max_nash"])
def test_the_listing_order_of_people_and_items_does_not_change_the_numbers(method):
    base = json.loads(run_json(roommates(method), "--json").stdout)
    people, items = list(reversed(ROOMMATES)), list(reversed(STUFF))
    values = {name: list(reversed(ROOMMATE_VALUES[name])) for name in people}
    again = json.loads(run_json(make_input(people, items, values, method), "--json").stdout)
    for key in ("owner", "own_value_cents", "max_envy_cents", "tie_break"):
        assert again["result"][key] == base["result"][key], key
    for key in ("cash_cents", "worth_cents"):
        assert again["result"].get(key) == base["result"].get(key), key
    for name in ROOMMATES:
        assert sorted(again["result"]["allocation"][name]) == sorted(
            base["result"]["allocation"][name]
        )
    assert again["certificate"]["envy_table"] == base["certificate"]["envy_table"]
