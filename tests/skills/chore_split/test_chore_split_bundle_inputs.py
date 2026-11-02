"""Plan B, the input: how the plan is chosen, the fields each plan refuses by name, the checks
on costs and caps, the exit codes, and fuzzing."""

from __future__ import annotations

import copy
import json

import chore_split as cs
import fsq_core as fc
import pytest
from chore_support import (
    BUNDLE_SOURCE,
    EXAMPLES,
    PEOPLE3,
    PROPERTY,
    bundle_data,
    load_example,
    price_data,
    recorded_data,
    run_json,
    run_script,
)
from hypothesis import given
from hypothesis import strategies as st

BUNDLE_EXAMPLES = ["bundle_three_roommates.json", "bundle_uneven_caps.json"]


def base():
    return copy.deepcopy(price_data(source=BUNDLE_SOURCE, description="虚构示例：某公开开奖"))


def field_of(data):
    """The field and message of the InputError that parse_problem raises for this input."""
    with pytest.raises(fc.InputError) as caught:
        cs.parse_problem(data)
    return caught.value.field, caught.value.message


def mutated(change, start=None):
    data = copy.deepcopy(start if start is not None else base())
    change(data)
    return data


class TestChoosingThePlan:
    def test_an_input_without_a_plan_is_plan_a(self):
        assert isinstance(cs.parse_problem(recorded_data()), cs.Problem)

    def test_rules_plan_bundle_pay_is_plan_b(self):
        assert isinstance(cs.parse_problem(base()), cs.BundleProblem)

    def test_naming_round_robin_gives_exactly_the_output_of_plan_a(self):
        plain = recorded_data(weeks=2)
        named = copy.deepcopy(plain)
        named["rules"]["plan"] = "round_robin"
        for lang in fc.LANGS:
            first, second = cs.solve(plain, lang), cs.solve(named, lang)
            assert fc.envelope(first) == fc.envelope(second)
            for fmt in fc.FORMATS:
                assert fc.render(first, fmt, False, lang) == fc.render(second, fmt, False, lang)

    @pytest.mark.parametrize("value", ["roundrobin", "B", "", None, 3, True, ["bundle_pay"]])
    def test_an_unknown_plan_is_refused_and_the_choices_are_listed(self, value):
        data = base()
        data["rules"]["plan"] = value
        field, message = field_of(data)
        assert field == "rules.plan"
        assert "round_robin" in message and "bundle_pay" in message

    def test_the_plan_is_checked_before_anything_else(self):
        data = base()
        data["rules"]["plan"] = "nope"
        data["people"] = []
        assert field_of(data)[0] == "rules.plan"

    def test_the_constants_name_the_two_plans(self):
        assert cs.PLANS == ("round_robin", "bundle_pay")
        assert cs.RULE_FIELDS == ("plan", "random_source", "source_description", "rotate")
        assert cs.BUNDLE_TOP_FIELDS == ("people", "chores", "costs", "caps", "cannot", "rules")
        assert cs.BUNDLE_RULE_FIELDS == ("plan", "random_source", "source_description")


class TestFieldsOfTheOtherPlan:
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("rankings", {}),
            ("likes", {}),
            ("weeks", 2),
        ],
    )
    def test_plan_b_names_the_top_level_field_of_plan_a(self, field, value):
        data = base()
        data[field] = value
        name, message = field_of(data)
        assert name == field
        assert "used by plan round_robin only" in message and "plan bundle_pay" in message

    def test_plan_b_names_the_rotation(self):
        data = base()
        data["rules"]["rotate"] = "shift"
        name, message = field_of(data)
        assert name == "rules.rotate" and "used by plan round_robin only" in message

    @pytest.mark.parametrize("field", ["costs", "caps"])
    def test_plan_a_names_the_fields_of_plan_b_and_says_how_to_switch(self, field):
        data = recorded_data()
        data[field] = {}
        name, message = field_of(data)
        assert name == field
        assert (
            "used by plan bundle_pay only" in message and "set rules.plan to bundle_pay" in message
        )

    def test_a_refusal_exits_2_with_the_field_in_the_message(self):
        data = base()
        data["rankings"] = {}
        done = run_json(data)
        assert done.returncode == 2 and done.stdout == ""
        assert done.stderr.startswith('error: invalid input, field "rankings": ')

    def test_the_message_of_an_unknown_field_lists_the_fields_of_the_plan_in_use(self):
        data = base()
        data["zzz"] = 1
        name, message = field_of(data)
        assert name == "zzz" and message.endswith("allowed: " + ", ".join(cs.BUNDLE_TOP_FIELDS))
        data = recorded_data()
        data["zzz"] = 1
        name, message = field_of(data)
        assert message.endswith("allowed: " + ", ".join(cs.TOP_FIELDS))

    def test_unknown_rules_fields_list_the_fields_of_the_plan_in_use(self):
        data = base()
        data["rules"]["zzz"] = 1
        assert field_of(data) == (
            "rules.zzz",
            "is not a known field; allowed: plan, random_source, source_description",
        )


