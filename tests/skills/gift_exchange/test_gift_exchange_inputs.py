"""Bad input: exit code 2 and the message names the field that is wrong. A rule set without a
legal draw: exit code 3 and the message says who has too few receivers."""

from __future__ import annotations

import copy
import json
from unittest import mock

import fsq_core as fc
import gift_exchange as ge
import pytest
from gift_support import (
    PEOPLE6,
    THREE,
    THREE_FORBIDDEN,
    exchange_data,
    run_json,
    run_script,
    six_people,
)

BASE = six_people()


def changed(base: dict, **fields) -> dict:
    """A copy of base with some fields replaced; a value of None removes the field."""
    data = copy.deepcopy(base)
    for key, value in fields.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    return data


def rules(base: dict, **fields) -> dict:
    """A copy of base whose rules block has some fields replaced (None removes one)."""
    data = copy.deepcopy(base)
    for key, value in fields.items():
        if value is None:
            data["rules"].pop(key, None)
        else:
            data["rules"][key] = value
    return data


def entry(base: dict, index: int, value) -> dict:
    """A copy of base whose forbidden entry number index is replaced."""
    data = copy.deepcopy(base)
    data["forbidden"][index] = value
    return data


BAD_INPUTS = [
    # --- the top level
    ("unknown top-level field", changed(BASE, n_slots=3), "n_slots"),
    ("mode unknown", changed(BASE, mode="circle"), "mode"),
    ("mode is a number", changed(BASE, mode=1), "mode"),
    # --- people
    ("people missing", changed(BASE, people=None), "people"),
    ("people not a list", changed(BASE, people="阿明"), "people"),
    ("one person", changed(BASE, people=["阿明"]), "people"),
    ("no people", changed(BASE, people=[]), "people"),
    ("more people than allowed", changed(BASE, people=[f"p{i}" for i in range(101)]), "people"),
    ("duplicate person", changed(BASE, people=["a", "b", "a"]), "people[2]"),
    ("blank person", changed(BASE, people=["a", " "]), "people[1]"),
    ("person with a leading space", changed(BASE, people=[" a", "b"]), "people[0]"),
    ("person is a number", changed(BASE, people=["a", "b", 3]), "people[2]"),
    ("unpaired surrogate in a name", changed(BASE, people=["a\ud800", "b"]), "people[0]"),
    # --- forbidden
    ("forbidden not a list", changed(BASE, forbidden={"pair": ["阿明", "小红"]}), "forbidden"),
    ("forbidden entry is text", entry(BASE, 0, "阿明"), "forbidden[0]"),
    ("forbidden entry is empty", entry(BASE, 1, {}), "forbidden[1]"),
    (
        "unknown field in an entry",
        entry(BASE, 0, {"pair": ["阿明", "小红"], "why": "x"}),
        "forbidden[0].why",
    ),
    ("pair with one name", entry(BASE, 0, {"pair": ["阿明"]}), "forbidden[0].pair"),
    (
        "pair with three names",
        entry(BASE, 0, {"pair": ["阿明", "小红", "Coco"]}),
        "forbidden[0].pair",
    ),
    ("pair is text", entry(BASE, 0, {"pair": "阿明小红"}), "forbidden[0].pair"),
    (
        "pair with an unknown name",
        entry(BASE, 1, {"pair": ["大刘", "路人"]}),
        "forbidden[1].pair[1]",
    ),
    ("pair of one person", entry(BASE, 0, {"pair": ["阿明", "阿明"]}), "forbidden[0].pair"),
    ("pair name is a number", entry(BASE, 0, {"pair": [1, "阿明"]}), "forbidden[0].pair[0]"),
    ("giver without receiver", entry(BASE, 2, {"giver": "老王"}), "forbidden[2]"),
    ("receiver without giver", entry(BASE, 2, {"receiver": "Yuki"}), "forbidden[2]"),
    ("unknown giver", entry(BASE, 2, {"giver": "路人", "receiver": "Yuki"}), "forbidden[2].giver"),
    (
        "unknown receiver",
        entry(BASE, 2, {"giver": "老王", "receiver": "路人"}),
        "forbidden[2].receiver",
    ),
    (
        "giver is the receiver",
        entry(BASE, 2, {"giver": "老王", "receiver": "老王"}),
        "forbidden[2]",
    ),
    (
        "pair together with giver",
        entry(BASE, 0, {"pair": ["阿明", "小红"], "giver": "阿明"}),
        "forbidden[0]",
    ),
    (
        "more exclusions than allowed",
        changed(BASE, forbidden=[{"giver": "阿明", "receiver": "小红"}] * 5001),
        "forbidden",
    ),
    # --- the randomness
    ("random source missing", changed(BASE, random_source=None), "random_source"),
    ("random source blank", changed(BASE, random_source="   "), "random_source"),
    ("random source is a number", changed(BASE, random_source=20261108), "random_source"),
    (
        "random source too long",
        changed(BASE, random_source="x" * (fc.MAX_SOURCE_CHARS + 1)),
        "random_source",
    ),
    ("random source with a surrogate", changed(BASE, random_source="draw \ud800"), "random_source"),
    # --- rules
    ("rules missing", changed(BASE, rules=None), "rules"),
    ("rules not an object", changed(BASE, rules=["x"]), "rules"),
    ("deadline missing", rules(BASE, deadline=None), "rules.deadline"),
    ("deadline blank", rules(BASE, deadline="  "), "rules.deadline"),
    ("deadline over two lines", rules(BASE, deadline="a\nb"), "rules.deadline"),
    ("deadline too long", rules(BASE, deadline="d" * 301), "rules.deadline"),
    (
        "source description missing",
        rules(BASE, source_description=None),
        "rules.source_description",
    ),
    (
        "source description with a surrogate",
        rules(BASE, source_description="x\ud800"),
        "rules.source_description",
    ),
    ("unknown rule", rules(BASE, tie_break="name"), "rules.tie_break"),
]
IDS = [case[0] for case in BAD_INPUTS]


