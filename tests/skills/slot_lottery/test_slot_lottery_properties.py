"""Properties of the draw and of the serial dictatorship, checked with hypothesis.

The serial dictatorship is compared with exhaustive search over all assignments, which shares
no code with the script (lottery_reference.py). The sizes stay small so that search is fast.
"""

from __future__ import annotations

import hashlib

import fsq_core as fc
import slot_lottery as sl
from hypothesis import assume, given
from hypothesis import strategies as st
from lottery_reference import (
    all_reports,
    lexicographic_best,
    pareto_improvements,
    reference_order,
    value,
)
from lottery_support import (
    PROPERTY,
    SOURCES,
    lottery_inputs,
    rsd_cases,
    rsd_data,
)


def outcome(data):
    return sl.compute(sl.parse_problem(data))


def rsd_outcome(case):
    people, slots, prefs, source = case
    return outcome(rsd_data(people, slots, prefs, source))


# ---------------------------------------------------------------------------------------
# The lottery
# ---------------------------------------------------------------------------------------


@PROPERTY
@given(lottery_inputs())
def test_the_order_is_a_permutation_of_the_participants(data):
    out = outcome(data)
    assert sorted(out.order) == sorted(data["people"])
    assert len(set(out.order)) == len(out.order)
    n = data["n_slots"]
    assert out.winners == out.order[:n]
    assert out.waiting == out.order[n:]
    assert len(out.winners) == min(n, len(data["people"]))


@PROPERTY
@given(lottery_inputs(), st.randoms(use_true_random=False))
def test_the_result_does_not_depend_on_the_order_people_are_listed(data, rnd):
    people = list(data["people"])
    rnd.shuffle(people)
    first = sl.solve(data)
    second = sl.solve(dict(data, people=people))
    assert fc.envelope(first) == fc.envelope(second)
    for fmt in ("md", "dm", "group"):
        assert fc.render(first, fmt) == fc.render(second, fmt)


@PROPERTY
@given(lottery_inputs(), SOURCES)
def test_a_different_source_text_gives_a_different_seed(data, other):
    assume(other != data["random_source"])
    first = outcome(data)
    second = outcome(dict(data, random_source=other))
    assert first.draws[0].seed_hex != second.draws[0].seed_hex


@PROPERTY
@given(lottery_inputs())
def test_the_script_agrees_with_the_independent_reference(data):
    out = outcome(data)
    expected = reference_order(
        "uniform_lottery_v1", data["people"], data["n_slots"], data["random_source"]
    )
    assert out.order == expected


@PROPERTY
@given(lottery_inputs())
def test_the_printed_preimage_hashes_to_the_seed(data):
    draw = outcome(data).draws[0]
    assert hashlib.sha256(draw.preimage.encode("utf-8")).hexdigest() == draw.seed_hex
    assert bytes.fromhex(draw.seed_hex) == fc.make_seed(
        "uniform_lottery_v1", data["people"], data["n_slots"], data["random_source"]
    )


@PROPERTY
@given(lottery_inputs())
def test_with_enough_slots_everybody_is_drawn(data):
    data = dict(data, n_slots=len(data["people"]) + 1)
    out = outcome(data)
    assert out.winners == out.order and out.waiting == []


@PROPERTY
@given(lottery_inputs())
def test_every_text_output_names_every_participant(data):
    result = sl.solve(data)
    for fmt in ("md", "dm", "group"):
        text = fc.render(result, fmt)
        for name in data["people"]:
            assert name in text


# ---------------------------------------------------------------------------------------
# The serial dictatorship
# ---------------------------------------------------------------------------------------


@PROPERTY
@given(rsd_cases())
def test_rsd_gives_everyone_at_most_one_slot_and_never_an_unacceptable_one(case):
    people, slots, prefs, _ = case
    out = rsd_outcome(case)
    got = list(out.allocation.values())
    assert len(got) == len(set(got)), "a slot was given twice"
    for person, slot in out.allocation.items():
        assert person in people and slot in slots
        assert slot in prefs[person], "an unacceptable slot was assigned"
    assert sorted(out.order) == sorted(people)
    assert out.waiting == [p for p in out.order if p not in out.allocation]
    assert out.free_slots == [s for s in slots if s not in got]


@PROPERTY
@given(rsd_cases())
def test_rsd_nobody_prefers_a_slot_that_was_still_free_at_their_turn(case):
    _, _, prefs, _ = case
    out = rsd_outcome(case)
    taken = set()
    for person in out.order:
        ranking = prefs[person]
        got = out.allocation.get(person)
        better = ranking if got is None else ranking[: ranking.index(got)]
        assert all(slot in taken for slot in better), f"{person} skipped a free slot"
        if got is not None:
            assert got not in taken
            taken.add(got)


