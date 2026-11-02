"""Plan B, the money: payments that add up to zero, leave nobody envying a bundle they can take,
and make the worst-off person as well off as possible. Also the cases in which the guarantee
stops, and the rent-split kernel that does the arithmetic."""

from __future__ import annotations

import ast
import importlib.util
import inspect
import itertools
import json
import random
import sys
import textwrap
from collections import Counter
from fractions import Fraction

import chore_split as cs
import fsq_core as fc
import pytest
from bundle_reference import (
    bundle_cases,
    cheapest_by_brute_force,
    exact_envy,
    lp_best_worst_off,
    reference_cost_table,
    unit_list,
)
from chore_support import (
    BUNDLE_SOURCE,
    CHORES6,
    HARD3,
    PEOPLE3,
    PROPERTY,
    REPO_ROOT,
    bundle_data,
    price_data,
    run_json,
    table_costs,
)
from hypothesis import given


def plan_of(data):
    return cs.compute(cs.parse_problem(data))


def reference_table(plan):
    """The cost to every person of every bundle, worked out again from the input."""
    problem = plan.problem
    split = frozenset((p, tuple(plan.bundles[p])) for p in plan.people)
    return reference_cost_table(split, problem.costs, problem.caps)


def exact_nets(plan):
    return {p: plan.exact_transfer[p] - plan.cost[p] for p in plan.people}


def feasible(data):
    """True when some way to give out the chores exists (for the sizes used here)."""
    problem = cs.parse_problem(data)
    people = sorted(problem.people)
    return cheapest_by_brute_force(people, problem.units_of, problem.costs, problem.caps)


_RENT_SPLIT_NAME = "rent_split_for_the_chore_tests"