@pytest.mark.parametrize(("label", "data", "field"), BAD_INPUTS, ids=IDS)
def test_bad_input_raises_an_input_error_that_names_the_field(label, data, field):
    with pytest.raises(fc.InputError) as caught:
        ge.parse_problem(data)
    assert caught.value.field == field, f"{label}: {caught.value}"
    assert caught.value.message


@pytest.mark.parametrize(("label", "data", "field"), BAD_INPUTS, ids=IDS)
def test_bad_input_exits_2_and_names_the_field_on_the_command_line(label, data, field):
    # json.dumps keeps its ASCII escapes, so an unpaired surrogate survives the pipe
    done = run_script("--input", "-", stdin=json.dumps(data))
    assert done.returncode == 2, f"{label}: {done.stderr}"
    assert done.stdout == ""
    assert f'field "{field}"' in done.stderr, done.stderr


def test_the_top_level_must_be_an_object():
    for text in ("[]", '"x"', "3", "null"):
        done = run_script("--input", "-", stdin=text)
        assert done.returncode == 2 and done.stdout == ""
        assert 'field "input"' in done.stderr


def test_text_that_is_not_json_is_refused():
    done = run_script("--input", "-", stdin="{not json")
    assert done.returncode == 2 and 'field "input"' in done.stderr


def test_a_duplicate_key_is_refused():
    text = '{"people": ["a", "b"], "people": ["c", "d"]}'
    done = run_script("--input", "-", stdin=text)
    assert done.returncode == 2 and "duplicate key" in done.stderr


def test_the_unknown_field_message_lists_the_known_fields():
    done = run_json(changed(BASE, zzz=1))
    assert done.stderr == (
        'error: invalid input, field "zzz": is not a known field; allowed: '
        "mode, people, forbidden, random_source, rules\n"
    )


# ---------------------------------------------------------------------------------------
# Valid inputs at the edges
# ---------------------------------------------------------------------------------------


def test_the_way_of_giving_defaults_to_any():
    data = changed(BASE, mode=None)
    assert ge.parse_problem(data).mode == "any"
    assert (
        ge.compute(ge.parse_problem(data)).receiver_of
        == ge.compute(ge.parse_problem(BASE)).receiver_of
    )


def test_the_exclusions_are_optional_and_may_be_empty():
    for data in (changed(BASE, forbidden=None), changed(BASE, forbidden=[])):
        assert ge.parse_problem(data).blocked == frozenset()


