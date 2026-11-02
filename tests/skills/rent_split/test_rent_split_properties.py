"""Property tests of the rent-split skill (hypothesis).

Each property is checked on random bids with an independent computation in the test, in exact
arithmetic wherever the claim is exact.
"""

from __future__ import annotations

import itertools
import json
import math
from fractions import Fraction

import pytest
from hypothesis import given
from hypothesis import strategies as st
from rent_split_strategies import (
    SETTINGS,
    bid_matrices,
    json_values,
    loose_bid_matrices,
)
from rent_split_support import four_roommates, load_script, make_input, matrix_input

rs = load_script()
fc = rs.fc

RULES = ("allow", "spliddit")


def compute(rows, total, rule="spliddit", **extra):
    return rs.compute(rs.read_problem(matrix_input(rows, total, rule, **extra)))


def used_bids(outcome):
    """The bids the solver worked with: the given bids plus the exact per-room shift."""
    return [
        [Fraction(x) + outcome.shift_exact[i] for x in row]
        for i, row in enumerate(outcome.problem.bids)
    ]


def exact_surplus(outcome, i, room):
    return used_bids(outcome)[i][room] - outcome.exact_rents[room]


# --------------------------------------------------------------------------------------
# What the numbers must satisfy
# --------------------------------------------------------------------------------------


@SETTINGS
@given(bid_matrices(), st.sampled_from(RULES))
def test_rents_add_up_to_the_total_and_every_room_is_rented_once(case, rule):
    rows, total = case
    outcome = compute(rows, total, rule)
    assert sum(outcome.rents) == total
    assert sorted(outcome.room_of) == list(range(len(rows)))
    assert sum(outcome.exact_rents) == total


@SETTINGS
@given(bid_matrices(), st.sampled_from(RULES))
def test_nobody_envies_anybody_in_exact_arithmetic(case, rule):
    rows, total = case
    outcome = compute(rows, total, rule)
    values = used_bids(outcome)
    n = len(rows)
    for i in range(n):
        mine = exact_surplus(outcome, i, outcome.room_of[i])
        assert all(values[i][k] - outcome.exact_rents[k] <= mine for k in range(n))


@SETTINGS
@given(bid_matrices(), st.sampled_from(RULES))
def test_rounded_envy_is_at_most_one_cent_and_rents_are_floor_or_ceiling(case, rule):
    rows, total = case
    outcome = compute(rows, total, rule)
    for exact, rounded in zip(outcome.exact_rents, outcome.rents):
        assert rounded in (math.floor(exact), math.ceil(exact))
    bids = {
        f"p{i}": {f"r{k}": Fraction(outcome.shown[i][k], 100) for k in range(len(rows))}
        for i in range(len(rows))
    }
    assignment = {f"p{i}": f"r{outcome.room_of[i]}" for i in range(len(rows))}
    price_cents = {f"r{k}": outcome.rents[k] for k in range(len(rows))}
    envy = fc.max_envy_cents(bids, assignment, price_cents)
    assert envy == outcome.max_envy <= 1


@SETTINGS
@given(bid_matrices(), st.sampled_from(RULES))
def test_nobody_pays_more_than_their_own_bid_for_their_room(case, rule):
    rows, total = case
    outcome = compute(rows, total, rule)
    for i in range(len(rows)):
        room = outcome.room_of[i]
        assert outcome.exact_rents[room] <= used_bids(outcome)[i][room]
        assert outcome.rents[room] <= outcome.shown[i][room]


@SETTINGS
@given(bid_matrices())
def test_spliddit_and_forbid_never_pay_anyone_to_live_when_a_split_without_exists(case):
    rows, total = case
    spliddit = compute(rows, total, "spliddit")
    if spliddit.applied == rs.APPLIED_NON_NEGATIVE:
        assert min(spliddit.exact_rents) >= 0
        assert min(spliddit.rents) >= 0
        forbid = compute(rows, total, "forbid")
        assert (forbid.rents, forbid.room_of) == (spliddit.rents, spliddit.room_of)
    else:
        assert spliddit.applied == rs.APPLIED_FALLBACK
        assert compute(rows, total, "allow").rents == spliddit.rents
        with pytest.raises(fc.NoSolution):
            compute(rows, total, "forbid")


