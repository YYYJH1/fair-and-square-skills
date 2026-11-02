"""Properties of the picking and of the envy checks, tested with hypothesis.

Envy up to one chore is decided in two independent ways. The script compares two bundles place
by place in a ranking. chore_reference.py tries every integer cost that fits the ranking, which
shares no code with the script. The tests check that the two agree on everything the script can
produce, and on arbitrary bundles that picking would never produce.
"""

from __future__ import annotations

import itertools
from collections import Counter

import chore_split as cs
import fsq_core as fc
from chore_reference import (
    classify,
    envy_by_brute_force,
    reference_picks,
    reference_start_order,
    reference_week_order,
)
from chore_support import PROPERTY, SOURCES, chore_cases
from hypothesis import assume, given
from hypothesis import strategies as st

COSTS6 = [
    cost
    for cost in itertools.product(range(3), repeat=6)
    if all(cost[i] <= cost[i + 1] for i in range(5))
]


def plan_of(data):
    return cs.compute(cs.parse_problem(data))


def units_of(data):
    return {
        (item["name"] if isinstance(item, dict) else item): (
            item.get("units", 1) if isinstance(item, dict) else 1
        )
        for item in data["chores"]
    }


# ---------------------------------------------------------------------------------------
# The guarantee
# ---------------------------------------------------------------------------------------


@PROPERTY
@given(chore_cases(max_people=4, max_chores=5, max_units=2))
def test_every_week_is_ef1_for_every_cost_that_fits_the_rankings(data):
    plan = plan_of(data)
    assert plan.ef1_holds
    for week in plan.weeks:
        for person in week.order:
            ranking = plan.problem.rankings[person]
            own = Counter(week.bundles[person])
            for other in week.order:
                if other != person:
                    _, ef1 = envy_by_brute_force(own, Counter(week.bundles[other]), ranking)
                    assert ef1, (week.number, person, other)


@PROPERTY
@given(chore_cases(max_people=4, max_chores=5, max_units=2))
def test_without_cannot_lists_no_pair_fails_and_nobody_runs_out(data):
    plan = plan_of(data)
    assert all(check.status != "fails" for check in plan.checks)
    assert all(week.ran_out == {} for week in plan.weeks)
    assert plan.failures == []


@PROPERTY
@given(chore_cases(max_people=4, max_chores=5, max_units=2, with_cannot=True))
def test_the_status_of_every_pair_equals_brute_force(data):
    plan = plan_of(data)
    verdicts = []
    for check in plan.checks:
        week = plan.weeks[check.week - 1]
        ranking = plan.problem.rankings[check.person]
        own = Counter(week.bundles[check.person])
        other = Counter(week.bundles[check.other])
        want = classify(own, other, ranking)
        assert check.status == want, (check.week, check.person, check.other)
        verdicts.append(want != "fails")
    assert plan.ef1_holds == all(verdicts)


@PROPERTY
@given(st.data())
def test_ef1_detection_on_arbitrary_bundles_agrees_with_brute_force(choose):
    """Not only bundles that picking can produce: any bundles, any ranking, with chores that the
    person cannot do in the other bundle."""
    m = choose.draw(st.integers(1, 5))
    names = [f"c{i}" for i in range(m)]
    can = choose.draw(st.lists(st.sampled_from(names), unique=True, min_size=1))
    ranking = choose.draw(st.permutations(can))
    own = Counter({c: choose.draw(st.integers(0, 2)) for c in can})
    other = Counter({c: choose.draw(st.integers(0, 2)) for c in names})
    own, other = +own, +other
    status, witness, exempt = cs.compare_bundles(dict(own), dict(other), ranking)
    assert status == classify(own, other, ranking)
    if status == "fails":
        assert witness["own_heavy"] > witness["other_heavy"]
    if status == "exempt":
        assert exempt and all(c not in ranking for c in exempt)


@PROPERTY
@given(st.lists(st.integers(1, 6), max_size=5), st.lists(st.integers(1, 6), max_size=5))
def test_dominance_means_no_larger_cost_for_every_non_decreasing_cost(mine, theirs):
    mine, theirs = sorted(mine, reverse=True), sorted(theirs, reverse=True)
    every = all(
        sum(cost[p - 1] for p in mine) <= sum(cost[p - 1] for p in theirs) for cost in COSTS6
    )
    assert cs.dominated(mine, theirs) == every


# ---------------------------------------------------------------------------------------
# The picking
# ---------------------------------------------------------------------------------------


