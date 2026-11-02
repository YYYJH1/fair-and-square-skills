"""Method da: no blocking pair, the best result among the stable ones for the applicants, nobody
gains by reporting another ranking, and the lottery that breaks ties.

The script is compared with matching_reference.py, which shares no code with it: the definition of a
blocking pair, a search over all assignments, a second run of Gale and Shapley on a market in
which every seat is a college of its own, and a replay of the printed rounds.
"""

from __future__ import annotations

import collections
import json

import fsq_core as fc
import pytest
import slot_lottery as sl
from hypothesis import given
from hypothesis import strategies as st
from lottery_reference import all_reports, lexicographic_best, reference_order, spec_seed
from lottery_support import (
    EXAMPLES,
    PROPERTY,
    da_data,
    load_example,
    matching_cases,
    run_json,
)
from matching_reference import (
    blocking_pairs_by_definition,
    feasible_assignments,
    gale_shapley_by_seats,
    pareto_improvement,
    rank_of,
    reference_key,
    replay_rounds,
    stable_assignments,
)

PEOPLE = ["x", "y", "z"]
SLOTS = ["a", "b"]
# The recorded example of an outcome that is stable and still improved by a swap that ignores
# the priorities: x lists a before b, z lists b before a, y lists only b.
PARETO_PREFS = {"x": ["a", "b"], "y": ["b"], "z": ["b", "a"]}
PARETO_PRIORITIES = {"a": [["z"], ["y"], ["x"]], "b": [["x"], ["y"], ["z"]]}


def outcome(data):
    return sl.compute(sl.parse_problem(data))


def case_data(case):
    people, slots, prefs, capacities, priorities, source = case
    return da_data(people, slots, prefs, source, capacities=capacities, priorities=priorities)


def case_outcome(case):
    return outcome(case_data(case))


def assignment_of(out, people):
    return {p: out.allocation.get(p) for p in people}


# ---------------------------------------------------------------------------------------
# What deferred acceptance guarantees, checked against the definitions
# ---------------------------------------------------------------------------------------


@PROPERTY
@given(matching_cases(max_people=5, max_slots=3, with_priorities=True))
def test_everybody_gets_at_most_one_slot_that_they_list_and_that_accepts_them_within_its_seats(
    case,
):
    people, _, prefs, capacities, priorities, _ = case
    out = case_outcome(case)
    key = reference_key(priorities, out.da.order)
    used = collections.Counter(out.allocation.values())
    assert all(count <= capacities[s] for s, count in used.items())
    for person, slot in out.allocation.items():
        assert slot in prefs[person] and key(slot, person) is not None
    assert sorted(out.unassigned + list(out.allocation)) == sorted(people)


@PROPERTY
@given(matching_cases(max_people=5, max_slots=3, with_priorities=True))
def test_there_is_no_blocking_pair(case):
    people, slots, prefs, capacities, priorities, _ = case
    out = case_outcome(case)
    key = reference_key(priorities, out.da.order)
    names = sorted(people)
    got = assignment_of(out, names)
    assert blocking_pairs_by_definition(names, slots, capacities, prefs, key, got) == []
    assert (
        sl.blocking_pairs(
            names,
            prefs,
            capacities,
            sl.priority_key(priorities, {p: i for i, p in enumerate(out.da.order, 1)}),
            out.allocation,
        )
        == []
    )


@PROPERTY
@given(matching_cases(max_people=5, max_slots=3, with_priorities=True))
def test_the_result_equals_gale_shapley_on_the_market_with_one_college_per_seat(case):
    people, _, prefs, capacities, priorities, _ = case
    out = case_outcome(case)
    key = reference_key(priorities, out.da.order)
    assert out.allocation == gale_shapley_by_seats(sorted(people), prefs, capacities, key)


