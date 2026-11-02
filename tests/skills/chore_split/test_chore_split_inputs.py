"""Input validation and exit codes. Exit code 2 names the field, exit code 3 means that some
chore is on every person's cannot list."""

from __future__ import annotations

import copy
import json

import chore_split as cs
import fsq_core as fc
import pytest
from chore_support import (
    CHORES6,
    EXAMPLES,
    PEOPLE3,
    RANKINGS3,
    chore_data,
    recorded_data,
    run_json,
    run_script,
    run_script_bytes,
)


def field_of(data):
    """The field named by the InputError that parse_problem raises for this input."""
    with pytest.raises(fc.InputError) as caught:
        cs.parse_problem(data)
    return caught.value.field, caught.value.message


def mutated(change):
    data = copy.deepcopy(recorded_data())
    change(data)
    return data


def cli_exit(data, *flags):
    return run_json(data, *flags)


# ---------------------------------------------------------------------------------------
# Whole-input problems
# ---------------------------------------------------------------------------------------


class TestWholeInput:
    def test_the_valid_recorded_input_is_accepted(self):
        assert cs.parse_problem(recorded_data()).people == PEOPLE3

    def test_not_a_json_object_exits_2(self):
        for text in ("[1, 2]", '"x"', "3", "null"):
            done = run_script("--input", "-", stdin=text)
            assert done.returncode == 2, text
            assert 'field "input"' in done.stderr

    def test_invalid_json_exits_2(self):
        done = run_script("--input", "-", stdin="{not json")
        assert done.returncode == 2
        assert "not valid JSON" in done.stderr

    def test_empty_input_exits_2(self):
        done = run_script("--input", "-", stdin="")
        assert done.returncode == 2

    def test_invalid_utf8_exits_2(self):
        done = run_script_bytes("--input", "-", stdin=b'{"people": "\xff\xfe"}')
        assert done.returncode == 2
        assert b"Traceback" not in done.stderr

    def test_duplicate_keys_exit_2(self):
        done = run_script("--input", "-", stdin='{"people": [], "people": []}')
        assert done.returncode == 2
        assert "duplicate key" in done.stderr

    def test_a_missing_file_exits_2(self):
        done = run_script("--input", "no-such-file.json")
        assert done.returncode == 2

    def test_an_unknown_top_level_field_is_named(self):
        field, message = field_of(mutated(lambda d: d.update(rankingz={})))
        assert field == "rankingz" and "allowed" in message

    def test_a_misspelled_cannot_is_not_ignored(self):
        data = mutated(lambda d: d.update(cant={"阿明": ["做饭"]}))
        assert field_of(data)[0] == "cant"

    def test_demo_and_selftest_together_exit_2(self):
        assert run_script("--demo", "--selftest").returncode == 2


# ---------------------------------------------------------------------------------------
# People and chores
# ---------------------------------------------------------------------------------------