@PROPERTY
@given(chore_cases(max_units=3, with_cannot=True))
def test_every_chore_unit_is_assigned_exactly_once(data):
    plan = plan_of(data)
    units = units_of(data)
    for week in plan.weeks:
        taken = Counter(chore for person in week.order for chore in week.bundles[person])
        assert taken == Counter(units)
        assert len(week.picks) == sum(units.values())
        assert sorted(p.seq for p in week.picks) == list(range(1, len(week.picks) + 1))


@PROPERTY
@given(chore_cases(max_units=3, with_cannot=True))
def test_the_picks_equal_the_independent_reference(data):
    plan = plan_of(data)
    units = units_of(data)
    base = reference_start_order(
        data["people"], sum(units.values()), data["rules"]["random_source"]
    )
    assert plan.base_order == base
    for week in plan.weeks:
        order = reference_week_order(base, week.number, data["rules"].get("rotate", "shift"))
        assert week.order == order
        want = reference_picks(order, plan.problem.rankings, units)
        assert [(p.person, p.chore) for p in week.picks] == want


@PROPERTY
@given(chore_cases(max_units=3, with_cannot=True))
def test_nobody_picks_a_chore_on_their_cannot_list(data):
    plan = plan_of(data)
    for week in plan.weeks:
        for person in week.order:
            blocked = set(data.get("cannot", {}).get(person, []))
            assert not blocked & set(week.bundles[person])


@PROPERTY
@given(chore_cases(max_units=3, with_cannot=True))
def test_a_person_is_skipped_only_when_nothing_they_can_do_is_left(data):
    plan = plan_of(data)
    units = units_of(data)
    for week in plan.weeks:
        for person, round_no in week.ran_out.items():
            spot = week.order.index(person)
            before = [
                pick
                for pick in week.picks
                if pick.round < round_no
                or (pick.round == round_no and week.order.index(pick.person) < spot)
            ]
            left = Counter(units)
            left.subtract(pick.chore for pick in before)
            assert not any(left[c] > 0 for c in plan.problem.rankings[person])
            assert all(pick.person != person for pick in week.picks if pick.round >= round_no)


@PROPERTY
@given(chore_cases(max_units=3, with_cannot=True))
def test_with_cannot_lists_a_pair_can_only_fail_when_the_other_person_ran_out(data):
    """The round-robin argument needs the other person to keep picking until the end. A
    person is skipped only when nothing they can do is left, and only then can it break."""
    plan = plan_of(data)
    for check in plan.failures:
        assert check.other_out_round is not None
    for week in plan.weeks:
        if not week.ran_out:
            assert all(c.status != "fails" for c in plan.checks if c.week == week.number)


