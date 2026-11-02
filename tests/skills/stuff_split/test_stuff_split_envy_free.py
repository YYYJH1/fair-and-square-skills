"""Property tests of the envy_free rule (hypothesis).

Each property is checked on random values with an independent computation in the test, in exact
arithmetic wherever the claim is exact. The reference code works on lists and indices and shares
no code with the script.
"""

from __future__ import annotations

import itertools
import math
import random
from fractions import Fraction

import stuff_split as ss
import stuff_split_reference as ref
from hypothesis import given
from stuff_split_strategies import SETTINGS, small_matrices, value_matrices
from stuff_split_support import matrix_input, piano

fc = ss.fc

SOURCES = ["（虚构）第一期", "（虚构）第二期", "（虚构）第三期", "（虚构）第四期", "fictional 5"]


def solve(rows, method="envy_free", **rules):
    return ss.compute(ss.parse_problem(matrix_input(rows, method, **rules)))


def owners_of(outcome, rows):
    """The owner list of the outcome as person indices."""
    return [int(outcome.owner[f"g{j}"][1:]) for j in range(len(rows[0]))]


def exact_cash(outcome, rows):
    return [outcome.exact_cash[f"p{p}"] for p in range(len(rows))]


# --------------------------------------------------------------------------------------
# What the numbers must satisfy
# --------------------------------------------------------------------------------------


@SETTINGS
@given(value_matrices())
def test_every_item_goes_to_a_person_who_values_it_most_and_the_cash_adds_up_to_zero(rows):
    outcome = solve(rows)
    owner = owners_of(outcome, rows)
    best = ref.highest(rows)
    assert all(rows[owner[j]][j] == best[j] for j in range(len(best)))
    assert sum(outcome.cash.values()) == 0
    assert sum(exact_cash(outcome, rows)) == 0
    assert outcome.total_best == ref.welfare(rows)


@SETTINGS
@given(value_matrices())
def test_everybody_ends_with_the_same_worth_in_exact_arithmetic(rows):
    outcome = solve(rows)
    owner = owners_of(outcome, rows)
    common = Fraction(ref.welfare(rows), len(rows))
    assert outcome.worth_exact == common
    for p in range(len(rows)):
        assert ref.own_value(rows, owner, p) + exact_cash(outcome, rows)[p] == common


@SETTINGS
@given(value_matrices())
def test_nobody_envies_anybody_in_exact_arithmetic(rows):
    outcome = solve(rows)
    owner = owners_of(outcome, rows)
    assert ref.exact_envy(rows, owner, exact_cash(outcome, rows)) == 0


@SETTINGS
@given(value_matrices())
def test_nobody_ends_below_one_nth_of_their_own_total_value(rows):
    outcome = solve(rows)
    n = len(rows)
    for p in range(n):
        assert outcome.worth_exact >= Fraction(sum(rows[p]), n)
        assert outcome.worth[f"p{p}"] >= sum(rows[p]) // n  # rounded down to the cent


@SETTINGS
@given(small_matrices())
def test_the_common_worth_is_the_largest_smallest_worth_of_any_allocation_with_cash(rows):
    outcome = solve(rows)
    assert outcome.worth_exact == ref.largest_smallest_worth(rows)


@SETTINGS
@given(value_matrices())
def test_the_rounded_cash_adds_up_and_is_within_a_cent_of_the_exact_cash(rows):
    outcome = solve(rows)
    exact = exact_cash(outcome, rows)
    for p in range(len(rows)):
        assert abs(outcome.cash[f"p{p}"] - exact[p]) < 1
    assert sum(outcome.cash.values()) == 0


@SETTINGS
@given(value_matrices())
def test_rounded_worths_differ_by_at_most_one_cent_and_the_largest_envy_is_at_most_one_cent(rows):
    outcome = solve(rows)
    low = ref.welfare(rows) // len(rows)
    assert set(outcome.worth.values()) <= {low, low + 1}
    assert 0 <= outcome.max_envy <= 1


def test_with_more_than_eight_people_the_rounding_keeps_the_same_bounds():
    # Above 8 people the search for the best rounding is no longer exhaustive. Any rounding
    # that only goes down or up to the next cent keeps the bounds, so they must still hold.
    rng = random.Random(8)
    for people, items in ((9, 3), (10, 5), (11, 4), (12, 8), (12, 2)):
        for _ in range(8):
            unit = rng.choice([1, 7, 333])
            rows = [[rng.randint(0, 6) * unit for _ in range(items)] for _ in range(people)]
            outcome = solve(rows)
            low = ref.welfare(rows) // people
            assert set(outcome.worth.values()) <= {low, low + 1}
            assert sum(outcome.cash.values()) == 0 and 0 <= outcome.max_envy <= 1
            exact = exact_cash(outcome, rows)
            assert all(abs(outcome.cash[f"p{p}"] - exact[p]) < 1 for p in range(people))


@SETTINGS
@given(small_matrices())
def test_the_rounding_has_the_smallest_possible_largest_envy(rows):
    outcome = solve(rows)
    owner = owners_of(outcome, rows)
    n = len(rows)
    floors = [math.floor(x) for x in ref.envy_free_exact_cash(rows, owner)]
    up_count = -sum(floors)
    best = min(
        ref.exact_envy(rows, owner, [f + (p in up) for p, f in enumerate(floors)])
        for up in itertools.combinations(range(n), up_count)
    )
    assert outcome.max_envy == best


