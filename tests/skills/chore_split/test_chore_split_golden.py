"""Golden values: the recorded example, the examples folder and a byte-stable demo."""

from __future__ import annotations

import json
import os
from collections import Counter
from typing import ClassVar

import chore_split as cs
import fsq_core as fc
import pytest
from chore_reference import reference_picks, reference_start_order, reference_week_order, spec_seed
from chore_support import (
    CHORES6,
    EXAMPLES,
    GOLDEN_DIR,
    GOLDEN_SEED,
    PEOPLE3,
    RANKINGS3,
    RECORDED_BUNDLES,
    RECORDED_PICKS,
    RECORDED_SCORES,
    SOURCE,
    load_example,
    recorded_data,
    run_json,
    run_script,
)


def plan_of(data):
    return cs.compute(cs.parse_problem(data))


class TestRecordedExample:
    """Three roommates, six chores, 阿明 first. The rankings are the ones implied by the scores
    of the first computation, where the dislike totals came out as 3, 7 and 8."""

    def test_the_pick_order_of_the_demo_source_is_the_recorded_one(self):
        plan = plan_of(recorded_data())
        assert plan.base_order == PEOPLE3
        assert plan.weeks[0].order == PEOPLE3

    def test_the_picks_are_the_recorded_ones(self):
        week = plan_of(recorded_data()).weeks[0]
        assert [(p.person, p.chore) for p in week.picks] == RECORDED_PICKS
        assert [p.round for p in week.picks] == [1, 1, 1, 2, 2, 2]
        assert week.bundles == RECORDED_BUNDLES

    def test_the_rankings_are_the_ones_the_scores_imply(self):
        for person, scores in RECORDED_SCORES.items():
            implied = sorted(CHORES6, key=lambda chore: (scores[chore], chore))
            assert implied == RANKINGS3[person]

    def test_dislike_totals_are_3_7_and_8_and_nobody_envies_anybody_under_those_scores(self):
        week = plan_of(recorded_data()).weeks[0]
        total = {
            person: {
                owner: sum(RECORDED_SCORES[person][chore] for chore in week.bundles[owner])
                for owner in PEOPLE3
            }
            for person in PEOPLE3
        }
        assert [total[p][p] for p in PEOPLE3] == [3, 7, 8]
        for person in PEOPLE3:
            for other in PEOPLE3:
                assert total[person][person] <= total[person][other]

    def test_the_guarantee_is_ef1_from_the_rankings_alone(self):
        plan = plan_of(recorded_data())
        status = {(c.person, c.other): c.status for c in plan.checks}
        assert plan.ef1_holds
        assert status == {
            ("阿明", "小红"): "envy_free",
            ("阿明", "大刘"): "envy_free",
            ("小红", "阿明"): "ef1",
            ("小红", "大刘"): "envy_free",
            ("大刘", "阿明"): "ef1",
            ("大刘", "小红"): "envy_free",
        }

    def test_a_cost_that_fits_the_ranking_shows_why_one_chore_is_set_aside(self):
        bundles = plan_of(recorded_data()).weeks[0].bundles
        ranking = RANKINGS3["小红"]
        cost = {chore: 1 for chore in ranking}
        cost["倒垃圾"] = 0
        assert all(cost[a] <= cost[b] for a, b in zip(ranking, ranking[1:]))  # fits her ranking
        own = sum(cost[c] for c in bundles["小红"])
        theirs = sum(cost[c] for c in bundles["阿明"])
        assert (own, theirs) == (2, 1)  # she envies 阿明 until one chore is set aside
        assert own - cost["擦窗"] <= theirs

    def test_the_certificate_of_daliu_against_aming_is_the_recorded_sentence(self):
        dm = run_json(recorded_data(), "--format", "dm").stdout
        block = dm.split("--- 发给 大刘 ---")[1]
        assert (
            "第 1 周，对阿明（阿明每轮先挑）：第 1 轮你挑的「拖地」（你的第 1 位）不比阿明下一轮"
            "（第 2 轮）挑的「做饭」（第 3 位）更讨厌；去掉你最后挑的「刷厕所」，你就不羡慕阿明。"
        ) in block

    def test_a_person_who_picks_first_compares_with_the_same_round(self):
        check = next(
            c for c in plan_of(recorded_data()).checks if (c.person, c.other) == ("阿明", "小红")
        )
        assert check.person_first
        assert [(c.own.round, c.other.round) for c in check.comparisons] == [(1, 1), (2, 2)]
        assert [(c.own_rank, c.other_rank) for c in check.comparisons] == [(1, 5), (2, 4)]

    def test_a_person_who_picks_later_compares_with_the_next_round(self):
        check = next(
            c for c in plan_of(recorded_data()).checks if (c.person, c.other) == ("大刘", "阿明")
        )
        assert not check.person_first
        assert [(c.own.round, c.other.round) for c in check.comparisons] == [(1, 2)]
        assert [p.chore for p in check.unmatched] == ["刷厕所"]

    def test_the_command_line_prints_the_same_values(self):
        done = run_json(recorded_data(), "--json")
        assert done.returncode == 0, done.stderr
        parsed = json.loads(done.stdout)
        week = parsed["result"]["weeks"][0]
        assert [(p["person"], p["chore"]) for p in week["picks"]] == RECORDED_PICKS
        assert week["bundles"] == RECORDED_BUNDLES
        assert parsed["result"]["seed_hex"] == GOLDEN_SEED
        assert parsed["result"]["ef1_holds"] is True