@PROPERTY
@given(chore_cases(max_people=5, max_chores=6, max_units=3))
def test_without_cannot_the_number_of_chores_differs_by_at_most_one(data):
    plan = plan_of(data)
    total = sum(units_of(data).values())
    n = len(data["people"])
    for week in plan.weeks:
        sizes = [len(week.bundles[p]) for p in week.order]
        assert sum(sizes) == total
        assert max(sizes) - min(sizes) <= 1
        assert sizes == sorted(sizes, reverse=True)  # earlier pickers hold at least as many
        assert max(sizes) == -(-total // n)


@PROPERTY
@given(chore_cases(max_people=5, max_chores=6, max_units=3))
def test_without_cannot_at_most_one_pick_is_left_without_a_comparison(data):
    plan = plan_of(data)
    for check in plan.checks:
        assert len(check.unmatched) <= 1


@PROPERTY
@given(chore_cases(max_units=3, with_cannot=True))
def test_the_round_by_round_comparisons_always_hold(data):
    plan = plan_of(data)
    assert plan.n_comparisons_failed == 0
    for check in plan.checks:
        for comparison in check.comparisons:
            assert comparison.holds
            if comparison.other_rank is not None:
                assert comparison.own_rank <= comparison.other_rank
            assert comparison.other.seq > comparison.own.seq
            assert comparison.other.round - comparison.own.round in (0, 1)
            same = comparison.other.round == comparison.own.round
            assert same == check.person_first


# ---------------------------------------------------------------------------------------
# The order of the weeks
# ---------------------------------------------------------------------------------------


@PROPERTY
@given(chore_cases(max_people=5, max_weeks=12))
def test_the_start_order_rotates_as_declared(data):
    plan = plan_of(data)
    base = plan.base_order
    n = len(base)
    rotate = data["rules"].get("rotate", "shift")
    for week in plan.weeks:
        if rotate == "none":
            assert week.order == base
        else:
            shift = (week.number - 1) % n
            assert week.order == base[shift:] + base[:shift]
    if rotate == "shift" and len(plan.weeks) >= n:
        starters = [week.order[0] for week in plan.weeks[:n]]
        assert sorted(starters) == sorted(base)
        assert [week.order[-1] for week in plan.weeks[1:n]] == base[: n - 1]


@PROPERTY
@given(chore_cases(max_weeks=2), SOURCES)
def test_a_different_source_text_gives_a_different_seed(data, other):
    assume(other != data["rules"]["random_source"])
    first = plan_of(data)
    data["rules"]["random_source"] = other
    assert plan_of(data).seed_hex != first.seed_hex


@PROPERTY
@given(chore_cases(max_weeks=4), st.randoms(use_true_random=False))
def test_the_weeks_planned_do_not_change_the_earlier_weeks(data, rnd):
    longer = dict(data, weeks=data["weeks"] + rnd.randint(1, 3))
    short, long = plan_of(data), plan_of(longer)
    assert short.seed_hex == long.seed_hex
    for week in short.weeks:
        assert long.weeks[week.number - 1].picks == week.picks


# ---------------------------------------------------------------------------------------
# Independence from the order of the input
# ---------------------------------------------------------------------------------------


def shuffled_copy(data, rnd, chores_too=False):
    copy = dict(data)
    people = list(data["people"])
    rnd.shuffle(people)
    copy["people"] = people
    keys = list(data["rankings"])
    rnd.shuffle(keys)
    copy["rankings"] = {key: data["rankings"][key] for key in keys}
    if "cannot" in data:
        keys = list(data["cannot"])
        rnd.shuffle(keys)
        copy["cannot"] = {key: data["cannot"][key] for key in keys}
    if chores_too:
        chores = list(data["chores"])
        rnd.shuffle(chores)
        copy["chores"] = chores
    return copy


@PROPERTY
@given(chore_cases(with_cannot=True, max_units=3), st.randoms(use_true_random=False))
def test_the_result_does_not_depend_on_the_order_people_are_listed(data, rnd):
    for lang in fc.LANGS:
        first = cs.solve(data, lang)
        second = cs.solve(shuffled_copy(data, rnd), lang)
        assert fc.envelope(first) == fc.envelope(second)
        for fmt in ("md", "dm", "group"):
            assert fc.render(first, fmt, lang=lang) == fc.render(second, fmt, lang=lang)


@PROPERTY
@given(chore_cases(with_cannot=True, max_units=3), st.randoms(use_true_random=False))
def test_the_result_does_not_depend_on_the_order_chores_are_listed(data, rnd):
    first = cs.solve(data)
    second = cs.solve(shuffled_copy(data, rnd, chores_too=True))
    one, two = fc.envelope(first), fc.envelope(second)
    assert one["result"] == two["result"] and one["certificate"] == two["certificate"]
    for fmt in ("md", "dm", "group"):
        assert fc.render(first, fmt) == fc.render(second, fmt)


# ---------------------------------------------------------------------------------------
# Not strategy-proof
# ---------------------------------------------------------------------------------------


def test_round_robin_is_not_strategy_proof():
    """A picks first and truly ranks c, a, b, d. Ranking a first instead gets A both a and c,
    which is lighter than the c and b of the truthful ranking for every cost that fits the
    true ranking."""
    chores = ["a", "b", "c", "d"]
    truth = ["c", "a", "b", "d"]
    lie = ["a", "b", "c", "d"]

    def bundle_of_a(ranking_of_a):
        data = {
            "people": ["A", "B"],
            "chores": chores,
            "rankings": {"A": ranking_of_a, "B": ["a", "b", "c", "d"]},
            "rules": {"random_source": "x", "rotate": "none"},
        }
        problem = cs.parse_problem(data)
        week = cs.run_week(problem, 1, ["A", "B"])
        return week.bundles["A"]

    honest, lying = bundle_of_a(truth), bundle_of_a(lie)
    assert honest == ["c", "b"] and lying == ["a", "c"]
    place = {c: i for i, c in enumerate(truth, 1)}
    assert cs.dominated(
        sorted((place[c] for c in lying), reverse=True),
        sorted((place[c] for c in honest), reverse=True),
    )
    assert sorted(place[c] for c in lying) != sorted(place[c] for c in honest)
