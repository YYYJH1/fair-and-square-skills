"""Method ps: the chances, their decomposition into fixed assignments, the draw, and its limits.

The script is compared with matching_reference.py, which shares no code with it: a second
simulation of the eating, the stochastic dominance check from its definition, a linear program for
ordinal efficiency, and a check of every fixed assignment against the rules of the slots.
"""

from __future__ import annotations

import collections
import hashlib
import itertools
import json
import math
from fractions import Fraction

import fsq_core as fc
import pytest
import slot_lottery as sl
from hypothesis import given
from hypothesis import strategies as st
from lottery_reference import spec_seed
from lottery_support import (
    EXAMPLES,
    PROPERTY,
    SOURCE,
    load_example,
    matching_cases,
    ps_data,
    run_json,
    run_script,
)
from matching_reference import (
    dominates,
    eat,
    envy_pairs,
    expected_utility,
    ordinal_gain,
    pareto_improvement,
    prefix_sums,
    serial_dictatorship_chances,
    utilities_for_prefix,
)

# The classic example: A and B rank a > b > c > d, C and D rank b > a > d > c.
CLASSIC_PEOPLE = ["A", "B", "C", "D"]
CLASSIC_SLOTS = ["a", "b", "c", "d"]
CLASSIC_PREFS = {
    "A": list("abcd"),
    "B": list("abcd"),
    "C": list("badc"),
    "D": list("badc"),
}
CLASSIC_PS_SEED = "dd99a64e48d58a496efd4e0844177051fbd952edc2deea07dbec04934be20f31"

# Three people, three slots. The truthful table and the table after p0 lies are recorded.
LIE_PEOPLE = ["p0", "p1", "p2"]
LIE_SLOTS = ["a", "b", "c"]
LIE_PREFS = {"p0": ["b", "c", "a"], "p1": ["c", "a", "b"], "p2": ["c", "b", "a"]}
LIE_REPORT = ["c", "b", "a"]
FOUND_PROFILES = 24  # of the 216 profiles of three complete rankings, those in which p0 has a misreport that pays


def outcome(data):
    return sl.compute(sl.parse_problem(data))


def case_outcome(case):
    people, slots, prefs, capacities, _, source = case
    return outcome(ps_data(people, slots, prefs, source, capacities=capacities))


def classic(**extra):
    return ps_data(CLASSIC_PEOPLE, CLASSIC_SLOTS, CLASSIC_PREFS, **extra)


def frac(text):
    return Fraction(text)


# ---------------------------------------------------------------------------------------
# The classic example
# ---------------------------------------------------------------------------------------


class TestClassicExample:
    def test_everybody_gets_the_first_choice_with_chance_one_half_where_serial_dictatorship_gives_5_12(
        self,
    ):
        out = outcome(classic())
        chances = out.ps.chances
        for person, first in (("A", "a"), ("B", "a"), ("C", "b"), ("D", "b")):
            assert chances[person][first] == Fraction(1, 2)
        assert chances["A"]["c"] == chances["B"]["c"] == Fraction(1, 2)
        assert chances["C"]["d"] == chances["D"]["d"] == Fraction(1, 2)
        rsd = serial_dictatorship_chances(CLASSIC_PEOPLE, CLASSIC_SLOTS, CLASSIC_PREFS)
        assert rsd["A"]["a"] == Fraction(5, 12) < chances["A"]["a"]

    def test_the_eating_schedule_has_two_stretches(self):
        out = outcome(classic())
        first, second = out.ps.stages
        assert (first.start, first.end, second.start, second.end) == (
            0,
            Fraction(1, 2),
            Fraction(1, 2),
            1,
        )
        assert first.eating == {"A": "a", "B": "a", "C": "b", "D": "b"}
        assert first.used_up == ["a", "b"]
        assert second.eating == {"A": "c", "B": "c", "C": "d", "D": "d"}
        assert second.used_up == ["c", "d"]

    def test_the_independent_simulation_agrees(self):
        out = outcome(classic())
        assert out.ps.chances == eat(CLASSIC_PEOPLE, CLASSIC_PREFS, {s: 1 for s in CLASSIC_SLOTS})

    def test_two_fixed_assignments_of_one_half_each(self):
        out = outcome(classic())
        assert [term.weight for term in out.ps.terms] == [Fraction(1, 2), Fraction(1, 2)]
        pairs = sorted((term.assignment["A"], term.assignment["B"]) for term in out.ps.terms)
        assert pairs == [("a", "c"), ("c", "a")]
        for term in out.ps.terms:
            assert {term.assignment["C"], term.assignment["D"]} == {"b", "d"}

    def test_the_recorded_seed_number_and_term(self):
        out = outcome(classic())
        assert out.draws[0].seed_hex == CLASSIC_PS_SEED
        assert out.draws[0].seed_hex == spec_seed("ps_bvn_v1", CLASSIC_PEOPLE, 4, SOURCE).hex()
        assert (out.ps.modulus, out.ps.number, out.ps.index) == (2, 0, 0)
        assert out.allocation == {"A": "c", "B": "a", "C": "d", "D": "b"}

    def test_the_command_line_prints_the_table_and_the_terms(self):
        done = run_json(classic(), "--json")
        assert done.returncode == 0, done.stderr
        parsed = json.loads(done.stdout)
        certificate = parsed["certificate"]
        assert certificate["probabilities"]["A"] == {
            "slots": {"a": "1/2", "c": "1/2"},
            "no_slot": "0",
        }
        assert [t["weight"] for t in certificate["decomposition"]] == ["1/2", "1/2"]
        assert certificate["draw"] == {
            "modulus": 2,
            "random_number": 0,
            "term": 1,
            "first": 0,
            "last": 0,
        }
        assert parsed["result"]["allocation"] == {"A": "c", "B": "a", "C": "d", "D": "b"}
        assert parsed["result"]["method"] == "ps" and parsed["result"]["rule"] == "ps_bvn_v1"
        assert parsed["inputs_echo"]["method"] == "ps" and parsed["inputs_echo"]["seats"] == 4