class TestSeedAndOrder:
    def test_the_recorded_seed(self):
        plan = plan_of(recorded_data())
        assert plan.seed_hex == GOLDEN_SEED

    def test_the_independent_reference_agrees(self):
        assert spec_seed(PEOPLE3, 6, SOURCE).hex() == GOLDEN_SEED
        assert reference_start_order(PEOPLE3, 6, SOURCE) == PEOPLE3

    def test_the_shared_core_gives_the_same_order(self):
        assert fc.draw_order(cs.RULE_NAME, PEOPLE3, 6, SOURCE) == PEOPLE3

    def test_the_rule_name_is_recorded(self):
        assert cs.RULE_NAME == "chore_pick_order_v1"

    def test_the_printed_preimage_hashes_to_the_seed(self):
        import hashlib

        plan = plan_of(recorded_data())
        assert hashlib.sha256(plan.preimage.encode("utf-8")).hexdigest() == GOLDEN_SEED
        assert json.loads(plan.preimage) == {
            "n_slots": 6,
            "participants": sorted(PEOPLE3),
            "rule": "chore_pick_order_v1",
            "source": SOURCE,
        }

    def test_the_number_of_chore_units_goes_into_the_seed(self):
        data = recorded_data()
        data["chores"][0] = {"name": "洗碗", "units": 2}
        assert plan_of(data).seed_hex != GOLDEN_SEED