@PROPERTY
@given(matching_cases(max_people=4, max_slots=3, with_priorities=True))
def test_every_applicant_gets_the_best_slot_that_any_stable_assignment_gives_them(case):
    people, slots, prefs, capacities, priorities, _ = case
    out = case_outcome(case)
    key = reference_key(priorities, out.da.order)
    names = sorted(people)
    got = assignment_of(out, names)
    stable = stable_assignments(names, slots, capacities, prefs, key)
    assert got in stable
    for other in stable:
        for person in names:
            assert rank_of(prefs, person, got[person]) <= rank_of(prefs, person, other[person])


@PROPERTY
@given(matching_cases(max_people=4, max_slots=3, with_priorities=True), st.data())
def test_nobody_gains_by_reporting_a_ranking_that_is_not_their_own(case, data):
    people, slots, prefs, capacities, priorities, _ = case
    out = case_outcome(case)
    key = reference_key(priorities, out.da.order)
    names = sorted(people)
    person = data.draw(st.sampled_from(names))
    truthful = rank_of(prefs, person, out.allocation.get(person))
    for report in all_reports(slots):
        lied = dict(prefs, **{person: report})
        result = gale_shapley_by_seats(names, lied, capacities, key)
        assert truthful <= rank_of(prefs, person, result.get(person)), (
            f"{person} gains by reporting {report}"
        )


@PROPERTY
@given(matching_cases(max_people=4, max_slots=3, with_priorities=True), st.data())
def test_the_script_itself_gives_nobody_a_gain_from_another_ranking(case, data):
    people, slots, prefs, capacities, priorities, source = case
    out = case_outcome(case)
    person = data.draw(st.sampled_from(sorted(people)))
    truthful = rank_of(prefs, person, out.allocation.get(person))
    for report in all_reports(slots):
        lied = dict(prefs, **{person: report})
        result = outcome(
            da_data(people, slots, lied, source, capacities=capacities, priorities=priorities)
        )
        assert truthful <= rank_of(prefs, person, result.allocation.get(person))


@PROPERTY
@given(matching_cases(with_priorities=True), st.randoms(use_true_random=False))
def test_the_result_does_not_depend_on_how_people_prefs_and_slots_are_listed(case, rnd):
    people, slots, prefs, capacities, priorities, source = case
    first = sl.solve(
        da_data(people, slots, prefs, source, capacities=capacities, priorities=priorities)
    )
    shuffled_people = rnd.sample(people, len(people))
    shuffled_prefs = {p: prefs[p] for p in rnd.sample(list(prefs), len(prefs))}
    second = sl.solve(
        da_data(
            shuffled_people,
            slots,
            shuffled_prefs,
            source,
            capacities=capacities,
            priorities={s: priorities[s] for s in rnd.sample(list(priorities), len(priorities))},
        )
    )
    assert fc.envelope(first) == fc.envelope(second)
    for fmt in ("md", "dm", "group"):
        assert fc.render(first, fmt) == fc.render(second, fmt)
    reordered = sl.solve(
        da_data(
            people,
            rnd.sample(slots, len(slots)),
            prefs,
            source,
            capacities=capacities,
            priorities=priorities,
        )
    )
    for key in ("allocation", "tie_break_order"):
        assert fc.envelope(reordered)["certificate"].get(
            key, fc.envelope(reordered)["result"].get(key)
        ) == (fc.envelope(first)["certificate"].get(key, fc.envelope(first)["result"].get(key)))


# ---------------------------------------------------------------------------------------
# The lottery that breaks ties
# ---------------------------------------------------------------------------------------


@PROPERTY
@given(matching_cases(with_priorities=True))
def test_the_lottery_order_is_the_shuffle_of_the_shared_mapping_with_the_rule_da_tiebreak_v1(case):
    people, _, _, capacities, _, source = case
    out = case_outcome(case)
    seats = sum(capacities.values())
    assert out.da.order == reference_order("da_tiebreak_v1", people, seats, source)
    assert out.draws[0].seed_hex == spec_seed("da_tiebreak_v1", people, seats, source).hex()
    assert out.draws[0].seed_hex != spec_seed("uniform_lottery_v1", people, seats, source).hex()
    assert out.order == out.da.order