# ---------------------------------------------------------------------------------------
# The chances
# ---------------------------------------------------------------------------------------


@PROPERTY
@given(matching_cases())
def test_every_row_adds_up_to_one_and_no_slot_is_given_out_more_than_it_has_seats(case):
    people, slots, prefs, capacities, _, _ = case
    chances = case_outcome(case).ps.chances
    for person in people:
        row = chances[person]
        assert sum(row.values()) == 1
        assert all(value >= 0 for value in row.values())
        for slot in slots:
            assert row[slot] == 0 or slot in prefs[person], "a slot they do not list"
    for slot in slots:
        assert sum(chances[p][slot] for p in people) <= capacities[slot]


@PROPERTY
@given(matching_cases())
def test_the_script_agrees_with_the_independent_simulation(case):
    people, _, prefs, capacities, _, _ = case
    chances = case_outcome(case).ps.chances
    assert chances == eat(sorted(people), prefs, capacities)


@PROPERTY
@given(matching_cases(), st.randoms(use_true_random=False))
def test_the_chances_do_not_depend_on_how_people_prefs_and_slots_are_listed(case, rnd):
    people, slots, prefs, capacities, _, source = case
    first = sl.solve(ps_data(people, slots, prefs, source, capacities=capacities))
    shuffled_people = rnd.sample(people, len(people))
    shuffled_prefs = {p: prefs[p] for p in rnd.sample(list(prefs), len(prefs))}
    second = sl.solve(
        ps_data(shuffled_people, slots, shuffled_prefs, source, capacities=capacities)
    )
    assert fc.envelope(first) == fc.envelope(second)
    for fmt in ("md", "dm", "group"):
        assert fc.render(first, fmt) == fc.render(second, fmt)
    reordered = rnd.sample(slots, len(slots))
    third = sl.solve(ps_data(people, reordered, prefs, source, capacities=capacities))
    assert (
        fc.envelope(third)["certificate"]["probabilities"]
        == (fc.envelope(first)["certificate"]["probabilities"])
    )
    assert fc.envelope(third)["result"]["allocation"] == fc.envelope(first)["result"]["allocation"]
    assert (
        fc.envelope(third)["certificate"]["decomposition"]
        == (fc.envelope(first)["certificate"]["decomposition"])
    )


@PROPERTY
@given(matching_cases(everybody_ranks=True), st.data())
def test_people_with_the_same_ranking_have_the_same_chances(case, data):
    people, slots, prefs, capacities, _, source = case
    twin = data.draw(st.sampled_from(people))
    other = data.draw(st.sampled_from(people))
    prefs = dict(prefs, **{other: list(prefs[twin])})
    chances = outcome(ps_data(people, slots, prefs, source, capacities=capacities)).ps.chances
    assert chances[twin] == chances[other]


# ---------------------------------------------------------------------------------------
# Envy-freeness and efficiency before the draw
# ---------------------------------------------------------------------------------------


@PROPERTY
@given(matching_cases(max_people=6, max_slots=5, max_capacity=3))
def test_nobody_prefers_the_lottery_of_somebody_else(case):
    people, _, prefs, _, _, _ = case
    out = case_outcome(case)
    assert envy_pairs(sorted(people), prefs, out.ps.chances) == []
    assert sl.envy_violations(sorted(people), prefs, out.ps.chances) == []


