"""Plan B, the split: the cheapest way to give out the chores within the caps and the cannot
lists, the rule that settles ties, and the detection of inputs that have no way."""

from __future__ import annotations

import itertools
import random
import re
import time
from typing import ClassVar

import chore_split as cs
import fsq_core as fc
import pytest
from bundle_reference import (
    bundle_cases,
    cheapest_by_brute_force,
    unit_list,
)
from chore_reference import spec_order, spec_seed
from chore_support import (
    BUNDLE_SOURCE,
    CHORES6,
    PEOPLE3,
    PROPERTY,
    SOURCE,
    bundle_data,
    price_data,
    run_json,
)
from hypothesis import given
from hypothesis import strategies as st

BUNDLE_RULE = "chore_bundle_tiebreak_v1"


def problem_of(data):
    return cs.parse_problem(data)


def plan_of(data):
    return cs.compute(cs.parse_problem(data))


def tie_order(problem):
    """The order in which the tie rule prefers people: sorted names, or the seeded order."""
    if problem.source is None:
        return sorted(problem.people)
    seed = spec_seed(problem.people, problem.total_units, problem.source, BUNDLE_RULE)
    return spec_order(seed, problem.people)


def brute(problem):
    return cheapest_by_brute_force(
        tie_order(problem), problem.units_of, problem.costs, problem.caps
    )


def split_from_plan(plan):
    return frozenset((p, tuple(sorted(plan.bundles[p]))) for p in plan.people)


class TestHungarianMethod:
    """The assignment step alone, on integer matrices."""

    @PROPERTY
    @given(
        st.integers(1, 4).flatmap(
            lambda rows: st.integers(rows, 5).flatmap(
                lambda cols: st.lists(
                    st.lists(st.integers(0, 9), min_size=cols, max_size=cols),
                    min_size=rows,
                    max_size=rows,
                )
            )
        )
    )
    def test_hungarian_method_equals_brute_force_on_random_matrices(self, matrix):
        rows, cols = len(matrix), len(matrix[0])
        chosen = cs.hungarian(matrix)
        assert len(set(chosen)) == rows and all(0 <= c < cols for c in chosen)
        got = sum(matrix[r][c] for r, c in enumerate(chosen))
        best = min(
            sum(matrix[r][c] for r, c in enumerate(pick))
            for pick in itertools.permutations(range(cols), rows)
        )
        assert got == best

    def test_negative_and_large_entries_are_fine(self):
        matrix = [[-5, 10**30, 3], [10**30, -7, 2]]
        chosen = cs.hungarian(matrix)
        assert sum(matrix[r][c] for r, c in enumerate(chosen)) == -12