def test_the_recorded_seed_and_order_of_the_classic_example():
    people = ["A", "B", "C", "D"]
    slots = ["a", "b", "c", "d"]
    prefs = {"A": list("abcd"), "B": list("abcd"), "C": list("badc"), "D": list("badc")}
    out = outcome(da_data(people, slots, prefs))
    assert (
        out.draws[0].seed_hex == "69d87eaedb703a44be9aea6020f54d9728c90983ab06951e0642e942cf5e19f7"
    )
    assert out.da.order == ["B", "C", "A", "D"]
    assert out.allocation == {"B": "a", "C": "b", "A": "c", "D": "d"}


@PROPERTY
@given(matching_cases(max_people=5, max_slots=3, max_capacity=1))
def test_with_everybody_tied_everywhere_and_one_seat_each_it_is_serial_dictatorship_in_that_order(
    case,
):
    people, slots, prefs, _, _, source = case
    out = outcome(da_data(people, slots, prefs, source))
    order = out.da.order
    assert out.allocation == lexicographic_best(order, prefs, slots)


@PROPERTY
@given(matching_cases(max_people=4, max_slots=3), st.data())
def test_with_a_strict_priority_order_at_every_slot_no_source_changes_the_result(case, data):
    people, slots, prefs, capacities, _, source = case
    priorities = {s: [[p] for p in data.draw(st.permutations(people))] for s in slots}
    other = data.draw(st.text(min_size=1, max_size=8).filter(lambda t: t.strip() and t != source))
    first = outcome(
        da_data(people, slots, prefs, source, capacities=capacities, priorities=priorities)
    )
    second = outcome(
        da_data(people, slots, prefs, other, capacities=capacities, priorities=priorities)
    )
    assert first.allocation == second.allocation


def test_with_strict_priorities_everywhere_no_source_matters():
    people = ["x", "y", "z", "w"]
    slots = ["a", "b"]
    prefs = {"x": ["a", "b"], "y": ["a", "b"], "z": ["b", "a"], "w": ["a"]}
    priorities = {
        "a": [["x"], ["y"], ["z"], ["w"]],
        "b": [["z"], ["x"], ["y"], ["w"]],
    }
    results = {
        json.dumps(
            outcome(da_data(people, slots, prefs, f"source {i}", priorities=priorities)).allocation,
            sort_keys=True,
        )
        for i in range(40)
    }
    assert len(results) == 1


def test_priority_tiers_beat_the_lottery_and_the_lottery_breaks_ties_inside_a_tier():
    people = ["m", "n", "o"]
    prefs = {p: ["z"] for p in people}
    first = outcome(da_data(people, ["z"], prefs, priorities={"z": [["n"], ["m", "o"]]}))
    assert first.allocation == {"n": "z"}
    tied = outcome(da_data(people, ["z"], prefs, priorities={"z": [["m", "n", "o"]]}))
    winner = next(iter(tied.allocation))
    assert winner == tied.da.order[0]


def test_the_lottery_is_uniform_in_a_tier_over_many_sources():
    """Three people tie for one seat: each wins about a third of 3000 fixed sources."""
    people = ["m", "n", "o"]
    prefs = {p: ["z"] for p in people}
    wins = collections.Counter()
    n = 3000
    for i in range(n):
        out = outcome(da_data(people, ["z"], prefs, source=f"da-tie-{i}"))
        wins.update(list(out.allocation))
    sd = (n * (1 / 3) * (2 / 3)) ** 0.5
    for person in people:
        assert abs(wins[person] - n / 3) / sd < 4.5, (person, wins[person])


# ---------------------------------------------------------------------------------------
# The rounds
# ---------------------------------------------------------------------------------------


@PROPERTY
@given(matching_cases(max_people=5, max_slots=3, with_priorities=True))
def test_replaying_the_printed_rounds_with_plain_rules_gives_the_result(case):
    people, _, prefs, capacities, priorities, _ = case
    out = case_outcome(case)
    rounds = fc.envelope(sl.solve(case_data(case)))["certificate"]["rounds"]
    key = reference_key(priorities, out.da.order)
    held = replay_rounds(sorted(people), prefs, capacities, key, rounds)
    assert {p: s for s, holders in held.items() for p in holders} == out.allocation