def test_every_assignment_of_the_classic_example_leaves_one_of_two_people_envious():
    """After the draw there is envy: A and B rank the slots alike, one of them holds c and
    envies the other, who holds a. The envy-freeness of ps is about the lotteries before the draw."""
    out = outcome(classic())
    assert len(out.ps.terms) == 2
    for term in out.ps.terms:
        held = {term.assignment["A"], term.assignment["B"]}
        assert held == {"a", "c"}
        loser = "A" if term.assignment["A"] == "c" else "B"
        assert CLASSIC_PREFS[loser].index("a") < CLASSIC_PREFS[loser].index("c")


def test_the_check_finds_a_person_who_would_prefer_the_lottery_of_another():
    out = outcome(classic())
    chances = {person: dict(row) for person, row in out.ps.chances.items()}
    chances["A"], chances["C"] = chances["C"], chances["A"]  # A now holds the lottery of C
    pairs = envy_pairs(CLASSIC_PEOPLE, CLASSIC_PREFS, chances)
    assert ("A", "B") in pairs or ("A", "C") in pairs
    assert sl.envy_violations(CLASSIC_PEOPLE, CLASSIC_PREFS, chances)


@PROPERTY
@given(matching_cases(max_people=5, max_slots=4, max_capacity=2))
def test_the_chances_are_ordinally_efficient(case):
    pytest.importorskip("scipy")
    people, slots, prefs, capacities, _, _ = case
    chances = case_outcome(case).ps.chances
    assert abs(ordinal_gain(sorted(people), slots, prefs, capacities, chances)) < 1e-9


def test_the_same_check_finds_that_serial_dictatorship_is_not_ordinally_efficient():
    pytest.importorskip("scipy")
    rsd = serial_dictatorship_chances(CLASSIC_PEOPLE, CLASSIC_SLOTS, CLASSIC_PREFS)
    capacity = {s: 1 for s in CLASSIC_SLOTS}
    gain = ordinal_gain(CLASSIC_PEOPLE, CLASSIC_SLOTS, CLASSIC_PREFS, capacity, rsd)
    assert abs(gain - 2 / 3) < 1e-6, (
        "the classic example has a gain of 2/3 over serial dictatorship"
    )
    ps = outcome(classic()).ps.chances
    assert abs(ordinal_gain(CLASSIC_PEOPLE, CLASSIC_SLOTS, CLASSIC_PREFS, capacity, ps)) < 1e-9
    assert all(dominates(CLASSIC_PREFS[p], ps[p], rsd[p]) for p in CLASSIC_PEOPLE)


# ---------------------------------------------------------------------------------------
# The decomposition into fixed assignments
# ---------------------------------------------------------------------------------------


def check_fixed_assignments(people, slots, prefs, capacities, chances, terms):
    """The terms checked from their definition, with nothing taken from the script."""
    assert all(term.weight > 0 for term in terms)
    assert sum(term.weight for term in terms) == 1
    for term in terms:
        assert set(term.assignment) == set(people)
        used = collections.Counter(s for s in term.assignment.values() if s is not None)
        assert all(count <= capacities[s] for s, count in used.items())
        for person, slot in term.assignment.items():
            assert slot is None or slot in prefs[person], "a slot the person does not list"
    for person in people:
        for slot in [*slots, None]:
            got = sum(t.weight for t in terms if t.assignment[person] == slot)
            assert got == chances[person][slot], (person, slot)


@PROPERTY
@given(matching_cases(max_people=6, max_slots=5, max_capacity=3))
def test_the_terms_are_fixed_assignments_that_add_up_to_the_chances(case):
    people, slots, prefs, capacities, _, _ = case
    out = case_outcome(case)
    check_fixed_assignments(sorted(people), slots, prefs, capacities, out.ps.chances, out.ps.terms)


@PROPERTY
@given(matching_cases(max_people=4, max_slots=3, max_capacity=2))
def test_every_fixed_assignment_of_the_decomposition_is_pareto_efficient(case):
    people, slots, prefs, capacities, _, _ = case
    names = sorted(people)
    for term in case_outcome(case).ps.terms:
        assert pareto_improvement(names, slots, capacities, prefs, term.assignment) is None


@PROPERTY
@given(matching_cases(max_people=6, max_slots=5, max_capacity=3))
def test_the_terms_come_by_falling_weight_and_no_assignment_comes_twice(case):
    terms = case_outcome(case).ps.terms
    weights = [t.weight for t in terms]
    assert weights == sorted(weights, reverse=True)
    keys = [tuple(sorted(t.assignment.items())) for t in terms]
    assert len(set(keys)) == len(keys)