class TestPeopleAndChores:
    @pytest.mark.parametrize(
        ("change", "field"),
        [
            (lambda d: d.pop("people"), "people"),
            (lambda d: d.update(people="阿明"), "people"),
            (lambda d: d.update(people=["阿明"]), "people"),
            (lambda d: d.update(people=["阿明", "阿明", "大刘"]), "people[1]"),
            (lambda d: d.update(people=["阿明", " 小红", "大刘"]), "people[1]"),
            (lambda d: d.update(people=["阿明", "", "大刘"]), "people[1]"),
            (lambda d: d.update(people=["阿明", 7, "大刘"]), "people[1]"),
            (lambda d: d.update(people=[f"p{i}" for i in range(13)]), "people"),
        ],
    )
    def test_bad_people(self, change, field):
        assert field_of(mutated(change))[0] == field

    @pytest.mark.parametrize(
        ("change", "field"),
        [
            (lambda d: d.pop("chores"), "chores"),
            (lambda d: d.update(chores=[]), "chores"),
            (lambda d: d.update(chores="洗碗"), "chores"),
            (lambda d: d.update(chores=["洗碗", "倒垃圾", "洗碗"]), "chores[2]"),
            (lambda d: d["chores"].__setitem__(1, 5), "chores[1]"),
            (lambda d: d["chores"].__setitem__(1, {"units": 2}), "chores[1]"),
            (lambda d: d["chores"].__setitem__(1, {"name": "x", "kind": "y"}), "chores[1].kind"),
            (lambda d: d["chores"].__setitem__(0, {"name": "洗碗", "units": 0}), "chores[0].units"),
            (
                lambda d: d["chores"].__setitem__(0, {"name": "洗碗", "units": 22}),
                "chores[0].units",
            ),
            (
                lambda d: d["chores"].__setitem__(0, {"name": "洗碗", "units": 2.5}),
                "chores[0].units",
            ),
            (
                lambda d: d["chores"].__setitem__(0, {"name": "洗碗", "units": True}),
                "chores[0].units",
            ),
            (
                lambda d: d["chores"].__setitem__(0, {"name": "洗碗", "units": "3"}),
                "chores[0].units",
            ),
        ],
    )
    def test_bad_chores(self, change, field):
        assert field_of(mutated(change))[0] == field

    def test_duplicate_chores_exit_2_through_the_command_line(self):
        data = mutated(lambda d: d.update(chores=["洗碗", "倒垃圾", "洗碗"]))
        done = cli_exit(data)
        assert done.returncode == 2
        assert 'field "chores[2]"' in done.stderr and "duplicate" in done.stderr

    def test_too_many_units_in_total(self):
        names = [f"c{i}" for i in range(7)]
        data = chore_data(
            ["A", "B"],
            names,
            {"A": names, "B": names},
            units={c: 20 for c in names},
        )
        assert field_of(data)[0] == "chores"

    def test_too_many_chores(self):
        names = [f"c{i}" for i in range(41)]
        data = chore_data(["A", "B"], names, {"A": names, "B": names})
        assert field_of(data)[0] == "chores"

    def test_units_may_be_given_as_a_whole_decimal(self):
        data = mutated(lambda d: d["chores"].__setitem__(0, {"name": "洗碗", "units": 2}))
        text = json.dumps(data, ensure_ascii=False).replace('"units": 2', '"units": 2.0')
        assert '"units": 2.0' in text
        assert cs.parse_problem(fc.parse_input(text)).chores[0] == ("洗碗", 2)

    def test_the_largest_allowed_input_runs(self):
        names = [f"c{i}" for i in range(40)]
        people = [f"p{i}" for i in range(12)]
        rankings = {p: names[i:] + names[:i] for i, p in enumerate(people)}
        data = chore_data(people, names, rankings, units={c: 3 for c in names}, weeks=12)
        plan = cs.compute(cs.parse_problem(data))
        assert plan.ef1_holds and len(plan.weeks) == 12


# ---------------------------------------------------------------------------------------
# Rankings
# ---------------------------------------------------------------------------------------