def test_a_ranking_longer_than_the_rounds_is_walked_slot_by_slot():
    people = ["a1", "a2", "a3"]
    prefs = {p: ["s1", "s2", "s3"] for p in people}
    priorities = {
        "s1": [["a1"], ["a2"], ["a3"]],
        "s2": [["a2"], ["a3"], ["a1"]],
        "s3": [["a3"], ["a1"], ["a2"]],
    }
    out = outcome(da_data(people, ["s1", "s2", "s3"], prefs, priorities=priorities))
    assert out.allocation == {"a1": "s1", "a2": "s2", "a3": "s3"}
    assert [len(r.proposals) for r in out.da.rounds] == [3, 2, 1]


def test_a_slot_that_does_not_list_a_person_turns_them_away_in_the_round_they_apply():
    people = ["p", "q"]
    out = outcome(
        da_data(people, ["s", "t"], {"p": ["s", "t"], "q": ["s"]}, priorities={"s": [["q"]]})
    )
    first = out.da.rounds[0]
    assert ("p", "s", "ineligible") in first.rejections
    assert out.allocation == {"q": "s", "p": "t"}


def test_a_person_who_lists_nothing_never_applies():
    out = outcome(da_data(["p", "q"], ["s"], {"p": [], "q": ["s"]}))
    assert out.allocation == {"q": "s"} and out.unassigned == ["p"]
    assert all("p" not in r.proposals for r in out.da.rounds)
    assert out.da.reasons["p"] == []


# ---------------------------------------------------------------------------------------
# What da does not promise
# ---------------------------------------------------------------------------------------


class TestNotPareto:
    def test_the_result_is_stable_and_x_and_z_would_both_prefer_to_swap(self):
        out = outcome(da_data(PEOPLE, SLOTS, PARETO_PREFS, priorities=PARETO_PRIORITIES))
        assert out.allocation == {"x": "b", "z": "a"} and out.unassigned == ["y"]
        key = reference_key(PARETO_PRIORITIES, out.da.order)
        got = assignment_of(out, PEOPLE)
        capacities = {s: 1 for s in SLOTS}
        assert blocking_pairs_by_definition(PEOPLE, SLOTS, capacities, PARETO_PREFS, key, got) == []
        better = pareto_improvement(PEOPLE, SLOTS, capacities, PARETO_PREFS, got)
        assert better == {"x": "a", "y": None, "z": "b"}
        assert better not in stable_assignments(PEOPLE, SLOTS, capacities, PARETO_PREFS, key)

    def test_the_swap_would_leave_y_with_a_claim_on_b_that_b_would_honour(self):
        capacities = {s: 1 for s in SLOTS}
        key = reference_key(PARETO_PRIORITIES, PEOPLE)
        swapped = {"x": "a", "y": None, "z": "b"}
        blocking = blocking_pairs_by_definition(
            PEOPLE, SLOTS, capacities, PARETO_PREFS, key, swapped
        )
        assert blocking == [("y", "b")], "y ranks above z at b and would be left with nothing"

    def test_serial_dictatorship_has_no_such_improvement_for_the_same_lists(self):
        capacities = {s: 1 for s in SLOTS}
        for order in (["x", "y", "z"], ["z", "x", "y"], ["y", "z", "x"]):
            best = lexicographic_best(order, PARETO_PREFS, SLOTS)
            got = {p: best.get(p) for p in PEOPLE}
            assert pareto_improvement(PEOPLE, SLOTS, capacities, PARETO_PREFS, got) is None


# ---------------------------------------------------------------------------------------
# People without a ranking, seats and limits
# ---------------------------------------------------------------------------------------