class TestCheapestSplit:
    @PROPERTY
    @given(bundle_cases())
    def test_the_smallest_total_cost_equals_brute_force(self, data):
        problem = problem_of(data)
        found = brute(problem)
        if found is None:
            return
        assert plan_of(data).total_cost == found[0]

    @PROPERTY
    @given(bundle_cases())
    def test_a_way_exists_exactly_when_brute_force_finds_one(self, data):
        problem = problem_of(data)
        if brute(problem) is None:
            with pytest.raises(fc.NoSolution):
                cs.compute(problem)
        else:
            assert cs.compute(problem).total_cost >= 0

    def test_a_seeded_sweep_sees_both_kinds_of_case(self):
        rng = random.Random(20261101)
        feasible = infeasible = 0
        for _ in range(300):
            people = ["p0", "p1", "p2"]
            chores = ["c0", "c1", "c2", "c3"]
            cannot = {p: [c for c in chores if rng.random() < 0.2] for p in people}
            costs = {
                p: {c: rng.randint(0, 5) for c in chores if c not in cannot[p]} for p in people
            }
            caps = {p: rng.randint(0, 3) for p in people}
            data = bundle_data(
                people, chores, costs, caps, cannot={p: c for p, c in cannot.items() if c}
            )
            problem = problem_of(data)
            found = brute(problem)
            try:
                plan = cs.compute(problem)
            except fc.NoSolution:
                assert found is None
                infeasible += 1
                continue
            assert found is not None and plan.total_cost == found[0]
            feasible += 1
        assert feasible > 50 and infeasible > 20

    @PROPERTY
    @given(bundle_cases())
    def test_every_unit_is_given_out_once_within_the_caps_and_the_cannot_lists(self, data):
        problem = problem_of(data)
        if brute(problem) is None:
            return
        plan = cs.compute(problem)
        given_out = sorted(c for bundle in plan.bundles.values() for c in bundle)
        assert given_out == unit_list(problem.units_of)
        for person, bundle in plan.bundles.items():
            assert len(bundle) <= problem.caps[person]
            assert all(c in problem.costs[person] for c in bundle)

    @PROPERTY
    @given(bundle_cases())
    def test_the_split_is_the_first_cheapest_one_in_the_order_of_the_tie_rule(self, data):
        problem = problem_of(data)
        found = brute(problem)
        if found is None:
            return
        assert split_from_plan(cs.compute(problem)) == found[1]

    @PROPERTY
    @given(bundle_cases(), st.text(min_size=1, max_size=8).filter(lambda s: s.strip() != ""))
    def test_with_a_public_source_the_first_cheapest_split_follows_the_drawn_order(
        self, data, source
    ):
        data["rules"]["random_source"] = source
        try:
            problem = problem_of(data)
        except fc.InputError:
            return  # a source that the script refuses, such as an unpaired surrogate
        found = brute(problem)
        if found is None:
            return
        plan = cs.compute(problem)
        assert plan.priority == tie_order(problem)
        assert split_from_plan(plan) == found[1]

    @PROPERTY
    @given(bundle_cases())
    def test_the_script_says_there_was_a_tie_exactly_when_brute_force_finds_two_splits(self, data):
        problem = problem_of(data)
        found = brute(problem)
        if found is None:
            return
        assert cs.compute(problem).was_tie == (found[2] > 1)

    def test_the_recorded_example_has_exactly_two_cheapest_splits(self):
        problem = problem_of(price_data())
        total, _, count = brute(problem)
        assert (total, count) == (13500, 2)
        assert cs.compute(problem).was_tie

    def test_units_of_one_chore_swapped_between_people_are_one_split(self):
        data = bundle_data(
            ["A", "B"],
            ["dishes"],
            {"A": {"dishes": 4}, "B": {"dishes": 4}},
            {"A": 3, "B": 3},
            units={"dishes": 3},
        )
        total, _, count = brute(problem_of(data))
        assert total == 1200
        assert count == 4  # 3 and 0, 2 and 1, 1 and 2, 0 and 3
        assert cs.compute(problem_of(data)).was_tie

    def test_a_unique_cheapest_split_is_not_a_tie(self):
        plan = plan_of(price_data(table={**_UNIQUE_PRICES}))
        assert not plan.was_tie

    @PROPERTY
    @given(bundle_cases(), st.randoms(use_true_random=False))
    def test_the_split_does_not_depend_on_the_order_the_input_is_listed_in(self, data, shuffler):
        problem = problem_of(data)
        if brute(problem) is None:
            return
        before = cs.compute(problem)
        data["people"] = _shuffled(shuffler, data["people"])
        data["chores"] = _shuffled(shuffler, data["chores"])
        data["costs"] = {
            p: dict(_shuffled(shuffler, list(row.items()))) for p, row in data["costs"].items()
        }
        after = cs.compute(problem_of(data))
        assert after.bundles == before.bundles
        assert after.transfer == before.transfer


_UNIQUE_PRICES = {
    "阿明": [31, 5, 22, 61, 41, 26],
    "小红": [21, 11, 26, 51, 71, 19],
    "大刘": [36, 16, 11, 41, 29, 46],
}


def _shuffled(shuffler, items):
    items = list(items)
    shuffler.shuffle(items)
    return items