@PROPERTY
@given(matching_cases(max_people=6, max_slots=5, max_capacity=3))
def test_the_completion_table_is_square_and_doubly_stochastic_and_holds_the_chances(case):
    people, slots, _, capacities, _, _ = case
    names = sorted(people)
    chances = case_outcome(case).ps.chances
    table, owners = sl.completion_table(names, sorted(slots), capacities, chances)
    size = len(table)
    assert size == len(owners) >= len(names)
    assert all(len(row) == size for row in table)
    assert all(sum(row) == 1 for row in table)
    assert all(sum(table[r][c] for r in range(size)) == 1 for c in range(size))
    for row, person in enumerate(names):
        for slot in slots:
            assert (
                sum(table[row][c] for c in range(size) if owners[c] == slot)
                == chances[person][slot]
            )
        assert sum(table[row][c] for c in range(size) if owners[c] is None) == chances[person][None]


@PROPERTY
@given(matching_cases(max_people=6, max_slots=5, max_capacity=3))
def test_the_number_of_pieces_is_at_most_the_positive_cells_minus_the_side_plus_one(case):
    people, slots, _, capacities, _, _ = case
    chances = case_outcome(case).ps.chances
    table, _ = sl.completion_table(sorted(people), sorted(slots), capacities, chances)
    size = len(table)
    positive = sum(1 for row in table for cell in row if cell > 0)
    pieces = sl.bvn_decompose(table)
    assert len(pieces) <= positive - size + 1
    rebuilt = [[Fraction(0)] * size for _ in range(size)]
    for weight, columns in pieces:
        assert sorted(columns) == list(range(size)), "a piece is not a permutation"
        for row, column in enumerate(columns):
            rebuilt[row][column] += weight
    assert rebuilt == table


def test_a_table_with_known_pieces_is_taken_apart_exactly():
    third = Fraction(1, 3)
    table = [
        [Fraction(1, 2), Fraction(1, 2), Fraction(0)],
        [Fraction(1, 6), third, Fraction(1, 2)],
        [third, Fraction(1, 6), Fraction(1, 2)],
    ]
    pieces = sl.bvn_decompose(table)
    assert sum(weight for weight, _ in pieces) == 1
    rebuilt = [[Fraction(0)] * 3 for _ in range(3)]
    for weight, columns in pieces:
        for row, column in enumerate(columns):
            rebuilt[row][column] += weight
    assert rebuilt == table


def test_another_decomposition_of_the_same_table_pairs_the_outcomes_of_different_people_differently():
    """The classic table has more than one decomposition. Both give every person the same chances,
    and they differ in who gets what together: in one, A holds a exactly when C holds b, in the
    other exactly when C holds d. The decomposition of the script is one of them."""
    half = Fraction(1, 2)
    first = [
        (half, {"A": "a", "B": "c", "C": "b", "D": "d"}),
        (half, {"A": "c", "B": "a", "C": "d", "D": "b"}),
    ]
    second = [
        (half, {"A": "a", "B": "c", "C": "d", "D": "b"}),
        (half, {"A": "c", "B": "a", "C": "b", "D": "d"}),
    ]
    for decomposition in (first, second):
        for person in CLASSIC_PEOPLE:
            for slot in CLASSIC_SLOTS:
                got = sum(w for w, a in decomposition if a[person] == slot)
                assert got == outcome(classic()).ps.chances[person][slot]

    def together(decomposition):
        return sum(w for w, a in decomposition if a["A"] == "a" and a["C"] == "b")

    assert together(first) == half and together(second) == 0
    mine = [(t.weight, t.assignment) for t in outcome(classic()).ps.terms]
    assert together(mine) in (half, 0)


def test_the_identity_table_has_one_piece():
    table = [[Fraction(int(i == j)) for j in range(3)] for i in range(3)]
    assert sl.bvn_decompose(table) == [(Fraction(1), [0, 1, 2])]


def test_a_table_that_is_not_doubly_stochastic_is_refused_not_looped_on():
    table = [[Fraction(1), Fraction(0)], [Fraction(1), Fraction(0)]]
    with pytest.raises(AssertionError):
        sl.bvn_decompose(table)


# ---------------------------------------------------------------------------------------
# Seats and places without a slot
# ---------------------------------------------------------------------------------------