class TestNoRanking:
    def data(self, rule):
        prefs = {"p": ["x", "y"], "q": ["x"]}
        return da_data(
            ["p", "q", "r", "s"],
            ["x", "y", "z"],
            prefs,
            no_ranking=rule,
            capacities={"x": 1, "z": 2},
        )

    def test_forfeit_removes_them_before_the_draw(self):
        out = outcome(self.data("forfeit"))
        assert out.removed == ["r", "s"] and out.people == ["p", "q"]
        assert out.draws[0].members == ["p", "q"]

    def test_assigned_gives_them_what_is_left_in_slot_order_after_the_deferred_acceptance(self):
        out = outcome(self.data("assigned"))
        assert out.removed == [] and sorted(out.penalized) == ["r", "s"]
        assert out.draws[1].members == ["r", "s"] and out.draws[1].group == "penalty"
        main = {p: s for p, s in out.allocation.items() if p in out.people}
        taken = collections.Counter(main.values())
        free = [s for s in ["x", "y", "z"] for _ in range({"x": 1, "y": 1, "z": 2}[s] - taken[s])]
        for person, slot in zip(out.penalized, free):
            assert out.allocation[person] == slot
        assert out.order == out.da.order + out.penalized

    def test_messages_of_the_two_groups(self):
        messages = fc.render_dm_messages(sl.solve(self.data("assigned")))
        assert "拿剩下的时段" in messages["r"]
        messages = fc.render_dm_messages(sl.solve(self.data("forfeit")))
        assert "退出这次分配" in messages["r"]


class TestLimits:
    def test_more_people_than_the_limit_are_refused_naming_the_people(self):
        people = [f"p{i:03d}" for i in range(sl.MAX_DA_PEOPLE + 1)]
        done = run_json(da_data(people, ["s"], {p: ["s"] for p in people}))
        assert done.returncode == 2 and "people" in done.stderr

    def test_the_largest_allowed_instance_runs_and_has_no_blocking_pair(self):
        people = [f"p{i:03d}" for i in range(sl.MAX_DA_PEOPLE)]
        slots = [f"s{i:02d}" for i in range(20)]
        prefs = {p: slots[i % 20 :] + slots[: i % 20] for i, p in enumerate(people)}
        capacities = {s: 10 for s in slots}
        out = outcome(da_data(people, slots, prefs, capacities=capacities))
        key = reference_key({}, out.da.order)
        got = assignment_of(out, people)
        assert blocking_pairs_by_definition(people, slots, capacities, prefs, key, got) == []
        assert len(out.allocation) == 200


# ---------------------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------------------