class TestCostsAndCaps:
    @pytest.mark.parametrize(
        ("change", "field"),
        [
            (lambda d: d.pop("costs"), "costs"),
            (lambda d: d.update(costs=[]), "costs"),
            (lambda d: d.update(costs="x"), "costs"),
            (lambda d: d["costs"].update(Zed={}), "costs.Zed"),
            (lambda d: d["costs"].pop("小红"), "costs.小红"),
            (lambda d: d["costs"].update(小红=[1, 2, 3, 4, 5, 6]), "costs.小红"),
            (lambda d: d["costs"].update(小红={}), "costs.小红"),
            (lambda d: d["costs"]["小红"].pop("洗碗"), "costs.小红"),
            (lambda d: d["costs"]["小红"].update(遛狗=3), "costs.小红.遛狗"),
            (lambda d: d["costs"]["小红"].update(洗碗=-1), "costs.小红.洗碗"),
            (lambda d: d["costs"]["小红"].update(洗碗=0.001), "costs.小红.洗碗"),
            (lambda d: d["costs"]["小红"].update(洗碗=True), "costs.小红.洗碗"),
            (lambda d: d["costs"]["小红"].update(洗碗="a lot"), "costs.小红.洗碗"),
            (lambda d: d["costs"]["小红"].update(洗碗=None), "costs.小红.洗碗"),
            (lambda d: d["costs"]["小红"].update(洗碗=10**13), "costs.小红.洗碗"),
            (lambda d: d["costs"]["小红"].update(洗碗=[3]), "costs.小红.洗碗"),
        ],
    )
    def test_bad_costs(self, change, field):
        assert field_of(mutated(change))[0] == field

    def test_a_cost_may_be_zero_a_decimal_or_a_decimal_text(self):
        data = base()
        data["costs"]["小红"]["洗碗"] = 0
        data["costs"]["小红"]["擦窗"] = 12.5
        data["costs"]["小红"]["做饭"] = "70.25"
        problem = cs.parse_problem(data)
        assert problem.costs["小红"]["洗碗"] == 0
        assert problem.costs["小红"]["擦窗"] == 1250
        assert problem.costs["小红"]["做饭"] == 7025

    def test_a_chore_on_the_cannot_list_must_be_left_out_of_costs(self):
        data = base()
        data["cannot"] = {"小红": ["做饭"]}
        name, message = field_of(data)
        assert name == "costs.小红.做饭" and "in cannot for 小红" in message
        del data["costs"]["小红"]["做饭"]
        assert cs.parse_problem(data).cannot["小红"] == ["做饭"]

    def test_a_missing_cost_is_named_in_the_message(self):
        data = base()
        del data["costs"]["大刘"]["拖地"]
        name, message = field_of(data)
        assert name == "costs.大刘" and "'拖地'" in message

    @pytest.mark.parametrize(
        ("change", "field"),
        [
            (lambda d: d.pop("caps"), "caps"),
            (lambda d: d.update(caps=[2, 2, 2]), "caps"),
            (lambda d: d["caps"].update(Zed=1), "caps.Zed"),
            (lambda d: d["caps"].pop("小红"), "caps.小红"),
            (lambda d: d["caps"].update(小红=-1), "caps.小红"),
            (lambda d: d["caps"].update(小红=2.5), "caps.小红"),
            (lambda d: d["caps"].update(小红="2"), "caps.小红"),
            (lambda d: d["caps"].update(小红=True), "caps.小红"),
            (lambda d: d["caps"].update(小红=None), "caps.小红"),
            (lambda d: d["caps"].update(小红=cs.MAX_TOTAL_UNITS + 1), "caps.小红"),
        ],
    )
    def test_bad_caps(self, change, field):
        assert field_of(mutated(change))[0] == field

    def test_a_cap_may_be_zero_or_a_whole_number_written_with_a_decimal_point(self):
        data = base()
        data["caps"] = {"阿明": 0, "小红": 3.0, "大刘": 3}
        problem = cs.parse_problem(fc.parse_input(json.dumps(data, ensure_ascii=False)))
        assert [problem.caps[p] for p in PEOPLE3] == [0, 3, 3]

    @pytest.mark.parametrize(
        ("change", "field"),
        [
            (lambda d: d.pop("people"), "people"),
            (lambda d: d.update(people=["阿明"]), "people"),
            (lambda d: d.update(people=["阿明", "阿明", "大刘"]), "people[1]"),
            (lambda d: d.update(people=[f"p{i}" for i in range(13)]), "people"),
            (lambda d: d.pop("chores"), "chores"),
            (lambda d: d.update(chores=[]), "chores"),
            (lambda d: d["chores"].__setitem__(1, {"name": "x", "kind": 1}), "chores[1].kind"),
            (lambda d: d.update(cannot={"Zed": ["洗碗"]}), "cannot.Zed"),
            (lambda d: d.update(cannot={"小红": ["遛狗"]}), "cannot.小红[0]"),
            (lambda d: d.update(cannot={"小红": ["洗碗", "洗碗"]}), "cannot.小红[1]"),
        ],
    )
    def test_the_checks_shared_with_plan_a(self, change, field):
        assert field_of(mutated(change))[0] == field

    def test_the_sizes_are_those_of_plan_a(self):
        data = bundle_data(
            ["A", "B"],
            ["x"],
            {"A": {"x": 1}, "B": {"x": 1}},
            {"A": 1, "B": 1},
            units={"x": cs.MAX_UNITS + 1},
        )
        assert field_of(data)[0] == "chores[0].units"