class TestSeatsAndNoSlot:
    def test_a_slot_with_two_seats_can_hold_two_people_in_one_assignment(self):
        people = ["p", "q", "r"]
        prefs = {"p": ["x"], "q": ["x"], "r": ["x", "y"]}
        out = outcome(ps_data(people, ["x", "y"], prefs, capacities={"x": 2}))
        assert any(
            sum(1 for s in term.assignment.values() if s == "x") == 2 for term in out.ps.terms
        )
        assert out.ps.chances["p"]["x"] == Fraction(2, 3)
        assert out.ps.chances["r"] == {"x": Fraction(2, 3), "y": Fraction(1, 3), None: 0}

    def test_more_people_than_seats_leaves_some_without_a_slot_in_every_assignment(self):
        people = ["p", "q", "r"]
        prefs = {p: ["x"] for p in people}
        out = outcome(ps_data(people, ["x"], prefs))
        assert {p: out.ps.chances[p][None] for p in people} == {p: Fraction(2, 3) for p in people}
        for term in out.ps.terms:
            assert sum(1 for s in term.assignment.values() if s is None) == 2
        assert sorted(out.unassigned) == sorted(set(people) - set(out.allocation))
        assert len(out.allocation) == 1

    def test_more_seats_than_people_leaves_seats_free(self):
        out = outcome(
            ps_data(["p", "q"], ["x", "y"], {"p": ["x"], "q": ["x"]}, capacities={"x": 5, "y": 3})
        )
        assert out.allocation == {"p": "x", "q": "x"}
        assert out.free_seats == {"x": 3, "y": 3}
        assert out.unassigned == []

    def test_a_person_who_lists_nothing_never_gets_a_slot_and_is_reported(self):
        prefs = {"p": ["x"], "q": []}
        out = outcome(ps_data(["p", "q"], ["x"], prefs))
        assert out.ps.chances["q"] == {"x": 0, None: 1}
        assert out.allocation == {"p": "x"} and out.unassigned == ["q"]
        message = fc.render_dm_messages(sl.solve(ps_data(["p", "q"], ["x"], prefs)))["q"]
        assert "没有列出能接受的时段" in message

    def test_a_slot_that_nobody_lists_stays_free(self):
        out = outcome(ps_data(["p", "q"], ["x", "y"], {"p": ["x"], "q": ["x"]}))
        assert out.free_seats == {"y": 1}
        assert all(row["y"] == 0 for row in out.ps.chances.values())

    @PROPERTY
    @given(matching_cases(max_people=6, max_slots=4, max_capacity=3))
    def test_the_assignment_drawn_respects_seats_and_lists(self, case):
        people, slots, prefs, capacities, _, _ = case
        out = case_outcome(case)
        used = collections.Counter(out.allocation.values())
        assert all(count <= capacities[slot] for slot, count in used.items())
        for person, slot in out.allocation.items():
            assert slot in prefs[person]
        assert sorted(out.unassigned + list(out.allocation)) == sorted(people)
        assert out.free_seats == {
            slot: capacities[slot] - used[slot] for slot in slots if used[slot] < capacities[slot]
        }


# ---------------------------------------------------------------------------------------
# The draw
# ---------------------------------------------------------------------------------------


def manual_number(seed, modulus):
    """The random number by hand: the rule of the seed mapping, and several draws for a large
    modulus, written again from the description."""
    counter = 0

    def draw():
        nonlocal counter
        block = hashlib.sha256(seed + counter.to_bytes(8, "big")).digest()
        counter += 1
        return int.from_bytes(block[:8], "big")

    if modulus <= 2**64:
        while True:
            x = draw()
            if x < 2**64 - 2**64 % modulus:
                return x % modulus
    words = 1
    while modulus > 2 ** (64 * words):
        words += 1
    while True:
        x = 0
        for _ in range(words):
            x = x * 2**64 + draw()
        if x < 2 ** (64 * words) - 2 ** (64 * words) % modulus:
            return x % modulus


@PROPERTY
@given(matching_cases(max_people=6, max_slots=5, max_capacity=3))
def test_the_random_number_is_the_one_computed_by_hand(case):
    people, _, _, _, _, source = case
    out = case_outcome(case)
    seed = spec_seed("ps_bvn_v1", sorted(people), sum(case[3].values()), source)
    assert out.draws[0].seed_hex == seed.hex()
    assert out.ps.number == manual_number(seed, out.ps.modulus)


@pytest.mark.parametrize("modulus", [1, 2, 3, 12, 2**64 - 1, 2**64, 2**64 + 1, 2**70 + 12345])
def test_a_random_number_below_any_modulus_follows_the_documented_rule(modulus):
    seed = hashlib.sha256(f"modulus {modulus}".encode()).digest()
    assert sl.uniform_below(fc.SeedStream(seed), modulus) == manual_number(seed, modulus)