def test_two_people_give_to_each_other_in_both_ways():
    for mode in ("any", "ring"):
        out = ge.compute(ge.parse_problem(exchange_data(["a", "b"], [], mode)))
        assert out.receiver_of == {"a": "b", "b": "a"}
        assert out.draw.count == 1 and out.draw.number == 1


def test_a_hundred_people_are_accepted_in_both_ways_of_giving():
    people = [f"q{i:03d}" for i in range(100)]
    forbidden = [{"pair": [people[2 * i], people[2 * i + 1]]} for i in range(50)]
    for mode in ("any", "ring"):
        out = ge.compute(ge.parse_problem(exchange_data(people, forbidden, mode)))
        assert out.draw.method == "rejection"
        assert sorted(out.receiver_of.values()) == people


def test_a_person_may_appear_in_many_exclusions():
    people = ["a", "b", "c", "d", "e"]
    forbidden = [{"giver": "a", "receiver": other} for other in ("b", "c")]
    out = ge.compute(ge.parse_problem(exchange_data(people, forbidden)))
    assert out.receiver_of["a"] in ("d", "e")


def test_names_may_contain_vertical_bars_and_the_tables_keep_working():
    people = ["a|b", "c", "d"]
    done = run_json(exchange_data(people, []))
    assert done.returncode == 0, done.stderr
    assert "a\\|b" in done.stdout
    assert "竖线" in done.stdout


# ---------------------------------------------------------------------------------------
# Exit code 3: the rules leave no legal draw
# ---------------------------------------------------------------------------------------


def test_three_people_with_a_couple_exit_3_and_name_the_couple():
    done = run_json(exchange_data(THREE, THREE_FORBIDDEN))
    assert done.returncode == 3 and done.stdout == ""
    assert done.stderr.startswith("no solution: No legal draw exists. ")
    assert "甲, 乙 (2 people) can only give to 丙 (1 person)" in done.stderr
    assert "甲、乙这 2 个人能送的只有丙（1 人）" in done.stderr


def test_a_person_who_may_not_give_to_anybody_is_the_reason_with_zero_receivers():
    people = ["a", "b", "c"]
    forbidden = [{"giver": "a", "receiver": "b"}, {"giver": "a", "receiver": "c"}]
    with pytest.raises(ge.NoLegalPlan) as caught:
        ge.compute(ge.parse_problem(exchange_data(people, forbidden)))
    assert caught.value.kind == "hall"
    assert caught.value.group == ["a"] and caught.value.others == []
    assert "a (1 person) cannot give to anybody" in str(caught.value)
    assert "a 这 1 个人一个能送的人都没有" in str(caught.value)


def test_two_people_who_are_a_pair_have_no_draw():
    with pytest.raises(ge.NoLegalPlan) as caught:
        ge.compute(ge.parse_problem(exchange_data(["a", "b"], [{"pair": ["a", "b"]}])))
    assert caught.value.kind == "hall" and caught.value.group == ["a"]


def test_the_group_is_shown_in_the_order_the_people_were_listed():
    people = ["丙", "乙", "甲"]
    with pytest.raises(ge.NoLegalPlan) as caught:
        ge.compute(ge.parse_problem(exchange_data(people, [{"pair": ["乙", "甲"]}])))
    assert caught.value.group == ["乙", "甲"] and caught.value.others == ["丙"]


def test_two_groups_that_only_give_among_themselves_cannot_form_one_circle():
    people = ["A", "B", "C", "D"]
    forbidden = [{"giver": g, "receiver": r} for g in "AB" for r in "CD"]
    out = ge.compute(ge.parse_problem(exchange_data(people, forbidden, "any")))
    assert out.receiver_of["A"] == "B" and out.receiver_of["B"] == "A"
    with pytest.raises(ge.NoLegalPlan) as caught:
        ge.compute(ge.parse_problem(exchange_data(people, forbidden, "ring")))
    assert caught.value.kind == "closed" and caught.value.group == ["A", "B"]
    assert "A, B (2 people) may only give to each other" in str(caught.value)
    assert "没法把全部 4 个人连成一圈" in str(caught.value)


def test_the_exit_code_of_a_missing_circle_is_3_too():
    people = ["A", "B", "C", "D"]
    forbidden = [{"giver": g, "receiver": r} for g in "AB" for r in "CD"]
    done = run_json(exchange_data(people, forbidden, "ring"))
    assert done.returncode == 3 and done.stdout == ""