class TestRules:
    def test_rules_must_be_an_object(self):
        data = recorded_data()
        data["rules"] = "none"
        assert field_of(data)[0] == "rules"

    def test_without_a_rules_object_the_plan_cannot_be_named_so_plan_a_applies(self):
        data = base()
        data["rules"] = "bundle_pay"
        name, message = field_of(data)  # the costs of plan B are refused by plan A, by name
        assert name == "costs" and "set rules.plan to bundle_pay" in message

    def test_the_random_source_is_optional(self):
        data = base()
        del data["rules"]["random_source"], data["rules"]["source_description"]
        problem = cs.parse_problem(data)
        assert problem.source is None and problem.description == ""

    @pytest.mark.parametrize("source", ["", "   ", 5, None, "x" * 10001, "a\ud800"])
    def test_a_bad_random_source(self, source):
        data = base()
        data["rules"]["random_source"] = source
        assert field_of(data)[0] == "rules.random_source"

    def test_a_description_needs_a_source(self):
        data = base()
        del data["rules"]["random_source"]
        name, message = field_of(data)
        assert name == "rules.source_description" and "random_source" in message

    @pytest.mark.parametrize("text", ["", "two\nlines", 4, "x" * 301])
    def test_a_bad_description(self, text):
        data = base()
        data["rules"]["source_description"] = text
        assert field_of(data)[0] == "rules.source_description"

    def test_the_source_is_kept_exactly_as_given(self):
        data = base()
        data["rules"]["random_source"] = "  03 11 | 19 24 "
        assert cs.parse_problem(data).source == "  03 11 | 19 24 "


class TestExitCodesAndOptions:
    def test_a_valid_input_exits_0_in_every_format(self):
        for fmt in ("md", "dm", "group"):
            done = run_json(base(), "--format", fmt)
            assert done.returncode == 0, done.stderr
            assert done.stdout.strip() and done.stderr == ""

    def test_an_invalid_input_exits_2_and_prints_nothing_on_standard_output(self):
        data = base()
        data["caps"]["小红"] = -1
        done = run_json(data)
        assert done.returncode == 2 and done.stdout == ""
        assert done.stderr.startswith('error: invalid input, field "caps.小红": ')

    def test_no_way_to_share_out_the_chores_exits_3(self):
        data = base()
        data["caps"] = {p: 1 for p in PEOPLE3}
        done = run_json(data)
        assert done.returncode == 3 and done.stdout == ""
        assert done.stderr.startswith("no solution: ")

    def test_the_demo_runs_and_is_the_example_file(self):
        demo = run_script("--demo-bundle")
        by_file = run_script("--input", str(EXAMPLES / "bundle_three_roommates.json"))
        assert demo.returncode == by_file.returncode == 0
        assert demo.stdout.replace("--demo-bundle", "--input -") == by_file.stdout

    def test_the_demo_input_is_the_first_example(self):
        assert load_example("bundle_three_roommates.json") == json.loads(cs.BUNDLE_DEMO_JSON)

    @pytest.mark.parametrize("other", ["--demo", "--selftest"])
    def test_the_demo_cannot_be_combined_with_another_mode(self, other):
        done = run_script("--demo-bundle", other)
        assert done.returncode == 2 and done.stdout == ""
        assert "choose at most one of --demo, --demo-bundle and --selftest" in done.stderr

    def test_the_demo_reads_no_file_and_deletes_none(self, tmp_path):
        path = tmp_path / "input.json"
        path.write_text(json.dumps(base(), ensure_ascii=False), encoding="utf-8")
        done = run_script("--demo-bundle", "--input", str(path), "--delete-input")
        assert done.returncode == 0 and path.exists()

    def test_a_file_of_plan_b_is_read_and_deleted_like_any_other(self, tmp_path):
        path = tmp_path / "input.json"
        path.write_text(json.dumps(base(), ensure_ascii=False), encoding="utf-8")
        by_file = run_script("--input", str(path), "--delete-input", "--json")
        by_stdin = run_json(base(), "--json")
        assert by_file.returncode == 0 and not path.exists()
        assert by_file.stdout == by_stdin.stdout

    def test_the_reproduce_line_names_the_bundle_demo(self):
        parsed = json.loads(run_script("--demo-bundle", "--json", "--lang", "en").stdout)
        assert (
            parsed["reproduce"] == "python3 scripts/chore_split.py --demo-bundle --json --lang en"
        )

    def test_the_selftest_covers_plan_b(self):
        done = run_script("--selftest")
        assert done.returncode == 0, done.stdout
        assert done.stdout.count("plan B") >= 6 and " 0 failed" in done.stdout