class TestRankings:
    def test_a_missing_ranking_exits_2_and_names_the_person(self):
        data = mutated(lambda d: d["rankings"].pop("小红"))
        done = cli_exit(data)
        assert done.returncode == 2
        assert 'field "rankings.小红"' in done.stderr and "missing" in done.stderr

    def test_no_rankings_at_all(self):
        assert field_of(mutated(lambda d: d.pop("rankings")))[0] == "rankings"

    def test_rankings_that_are_not_an_object(self):
        assert field_of(mutated(lambda d: d.update(rankings=[1, 2])))[0] == "rankings"

    def test_a_ranking_of_somebody_who_is_not_listed(self):
        data = mutated(lambda d: d["rankings"].update({"路人": CHORES6}))
        assert field_of(data)[0] == "rankings.路人"

    def test_a_ranking_that_is_not_a_list(self):
        data = mutated(lambda d: d["rankings"].update({"阿明": "倒垃圾"}))
        assert field_of(data)[0] == "rankings.阿明"

    def test_a_ranking_with_a_chore_missing_is_not_a_permutation(self):
        data = mutated(lambda d: d["rankings"]["阿明"].remove("拖地"))
        field, message = field_of(data)
        assert field == "rankings.阿明" and "拖地" in message

    def test_a_ranking_with_a_chore_twice_is_not_a_permutation(self):
        data = mutated(lambda d: d["rankings"]["阿明"].__setitem__(5, "倒垃圾"))
        done = cli_exit(data)
        assert done.returncode == 2
        assert 'field "rankings.阿明[5]"' in done.stderr and "duplicate" in done.stderr

    def test_a_ranking_with_an_unknown_chore(self):
        data = mutated(lambda d: d["rankings"]["阿明"].__setitem__(0, "遛狗"))
        field, message = field_of(data)
        assert field == "rankings.阿明[0]" and "遛狗" in message

    def test_a_ranking_with_something_that_is_not_text(self):
        data = mutated(lambda d: d["rankings"]["阿明"].__setitem__(0, 3))
        assert field_of(data)[0] == "rankings.阿明[0]"

    def test_a_ranking_that_is_too_long(self):
        data = mutated(lambda d: d["rankings"]["阿明"].append("倒垃圾"))
        assert field_of(data)[0] == "rankings.阿明[6]"

    def test_every_permutation_is_accepted(self):
        data = mutated(lambda d: d["rankings"].update({"阿明": list(reversed(CHORES6))}))
        assert cs.parse_problem(data).rankings["阿明"] == list(reversed(CHORES6))

    def test_two_people_may_rank_alike(self):
        data = mutated(lambda d: d["rankings"].update({"小红": RANKINGS3["阿明"]}))
        assert cs.compute(cs.parse_problem(data)).ef1_holds


# ---------------------------------------------------------------------------------------
# Liked tasks
# ---------------------------------------------------------------------------------------


class TestLikedTasks:
    def test_a_liked_task_exits_2_and_says_chores_only(self):
        data = mutated(lambda d: d.update(likes={"小红": ["做饭"]}))
        done = cli_exit(data)
        assert done.returncode == 2
        assert 'field "likes.小红"' in done.stderr
        assert "only chores" in done.stderr and "做饭" in done.stderr
        assert done.stdout == ""

    def test_a_liked_task_is_refused_whatever_the_ranking_says(self):
        data = mutated(lambda d: d.update(likes={"阿明": ["倒垃圾"]}))
        assert field_of(data)[0] == "likes.阿明"

    def test_empty_likes_are_fine(self):
        data = mutated(lambda d: d.update(likes={"小红": [], "阿明": []}))
        assert cs.compute(cs.parse_problem(data)).ef1_holds
        assert cs.compute(cs.parse_problem(mutated(lambda d: d.update(likes={})))).ef1_holds

    def test_likes_must_name_known_people_and_chores(self):
        data = mutated(lambda d: d.update(likes={"路人": ["做饭"]}))
        assert field_of(data)[0] == "likes.路人"
        data = mutated(lambda d: d.update(likes={"小红": ["遛狗"]}))
        assert field_of(data)[0] == "likes.小红[0]"


# ---------------------------------------------------------------------------------------
# cannot lists
# ---------------------------------------------------------------------------------------