@PROPERTY
@given(rsd_cases(max_people=4, max_slots=4))
def test_rsd_equals_brute_force_serial_dictatorship_for_the_drawn_order(case):
    _, slots, prefs, _ = case
    out = rsd_outcome(case)
    assert out.allocation == lexicographic_best(out.order, prefs, slots)


@PROPERTY
@given(rsd_cases(max_people=4, max_slots=4))
def test_rsd_is_pareto_efficient_after_the_draw(case):
    people, slots, prefs, _ = case
    out = rsd_outcome(case)
    assert pareto_improvements(out.allocation, people, slots, prefs) == []


@PROPERTY
@given(rsd_cases(max_people=4, max_slots=3), st.data())
def test_rsd_is_strategy_proof_for_the_drawn_order(case, data):
    people, slots, prefs, _ = case
    out = rsd_outcome(case)
    person = data.draw(st.sampled_from(people))
    truthful = value(prefs, person, out.allocation.get(person))
    for report in all_reports(slots):
        lied = dict(prefs, **{person: report})
        allocation = sl.serial_dictatorship(out.order, lied, slots)[0]
        assert truthful <= value(prefs, person, allocation.get(person)), (
            f"{person} gains by reporting {report}"
        )


@PROPERTY
@given(rsd_cases(), st.randoms(use_true_random=False))
def test_rsd_does_not_depend_on_how_people_prefs_and_slots_are_listed(case, rnd):
    people, slots, prefs, source = case
    first = sl.solve(rsd_data(people, slots, prefs, source))
    shuffled_people = rnd.sample(people, len(people))
    shuffled_prefs = {p: prefs[p] for p in rnd.sample(list(prefs), len(prefs))}
    second = sl.solve(rsd_data(shuffled_people, slots, shuffled_prefs, source))
    assert fc.envelope(first) == fc.envelope(second)
    for fmt in ("md", "dm", "group"):
        assert fc.render(first, fmt) == fc.render(second, fmt)
    # the allocation does not depend on the order the slots are listed either
    reordered = sl.solve(rsd_data(people, rnd.sample(slots, len(slots)), prefs, source))
    assert (
        fc.envelope(reordered)["result"]["allocation"] == fc.envelope(first)["result"]["allocation"]
    )
    assert fc.envelope(reordered)["result"]["order"] == fc.envelope(first)["result"]["order"]


@PROPERTY
@given(rsd_cases(everybody_ranks=False))
def test_people_without_a_ranking_are_out_under_forfeit(case):
    people, slots, prefs, source = case
    out = rsd_outcome(case)
    silent = sorted(p for p in people if p not in prefs)
    assert out.removed == silent
    assert sorted(out.order) == sorted(prefs)
    assert not set(out.allocation) & set(silent)
    expected = reference_order("rsd_v1", sorted(prefs), len(slots), source)
    assert out.order == expected


@PROPERTY
@given(rsd_cases(everybody_ranks=False))
def test_people_without_a_ranking_take_what_is_left_under_assigned(case):
    people, slots, prefs, source = case
    out = outcome(rsd_data(people, slots, prefs, source, no_ranking="assigned"))
    silent = [p for p in people if p not in prefs]
    ranked_part = [p for p in out.order if p in prefs]
    assert out.order[: len(ranked_part)] == ranked_part, "people with a ranking pick first"
    assert sorted(out.order[len(ranked_part) :]) == sorted(silent)
    assert out.removed == []
    # a person without a ranking takes the first free slot in the order of slot_names
    taken = {out.allocation[p] for p in ranked_part if p in out.allocation}
    for person in out.order[len(ranked_part) :]:
        free = [s for s in slots if s not in taken]
        got = out.allocation.get(person)
        assert got == (free[0] if free else None)
        if got is not None:
            taken.add(got)


@PROPERTY
@given(rsd_cases())
def test_rsd_script_order_equals_the_independent_reference(case):
    people, slots, _, source = case
    out = rsd_outcome(case)
    assert out.order == reference_order("rsd_v1", people, len(slots), source)


@PROPERTY
@given(lottery_inputs())
def test_json_positions_follow_the_order(data):
    result = fc.envelope(sl.solve(data))["result"]
    positions = result["positions"]
    assert sorted(positions.values()) == list(range(1, len(data["people"]) + 1))
    assert sorted(positions, key=positions.get) == result["order"]