@SETTINGS
@given(bid_matrices())
def test_the_three_rules_agree_when_the_standard_solution_has_no_negative_rent(case):
    rows, total = case
    allow = compute(rows, total, "allow")
    if min(allow.exact_rents) >= 0:
        for rule in ("spliddit", "forbid"):
            other = compute(rows, total, rule)
            assert (other.rents, other.room_of) == (allow.rents, allow.room_of)


# --------------------------------------------------------------------------------------
# Relabelling, reordering and shifting
# --------------------------------------------------------------------------------------


def named(outcome):
    p = outcome.problem
    return {
        "assignment": {p.people[i]: p.rooms[outcome.room_of[i]] for i in range(len(p.people))},
        "rent": {p.rooms[k]: outcome.rents[k] for k in range(len(p.rooms))},
        "surplus": {p.people[i]: outcome.surplus[i] for i in range(len(p.people))},
    }


@SETTINGS
@given(bid_matrices(), st.sampled_from(RULES), st.data())
def test_reordering_people_and_rooms_changes_nothing_but_the_order(case, rule, data):
    rows, total = case
    n = len(rows)
    people = data.draw(st.permutations(list(range(n))))
    rooms = data.draw(st.permutations(list(range(n))))
    base = matrix_input(rows, total, rule)
    shuffled = make_input(
        base["total_rent"],
        [f"r{k}" for k in rooms],
        {f"p{i}": [base["bids"][f"p{i}"][k] for k in rooms] for i in people},
        rule,
    )
    assert named(rs.compute(rs.read_problem(shuffled))) == named(rs.compute(rs.read_problem(base)))


@SETTINGS
@given(bid_matrices(max_people=5), st.sampled_from(RULES), st.data())
def test_exact_solution_follows_a_renumbering_of_people_and_rooms(case, rule, data):
    rows, total = case
    n = len(rows)
    who = data.draw(st.permutations(list(range(n))))
    where = data.draw(st.permutations(list(range(n))))
    values = [[Fraction(x) for x in row] for row in rows]
    moved = [[values[who[i]][where[k]] for k in range(n)] for i in range(n)]
    first = rs.solve_exact(values, Fraction(total), rule)
    second = rs.solve_exact(moved, Fraction(total), rule)
    assert first.applied == second.applied
    assert [second.rents[k] for k in range(n)] == [first.rents[where[k]] for k in range(n)]
    assert second.utilities == [first.utilities[who[i]] for i in range(n)]


@SETTINGS
@given(bid_matrices(), st.sampled_from(RULES), st.data())
def test_shifting_all_of_one_persons_bids_changes_nothing(case, rule, data):
    rows, total = case
    n = len(rows)
    person = data.draw(st.integers(0, n - 1))
    amount = data.draw(st.integers(1, 1_000_000))
    moved = [list(row) for row in rows]
    moved[person] = [x + amount for x in moved[person]]
    plain = compute(rows, total, rule)
    shifted = compute(moved, total, rule)
    assert shifted.rents == plain.rents
    assert shifted.room_of == plain.room_of
    assert shifted.surplus == plain.surplus
    assert shifted.shift_exact[person] == -amount


@SETTINGS
@given(loose_bid_matrices(), st.sampled_from(RULES))
def test_bids_that_do_not_add_up_are_shifted_so_the_given_bids_show_no_envy(case, rule):
    rows, total = case
    outcome = compute(rows, total, rule)
    for i, row in enumerate(rows):
        own = outcome.room_of[i]
        gains = [row[k] - outcome.rents[k] for k in range(len(rows))]
        assert max(gains) - gains[own] <= 1  # judged by the numbers the person actually gave
        over = outcome.rents[own] - outcome.shown[i][own]  # rent above the (shifted) own bid
        assert over <= 1
        if outcome.shift_exact[i].denominator == 1:
            assert over <= 0  # a shift of whole cents leaves no excess at all
    assert sum(outcome.rents) == total


# --------------------------------------------------------------------------------------
# The assignment and its ties
# --------------------------------------------------------------------------------------


@SETTINGS
@given(bid_matrices(max_people=6))
def test_the_assignment_has_the_largest_total_bid(case):
    rows, total = case
    outcome = compute(rows, total, "allow")
    n = len(rows)
    best = max(sum(rows[i][perm[i]] for i in range(n)) for perm in itertools.permutations(range(n)))
    assert sum(rows[i][outcome.room_of[i]] for i in range(n)) == best


