"""Property tests of the knaster rule, with and without weights (hypothesis).

Every property is checked against the plain formulas of the reference module. The values come
from the same generator as the other rules, so ties and zero values are common.
"""

from __future__ import annotations

from fractions import Fraction

import pytest
import stuff_split as ss
import stuff_split_reference as ref
from hypothesis import given
from hypothesis import strategies as st
from stuff_split_strategies import SETTINGS, value_matrices, weight_lists
from stuff_split_support import matrix_input, piano

fc = ss.fc


def solve(rows, weights=None, **rules):
    if weights is not None:
        rules["weights"] = {f"p{p}": w for p, w in enumerate(weights)}
    return ss.compute(ss.parse_problem(matrix_input(rows, "knaster", **rules)))


def owners_of(outcome, rows):
    return [int(outcome.owner[f"g{j}"][1:]) for j in range(len(rows[0]))]


@st.composite
def cases(draw):
    rows = draw(value_matrices())
    weights = draw(st.one_of(st.none(), weight_lists(len(rows))))
    return rows, weights


# --------------------------------------------------------------------------------------
# What the numbers must satisfy
# --------------------------------------------------------------------------------------


@SETTINGS
@given(cases())
def test_every_item_goes_to_a_person_who_values_it_most(case):
    rows, weights = case
    outcome = solve(rows, weights)
    owner = owners_of(outcome, rows)
    best = ref.highest(rows)
    assert all(rows[owner[j]][j] == best[j] for j in range(len(best)))
    assert outcome.total_best == ref.welfare(rows)


@SETTINGS
@given(cases())
def test_each_person_ends_with_the_fair_share_plus_a_part_of_the_surplus(case):
    rows, weights = case
    outcome = solve(rows, weights)
    owner = owners_of(outcome, rows)
    fair, surplus, cash = ref.knaster_exact(rows, owner, weights)
    people = [f"p{p}" for p in range(len(rows))]
    assert [outcome.fair_exact[p] for p in people] == fair
    assert outcome.surplus == surplus
    assert [outcome.exact_cash[p] for p in people] == cash


@SETTINGS
@given(cases())
def test_the_surplus_is_never_negative_and_the_exact_cash_adds_up_to_zero(case):
    rows, weights = case
    outcome = solve(rows, weights)
    assert outcome.surplus >= 0
    assert sum(outcome.exact_cash.values()) == 0


@SETTINGS
@given(cases())
def test_nobody_ends_below_the_fair_share_which_is_rounded_down_to_the_cent(case):
    rows, weights = case
    outcome = solve(rows, weights)
    n = len(rows)
    for p in range(n):
        name = f"p{p}"
        exact_worth = outcome.fair_exact[name] + outcome.shares[name] * outcome.surplus
        assert exact_worth >= outcome.fair_exact[name]
        assert outcome.worth[name] >= int(outcome.fair_exact[name] // 1)


@SETTINGS
@given(cases())
def test_the_rounded_cash_adds_up_to_zero_and_is_within_a_cent_of_the_exact_cash(case):
    rows, weights = case
    outcome = solve(rows, weights)
    assert sum(outcome.cash.values()) == 0
    for name, cash in outcome.cash.items():
        assert abs(cash - outcome.exact_cash[name]) < 1


@SETTINGS
@given(value_matrices(), st.sampled_from([1, 2, 3, 7]))
def test_equal_weights_of_any_size_are_the_same_as_no_weights(rows, size):
    plain = solve(rows)
    equal = solve(rows, [size] * len(rows))
    assert plain.cash == equal.cash and plain.owner == equal.owner
    assert (
        plain.shares == equal.shares == {f"p{p}": Fraction(1, len(rows)) for p in range(len(rows))}
    )


@SETTINGS
@given(cases(), st.sampled_from([2, 5, 10]))
def test_only_the_proportions_of_the_weights_count(case, factor):
    rows, weights = case
    if weights is None:
        weights = [1] * len(rows)
    scaled = [Fraction(w * factor, 1000) for w in weights]
    assert solve(rows, weights).cash == solve(rows, scaled).cash


@SETTINGS
@given(value_matrices())
def test_the_final_worth_is_the_same_whichever_source_settles_the_ties(rows):
    sources = ["（虚构）第一期", "（虚构）第二期", "（虚构）第三期"]
    worths = []
    for source in sources:
        outcome = solve(rows, random_source=source)
        worths.append(
            [
                outcome.fair_exact[p] + outcome.shares[p] * outcome.surplus
                for p in outcome.fair_exact
            ]
        )
    assert worths[0] == worths[1] == worths[2]


# --------------------------------------------------------------------------------------
# The piano, envy and shading
# --------------------------------------------------------------------------------------


def test_the_piano_example_matches_the_recorded_cash_and_the_first_heir_envies_the_third():
    outcome = ss.compute(ss.parse_problem(piano("knaster")))
    assert outcome.cash == {"甲": 10111, "乙": -49889, "丙": 39778}
    assert outcome.worth == {"甲": 10111, "乙": 40111, "丙": 39778}
    assert outcome.envy["甲"] == {"丙": 39778 - 10111}
    assert outcome.envy["乙"] == {} and outcome.envy["丙"] == {}


@SETTINGS
@given(value_matrices())
def test_the_envy_the_script_reports_is_the_envy_of_the_plain_formula(rows):
    outcome = solve(rows)
    owner = owners_of(outcome, rows)
    # The envy that the script reports is the envy the plain formula finds, rounded cash included.
    assert outcome.max_envy == ref.exact_envy(
        rows, owner, [outcome.cash[f"p{p}"] for p in range(len(rows))]
    )


def test_some_inputs_leave_envy_and_some_do_not():
    assert solve([[0], [10000], [8900]]).max_envy > 0
    assert solve([[500, 500], [500, 500]]).max_envy == 0


def test_the_winner_can_gain_by_understating_so_the_rule_is_not_strategy_proof():
    honest = solve([[10000], [6000]])
    assert honest.cash["p0"] == -4000  # the first person pays 40.00 and keeps a worth of 60.00
    shaded = solve([[7000], [6000]])  # the first person reports 70.00 instead of 100.00
    assert shaded.cash["p0"] == -3250
    assert 10000 + shaded.cash["p0"] == 6750 > 10000 + honest.cash["p0"]


def test_unequal_weights_move_the_fair_shares_and_the_surplus():
    outcome = ss.compute(ss.parse_problem(piano("knaster", weights={"甲": 2, "乙": 1, "丙": 1})))
    assert outcome.shares == {"甲": Fraction(1, 2), "乙": Fraction(1, 4), "丙": Fraction(1, 4)}
    assert outcome.fair_exact == {"甲": 0, "乙": Fraction(22500), "丙": Fraction(22250)}
    assert outcome.surplus == 45250  # 900.00 minus the fair shares 225.00 and 222.50
    assert outcome.exact_cash == {
        "甲": Fraction(22625),
        "乙": Fraction(-112375, 2),
        "丙": Fraction(67125, 2),
    }
    assert sum(outcome.cash.values()) == 0
    assert outcome.cash["甲"] == 22625 and {outcome.cash["乙"], outcome.cash["丙"]} <= {
        -56187,
        -56188,
        33562,
        33563,
    }


def test_weights_belong_to_knaster_alone():
    for method in ("envy_free", "max_nash"):
        data = piano(method, weights={"甲": 2, "乙": 1, "丙": 1})
        with pytest.raises(fc.InputError) as caught:
            ss.parse_problem(data)
        assert caught.value.field == "rules.weights"