class TestTheTieRule:
    """In the recorded example two splits cost 135. Which one is taken follows the rule."""

    SPLIT_A: ClassVar[dict] = {
        "阿明": ["倒垃圾", "拖地"],
        "小红": ["擦窗", "洗碗"],
        "大刘": ["做饭", "刷厕所"],
    }
    SPLIT_B: ClassVar[dict] = {
        "阿明": ["倒垃圾", "做饭"],
        "小红": ["擦窗", "洗碗"],
        "大刘": ["刷厕所", "拖地"],
    }

    @staticmethod
    def sorted_bundles(plan):
        return {p: sorted(b) for p, b in plan.bundles.items()}

    def test_without_a_source_the_names_decide_and_the_first_split_is_taken(self):
        plan = plan_of(price_data())
        assert self.sorted_bundles(plan) == {p: sorted(b) for p, b in self.SPLIT_A.items()}
        assert plan.priority == sorted(PEOPLE3)
        assert plan.seed_hex is None and plan.preimage is None

    def test_with_the_source_of_the_example_the_drawn_order_gives_the_same_split(self):
        plan = plan_of(price_data(source=BUNDLE_SOURCE))
        assert self.sorted_bundles(plan) == {p: sorted(b) for p, b in self.SPLIT_A.items()}
        assert plan.priority == ["大刘", "阿明", "小红"]

    def test_another_source_can_give_the_other_split(self):
        plan = plan_of(price_data(source=SOURCE))
        assert self.sorted_bundles(plan) == {p: sorted(b) for p, b in self.SPLIT_B.items()}
        assert plan.priority == ["小红", "阿明", "大刘"]

    def test_the_seed_and_order_equal_an_independent_computation(self):
        for source in (BUNDLE_SOURCE, SOURCE):
            plan = plan_of(price_data(source=source))
            seed = spec_seed(PEOPLE3, 6, source, BUNDLE_RULE)
            assert plan.seed_hex == seed.hex()
            assert plan.priority == spec_order(seed, PEOPLE3)

    def test_the_rule_name_and_the_preimage_are_the_documented_ones(self):
        plan = plan_of(price_data(source=BUNDLE_SOURCE))
        assert cs.BUNDLE_RULE_NAME == BUNDLE_RULE
        assert (
            fc.canonical_json(
                {
                    "n_slots": 6,
                    "participants": sorted(PEOPLE3),
                    "rule": BUNDLE_RULE,
                    "source": BUNDLE_SOURCE,
                }
            )
            == plan.preimage
        )

    def test_the_rule_name_is_not_the_one_of_plan_a(self):
        assert cs.BUNDLE_RULE_NAME != cs.RULE_NAME

    def test_a_source_changes_nothing_when_one_split_is_cheapest(self):
        plain = plan_of(price_data(table=_UNIQUE_PRICES))
        for source in (BUNDLE_SOURCE, SOURCE, "x"):
            seeded = plan_of(price_data(table=_UNIQUE_PRICES, source=source))
            assert seeded.bundles == plain.bundles and seeded.transfer == plain.transfer

    def test_the_tie_order_never_changes_the_total_cost(self):
        totals = {plan_of(price_data(source=s)).total_cost for s in (None, BUNDLE_SOURCE, SOURCE)}
        assert totals == {13500}