def test_a_modulus_above_2_to_the_64_takes_two_draws_and_a_rejected_pair_takes_two_more():
    modulus = (
        2**128 - 1
    )  # the largest multiple is 2**128 - 1 itself, so only x = 2**128 - 1 is rejected

    class Scripted:
        def __init__(self, values):
            self.values = list(values)

        def next_u64(self):
            return self.values.pop(0)

        def below(self, n):  # not used above 2**64
            raise AssertionError

    ok = Scripted([1, 5])
    assert sl.uniform_below(ok, modulus) == (1 << 64 | 5) % modulus and ok.values == []
    rejected = Scripted([2**64 - 1, 2**64 - 1, 3, 4])
    assert sl.uniform_below(rejected, modulus) == (3 << 64 | 4) % modulus and rejected.values == []


@PROPERTY
@given(matching_cases(max_people=6, max_slots=5, max_capacity=3))
def test_the_term_drawn_holds_the_number_and_is_the_assignment_given(case):
    out = case_outcome(case)
    ps = out.ps
    term = ps.terms[ps.index]
    assert ps.low <= ps.number < ps.high
    assert ps.high - ps.low == term.weight * ps.modulus
    assert out.allocation == {p: s for p, s in term.assignment.items() if s is not None}
    assert sl.pick_term(ps.terms, ps.modulus, ps.number) == (ps.index, ps.low, ps.high)


@PROPERTY
@given(matching_cases(max_people=5, max_slots=4, max_capacity=2))
def test_every_term_owns_exactly_weight_times_modulus_numbers(case):
    ps = case_outcome(case).ps
    assert ps.modulus == math.lcm(*[t.weight.denominator for t in ps.terms])
    if ps.modulus > 4000:
        return
    owned = collections.Counter(sl.pick_term(ps.terms, ps.modulus, x)[0] for x in range(ps.modulus))
    for index, term in enumerate(ps.terms):
        assert owned[index] == term.weight * ps.modulus
    assert sum(owned.values()) == ps.modulus


def test_a_different_source_gives_another_seed_and_the_same_table():
    first = outcome(classic())
    other = outcome(classic(source=SOURCE + " "))
    assert first.draws[0].seed_hex != other.draws[0].seed_hex
    assert first.ps.chances == other.ps.chances


def test_the_script_draws_each_person_a_slot_with_the_chance_of_the_table():
    """3000 fixed source texts. p0 gets b with chance 3/4 and a with chance 1/4, p2 gets c with 1/2."""
    n = 3000
    got = collections.Counter()
    for i in range(n):
        out = outcome(ps_data(LIE_PEOPLE, LIE_SLOTS, LIE_PREFS, source=f"ps-draw-{i}"))
        for person, slot in out.allocation.items():
            got[(person, slot)] += 1
    chances = outcome(ps_data(LIE_PEOPLE, LIE_SLOTS, LIE_PREFS)).ps.chances
    for person in LIE_PEOPLE:
        for slot in LIE_SLOTS:
            p = float(chances[person][slot])
            sd = (n * p * (1 - p)) ** 0.5
            if sd == 0:
                assert got[(person, slot)] in (0, n)
            else:
                assert abs(got[(person, slot)] - n * p) / sd < 4.5, (person, slot)


# ---------------------------------------------------------------------------------------
# What ps does not promise
# ---------------------------------------------------------------------------------------


class TestNotStrategyProof:
    def chances(self, prefs):
        return outcome(ps_data(LIE_PEOPLE, LIE_SLOTS, prefs)).ps.chances

    def test_the_recorded_tables_before_and_after_the_lie(self):
        truth = self.chances(LIE_PREFS)
        assert truth["p0"] == {"a": frac("1/4"), "b": frac("3/4"), "c": 0, None: 0}
        assert truth["p1"] == {"a": frac("1/2"), "b": 0, "c": frac("1/2"), None: 0}
        assert truth["p2"] == {"a": frac("1/4"), "b": frac("1/4"), "c": frac("1/2"), None: 0}
        lied = self.chances(dict(LIE_PREFS, p0=LIE_REPORT))
        assert lied["p0"] == {"a": frac("1/6"), "b": frac("1/2"), "c": frac("1/3"), None: 0}

    def test_the_lie_lowers_the_chance_of_the_first_choice_and_raises_that_of_the_first_two(self):
        ranking = LIE_PREFS["p0"]
        truth = prefix_sums(ranking, self.chances(LIE_PREFS)["p0"])
        lied = prefix_sums(ranking, self.chances(dict(LIE_PREFS, p0=LIE_REPORT))["p0"])
        assert truth[:2] == [frac("3/4"), frac("3/4")]
        assert lied[:2] == [frac("1/2"), frac("5/6")]

    def test_a_person_who_cares_a_lot_about_the_first_two_gains_by_lying(self):
        ranking = LIE_PREFS["p0"]
        truth = self.chances(LIE_PREFS)["p0"]
        lied = self.chances(dict(LIE_PREFS, p0=LIE_REPORT))["p0"]
        wants_two = utilities_for_prefix(2, 3)
        assert expected_utility(ranking, lied, wants_two) > expected_utility(
            ranking, truth, wants_two
        )
        wants_one = utilities_for_prefix(1, 3)
        assert expected_utility(ranking, lied, wants_one) < expected_utility(
            ranking, truth, wants_one
        )

    def test_such_profiles_exist_among_all_profiles_of_three_people_and_three_slots(self):
        rankings = list(itertools.permutations(LIE_SLOTS))
        capacity = {s: 1 for s in LIE_SLOTS}
        found = []
        for profile in itertools.product(rankings, repeat=3):
            prefs = {p: list(r) for p, r in zip(LIE_PEOPLE, profile)}
            truth = eat(LIE_PEOPLE, prefs, capacity)
            for report in rankings:
                lied = eat(LIE_PEOPLE, dict(prefs, p0=list(report)), capacity)
                before = prefix_sums(prefs["p0"], truth["p0"])
                after = prefix_sums(prefs["p0"], lied["p0"])
                if any(b > a for a, b in zip(before, after)):
                    found.append(profile)
                    break
        assert tuple(tuple(LIE_PREFS[p]) for p in LIE_PEOPLE) in found
        assert len(found) == FOUND_PROFILES