@SETTINGS
@given(bid_matrices(max_people=6))
def test_hungarian_method_agrees_with_brute_force(case):
    rows, _ = case
    n = len(rows)
    values = [[Fraction(x) for x in row] for row in rows]
    chosen = rs.welfare_max_assignment(values)
    best = max(sum(rows[i][perm[i]] for i in range(n)) for perm in itertools.permutations(range(n)))
    assert sorted(chosen) == list(range(n))
    assert sum(rows[i][chosen[i]] for i in range(n)) == best


SOURCES = st.text(alphabet="abcXYZ0189 年月日号", min_size=1, max_size=12).filter(str.strip)


@SETTINGS
@given(bid_matrices(), st.sampled_from(RULES), SOURCES)
def test_a_random_source_gives_a_valid_reproducible_assignment(case, rule, source):
    rows, total = case
    first = compute(rows, total, rule, random_source=source)
    second = compute(rows, total, rule, random_source=source)
    plain = compute(rows, total, rule)
    assert first.room_of == second.room_of
    assert first.rents == plain.rents  # ties never change the rents
    assert first.was_tie == plain.was_tie
    for i in range(len(rows)):  # or what anybody earns, up to the rounding of a room's rent
        before = exact_surplus(plain, i, plain.room_of[i])
        assert exact_surplus(first, i, first.room_of[i]) == before
        assert abs(first.surplus[i] - plain.surplus[i]) <= 1
    assert (first.seed_hex is not None) and (plain.seed_hex is None)


def test_a_random_source_spreads_the_rooms_when_everybody_is_indifferent():
    rows = [[100, 100, 100]] * 3
    seen = set()
    for number in range(100):
        outcome = compute(rows, 300, "allow", random_source=f"public draw {number}")
        assert outcome.was_tie
        seen.add(tuple(outcome.room_of))
    assert len(seen) == 6  # every one of the 3! assignments shows up


def test_without_a_random_source_ties_go_by_name():
    rows = [[100, 100, 100]] * 3
    outcome = compute(rows, 300, "allow")
    assert outcome.room_of == [0, 1, 2]
    assert outcome.was_tie


# --------------------------------------------------------------------------------------
# The audit
# --------------------------------------------------------------------------------------


@SETTINGS
@given(bid_matrices(max_people=5), st.sampled_from(RULES))
def test_auditing_the_rules_own_split_finds_nothing_to_change(case, rule):
    rows, total = case
    outcome = compute(rows, total, rule)
    p = outcome.problem
    audit = {
        "assignment": {p.people[i]: p.rooms[outcome.room_of[i]] for i in range(len(rows))},
        "rent": {
            p.people[i]: Fraction(outcome.rents[outcome.room_of[i]], 100) for i in range(len(rows))
        },
    }
    result = rs.analyse(matrix_input(rows, total, rule, audit=audit), want_audit=True)
    report = result.result["audit"]
    assert report["assignment_is_optimal"] is True
    for entry in report["per_person"].values():
        assert int(entry["delta_cents"]) == 0
        assert int(entry["envy_cents"]) <= 1


@SETTINGS
@given(bid_matrices(max_people=5), st.data())
def test_the_audit_flags_an_assignment_exactly_when_it_is_not_welfare_maximising(case, data):
    rows, total = case
    n = len(rows)
    perm = data.draw(st.permutations(list(range(n))))
    cut = sorted(data.draw(st.lists(st.integers(0, total), min_size=n - 1, max_size=n - 1)))
    paid = [b - a for a, b in zip([0, *cut], [*cut, total])]
    audit = {
        "assignment": {f"p{i}": f"r{perm[i]}" for i in range(n)},
        "rent": {f"p{i}": Fraction(paid[i], 100) for i in range(n)},
    }
    result = rs.analyse(matrix_input(rows, total, "allow", audit=audit), want_audit=True)
    best = max(sum(rows[i][q[i]] for i in range(n)) for q in itertools.permutations(range(n)))
    now = sum(rows[i][perm[i]] for i in range(n))
    report = result.result["audit"]
    assert report["assignment_is_optimal"] is (now == best)
    assert int(report["bids_total_now_cents"]) == now
    assert int(report["bids_total_best_cents"]) == best