class TestExamplesFolder:
    def test_the_first_example_is_the_demo_input(self):
        assert load_example("three_roommates.json") == json.loads(cs.DEMO_JSON)

    def test_the_demo_input_is_the_recorded_example(self):
        data = load_example("three_roommates.json")
        assert data["people"] == PEOPLE3
        assert data["chores"] == CHORES6
        assert data["rankings"] == RANKINGS3
        assert data["weeks"] == 1
        assert data["rules"]["random_source"] == SOURCE

    def test_the_weekly_rota_gives_the_recorded_schedule(self):
        data = load_example("weekly_rota.json")
        plan = plan_of(data)
        assert plan.base_order == ["大刘", "Coco", "小红", "阿明"]
        expected = [
            ("大刘", "Coco", "小红", "阿明"),
            ("Coco", "小红", "阿明", "大刘"),
            ("小红", "阿明", "大刘", "Coco"),
            ("阿明", "大刘", "Coco", "小红"),
        ]
        assert [tuple(w.order) for w in plan.weeks] == expected
        bundles = [{p: Counter(w.bundles[p]) for p in w.order} for w in plan.weeks]
        assert bundles[0] == {
            "大刘": Counter(["拖地", "洗碗", "刷厕所"]),
            "Coco": Counter(["买菜", "擦窗"]),
            "小红": Counter({"洗碗": 2}),
            "阿明": Counter({"倒垃圾": 2}),
        }
        # Nine chores among four people: the person who starts the week holds one more.
        for week in plan.weeks:
            sizes = {p: len(week.bundles[p]) for p in week.order}
            assert sizes[week.order[0]] == 3 and sorted(sizes.values()) == [2, 2, 2, 3]
        assert plan.ef1_holds

    def test_the_weekly_rota_agrees_with_the_independent_reference(self):
        data = load_example("weekly_rota.json")
        problem = cs.parse_problem(data)
        units = dict(problem.chores)
        base = reference_start_order(problem.people, sum(units.values()), problem.source)
        plan = cs.compute(problem)
        assert plan.base_order == base
        for week in plan.weeks:
            order = reference_week_order(base, week.number)
            assert week.order == order
            picks = reference_picks(order, problem.rankings, units)
            assert [(p.person, p.chore) for p in week.picks] == picks

    def test_the_cannot_example_breaks_the_guarantee_in_the_way_the_skill_describes(self):
        plan = plan_of(load_example("cannot_cook.json"))
        assert not plan.ef1_holds
        assert {(c.week, c.person, c.other) for c in plan.failures} == {
            (week, person, "小红") for week in (1, 2) for person in ("大刘", "Coco", "阿明")
        }
        first = plan.weeks[0]
        assert first.order == ["大刘", "Coco", "阿明", "小红"]
        assert {p: Counter(first.bundles[p]) for p in first.order} == {
            "大刘": Counter(["拖地", "洗碗", "做饭"]),
            "Coco": Counter(["擦窗", "做饭", "做饭"]),
            "阿明": Counter(["倒垃圾", "做饭", "做饭"]),
            "小红": Counter(["洗碗"]),
        }
        assert first.ran_out == {"小红": 2}
        assert sum(len(first.bundles[p]) for p in first.order) == 10

    def test_nobody_envies_the_person_who_cannot_cook_for_what_they_hold(self):
        plan = plan_of(load_example("cannot_cook.json"))
        for check in plan.checks:
            if check.person == "小红":
                assert check.status == "exempt"
                assert check.exempt == ["做饭"]

    @pytest.mark.parametrize(
        "name", ["three_roommates.json", "weekly_rota.json", "cannot_cook.json"]
    )
    def test_each_example_runs_from_the_command_line(self, name):
        done = run_script("--input", str(EXAMPLES / name))
        assert done.returncode == 0, done.stderr
        assert done.stdout.startswith("# 分家务结果")

    def test_there_are_exactly_five_examples_three_for_plan_a_and_two_for_plan_b(self):
        assert sorted(p.name for p in EXAMPLES.glob("*.json")) == [
            "bundle_three_roommates.json",
            "bundle_uneven_caps.json",
            "cannot_cook.json",
            "three_roommates.json",
            "weekly_rota.json",
        ]