# ---------------------------------------------------------------------------------------
# People without a ranking
# ---------------------------------------------------------------------------------------


class TestNoRanking:
    def data(self, rule):
        prefs = {"p": ["x", "y"], "q": ["x"], "r": ["y", "x"]}
        return ps_data(["p", "q", "r", "s", "t"], ["x", "y", "z"], prefs, no_ranking=rule)

    def test_forfeit_removes_them_before_the_draw(self):
        out = outcome(self.data("forfeit"))
        assert out.removed == ["s", "t"] and out.people == ["p", "q", "r"]
        assert all(person not in out.allocation for person in ("s", "t"))
        assert out.draws[0].members == ["p", "q", "r"]
        assert out.penalized == [] and out.unassigned != ["s", "t"]

    def test_assigned_gives_them_what_is_left_in_the_order_of_slot_names_after_the_draw(self):
        out = outcome(self.data("assigned"))
        assert out.removed == [] and out.people == ["p", "q", "r"]
        assert sorted(out.penalized) == ["s", "t"]
        assert [d.group for d in out.draws] == ["main", "penalty"]
        taken = collections.Counter(s for p, s in out.allocation.items() if p in out.people)
        left = [s for s in ["x", "y", "z"] if taken[s] < 1]
        for person, slot in zip(out.penalized, left):
            assert out.allocation[person] == slot
        assert out.draws[1].members == ["s", "t"]

    def test_the_people_who_take_what_is_left_get_a_message_of_their_own(self):
        messages = fc.render_dm_messages(sl.solve(self.data("assigned")))
        assert "拿剩下的时段" in messages["s"] and "你没交志愿" in messages["s"]
        assert "拿剩下的时段" not in messages["p"]

    def test_a_person_who_is_out_gets_a_message_that_says_so(self):
        messages = fc.render_dm_messages(sl.solve(self.data("forfeit")))
        assert "退出这次分配" in messages["s"]


# ---------------------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------------------