class TestCannot:
    def cook_data(self, **extra):
        rankings = {
            "阿明": ["倒垃圾", "洗碗", "做饭"],
            "小红": ["倒垃圾", "洗碗"],
            "大刘": ["洗碗", "倒垃圾", "做饭"],
        }
        return chore_data(
            PEOPLE3, ["洗碗", "倒垃圾", "做饭"], rankings, cannot={"小红": ["做饭"]}, **extra
        )

    def test_a_cannot_list_is_accepted_when_the_ranking_leaves_the_chore_out(self):
        assert cs.compute(cs.parse_problem(self.cook_data())).problem.cannot["小红"] == ["做饭"]

    def test_the_ranking_must_not_contain_a_chore_on_the_cannot_list(self):
        data = self.cook_data()
        data["rankings"]["小红"].append("做饭")
        field, message = field_of(data)
        assert field == "rankings.小红[2]" and "cannot" in message

    def test_the_ranking_must_contain_every_other_chore(self):
        data = self.cook_data()
        data["rankings"]["小红"].remove("洗碗")
        assert field_of(data)[0] == "rankings.小红"

    @pytest.mark.parametrize(
        ("cannot", "field"),
        [
            ({"路人": ["做饭"]}, "cannot.路人"),
            ({"小红": ["遛狗"]}, "cannot.小红[0]"),
            ({"小红": ["做饭", "做饭"]}, "cannot.小红[1]"),
            ({"小红": "做饭"}, "cannot.小红"),
            ({"小红": [3]}, "cannot.小红[0]"),
        ],
    )
    def test_bad_cannot_lists(self, cannot, field):
        data = self.cook_data()
        data["cannot"] = cannot
        assert field_of(data)[0] == field

    def test_cannot_that_is_not_an_object(self):
        data = self.cook_data()
        data["cannot"] = ["做饭"]
        assert field_of(data)[0] == "cannot"

    def test_a_chore_that_nobody_can_do_exits_3(self):
        rankings = {
            "阿明": ["倒垃圾", "洗碗"],
            "小红": ["倒垃圾", "洗碗"],
            "大刘": ["倒垃圾", "洗碗"],
        }
        data = chore_data(
            PEOPLE3,
            ["洗碗", "倒垃圾", "做饭"],
            rankings,
            cannot={p: ["做饭"] for p in PEOPLE3},
        )
        done = cli_exit(data)
        assert done.returncode == 3
        assert "做饭" in done.stderr and "nobody can do" in done.stderr
        assert done.stdout == ""

    def test_one_person_who_can_do_the_chore_is_enough(self):
        done = cli_exit(self.cook_data())
        assert done.returncode == 0, done.stderr

    def test_a_person_who_can_do_nothing_is_allowed_and_the_guarantee_says_what_it_costs(self):
        data = chore_data(
            ["A", "B"],
            ["x", "y"],
            {"A": [], "B": ["x", "y"]},
            cannot={"A": ["x", "y"]},
        )
        plan = cs.compute(cs.parse_problem(data))
        week = plan.weeks[0]
        assert week.bundles["A"] == [] and week.bundles["B"] == ["x", "y"]
        assert not plan.ef1_holds
        assert {(c.person, c.other) for c in plan.failures} == {("B", "A")}
        assert cli_exit(data).returncode == 0

    def test_a_person_left_with_nothing_they_can_do_makes_ef1_fail(self):
        data = chore_data(
            ["A", "B"],
            ["x", "y", "z"],
            {"A": ["x", "y", "z"], "B": ["x"]},
            cannot={"B": ["y", "z"]},
            rotate="none",
        )
        problem = cs.parse_problem(data)
        week = cs.run_week(problem, 1, ["A", "B"])
        assert week.bundles == {"A": ["x", "y", "z"], "B": []}
        assert week.ran_out == {"B": 1}
        a_to_b = cs.check_pair(problem, week, "A", "B")
        assert a_to_b.status == "fails" and a_to_b.other_out_round == 1
        assert a_to_b.witness == {"threshold": 1, "chore": "x", "own_heavy": 2, "other_heavy": 0}
        b_to_a = cs.check_pair(problem, week, "B", "A")
        assert b_to_a.status == "exempt" and b_to_a.exempt == ["y", "z"]

    def test_exit_code_is_0_even_when_the_guarantee_fails(self):
        text = (EXAMPLES / "cannot_cook.json").read_text(encoding="utf-8")
        done = run_script("--input", "-", stdin=text)
        assert done.returncode == 0
        assert "EF1 不成立" in done.stdout


# ---------------------------------------------------------------------------------------
# weeks and rules
# ---------------------------------------------------------------------------------------