class TestOutput:
    def data(self):
        return load_example("da_parking.json")

    def test_the_example_is_made_up_and_uses_the_method_da(self):
        data = self.data()
        assert data["rules"]["method"] == "da" and "priorities" in data and "capacities" in data
        assert "虚构示例" in (EXAMPLES / "da_parking.json").read_text(encoding="utf-8")

    def test_the_example_result_follows_from_the_priorities_and_the_lottery_order(self):
        out = outcome(self.data())
        assert out.da.order == ["Yuki", "老王", "阿明", "Coco", "小红", "大刘"]
        assert out.allocation == {
            "阿明": "充电车位",
            "Yuki": "地面车位",
            "老王": "地面车位",
            "Coco": "地下车位",
            "小红": "地下车位",
        }
        assert out.unassigned == ["大刘"]

    def test_a_private_message_names_nobody_else_and_holds_only_the_own_ranking(self):
        data = self.data()
        messages = fc.render_dm_messages(sl.solve(data))
        for person, text in messages.items():
            assert " > ".join(data["prefs"][person]) in text
            for other, ranking in data["prefs"].items():
                if other != person and len(other) > 1:
                    assert other not in text, f"{person}'s message names {other}"
                if " > ".join(ranking) not in " > ".join(data["prefs"][person]):
                    assert " > ".join(ranking) not in text

    def test_the_reasons_in_a_message_are_the_reasons_of_the_definitions(self):
        data = self.data()
        out = outcome(data)
        key = reference_key(data["priorities"], out.da.order)
        holders = collections.defaultdict(list)
        for person, slot in out.allocation.items():
            holders[slot].append(person)
        messages = fc.render_dm_messages(sl.solve(data))
        for person, text in messages.items():
            ranking = data["prefs"][person]
            got = out.allocation.get(person)
            better = ranking if got is None else ranking[: ranking.index(got)]
            for slot in better:
                mine = key(slot, person)
                if mine is None:
                    reason = "它不接受你"
                else:
                    worst = max(key(slot, h) for h in holders[slot])
                    reason = (
                        "优先级更高的人占满"
                        if worst[0] < mine[0]
                        else "同一档里抽签顺序在你之前的人占满"
                    )
                line = next(row for row in text.split("\n") if f"你更想要的「{slot}」" in row)
                assert reason in line, (person, slot, line)
            assert text.count("你更想要的") == len(better)

    def test_the_group_card_has_the_priorities_the_order_and_the_result_but_no_ranking(self):
        data = self.data()
        text = fc.render_group(sl.solve(data))
        assert (
            "抽签顺序（同档平局时靠前的人优先）：1 Yuki、2 老王、3 阿明、4 Coco、5 小红、6 大刘"
            in text
        )
        assert (
            "「充电车位」1 个名额，优先级：第 1 档：Coco、阿明；不接受：Yuki、大刘、小红、老王"
            in text
        )
        assert "阿明 分到「充电车位」" in text and "没分到：大刘" in text
        assert " > " not in text and "志愿顺序" not in text
        for name in data["people"]:
            assert name in text

    def test_the_md_output_has_the_result_the_slots_and_the_rounds(self):
        text = fc.render_md(sl.solve(self.data()))
        for needed in (
            "结果与理由（按抽签顺序）",
            "时段、优先级与结果",
            "申请过程",
            "da_tiebreak_v1",
            "不接受",
        ):
            assert needed in text, needed

    def test_the_json_certificate_has_the_rounds_the_reasons_and_the_stability_check(self):
        parsed = fc.envelope(sl.solve(self.data()))
        certificate = parsed["certificate"]
        assert certificate["stable"] is True and certificate["blocking_pairs"] == []
        assert certificate["tie_break_order"] == ["Yuki", "老王", "阿明", "Coco", "小红", "大刘"]
        assert [r["round"] for r in certificate["rounds"]] == [1, 2, 3]
        assert certificate["rounds"][0]["rejections"][1] == {
            "person": "小红",
            "slot": "充电车位",
            "reason": "ineligible",
        }
        assert certificate["why_not"]["小红"][0] == {"slot": "充电车位", "why": "ineligible"}
        assert parsed["result"]["method"] == "da" and parsed["result"]["rule"] == "da_tiebreak_v1"
        assert parsed["result"]["order"] == certificate["tie_break_order"]

    def test_english_says_the_same_in_english(self):
        result = sl.solve(self.data(), "en")
        text = fc.render_md(result, "en")
        assert "deferred acceptance" in text and "Slots, priorities and result" in text
        messages = fc.render_dm_messages(result)
        assert messages["小红"].startswith('You got "地下车位" (your choice number 3).')
        assert "it does not accept you" in messages["小红"]

    def test_every_format_and_language_renders(self):
        for flags in ([], ["--format", "dm"], ["--format", "group"], ["--json"], ["--lang", "en"]):
            done = run_json(self.data(), *flags)
            assert done.returncode == 0, done.stderr
            assert "Traceback" not in done.stdout + done.stderr


@pytest.mark.parametrize("extra_seats", [0, 1])
def test_feasible_assignments_helper_counts_what_it_should(extra_seats):
    """A sanity check of the reference search itself: one seat, two people who both list it."""
    prefs = {"p": ["s"], "q": ["s"]}

    def key(slot, person):
        return (0, 0)

    found = list(feasible_assignments(["p", "q"], ["s"], {"s": 1 + extra_seats}, prefs, key))
    assert len(found) == (3 if extra_seats == 0 else 4)