class TestOutput:
    def result(self, lang="zh", **extra):
        return sl.solve(classic(**extra), lang)

    def test_the_md_output_has_the_table_the_terms_the_draw_and_the_schedule(self):
        text = fc.render_md(self.result())
        for needed in (
            "每人拿到每个时段的概率",
            "分解成确定的分配（共 2 种",
            "## 抽取",
            "吃的过程",
            "1/2（50.0%）",
            "ps_bvn_v1",
            CLASSIC_PS_SEED,
        ):
            assert needed in text, needed

    def test_a_private_message_holds_only_the_receivers_chances_and_ranking(self):
        data = load_example("ps_holiday_weeks.json")
        messages = fc.render_dm_messages(sl.solve(data))
        for person, text in messages.items():
            own = " > ".join(data["prefs"][person])
            assert "概率" in text and own in text
            assert "你的第" in text or "没有分到" in text
            for other, ranking in data["prefs"].items():
                if other != person and " > ".join(ranking) != own:
                    assert " > ".join(ranking) not in text
                if other != person and len(other) > 1:
                    assert other not in text, f"{person}'s message names {other}"

    def test_the_message_states_the_envy_check_the_script_has_run(self):
        messages = fc.render_dm_messages(self.result())
        assert all("随机占优意义下无嫉妒" in text for text in messages.values())

    def test_the_group_card_has_the_result_and_the_draw_and_neither_chances_nor_rankings(self):
        text = fc.render_group(self.result())
        assert "A 分到「c」" in text and "B 分到「a」" in text
        assert CLASSIC_PS_SEED in text and "ps_bvn_v1" in text
        assert "抽取：随机数在 0 到 1 之间，抽到 0。" in text
        assert " > " not in text and "%" not in text and "1/2" not in text
        for name in CLASSIC_PEOPLE:
            assert name in text

    def test_the_group_card_does_not_claim_that_cheating_is_impossible(self):
        for lang in ("zh", "en"):
            result = self.result(lang)
            text = fc.render_md(result, lang) + fc.render_group(result)
            for phrase in (
                "无法作弊",
                "不可能作弊",
                "谁也做不了手脚",
                "cannot cheat",
                "tamper-proof",
            ):
                assert phrase not in text

    def test_the_json_certificate_has_the_table_the_schedule_the_terms_and_the_draw(self):
        certificate = fc.envelope(self.result())["certificate"]
        for key in (
            "one_liner",
            "recompute",
            "probabilities",
            "eating",
            "decomposition",
            "draw",
            "checks",
        ):
            assert key in certificate, key
        assert certificate["checks"]["pairs_with_envy"] == []
        assert certificate["checks"]["pairs_checked_for_envy"] == 12
        assert certificate["eating"][0]["used_up"] == ["a", "b"]
        assert certificate["recompute"]["seeds"] == {"main": CLASSIC_PS_SEED}

    def test_english_says_the_same_in_english(self):
        text = fc.render_md(self.result("en"), "en")
        assert "probabilistic serial" in text and "Decomposition into fixed assignments" in text
        messages = fc.render_dm_messages(self.result("en"))
        assert messages["A"].startswith('You got "c" (your choice number')

    def test_the_example_runs_in_every_format_and_language(self):
        data = load_example("ps_holiday_weeks.json")
        for flags in ([], ["--format", "dm"], ["--format", "group"], ["--json"], ["--lang", "en"]):
            done = run_json(data, *flags)
            assert done.returncode == 0, done.stderr
            assert "Traceback" not in done.stdout + done.stderr

    def test_the_example_folder_has_the_input_with_the_method_ps(self):
        data = load_example("ps_holiday_weeks.json")
        assert data["rules"]["method"] == "ps" and data["capacities"] == {"春节前一周": 2}
        assert "虚构示例" in (EXAMPLES / "ps_holiday_weeks.json").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------------------


class TestLimits:
    def test_more_people_than_the_limit_are_refused_naming_the_people(self):
        people = [f"p{i:02d}" for i in range(sl.MAX_PS_PEOPLE + 1)]
        slots = ["x", "y"]
        done = run_json(ps_data(people, slots, {p: slots for p in people}))
        assert done.returncode == 2 and "people" in done.stderr

    def test_a_table_that_is_too_large_is_refused_naming_the_method(self, monkeypatch):
        monkeypatch.setattr(sl, "MAX_PS_TABLE", 3)
        with pytest.raises(fc.InputError) as caught:
            outcome(classic())
        assert caught.value.field == "rules.method" and "ps needs a table of 4 by 4" in str(
            caught.value
        )

    def test_the_largest_allowed_instance_runs_and_its_terms_add_up(self):
        people = [f"p{i:02d}" for i in range(sl.MAX_PS_PEOPLE)]
        slots = [f"s{i:02d}" for i in range(25)]
        rotated = {p: slots[i % 25 :] + slots[: i % 25] for i, p in enumerate(people)}
        out = outcome(ps_data(people, slots, rotated, capacities={s: 2 for s in slots}))
        check_fixed_assignments(
            people, slots, rotated, {s: 2 for s in slots}, out.ps.chances, out.ps.terms
        )
        assert sl.envy_violations(people, rotated, out.ps.chances) == []

    def test_the_largest_table_still_runs(self):
        people = [f"p{i:02d}" for i in range(40)]
        slots = [f"s{i:02d}" for i in range(40)]
        rotated = {p: slots[i:] + slots[:i] for i, p in enumerate(people)}
        done = run_json(ps_data(people, slots, rotated), "--json")
        assert done.returncode == 0, done.stderr
        assert len(json.loads(done.stdout)["certificate"]["decomposition"]) >= 1


def test_the_demo_input_still_means_the_uniform_lottery():
    done = run_script("--demo", "--json")
    assert json.loads(done.stdout)["result"]["rule"] == "uniform_lottery_v1"


def test_the_serial_dictatorship_chances_by_enumeration_are_what_the_docs_quote():
    rsd = serial_dictatorship_chances(CLASSIC_PEOPLE, CLASSIC_SLOTS, CLASSIC_PREFS)
    assert [rsd["A"][s] for s in CLASSIC_SLOTS] == [frac("5/12"), frac("1/12")] * 2