class TestWeeksAndRules:
    @pytest.mark.parametrize("weeks", [0, 13, -1, 2.5, "3", True, None, [1]])
    def test_bad_weeks(self, weeks):
        assert field_of(mutated(lambda d: d.update(weeks=weeks)))[0] == "weeks"

    @pytest.mark.parametrize("weeks", ["1", "2", "12", "3.0"])
    def test_good_weeks(self, weeks):
        text = json.dumps(recorded_data(), ensure_ascii=False).replace(
            '"weeks": 1', f'"weeks": {weeks}'
        )
        assert f'"weeks": {weeks}' in text
        assert len(cs.compute(cs.parse_problem(fc.parse_input(text))).weeks) == int(float(weeks))

    def test_weeks_default_to_one(self):
        data = mutated(lambda d: d.pop("weeks"))
        assert len(cs.compute(cs.parse_problem(data)).weeks) == 1

    @pytest.mark.parametrize(
        ("change", "field"),
        [
            (lambda d: d.pop("rules"), "rules"),
            (lambda d: d.update(rules="x"), "rules"),
            (lambda d: d.update(rules={}), "rules.random_source"),
            (lambda d: d["rules"].update(random_source=""), "rules.random_source"),
            (lambda d: d["rules"].update(random_source="   "), "rules.random_source"),
            (lambda d: d["rules"].update(random_source=7), "rules.random_source"),
            (lambda d: d["rules"].update(random_source="x" * 10_001), "rules.random_source"),
            (lambda d: d["rules"].update(rotate="reverse"), "rules.rotate"),
            (lambda d: d["rules"].update(rotate=True), "rules.rotate"),
            (lambda d: d["rules"].update(deadline="x"), "rules.deadline"),
            (lambda d: d["rules"].update(source_description="a\nb"), "rules.source_description"),
            (lambda d: d["rules"].update(source_description="x" * 301), "rules.source_description"),
            (lambda d: d["rules"].update(source_description=""), "rules.source_description"),
        ],
    )
    def test_bad_rules(self, change, field):
        assert field_of(mutated(change))[0] == field

    def test_the_random_source_is_required_not_defaulted(self):
        done = cli_exit(mutated(lambda d: d["rules"].pop("random_source")))
        assert done.returncode == 2 and "rules.random_source" in done.stderr

    def test_the_source_is_kept_exactly(self):
        source = "  （虚构）03 11 | 19   "
        data = mutated(lambda d: d["rules"].update(random_source=source))
        assert cs.parse_problem(data).source == source
        parsed = json.loads(cli_exit(data, "--json").stdout)
        assert parsed["inputs_echo"]["random_source"] == source

    def test_a_lone_surrogate_in_a_name_exits_2(self):
        data = recorded_data()
        data["people"][0] = "\ud800"
        data["rankings"]["\ud800"] = data["rankings"].pop("阿明")
        text = json.dumps(data)
        assert "\\ud800" in text
        done = run_script("--input", "-", stdin=text)
        assert done.returncode == 2
        assert "surrogate" in done.stderr

    def test_a_lone_surrogate_in_the_source_exits_2(self):
        data = recorded_data()
        data["rules"]["random_source"] = "x\ud800"
        done = run_script("--input", "-", stdin=json.dumps(data))
        assert done.returncode == 2
        assert "surrogate" in done.stderr

    def test_the_default_rotation_is_shift(self):
        assert "rotate" not in recorded_data()["rules"]
        assert cs.parse_problem(recorded_data()).rotate == "shift"


class TestCommandLine:
    def test_help_lists_every_option_and_the_exit_codes(self):
        done = run_script("--help")
        assert done.returncode == 0
        for flag in ("--input", "--format", "--json", "--demo", "--selftest", "--lang"):
            assert flag in done.stdout
        assert "Exit code 0 means success" in done.stdout.replace("\n", " ")

    def test_selftest_passes(self):
        done = run_script("--selftest")
        assert done.returncode == 0, done.stdout
        assert "0 failed" in done.stdout

    def test_a_bad_format_or_language_is_refused_by_argparse(self):
        assert run_script("--demo", "--format", "html").returncode == 2
        assert run_script("--demo", "--lang", "fr").returncode == 2

    def test_input_can_be_read_from_a_file(self):
        done = run_script("--input", str(EXAMPLES / "three_roommates.json"), "--format", "group")
        assert done.returncode == 0
        assert done.stdout.startswith("分家务结果")

    def test_the_script_writes_nothing_to_stderr_on_success(self):
        assert run_script("--demo").stderr == ""