@SETTINGS
@given(bid_matrices(max_people=5), st.data())
def test_audit_envy_is_what_the_person_would_gain_by_taking_another_room(case, data):
    rows, total = case
    n = len(rows)
    perm = data.draw(st.permutations(list(range(n))))
    cut = sorted(data.draw(st.lists(st.integers(0, total), min_size=n - 1, max_size=n - 1)))
    paid = [b - a for a, b in zip([0, *cut], [*cut, total])]
    audit = {
        "assignment": {f"p{i}": f"r{perm[i]}" for i in range(n)},
        "rent": {f"p{i}": Fraction(paid[i], 100) for i in range(n)},
    }
    result = rs.analyse(matrix_input(rows, total, "allow", audit=audit), want_audit=True)
    rent_of_room = {perm[i]: paid[i] for i in range(n)}
    for i in range(n):
        gains = [rows[i][k] - rent_of_room[k] for k in range(n)]
        here = gains[perm[i]]
        expected = max(max(gains) - here, 0)
        assert int(result.result["audit"]["per_person"][f"p{i}"]["envy_cents"]) == expected


# --------------------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------------------


@SETTINGS
@given(bid_matrices(max_people=6), st.sampled_from(RULES), st.booleans())
def test_every_format_renders_and_the_json_has_no_floats(case, rule, with_audit):
    rows, total = case
    n = len(rows)
    extra = {}
    if with_audit:
        extra["audit"] = {
            "assignment": {f"p{i}": f"r{i}" for i in range(n)},
            "rent": {
                f"p{i}": Fraction(total // n + (1 if i < total % n else 0), 100) for i in range(n)
            },
        }
    result = rs.analyse(matrix_input(rows, total, rule, **extra), want_audit=with_audit)
    for fmt_name in ("md", "dm", "group"):
        text = fc.render(result, fmt_name)
        assert text.endswith("\n")
        assert "Traceback" not in text
    parsed = json.loads(fc.render_json(result), parse_float=lambda text: pytest.fail(text))
    assert set(parsed) == {"inputs_echo", "result", "certificate", "not_modeled", "reproduce"}
    assert sum(Fraction(value) for value in parsed["result"]["rent_cents"].values()) == Fraction(
        total, 100
    )


@SETTINGS
@given(bid_matrices(max_people=6), st.sampled_from(RULES))
def test_the_output_is_deterministic(case, rule):
    rows, total = case
    first = rs.analyse(matrix_input(rows, total, rule))
    second = rs.analyse(matrix_input(rows, total, rule))
    assert fc.render_json(first) == fc.render_json(second)
    assert fc.render_md(first) == fc.render_md(second)


# --------------------------------------------------------------------------------------
# Bad input never crashes the script
# --------------------------------------------------------------------------------------

DELETE = object()  # stands for "remove this key" in the mutation test

PATHS = [
    ("total_rent",),
    ("rooms",),
    ("rooms", 0),
    ("bids",),
    ("bids", "阿明"),
    ("bids", "阿明", 1),
    ("rules",),
    ("rules", "negative_rent"),
    ("rules", "random_source"),
    ("audit",),
    ("audit", "assignment"),
    ("audit", "assignment", "阿明"),
    ("audit", "rent"),
    ("audit", "rent", "小红"),
]


def _base():
    data = four_roommates(random_source="open")
    data["audit"] = {
        "assignment": {"阿明": "小书房", "小红": "南次卧", "大刘": "主卧带卫", "Coco": "北次卧"},
        "rent": dict.fromkeys(["阿明", "小红", "大刘", "Coco"], 2000),
    }
    return data


def _set(data, path, value):
    target = data
    for key in path[:-1]:
        target = target[key]
    if value is DELETE:
        del target[path[-1]]
    else:
        target[path[-1]] = value


@SETTINGS
@given(st.data())
def test_a_mutated_input_is_accepted_or_rejected_with_a_message_never_a_crash(data):
    document = _base()
    for _ in range(data.draw(st.integers(1, 3))):
        path = data.draw(st.sampled_from(PATHS))
        value = data.draw(st.one_of(json_values(), st.just(DELETE)))
        try:
            _set(document, path, value)
        except (KeyError, IndexError, TypeError):
            continue
    try:
        result = rs.analyse(document, want_audit=data.draw(st.booleans()))
    except (fc.InputError, fc.NoSolution):
        return
    for fmt_name in ("md", "dm", "group"):
        fc.render(result, fmt_name)
    fc.render_json(result)


@SETTINGS
@given(json_values())
def test_any_json_value_is_accepted_or_rejected_with_a_message(value):
    try:
        rs.analyse(value)
    except (fc.InputError, fc.NoSolution):
        return
    pytest.fail("a random JSON value was accepted as a rent problem")
