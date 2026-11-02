"""Properties of the draw, checked against plain search over all permutations and all subsets.

Every legal plan is a permutation without fixed points and without an excluded direction, and
for the way ring one single circle. The check for a legal draw is compared with a search over
all permutations, Hall's violators with a search over all subsets of givers.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from unittest import mock

import fsq_core as fc
import gift_exchange as ge
import pytest
from gift_reference import (
    SpecStream,
    blocked_indexes,
    enumeration_draw,
    hall_violators,
    has_perfect_matching,
    is_circle,
    legal_plans,
    receivers_of,
    rejection_draw,
    spec_seed,
)
from gift_support import PROPERTY, SOURCES, cases, directions, exchange_data
from hypothesis import find, given, settings
from hypothesis import strategies as st
from hypothesis.errors import NoSuchExample

MODES = st.sampled_from(["any", "ring"])
# Derangements of 2 .. 9 things and circles through 2 .. 9 people.
DERANGEMENTS = {2: 1, 3: 2, 4: 9, 5: 44, 6: 265, 7: 1854, 8: 14833, 9: 133496}


def problem_of(people, forbidden, source="s", mode="any"):
    return ge.parse_problem(exchange_data(people, forbidden, mode, source))


def blocked_of(people, forbidden):
    return blocked_indexes(people, directions(forbidden))


def outcome(data):
    return ge.compute(ge.parse_problem(data))


# ---------------------------------------------------------------------------------------
# A drawn plan is legal
# ---------------------------------------------------------------------------------------


@PROPERTY
@given(cases(2, 7), MODES)
def test_a_plan_that_is_drawn_is_legal(case, mode):
    people, forbidden, source = case
    try:
        out = outcome(exchange_data(people, forbidden, mode, source))
    except ge.NoLegalPlan:
        return
    blocked = directions(forbidden)
    gifts = out.receiver_of
    assert sorted(gifts) == sorted(people)
    assert sorted(gifts.values()) == sorted(people), "everybody receives exactly one gift"
    for giver, receiver in gifts.items():
        assert giver != receiver, "nobody draws themselves"
        assert (giver, receiver) not in blocked, "nobody gives in an excluded direction"
    if mode == "ring":
        assert ge.is_single_circle(out.draw.plan)
        assert out.circle is not None and sorted(out.circle) == sorted(people)
        for here, there in zip(out.circle, out.circle[1:] + out.circle[:1]):
            assert gifts[here] == there


def feasible(case, mode="any"):
    people, forbidden, _ = case
    plans = legal_plans(len(people), blocked_of(people, forbidden), mode == "ring")
    return bool(plans)


def test_the_strategy_reaches_both_cases_with_and_without_a_legal_plan():
    for mode in ("any", "ring"):
        for wanted in (True, False):
            try:
                find(
                    cases(2, 6),
                    lambda case, w=wanted, m=mode: feasible(case, m) is w,
                    settings=settings(database=None, derandomize=True, max_examples=300),
                )
            except NoSuchExample:  # pragma: no cover - would make the properties vacuous
                pytest.fail(f"no generated case has a legal plan: {wanted} in the way {mode}")


@PROPERTY
@given(cases(2, 6), MODES)
def test_the_listing_equals_a_search_over_all_permutations(case, mode):
    people, forbidden, source = case
    problem = problem_of(people, forbidden, source, mode)
    expected = legal_plans(len(people), blocked_of(people, forbidden), mode == "ring")
    assert ge.list_plans(problem.allowed, mode == "ring") == expected


@PROPERTY
@given(cases(2, 6), MODES)
def test_the_listing_is_increasing_and_has_no_plan_twice(case, mode):
    people, forbidden, source = case
    plans = ge.list_plans(problem_of(people, forbidden, source, mode).allowed, mode == "ring")
    assert plans == sorted(set(plans))


@pytest.mark.parametrize("n", sorted(DERANGEMENTS))
def test_without_exclusions_the_counts_are_the_derangement_and_circle_numbers(n):
    problem = problem_of([f"p{i}" for i in range(n)], [])
    assert len(ge.list_plans(problem.allowed, ring=False)) == DERANGEMENTS[n]
    factorial = 1
    for k in range(2, n):
        factorial *= k
    assert len(ge.list_plans(problem.allowed, ring=True)) == factorial


def test_the_derangement_numbers_follow_their_recurrence():
    for n in range(4, 10):
        assert DERANGEMENTS[n] == (n - 1) * (DERANGEMENTS[n - 1] + DERANGEMENTS[n - 2])


@pytest.mark.parametrize("n", [2, 3, 4, 5, 6])
def test_the_circle_test_agrees_with_following_the_gifts(n):
    for plan in itertools.permutations(range(n)):
        if all(plan[i] != i for i in range(n)):
            assert ge.is_single_circle(plan) == is_circle(plan)


# ---------------------------------------------------------------------------------------
# Is there a legal draw? Exactly when a search finds one
# ---------------------------------------------------------------------------------------


@PROPERTY
@given(cases(2, 6), MODES)
def test_the_check_says_there_is_a_draw_exactly_when_a_search_finds_one(case, mode):
    people, forbidden, source = case
    problem = problem_of(people, forbidden, source, mode)
    expected = legal_plans(len(people), blocked_of(people, forbidden), mode == "ring")
    try:
        found = ge.check_problem(problem)
    except ge.NoLegalPlan as err:
        assert not expected, f"the check refused ({err.kind}) but a plan exists"
        return
    assert expected, "the check accepted but no plan exists"
    assert found.count == len(expected)


@PROPERTY
@given(cases(2, 6))
def test_the_draw_and_the_check_agree_on_the_number_of_plans(case):
    people, forbidden, source = case
    problem = problem_of(people, forbidden, source)
    try:
        found = ge.check_problem(problem)
    except ge.NoLegalPlan:
        with pytest.raises(ge.NoLegalPlan):
            ge.compute(problem)
        return
    assert ge.compute(problem).draw.count == found.count


@PROPERTY
@given(cases(2, 6))
def test_a_violator_exists_exactly_when_the_perfect_matching_is_missing(case):
    people, forbidden, source = case
    problem = problem_of(people, forbidden, source)
    blocked = blocked_of(people, forbidden)
    violation = ge.hall_violator(problem.allowed)
    assert (violation is None) == has_perfect_matching(len(people), blocked)
    plans = legal_plans(len(people), blocked, False)
    assert (violation is None) == bool(plans)


@PROPERTY
@given(cases(2, 6))
def test_the_reported_group_is_a_real_violator_and_cannot_be_cut_down(case):
    people, forbidden, source = case
    problem = problem_of(people, forbidden, source)
    blocked = blocked_of(people, forbidden)
    violation = ge.hall_violator(problem.allowed)
    if violation is None:
        return
    group, receivers = violation
    n = len(people)
    assert group and group == sorted(set(group))
    assert set(receivers) == receivers_of(group, n, blocked), "the receivers are exactly theirs"
    assert len(receivers) < len(group), "fewer receivers than givers"
    assert tuple(group) in set(hall_violators(n, blocked))
    for size in range(1, len(group)):
        for part in itertools.combinations(group, size):
            assert len(receivers_of(part, n, blocked)) >= size, "a smaller group violates too"


@PROPERTY
@given(cases(2, 6))
def test_a_group_that_cannot_be_left_is_closed_and_a_proper_subset(case):
    people, forbidden, source = case
    problem = problem_of(people, forbidden, source, "ring")
    allowed = problem.allowed
    n = len(people)
    closed = ge.closed_group(allowed)
    reach = [{i} | {j for j in allowed[i]} for i in range(n)]
    changed = True
    while changed:  # Warshall's closure, written out
        changed = False
        for i in range(n):
            for j in list(reach[i]):
                if not reach[j] <= reach[i]:
                    reach[i] |= reach[j]
                    changed = True
    connected = all(len(row) == n for row in reach)
    assert (closed is None) == connected
    if closed is not None:
        assert closed and set(closed) != set(range(n))
        for person in closed:
            assert set(allowed[person]) <= set(closed), "a member can give outside the group"


def test_a_group_that_can_still_give_outside_is_not_closed():
    people = ["a", "b", "c", "d"]
    forbidden = [{"giver": "a", "receiver": "c"}, {"giver": "a", "receiver": "d"}]
    problem = problem_of(people, forbidden, "s", "ring")
    assert ge.closed_group(problem.allowed) is None


# A digraph with a perfect matching, strongly connected, and still no circle through everybody.
NO_CIRCLE = {"A": "D", "B": "CE", "C": "AB", "D": "C", "E": "BD"}


def no_circle_input(mode):
    people = list(NO_CIRCLE)
    forbidden = [
        {"giver": giver, "receiver": receiver}
        for giver in people
        for receiver in people
        if giver != receiver and receiver not in NO_CIRCLE[giver]
    ]
    return exchange_data(people, forbidden, mode)


def test_a_circle_can_be_missing_although_every_other_condition_holds():
    problem = ge.parse_problem(no_circle_input("ring"))
    assert ge.hall_violator(problem.allowed) is None
    assert ge.closed_group(problem.allowed) is None
    assert ge.list_plans(problem.allowed, ring=True) == []
    with pytest.raises(ge.NoLegalPlan) as caught:
        ge.compute(problem)
    assert caught.value.kind == "exhausted"
    assert "All 24 circles through the 5 people were checked" in str(caught.value)
    assert "所有 24 种一圈传下去的排法都查过了" in str(caught.value)


def test_the_same_people_can_be_drawn_in_the_way_any():
    out = outcome(no_circle_input("any"))
    assert out.draw.count is not None and out.draw.count >= 1
    assert sorted(out.receiver_of.values()) == sorted(NO_CIRCLE)


# ---------------------------------------------------------------------------------------
# The result is a function of the inputs, whatever the order of the lists
# ---------------------------------------------------------------------------------------


def comparable(result: fc.Result):
    return json.loads(fc.render_json(result))


@PROPERTY
@given(cases(2, 6), MODES, st.data())
def test_the_result_does_not_depend_on_the_order_people_and_exclusions_are_listed(case, mode, data):
    people, forbidden, source = case
    base = exchange_data(people, forbidden, mode, source)
    shuffled = exchange_data(
        data.draw(st.permutations(people)), data.draw(st.permutations(forbidden)), mode, source
    )
    try:
        first = ge.solve(base)
    except ge.NoLegalPlan:
        with pytest.raises(ge.NoLegalPlan):
            ge.solve(shuffled)
        return
    second = ge.solve(shuffled)
    assert comparable(first)["result"] == comparable(second)["result"]
    assert fc.render_dm(first) == fc.render_dm(second)
    assert fc.render_group(first) == fc.render_group(second)
    assert fc.render_md(first) == fc.render_md(second)


@PROPERTY
@given(cases(2, 6), st.data())
def test_a_pair_is_the_same_as_two_one_way_exclusions(case, data):
    people, _, source = case
    first, second = data.draw(st.permutations(people))[:2]
    as_pair = exchange_data(people, [{"pair": [first, second]}], "any", source)
    as_two = exchange_data(
        people,
        [{"giver": first, "receiver": second}, {"giver": second, "receiver": first}],
        "any",
        source,
    )
    try:
        left = ge.solve(as_pair)
    except ge.NoLegalPlan:
        with pytest.raises(ge.NoLegalPlan):
            ge.solve(as_two)
        return
    assert comparable(left) == comparable(ge.solve(as_two))


@PROPERTY
@given(cases(2, 6), MODES)
def test_listing_an_exclusion_twice_changes_nothing(case, mode):
    people, forbidden, source = case
    once = exchange_data(people, forbidden, mode, source)
    twice = exchange_data(people, forbidden + forbidden, mode, source)
    try:
        left = ge.solve(once)
    except ge.NoLegalPlan:
        with pytest.raises(ge.NoLegalPlan):
            ge.solve(twice)
        return
    assert comparable(left)["result"] == comparable(ge.solve(twice))["result"]


@PROPERTY
@given(cases(2, 6), MODES)
def test_the_same_input_gives_the_same_bytes(case, mode):
    people, forbidden, source = case
    data = exchange_data(people, forbidden, mode, source)
    try:
        first = ge.solve(data)
    except ge.NoLegalPlan:
        return
    second = ge.solve(data)
    for render in (fc.render_md, fc.render_dm, fc.render_group, fc.render_json):
        assert render(first) == render(second)


# ---------------------------------------------------------------------------------------
# The draw follows the specification
# ---------------------------------------------------------------------------------------


@PROPERTY
@given(cases(2, 7), MODES)
def test_the_listing_method_agrees_with_the_independent_reference(case, mode):
    people, forbidden, source = case
    ring = mode == "ring"
    if not feasible(case, mode):
        return
    out = outcome(exchange_data(people, forbidden, mode, source))
    plan, number, count = enumeration_draw(people, sorted(directions(forbidden)), ring, source)
    assert (out.draw.number, out.draw.count) == (number, count)
    assert out.draw.plan == plan
    assert out.draw.seed_hex == spec_seed(out.draw.rule, people, len(people), source).hex()


@PROPERTY
@given(cases(2, 6), MODES, st.integers(1, 40))
def test_the_proposal_method_agrees_with_the_independent_reference(case, mode, limit):
    """Force the proposal method on small groups, and a small limit of proposals, and compare
    with a search that follows the specification."""
    people, forbidden, source = case
    ring = mode == "ring"
    if not feasible(case, mode):
        return
    expected = rejection_draw(people, sorted(directions(forbidden)), ring, source, limit)
    with mock.patch.object(ge, "ENUMERATE_MAX", 1), mock.patch.object(ge, "MAX_ATTEMPTS", limit):
        try:
            out = outcome(exchange_data(people, forbidden, mode, source))
        except ge.NoLegalPlan as err:
            assert err.kind == "limit" and expected is None
            return
    assert expected is not None
    plan, attempts = expected
    assert out.draw.method == "rejection"
    assert (out.draw.plan, out.draw.attempts) == (plan, attempts)
    assert out.draw.count is None and out.draw.number is None
    assert 1 <= out.draw.attempts <= limit


@PROPERTY
@given(cases(2, 6), MODES)
def test_the_printed_preimage_hashes_to_the_seed_and_holds_the_four_inputs(case, mode):
    people, forbidden, source = case
    try:
        out = outcome(exchange_data(people, forbidden, mode, source))
    except ge.NoLegalPlan:
        return
    assert hashlib.sha256(out.draw.preimage.encode("utf-8")).hexdigest() == out.draw.seed_hex
    assert json.loads(out.draw.preimage) == {
        "n_slots": len(people),
        "participants": sorted(people),
        "rule": out.draw.rule,
        "source": source,
    }


@PROPERTY
@given(cases(2, 6), MODES)
def test_the_rule_name_follows_the_way_of_giving_and_the_method(case, mode):
    people, forbidden, source = case
    try:
        out = outcome(exchange_data(people, forbidden, mode, source))
    except ge.NoLegalPlan:
        return
    assert out.draw.rule == f"gift_exchange_{mode}_enum_v1"
    assert out.draw.rule in ge.RULE_NAMES.values()


def test_the_four_rule_names_are_different():
    assert len(set(ge.RULE_NAMES.values())) == 4
    assert set(ge.RULE_NAMES) == {(mode, method) for mode in ge.MODES for method in ge.METHODS}


@PROPERTY
@given(cases(3, 6), SOURCES)
def test_a_different_source_text_gives_a_different_seed(case, other):
    people, forbidden, source = case
    if other == source:
        return
    try:
        first = outcome(exchange_data(people, forbidden, "any", source))
        second = outcome(exchange_data(people, forbidden, "any", other))
    except ge.NoLegalPlan:
        return
    assert first.draw.seed_hex != second.draw.seed_hex


def test_the_proposals_use_one_stream_one_after_the_other():
    """Proposal t+1 goes on where proposal t stopped, it does not start the stream again."""
    stream = SpecStream(spec_seed("gift_exchange_any_reject_v1", ["a", "b", "c"], 3, "x"))
    first, second = stream.shuffled(3), stream.shuffled(3)
    again = SpecStream(spec_seed("gift_exchange_any_reject_v1", ["a", "b", "c"], 3, "x"))
    assert again.shuffled(3) == first
    assert again.shuffled(3) == second
    assert stream.counter == again.counter >= 4