def load_rent_split():
    """The script of rent-split, loaded from its file without leaving bytecode behind."""
    if _RENT_SPLIT_NAME in sys.modules:
        return sys.modules[_RENT_SPLIT_NAME]
    path = REPO_ROOT / "plugin" / "skills" / "rent-split" / "scripts" / "rent_split.py"
    spec = importlib.util.spec_from_file_location(_RENT_SPLIT_NAME, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[_RENT_SPLIT_NAME] = module  # dataclasses look their module up by name
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[_RENT_SPLIT_NAME]
        raise
    finally:
        sys.dont_write_bytecode = previous
    return module


class TestRecordedExample:
    """Three roommates, six chores, two each. Two splits cost 135 and both leave -45.00 each."""

    def test_the_payments_of_the_recorded_example(self):
        plan = plan_of(price_data())
        assert plan.total_cost == 13500
        assert plan.cost == {"阿明": 2500, "小红": 4000, "大刘": 7000}
        assert plan.transfer == {"阿明": -2000, "小红": -500, "大刘": 2500}
        assert plan.net == {"阿明": -4500, "小红": -4500, "大刘": -4500}
        assert plan.max_envy == 0

    def test_with_the_source_of_the_example_the_same_split_is_taken(self):
        plan = plan_of(price_data(source=BUNDLE_SOURCE))
        assert plan.transfer == {"阿明": -2000, "小红": -500, "大刘": 2500}

    def test_the_other_cheapest_split_also_leaves_everybody_at_minus_45(self):
        problem = cs.parse_problem(price_data())
        other = {"阿明": ["倒垃圾", "做饭"], "小红": ["擦窗", "洗碗"], "大刘": ["刷厕所", "拖地"]}
        cost_of, _, exact = cs.settle_exactly(problem, other)
        assert {p: exact[p] for p in other} == {"阿明": 0, "小红": -500, "大刘": 500}
        assert {p: exact[p] - cost_of[p][p] for p in other} == dict.fromkeys(other, -4500)

    def test_each_person_is_at_the_average_of_the_total_cost(self):
        plan = plan_of(price_data())
        assert set(exact_nets(plan).values()) == {Fraction(-plan.total_cost, 3)}

    def test_the_command_line_prints_the_same_numbers(self):
        done = run_json(price_data(), "--json")
        result = json.loads(done.stdout)["result"]
        assert result["transfer_cents"] == {"阿明": "-20.00", "小红": "-5.00", "大刘": "25.00"}
        assert result["net_cents"] == dict.fromkeys(PEOPLE3, "-45.00")
        assert result["total_cost_cents"] == "135.00"
        assert result["paid_in_cents"] == result["taken_out_cents"] == "25.00"


class TestThePayments:
    @PROPERTY
    @given(bundle_cases())
    def test_the_payments_add_up_to_zero_exactly_and_after_rounding(self, data):
        if not feasible(data):
            return
        plan = plan_of(data)
        assert sum(plan.transfer.values()) == 0
        assert sum(plan.exact_transfer.values()) == 0
        assert sum(plan.net.values()) == -plan.total_cost

    @PROPERTY
    @given(bundle_cases())
    def test_nobody_envies_a_bundle_they_can_take_in_exact_arithmetic(self, data):
        if not feasible(data):
            return
        plan = plan_of(data)
        assert exact_envy(reference_table(plan), plan.exact_transfer) <= 0

    @PROPERTY
    @given(bundle_cases())
    def test_after_rounding_the_largest_envy_is_at_most_one_cent(self, data):
        if not feasible(data):
            return
        plan = plan_of(data)
        envy = exact_envy(reference_table(plan), {p: Fraction(t) for p, t in plan.transfer.items()})
        assert envy == plan.max_envy and 0 <= envy <= 1

    @PROPERTY
    @given(bundle_cases(max_people=5, max_chores=3, max_units=1))
    def test_each_rounded_payment_is_within_one_cent_of_the_exact_one(self, data):
        if not feasible(data):
            return
        plan = plan_of(data)
        for p in plan.people:
            assert abs(plan.exact_transfer[p] - plan.transfer[p]) < 1

    @PROPERTY
    @given(bundle_cases())
    def test_a_net_is_the_payment_minus_the_cost_of_the_own_bundle(self, data):
        if not feasible(data):
            return
        plan = plan_of(data)
        table = reference_table(plan)
        for p in plan.people:
            assert plan.cost[p] == table[p][p]
            assert plan.net[p] == plan.transfer[p] - table[p][p]
            assert plan.shares[p][p] == plan.net[p]

    def test_with_more_than_eight_people_the_rounding_still_adds_up_and_leaves_one_cent(self):
        rng = random.Random(4)
        for _ in range(4):
            people = [f"p{i}" for i in range(10)]
            chores = [f"c{i}" for i in range(10)]
            costs = {p: {c: Fraction(rng.randint(0, 5000), 100) for c in chores} for p in people}
            data = bundle_data(
                people, chores, costs, {p: 2 for p in people}, source="a public draw"
            )
            plan = plan_of(data)
            assert sum(plan.transfer.values()) == 0
            assert plan.max_envy <= 1
            envy = exact_envy(
                reference_table(plan), {p: Fraction(t) for p, t in plan.transfer.items()}
            )
            assert envy == plan.max_envy
            assert exact_envy(reference_table(plan), plan.exact_transfer) <= 0


class TestTheWorstOffPerson:
    @PROPERTY
    @given(bundle_cases())
    def test_the_worst_off_person_is_as_well_off_as_a_linear_program_allows(self, data):
        if not feasible(data):
            return
        plan = plan_of(data)
        best = lp_best_worst_off(reference_table(plan))
        assert abs(best - float(min(exact_nets(plan).values()))) < 1e-6

    @PROPERTY
    @given(bundle_cases(with_cannot=False, uniform_cap=True))
    def test_the_money_equals_rent_split_with_a_total_rent_of_zero(self, data):
        plan = plan_of(data)
        rent = load_rent_split()
        people = plan.people
        values = [[Fraction(-plan.cost_of[i][k]) for k in people] for i in people]
        solved = rent.solve_exact(values, Fraction(0), "allow")
        assert sorted(solved.utilities) == sorted(exact_nets(plan).values())

    def test_the_two_functions_of_the_kernel_are_those_of_rent_split(self):
        rent = load_rent_split()
        for name in ("shortest_paths", "maximin_utilities"):
            ours = ast.dump(ast.parse(textwrap.dedent(inspect.getsource(getattr(cs, name)))))
            theirs = ast.dump(ast.parse(textwrap.dedent(inspect.getsource(getattr(rent, name)))))
            assert ours == theirs, name

    def test_the_kernel_works_with_a_rent_of_zero_on_a_hand_computed_case(self):
        # Two people and two bundles, A holding the first and B the second. A values the first
        # at 0 and the second at -10, B values them at -4 and 0. Going by the edges of the
        # envy graph, A may be at most 10 above B and B at most 4 above A. Nobody has to be
        # compensated, because the total value is 0 and splitting it evenly meets both bounds.
        values = [[Fraction(0), Fraction(-10)], [Fraction(-4), Fraction(0)]]
        dist = cs.shortest_paths(values, [0, 1])
        assert cs.maximin_utilities(dist, Fraction(0)) == [0, 0]

    @PROPERTY
    @given(bundle_cases(with_cannot=False, uniform_cap=True, always_feasible=False))
    def test_with_the_same_cap_for_everybody_every_bundle_can_be_taken_by_everybody(self, data):
        plan = plan_of(data)
        assert all(c is not None for row in plan.cost_of.values() for c in row.values())


class TestBundlesNobodyCanTake:
    def test_a_bundle_over_the_cap_is_left_out_of_the_comparison(self):
        data = bundle_data(
            ["A", "B"],
            ["x", "y", "z"],
            {"A": {"x": 1, "y": 1, "z": 1}, "B": {"x": 5, "y": 5, "z": 5}},
            {"A": 1, "B": 3},
        )
        plan = plan_of(data)
        assert plan.bundles["A"] == ["x"] and plan.bundles["B"] == ["y", "z"]
        assert plan.shares["A"]["B"] is None  # two units, over the cap of A
        assert plan.shares["B"]["A"] is not None
        assert (
            abs(lp_best_worst_off(reference_table(plan)) - float(min(exact_nets(plan).values())))
            < 1e-6
        )

    def test_the_cap_changes_the_money_because_it_changes_who_envies_what(self):
        base = bundle_data(
            ["A", "B"],
            ["x", "y", "z"],
            {"A": {"x": 1, "y": 1, "z": 1}, "B": {"x": 5, "y": 5, "z": 5}},
            {"A": 3, "B": 3},
        )
        capped = bundle_data(
            ["A", "B"],
            ["x", "y", "z"],
            {"A": {"x": 1, "y": 1, "z": 1}, "B": {"x": 5, "y": 5, "z": 5}},
            {"A": 1, "B": 3},
        )
        assert plan_of(base).total_cost < plan_of(capped).total_cost

    def test_a_bundle_with_a_chore_the_person_cannot_do_is_left_out(self):
        data = bundle_data(
            ["A", "B"],
            ["x", "y"],
            {"A": {"x": 1, "y": 9}, "B": {"x": 9}},
            {"A": 2, "B": 2},
            cannot={"B": ["y"]},
        )
        plan = plan_of(data)
        assert plan.bundles == {"A": ["x", "y"], "B": []}  # only A can do y, and x is cheaper for A
        assert plan.shares["B"]["A"] is None  # the bundle of A holds y, which B cannot do
        assert plan.shares["A"]["B"] is not None  # the empty bundle can be taken by anybody
        best = lp_best_worst_off(reference_table(plan))
        assert abs(best - float(min(exact_nets(plan).values()))) < 1e-6

    def test_the_uneven_example_leaves_the_person_with_one_unit_out_of_every_big_bundle(self):
        data = json.loads(
            (REPO_ROOT / "plugin/skills/chore-split/examples/bundle_uneven_caps.json").read_text(
                encoding="utf-8"
            )
        )
        plan = plan_of(data)
        assert plan.bundles["小红"] == ["洗碗"]
        assert all(plan.shares["小红"][h] is None for h in plan.people if h != "小红")


class TestEnvyFreePaymentsExist:
    @PROPERTY
    @given(bundle_cases(max_people=4, max_chores=3, max_units=2))
    def test_a_cheapest_split_always_has_envy_free_payments_even_with_uneven_caps(self, data):
        if not feasible(data):
            return
        # compute() raises when the payments cannot be found, or leave envy
        plan = plan_of(data)
        assert plan.max_envy <= 1

    def test_a_split_with_a_cheaper_rearrangement_of_whole_bundles_has_no_payments(self):
        data = bundle_data(
            ["A", "B"],
            ["x", "y"],
            {"A": {"x": 1, "y": 10}, "B": {"x": 10, "y": 1}},
            {"A": 1, "B": 1},
        )
        problem = cs.parse_problem(data)
        _, _, exact = cs.settle_exactly(problem, {"A": ["x"], "B": ["y"]})
        assert exact == {"A": Fraction(0), "B": Fraction(0)}
        with pytest.raises(ValueError):
            cs.settle_exactly(problem, {"A": ["y"], "B": ["x"]})

    def test_a_dearer_split_is_not_necessarily_open_to_payments(self):
        problem = cs.parse_problem(price_data())
        worse = {"阿明": ["洗碗", "刷厕所"], "小红": ["倒垃圾", "做饭"], "大刘": ["拖地", "擦窗"]}
        with pytest.raises(ValueError):
            cs.settle_exactly(problem, worse)


class TestWhenEveryNetIsEqual:
    @PROPERTY
    @given(bundle_cases(max_people=3, max_chores=3, max_units=2, top_cost=4))
    def test_when_every_net_is_equal_no_split_does_better_for_the_worst_off_person(self, data):
        found = feasible(data)
        if not found:
            return
        plan = plan_of(data)
        nets = exact_nets(plan)
        if len(set(nets.values())) != 1:
            return
        n = len(plan.people)
        level = next(iter(nets.values()))
        assert level == Fraction(-plan.total_cost, n)
        problem = plan.problem
        units = unit_list(problem.units_of)
        people = sorted(problem.people)
        for owners in itertools.product(people, repeat=len(units)):
            counts = Counter(owners)
            if any(counts[p] > problem.caps[p] for p in people):
                continue
            if any(c not in problem.costs[o] for c, o in zip(units, owners)):
                continue
            total = sum(problem.costs[o][c] for c, o in zip(units, owners))
            # with any payments that add up to zero the smallest net is at most the average
            assert Fraction(-total, n) <= level

    def test_the_recorded_example_is_such_a_case(self):
        plan = plan_of(price_data())
        assert len(set(exact_nets(plan).values())) == 1


class TestADearerSplitCanBeBetterForTheWorstOff:
    """The guarantee is for the cheapest split, not for the best split. These are the numbers."""

    def hard_plan(self):
        return plan_of(bundle_data(PEOPLE3, CHORES6, table_costs(HARD3), {p: 2 for p in PEOPLE3}))

    def test_the_cheapest_split_costs_38_and_leaves_the_worst_off_at_minus_55_over_3(self):
        plan = self.hard_plan()
        assert plan.total_cost == 3800
        nets = exact_nets(plan)
        assert min(nets.values()) == Fraction(-5500, 3)
        assert sorted(nets.values()) == [Fraction(-5500, 3), Fraction(-5500, 3), Fraction(-400, 3)]
        assert {p: sorted(b) for p, b in plan.bundles.items()} == {
            "阿明": ["拖地", "擦窗"],
            "小红": ["倒垃圾", "刷厕所"],
            "大刘": ["做饭", "洗碗"],
        }

    def test_after_rounding_the_cents_of_the_two_worst_off_are_18_33_and_18_34(self):
        plan = self.hard_plan()
        assert sorted(plan.net.values()) == [-1834, -1833, -133]
        assert sum(plan.net.values()) == -3800
        assert fc.fmt_cents(min(plan.net.values())) == "-18.34"

    def test_the_json_gives_the_exact_value_of_the_worst_off_person(self):
        done = run_json(
            bundle_data(PEOPLE3, CHORES6, table_costs(HARD3), {p: 2 for p in PEOPLE3}), "--json"
        )
        exact = json.loads(done.stdout)["result"]["exact_net"]
        assert sorted(exact.values()) == ["-4/3", "-55/3", "-55/3"]

    def test_another_split_with_total_cost_41_leaves_everybody_at_minus_41_over_3(self):
        problem = cs.parse_problem(
            bundle_data(PEOPLE3, CHORES6, table_costs(HARD3), {p: 2 for p in PEOPLE3})
        )
        other = {"阿明": ["拖地", "做饭"], "小红": ["倒垃圾", "刷厕所"], "大刘": ["洗碗", "擦窗"]}
        cost_of, _, exact = cs.settle_exactly(problem, other)
        assert sum(cost_of[p][p] for p in other) == 4100
        nets = {p: exact[p] - cost_of[p][p] for p in other}
        assert set(nets.values()) == {Fraction(-4100, 3)}
        table = {p: dict(row) for p, row in cost_of.items()}
        assert abs(lp_best_worst_off(table) - float(Fraction(-4100, 3))) < 1e-6

    def test_it_is_the_best_of_all_90_splits_into_pairs_that_have_envy_free_payments(self):
        problem = cs.parse_problem(
            bundle_data(PEOPLE3, CHORES6, table_costs(HARD3), {p: 2 for p in PEOPLE3})
        )
        results = []
        for owners in itertools.product(PEOPLE3, repeat=6):
            if any(owners.count(p) != 2 for p in PEOPLE3):
                continue
            bundles = {p: [c for c, o in zip(CHORES6, owners) if o == p] for p in PEOPLE3}
            try:
                cost_of, _, exact = cs.settle_exactly(problem, bundles)
            except ValueError:
                continue
            nets = [exact[p] - cost_of[p][p] for p in PEOPLE3]
            results.append((min(nets), sum(cost_of[p][p] for p in PEOPLE3)))
        assert len(results) == 15
        best = max(results)
        assert best == (Fraction(-4100, 3), 4100)
        cheapest = min(results, key=lambda r: r[1])
        assert cheapest == (Fraction(-5500, 3), 3800)
        assert best[0] > cheapest[0]

    def test_in_a_seeded_sweep_a_better_split_exists_in_some_cases_and_never_in_others(self):
        rng = random.Random(8)
        better = same = 0
        for _ in range(60):
            table = {p: [rng.randint(0, 30) for _ in CHORES6] for p in PEOPLE3}
            data = bundle_data(PEOPLE3, CHORES6, table_costs(table), {p: 2 for p in PEOPLE3})
            problem = cs.parse_problem(data)
            plan = cs.compute(problem)
            cheapest = min(exact_nets(plan).values())
            best = cheapest
            for owners in itertools.product(PEOPLE3, repeat=6):
                if any(owners.count(p) != 2 for p in PEOPLE3):
                    continue
                bundles = {p: [c for c, o in zip(CHORES6, owners) if o == p] for p in PEOPLE3}
                try:
                    cost_of, _, exact = cs.settle_exactly(problem, bundles)
                except ValueError:
                    continue
                best = max(best, min(exact[p] - cost_of[p][p] for p in PEOPLE3))
            if best > cheapest:
                better += 1
            else:
                same += 1
        assert better > 0 and same > 0
        assert better + same == 60


class TestNotStrategyProof:
    """A person who exaggerates a cost can end up better off by their true costs."""

    @staticmethod
    def data(first_costs):
        return bundle_data(
            ["阿明", "小红"],
            ["洗碗", "倒垃圾"],
            {"阿明": first_costs, "小红": {"洗碗": 0, "倒垃圾": 5}},
            {"阿明": 1, "小红": 1},
        )

    def test_telling_the_truth_gives_nothing_and_exaggerating_gives_2_50(self):
        honest = plan_of(self.data({"洗碗": 0, "倒垃圾": 0}))
        lying = plan_of(self.data({"洗碗": 1, "倒垃圾": 5}))
        # the same split in both cases: 阿明 does 倒垃圾, 小红 does 洗碗
        assert honest.bundles == lying.bundles == {"小红": ["洗碗"], "阿明": ["倒垃圾"]}
        # by the true costs, 倒垃圾 costs 阿明 nothing, so the net is the payment alone
        assert honest.transfer["阿明"] == 0
        assert lying.transfer["阿明"] == 250
        assert lying.transfer["小红"] == -250