class TestNoWayToShareOut:
    def test_a_chore_that_nobody_can_do_exits_3_with_the_message_of_plan_a(self):
        data = price_data(cannot={p: ["做饭"] for p in PEOPLE3})
        for p in PEOPLE3:
            del data["costs"][p]["做饭"]
        done = run_json(data)
        assert done.returncode == 3 and done.stdout == ""
        assert "nobody can do the chore '做饭'" in done.stderr

    def test_caps_that_add_up_to_less_than_the_units_exit_3_and_name_the_numbers(self):
        data = price_data(cap=1)
        done = run_json(data)
        assert done.returncode == 3 and done.stdout == ""
        assert done.stderr.startswith("no solution: there is no way to share out all the chores")
        assert re.search(r"\(\d+ units in all\)", done.stderr)
        assert "whose caps add up to 3" in done.stderr

    def test_the_message_names_the_chores_that_only_few_people_can_do(self):
        costs = {
            "A": {"x": 1, "y": 1, "z": 1, "w": 1},
            "B": {"x": 1, "y": 1, "z": 1, "w": 1},
            "C": {"w": 1},
        }
        data = bundle_data(
            ["A", "B", "C"],
            ["x", "y", "z", "w"],
            costs,
            {"A": 1, "B": 1, "C": 4},
            cannot={"C": ["x", "y", "z"]},
        )
        # w can go to C, but x, y and z can only go to A and B, who take two units between them
        done = run_json(data)
        assert done.returncode == 3
        message = done.stderr
        assert "'x', 'y', 'z' (3 units in all)" in message
        assert "can be done only by A, B" in message
        assert "whose caps add up to 2" in message

    @PROPERTY
    @given(bundle_cases())
    def test_the_named_chores_really_cannot_be_covered(self, data):
        problem = problem_of(data)
        if brute(problem) is not None:
            return
        with pytest.raises(fc.NoSolution) as caught:
            cs.compute(problem)
        message = str(caught.value)
        if message.startswith("nobody can do"):
            return
        found = re.fullmatch(
            r"there is no way to share out all the chores: (.+) \((\d+) units in all\) "
            r"can be done only by (.+), whose caps add up to (\d+)\. .*",
            message,
        )
        assert found, message
        chores = {c.strip("'") for c in found.group(1).split(", ")}
        doers = found.group(3).split(", ")
        units = sum(problem.units_of[c] for c in chores)
        assert units == int(found.group(2))
        assert set(doers) == {p for p in problem.people if chores & set(problem.costs[p])}
        assert sum(min(problem.caps[p], problem.total_units) for p in doers) == int(found.group(4))
        assert int(found.group(4)) < units

    def test_a_cap_of_zero_for_everybody_who_can_do_a_chore_has_no_way(self):
        data = bundle_data(
            ["A", "B"],
            ["x", "y"],
            {"A": {"x": 1, "y": 1}, "B": {"x": 1}},
            {"A": 1, "B": 0},
            cannot={"B": ["y"]},
        )
        done = run_json(data)
        assert done.returncode == 3
        assert "can be done only by A, B" in done.stderr or "caps add up to 1" in done.stderr


class TestCapsAndLimits:
    def test_a_cap_above_the_number_of_units_means_no_cap(self):
        base = price_data()
        loose = price_data(cap=6)
        very_loose = price_data(cap=cs.MAX_TOTAL_UNITS)
        assert plan_of(loose).bundles == plan_of(very_loose).bundles
        assert plan_of(loose).total_cost <= plan_of(base).total_cost

    def test_without_a_cap_that_binds_everything_goes_to_the_person_who_minds_least(self):
        data = bundle_data(
            ["A", "B"],
            ["x", "y"],
            {"A": {"x": 1, "y": 1}, "B": {"x": 5, "y": 5}},
            {"A": 2, "B": 2},
        )
        plan = plan_of(data)
        assert sorted(plan.bundles["A"]) == ["x", "y"] and plan.bundles["B"] == []

    def test_a_person_with_a_cap_of_zero_does_no_chore(self):
        data = bundle_data(
            ["A", "B", "C"],
            ["x", "y"],
            {p: {"x": 3, "y": 4} for p in "ABC"},
            {"A": 0, "B": 1, "C": 1},
        )
        plan = plan_of(data)
        assert plan.bundles["A"] == []
        assert plan.total_cost == 700

    def test_the_largest_input_is_answered_quickly(self):
        people = [f"p{i}" for i in range(cs.MAX_PEOPLE)]
        chores = [f"c{i}" for i in range(cs.MAX_CHORES)]
        rng = random.Random(1)
        costs = {p: {c: rng.randint(0, 50) for c in chores} for p in people}
        data = bundle_data(
            people,
            chores,
            costs,
            {p: cs.MAX_TOTAL_UNITS for p in people},
            units={c: 3 for c in chores},
        )
        started = time.monotonic()
        plan = plan_of(data)
        assert time.monotonic() - started < 60
        assert sum(len(b) for b in plan.bundles.values()) == cs.MAX_TOTAL_UNITS

    def test_chore_names_are_taken_in_code_point_order_for_the_tie_rule(self):
        data = bundle_data(
            ["A", "B"],
            ["b", "a"],
            {"A": {"a": 1, "b": 1}, "B": {"a": 1, "b": 1}},
            {"A": 1, "B": 1},
        )
        plan = plan_of(data)
        assert plan.bundles == {"A": ["a"], "B": ["b"]}  # a is given out first, to A

    def test_the_helper_that_lists_units_follows_the_names(self):
        problem = problem_of(price_data())
        assert cs.unit_chores(problem) == unit_list(problem.units_of)
        assert cs.unit_chores(problem) == sorted(CHORES6)