@SETTINGS
@given(small_matrices())
def test_every_division_to_top_valuers_is_envy_free_so_a_tie_may_go_either_way(rows):
    for owner in ref.all_top_valuer_owners(rows):
        cash = ref.envy_free_exact_cash(rows, owner)
        assert ref.exact_envy(rows, owner, cash) == 0
        assert {ref.own_value(rows, owner, p) + cash[p] for p in range(len(rows))} == {
            Fraction(ref.welfare(rows), len(rows))
        }


@SETTINGS
@given(value_matrices())
def test_the_final_worth_is_the_same_whichever_source_settles_the_ties(rows):
    results = [solve(rows, random_source=source) for source in SOURCES]
    worths = {outcome.worth_exact for outcome in results}
    assert worths == {Fraction(ref.welfare(rows), len(rows))}
    for outcome in results:
        owner = owners_of(outcome, rows)
        assert all(rows[owner[j]][j] == max(row[j] for row in rows) for j in range(len(owner)))


# --------------------------------------------------------------------------------------
# Ties, rounding and the piano
# --------------------------------------------------------------------------------------


def test_items_that_two_people_value_equally_are_spread_over_them():
    rows = [[1000] * 4, [1000] * 4]
    outcome = solve(rows)
    assert sorted(len(outcome.bundles[f"p{p}"]) for p in range(2)) == [2, 2]
    assert outcome.cash == {"p0": 0, "p1": 0}
    assert outcome.tops.tied == ["g0", "g1", "g2", "g3"]
    assert outcome.tops.needs_order == ["g0", "g2"]  # the other two were settled by the counts


def test_the_name_order_or_the_source_settles_a_tie_that_the_counts_leave_open():
    rows = [[500], [500]]
    by_name = solve(rows)
    assert by_name.owner == {"g0": "p0"}
    assert by_name.priority.method == "sorted_names" and by_name.was_tie
    owners = {solve(rows, random_source=source).owner["g0"] for source in SOURCES}
    assert owners == {"p0", "p1"}
    drawn = fc.seeded_order(ss.RULE_NAME, ["p0", "p1"], 1, SOURCES[0])
    assert solve(rows, random_source=SOURCES[0]).owner["g0"] == drawn.order[0]


def test_the_piano_gives_everybody_300_and_nobody_envies():
    outcome = ss.compute(ss.parse_problem(piano("envy_free")))
    assert outcome.cash == {"甲": 30000, "乙": -60000, "丙": 30000}
    assert outcome.worth == {"甲": 30000, "乙": 30000, "丙": 30000}
    assert outcome.max_envy == 0 and outcome.bundles["乙"] == ["钢琴"]


def test_rounding_can_leave_one_cent_of_envy_and_the_certificate_says_so():
    # One item worth 100.01 to the third person and nothing to the others. 10001 cents do not
    # divide by 3, two people must be rounded up, and one of the two empty-handed people then
    # envies the other by one cent.
    outcome = solve([[0], [0], [10001]])
    assert outcome.max_envy == 1
    envious = [name for name, row in outcome.envy.items() if row]
    assert len(envious) == 1
    for lang, words in (("zh", "取整"), ("en", "rounding")):
        line = ss.certificate_line(outcome, envious[0], lang)
        assert words in line and "0.01" in line


def test_a_person_who_shades_a_value_can_gain_so_the_rule_is_not_strategy_proof():
    honest = solve([[10000], [6000]])
    assert honest.worth == {"p0": 5000, "p1": 5000}
    shaded = solve([[6100], [6000]])  # the first person reports 61.00 instead of 100.00
    owner = shaded.owner["g0"]
    assert owner == "p0"
    true_worth = 10000 + shaded.cash["p0"]
    assert true_worth == 6950 and true_worth > honest.worth["p0"]


@SETTINGS
@given(value_matrices())
def test_when_the_two_rules_with_cash_differ_somebody_gets_less_under_either(rows):
    envy_free = solve(rows)
    knaster = solve(rows, "knaster")
    n = len(rows)
    common = envy_free.worth_exact
    under_knaster = [
        knaster.fair_exact[f"p{p}"] + knaster.shares[f"p{p}"] * knaster.surplus for p in range(n)
    ]
    assert sum(under_knaster) == n * common  # both rules hand out the same total
    if any(worth != common for worth in under_knaster):
        assert any(worth > common for worth in under_knaster)  # somebody has less here
        assert any(worth < common for worth in under_knaster)  # and somebody has less there


def test_in_the_piano_example_two_heirs_get_less_than_under_knaster():
    knaster = ss.compute(ss.parse_problem(piano("knaster")))
    envy_free = ss.compute(ss.parse_problem(piano("envy_free")))
    assert [knaster.worth[name] for name in ("甲", "乙", "丙")] == [10111, 40111, 39778]
    assert [envy_free.worth[name] for name in ("甲", "乙", "丙")] == [30000] * 3
    assert (
        envy_free.worth["乙"] < knaster.worth["乙"] and envy_free.worth["丙"] < knaster.worth["丙"]
    )