def test_a_search_that_finds_nothing_in_the_limit_exits_with_the_limit_message():
    people = [f"p{i}" for i in range(10)]
    near = {(i, (i + step) % 10) for i in range(10) for step in (1, 9)}
    forbidden = [
        {"giver": people[i], "receiver": people[j]}
        for i in range(10)
        for j in range(10)
        if i != j and (i, j) not in near
    ]
    with mock.patch.object(ge, "MAX_ATTEMPTS", 3), pytest.raises(ge.NoLegalPlan) as caught:
        ge.compute(ge.parse_problem(exchange_data(people, forbidden)))
    assert caught.value.kind == "limit"
    assert "No legal plan was found in 3 random tries" in str(caught.value)
    assert "随机试了 3 次，没有找到合法的抽法" in str(caught.value)


def test_the_limit_is_a_documented_constant():
    assert ge.MAX_ATTEMPTS == 20000 and ge.ENUMERATE_MAX == 9 and ge.MAX_PEOPLE == 100


# ---------------------------------------------------------------------------------------
# --check
# ---------------------------------------------------------------------------------------


def test_check_needs_neither_a_source_nor_rules():
    data = changed(BASE, random_source=None, rules=None)
    done = run_json(data, "--check")
    assert done.returncode == 0, done.stderr
    assert "有合法方案" in done.stdout and "96" in done.stdout


def test_check_still_validates_a_source_or_rules_that_are_given():
    for data in (changed(BASE, random_source="  "), rules(BASE, deadline="a\nb")):
        done = run_json(data, "--check")
        assert done.returncode == 2 and done.stdout == ""


def test_check_still_needs_the_people():
    done = run_json(changed(BASE, people=None), "--check")
    assert done.returncode == 2 and 'field "people"' in done.stderr


def test_check_exits_3_with_the_same_message_as_the_draw():
    checked = run_json(exchange_data(THREE, THREE_FORBIDDEN), "--check")
    drawn = run_json(exchange_data(THREE, THREE_FORBIDDEN))
    assert checked.returncode == drawn.returncode == 3
    assert checked.stderr == drawn.stderr


def test_check_counts_the_circles_for_the_way_ring():
    done = run_json(six_people("ring"), "--check", "--json")
    parsed = json.loads(done.stdout)
    assert parsed["result"] == {
        "legal_plan_exists": True,
        "method": "enumeration",
        "plan_count": 40,
    }


def test_check_of_a_big_circle_cannot_promise_that_one_exists():
    people = [f"p{i:02d}" for i in range(12)]
    done = run_json(exchange_data(people, [], "ring"), "--check", "--json")
    parsed = json.loads(done.stdout)
    assert parsed["result"] == {
        "legal_plan_exists": None,
        "method": "rejection",
        "plan_count": None,
    }


def test_check_of_a_big_group_in_the_way_any_knows_that_a_plan_exists():
    people = [f"p{i:02d}" for i in range(12)]
    done = run_json(exchange_data(people, [], "any"), "--check", "--json")
    assert json.loads(done.stdout)["result"]["legal_plan_exists"] is True


@pytest.mark.parametrize("fmt", ["dm", "group"])
def test_check_has_only_the_md_and_json_outputs(fmt):
    done = run_json(BASE, "--check", "--format", fmt)
    assert done.returncode == 2 and done.stdout == ""
    assert f'field "--format": {fmt} is not available with --check' in done.stderr


def test_check_with_json_ignores_the_format_option():
    done = run_json(BASE, "--check", "--json", "--format", "dm")
    assert done.returncode == 0 and json.loads(done.stdout)["result"]["plan_count"] == 96


def test_check_works_on_the_demo():
    done = run_script("--demo", "--check")
    assert done.returncode == 0 and "有合法方案" in done.stdout


def test_selftest_cannot_be_combined_with_the_demo_or_check():
    for flag in ("--demo", "--check"):
        done = run_script("--selftest", flag)
        assert done.returncode == 2 and 'field "options"' in done.stderr


def test_the_check_reads_the_people_in_any_order():
    data = changed(BASE, people=list(reversed(PEOPLE6)))
    first = json.loads(run_json(BASE, "--check", "--json").stdout)
    second = json.loads(run_json(data, "--check", "--json").stdout)
    assert first["result"] == second["result"]