SCALARS = (
    st.none()
    | st.booleans()
    | st.integers(-5, 200)
    | st.floats(allow_nan=False, allow_infinity=False, width=32)
    | st.text(max_size=6)
)
JSON_VALUES = st.recursive(
    SCALARS,
    lambda children: (
        st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=4), children, max_size=3)
    ),
    max_leaves=8,
)
TOP_KEYS = ["people", "chores", "costs", "caps", "cannot", "rules", "rankings", "likes", "weeks"]


def refuses_or_answers(data):
    """True when the input was answered, False when it was refused the proper way."""
    text = json.dumps(data, ensure_ascii=False)
    try:
        result = cs.solve(fc.parse_input(text))
    except (fc.InputError, fc.NoSolution):
        return False
    for fmt in ("md", "dm", "group"):
        assert fc.render(result, fmt).strip()
    return True


class TestFuzzing:
    @PROPERTY
    @given(st.sampled_from(BUNDLE_EXAMPLES), st.sampled_from(TOP_KEYS), JSON_VALUES)
    def test_any_value_in_any_top_level_field_is_answered_or_refused(self, name, key, value):
        data = copy.deepcopy(load_example(name))
        data[key] = value
        refuses_or_answers(data)

    @PROPERTY
    @given(st.sampled_from(BUNDLE_EXAMPLES), st.data())
    def test_any_value_deeper_in_the_input_is_answered_or_refused(self, name, draw):
        data = copy.deepcopy(load_example(name))
        where = draw.draw(st.sampled_from(["costs", "caps", "rules", "chores", "cannot", "people"]))
        container = data.get(where)
        value = draw.draw(JSON_VALUES)
        if isinstance(container, dict) and container:
            key = draw.draw(st.sampled_from(sorted(container)))
            if isinstance(container[key], dict) and container[key] and draw.draw(st.booleans()):
                inner = draw.draw(st.sampled_from(sorted(container[key])))
                container[key][inner] = value
            else:
                container[key] = value
        elif isinstance(container, list) and container:
            container[draw.draw(st.integers(0, len(container) - 1))] = value
        else:
            data.setdefault(where, {})
            if isinstance(data[where], dict):
                data[where][draw.draw(st.text(max_size=4))] = value
        refuses_or_answers(data)

    @PROPERTY
    @given(st.sampled_from(BUNDLE_EXAMPLES), st.data())
    def test_dropping_or_adding_a_field_is_answered_or_refused(self, name, draw):
        data = copy.deepcopy(load_example(name))
        if draw.draw(st.booleans()):
            data.pop(draw.draw(st.sampled_from(sorted(data))))
        else:
            data[draw.draw(st.text(min_size=1, max_size=5))] = draw.draw(JSON_VALUES)
        refuses_or_answers(data)

    @PROPERTY
    @given(st.sampled_from(BUNDLE_EXAMPLES), st.integers(0, 12), st.integers(0, 12))
    def test_any_caps_and_any_one_cost_are_answered_or_refused(self, name, cap, cost):
        data = copy.deepcopy(load_example(name))
        person = data["people"][0]
        data["caps"][person] = cap
        chore = min(data["costs"][person])
        data["costs"][person][chore] = cost
        refuses_or_answers(data)

    def test_the_examples_are_answered(self):
        for name in BUNDLE_EXAMPLES:
            assert refuses_or_answers(load_example(name)) is True