class TestDemoIsByteStable:
    """The demo prints the same bytes on every run and matches the stored copies."""

    CASES: ClassVar[dict] = {
        "demo_md_zh.txt": ["--demo"],
        "demo_dm_zh.txt": ["--demo", "--format", "dm"],
        "demo_group_zh.txt": ["--demo", "--format", "group"],
        "demo_json.txt": ["--demo", "--json"],
        "demo_md_en.txt": ["--demo", "--lang", "en"],
        "demo_dm_en.txt": ["--demo", "--format", "dm", "--lang", "en"],
        "demo_group_en.txt": ["--demo", "--format", "group", "--lang", "en"],
    }

    @pytest.mark.parametrize("name", sorted(CASES))
    def test_two_runs_are_identical(self, name):
        first = run_script(*self.CASES[name])
        second = run_script(*self.CASES[name])
        assert first.returncode == 0, first.stderr
        assert first.stdout == second.stdout

    @pytest.mark.parametrize("name", sorted(CASES))
    def test_output_matches_the_stored_copy(self, name):
        done = run_script(*self.CASES[name])
        assert done.returncode == 0, done.stderr
        stored = GOLDEN_DIR / name
        if os.environ.get("FSQ_UPDATE_GOLDEN") == "1":
            GOLDEN_DIR.mkdir(exist_ok=True)
            stored.write_text(done.stdout, encoding="utf-8", newline="\n")
        assert done.stdout == stored.read_text(encoding="utf-8"), (
            f"{name} differs from the stored copy. If the change is intended, rerun with "
            "FSQ_UPDATE_GOLDEN=1 and review the diff."
        )

    def test_demo_json_carries_the_recorded_values(self):
        parsed = json.loads(run_script("--demo", "--json").stdout)
        assert parsed["result"]["seed_hex"] == GOLDEN_SEED
        assert parsed["result"]["start_order"] == PEOPLE3
        assert parsed["reproduce"] == "python3 scripts/chore_split.py --demo --json"

    def test_demo_from_json_input_gives_the_same_result(self):
        by_input = run_json(json.loads(cs.DEMO_JSON), "--json")
        by_demo = run_script("--demo", "--json")
        assert json.loads(by_input.stdout)["result"] == json.loads(by_demo.stdout)["result"]

    def test_the_demo_does_not_change_with_the_listing_order_of_the_input(self):
        data = json.loads(cs.DEMO_JSON)
        data["people"] = list(reversed(data["people"]))
        data["rankings"] = dict(reversed(list(data["rankings"].items())))
        shuffled = run_json(data, "--json")
        assert (
            json.loads(shuffled.stdout)["result"]
            == json.loads(run_script("--demo", "--json").stdout)["result"]
        )


class TestStoredCopiesOfOtherExamples:
    """The rota and the cannot example have stored md, dm and group copies too."""

    CASES: ClassVar[dict] = {
        "rota_md_zh.txt": ("weekly_rota.json", []),
        "rota_dm_zh.txt": ("weekly_rota.json", ["--format", "dm"]),
        "rota_group_zh.txt": ("weekly_rota.json", ["--format", "group"]),
        "rota_md_en.txt": ("weekly_rota.json", ["--lang", "en"]),
        "cannot_md_zh.txt": ("cannot_cook.json", []),
        "cannot_dm_zh.txt": ("cannot_cook.json", ["--format", "dm"]),
        "cannot_group_zh.txt": ("cannot_cook.json", ["--format", "group"]),
        "cannot_dm_en.txt": ("cannot_cook.json", ["--format", "dm", "--lang", "en"]),
        "cannot_group_en.txt": ("cannot_cook.json", ["--format", "group", "--lang", "en"]),
    }

    @pytest.mark.parametrize("name", sorted(CASES))
    def test_output_matches_the_stored_copy(self, name):
        example, flags = self.CASES[name]
        done = run_script("--input", str(EXAMPLES / example), *flags)
        assert done.returncode == 0, done.stderr
        stored = GOLDEN_DIR / name
        if os.environ.get("FSQ_UPDATE_GOLDEN") == "1":
            GOLDEN_DIR.mkdir(exist_ok=True)
            stored.write_text(done.stdout, encoding="utf-8", newline="\n")
        assert done.stdout == stored.read_text(encoding="utf-8"), (
            f"{name} differs from the stored copy. If the change is intended, rerun with "
            "FSQ_UPDATE_GOLDEN=1 and review the diff."
        )
