"""Property tests of the max_nash rule and of the turns that replace it for large inputs.

The result is compared with a plain search over every allocation written for the tests. The
properties of the result (EF1 and Pareto efficiency) are checked on every example by trying
every allocation again, and the cases include zero values and fewer items than people.
"""

from __future__ import annotations

import time
from fractions import Fraction

import stuff_split as ss
import stuff_split_reference as ref
from hypothesis import assume, given
from hypothesis import strategies as st
from stuff_split_strategies import HEAVY, SETTINGS, small_matrices, value_matrices
from stuff_split_support import (
    ROOMMATE_VALUES,
    ROOMMATES,
    STUFF,
    example,
    matrix_input,
    roommates,
)

fc = ss.fc


def solve(rows, method="max_nash", **rules):
    return ss.compute(ss.parse_problem(matrix_input(rows, method, **rules)))


def solve_turns(rows, limit=1, **rules):
    """Solve with a limit so low that the script takes turns."""
    problem = ss.parse_problem(matrix_input(rows, "max_nash", **rules))
    old = ss.MAX_ALLOCATIONS
    ss.MAX_ALLOCATIONS = limit
    try:
        return ss.compute(problem)
    finally:
        ss.MAX_ALLOCATIONS = old


def owners_of(outcome, rows):
    return [int(outcome.owner[f"g{j}"][1:]) for j in range(len(rows[0]))]


def evenness(rows, owner):
    return sum(owner.count(p) ** 2 for p in range(len(rows)))


# --------------------------------------------------------------------------------------
# The search
# --------------------------------------------------------------------------------------


@HEAVY
@given(small_matrices())
def test_the_best_key_is_the_best_of_a_plain_search_over_every_allocation(rows):
    outcome = solve(rows)
    assert not outcome.fell_back
    assert (outcome.nash.n_positive, outcome.nash.product) == ref.best_nash_key(rows)
    assert outcome.allocations == len(rows) ** len(rows[0])


@SETTINGS
@given(small_matrices())
def test_among_the_best_allocations_the_most_even_wins_and_then_the_first_in_order(rows):
    outcome = solve(rows)
    best = ref.optimal_nash_owners(rows)
    expected = min(best, key=lambda owner: (evenness(rows, owner), owner))
    assert owners_of(outcome, rows) == list(expected)


@SETTINGS
@given(small_matrices())
def test_the_search_counts_the_best_allocations_and_the_most_even_of_them(rows):
    outcome = solve(rows)
    best = ref.optimal_nash_owners(rows)
    fewest = min(evenness(rows, owner) for owner in best)
    assert outcome.nash.n_optimal == len(best)
    assert outcome.nash.evenness == fewest
    assert outcome.nash.n_best_even == sum(1 for owner in best if evenness(rows, owner) == fewest)
    assert outcome.was_tie == (outcome.nash.n_best_even > 1)


@HEAVY
@given(small_matrices())
def test_the_result_is_envy_free_up_to_one_item_whatever_the_values(rows):
    outcome = solve(rows)
    owner = owners_of(outcome, rows)
    assert ref.is_ef1(rows, owner)
    assert all(step.status == ss.EF1_HOLDS for step in outcome.ef1.values())


@HEAVY
@given(small_matrices())
def test_the_result_is_pareto_efficient_whatever_the_values(rows):
    outcome = solve(rows)
    assert ref.is_pareto_efficient(rows, owners_of(outcome, rows))


@SETTINGS
@given(small_matrices(), st.sampled_from([2, 3, 10]), st.integers(min_value=0, max_value=3))
def test_when_everybody_gets_something_multiplying_one_persons_values_changes_nothing(
    rows, factor, who
):
    base = solve(rows)
    assume(base.nash.n_positive == len(rows))
    who %= len(rows)
    scaled = [[x * factor for x in row] if p == who else list(row) for p, row in enumerate(rows)]
    again = solve(scaled)
    assert again.owner == base.owner and again.nash.n_optimal == base.nash.n_optimal


def test_when_not_everybody_can_get_something_the_scale_of_a_person_can_matter():
    # One item for two people: the product is the value of whoever gets it, so the person
    # with the larger number wins. Multiplying one person's numbers moves the item.
    assert solve([[100], [100]]).owner == {"g0": "p0"}
    assert solve([[100], [200]]).owner == {"g0": "p1"}


@SETTINGS
@given(small_matrices())
def test_the_envy_reported_is_the_envy_of_the_plain_formula(rows):
    outcome = solve(rows)
    owner = owners_of(outcome, rows)
    assert outcome.max_envy == ref.exact_envy(rows, owner, [0] * len(rows))
    assert outcome.cash == {f"p{p}": 0 for p in range(len(rows))}


def test_the_result_does_not_depend_on_the_order_of_listing():
    first = ss.compute(ss.parse_problem(roommates()))
    data = roommates()
    data["people"].reverse()
    data["items"].reverse()
    data["values"] = {
        name: list(reversed(data["values"][name])) for name in reversed(data["people"])
    }
    second = ss.compute(ss.parse_problem(data))
    assert first.owner == second.owner


# --------------------------------------------------------------------------------------
# The roommates
# --------------------------------------------------------------------------------------


def test_the_roommates_example_gives_the_recorded_allocation():
    outcome = ss.compute(ss.parse_problem(roommates()))
    assert outcome.bundles == {
        "阿明": ["冰箱", "电视"],
        "小红": ["洗衣机", "书架"],
        "大刘": ["沙发", "微波炉"],
    }
    assert outcome.own == {"阿明": 4500, "小红": 4000, "大刘": 4000}
    assert (outcome.nash.n_positive, outcome.nash.product) == (3, 4500 * 4000 * 4000)


def test_two_allocations_tie_in_the_roommates_example_and_the_more_even_one_is_taken():
    outcome = ss.compute(ss.parse_problem(roommates()))
    assert outcome.nash.n_optimal == 2 and outcome.nash.n_best_even == 1
    assert not outcome.was_tie  # the numbers of items settled it, so no order was needed
    # The other allocation gives 阿明 only the fridge and 小红 three items, with the same product.
    values = [[x * 100 for x in ROOMMATE_VALUES[name]] for name in ROOMMATES]
    best = ref.optimal_nash_owners(values)
    assert len(best) == 2
    assert sorted(evenness(values, owner) for owner in best) == [12, 14]
    taken = [ROOMMATES.index(outcome.owner[item]) for item in STUFF]
    assert evenness(values, taken) == 12 and taken in [list(owner) for owner in best]


def test_in_the_roommates_example_two_people_envy_the_first_and_one_item_removes_it():
    outcome = ss.compute(ss.parse_problem(roommates()))
    assert outcome.envy == {"阿明": {}, "小红": {"阿明": 500}, "大刘": {"阿明": 500}}
    steps = {key: (s.item, s.item_value, s.rest) for key, s in outcome.ef1.items()}
    assert steps == {("小红", "阿明"): ("冰箱", 2500, 2000), ("大刘", "阿明"): ("冰箱", 3500, 1000)}
    values = [[x * 100 for x in ROOMMATE_VALUES[name]] for name in ROOMMATES]
    owner = [ROOMMATES.index(outcome.owner[item]) for item in STUFF]
    assert not ref.is_envy_free(values, owner)
    assert ref.is_ef1(values, owner) and ref.is_pareto_efficient(values, owner)


def test_a_tie_that_the_counts_leave_open_is_settled_by_the_name_order_or_the_source():
    rows = [[1000, 1000], [1000, 1000]]
    by_name = solve(rows)
    assert by_name.owner == {"g0": "p0", "g1": "p1"} and by_name.was_tie
    drawn = fc.seeded_order(ss.RULE_NAME, ["p0", "p1"], 2, "（虚构）某一期")
    chosen = solve(rows, random_source="（虚构）某一期")
    assert chosen.priority.order == list(drawn.order)
    assert chosen.owner["g0"] == drawn.order[0] and chosen.owner["g1"] == drawn.order[1]
    owners = {solve(rows, random_source=f"（虚构）第 {k} 期").owner["g0"] for k in range(1, 9)}
    assert owners == {"p0", "p1"}


# --------------------------------------------------------------------------------------
# Few items, zero values, strategy
# --------------------------------------------------------------------------------------


def test_with_fewer_items_than_people_the_people_who_get_something_are_as_many_as_possible():
    rows = [[500, 400], [450, 600], [700, 100]]
    outcome = solve(rows)
    assert outcome.nash.n_positive == 2
    assert sorted(len(v) for v in outcome.bundles.values()) == [0, 1, 1]
    assert ref.is_ef1(rows, owners_of(outcome, rows))


@SETTINGS
@given(value_matrices(min_people=3, max_people=4, max_items=3))
def test_a_person_with_nothing_of_value_never_makes_the_rule_fail(rows):
    rows = [[0] * len(rows[0]), *rows[1:]]
    outcome = solve(rows)
    assert ref.is_ef1(rows, owners_of(outcome, rows))
    assert outcome.own["p0"] == 0


def test_an_item_nobody_wants_is_given_out_and_the_notes_say_so():
    outcome = solve([[500, 0], [300, 0]])
    notes = "\n".join(ss.build_result(outcome, "en").notes)
    assert "Nobody wants g1" in notes
    assert outcome.owner["g1"] in {"p0", "p1"}


def test_a_person_can_gain_by_misreporting_so_the_rule_is_not_strategy_proof():
    true_values = [[500, 300, 400], [200, 500, 600]]
    honest = solve(true_values)
    lie = solve([[100, 100, 100], [200, 500, 600]])  # the first person reports flat values
    assert honest.nash.n_optimal == 1 and lie.nash.n_optimal == 1
    owner_honest = owners_of(honest, true_values)
    owner_lie = owners_of(lie, true_values)
    assert ref.own_value(true_values, owner_honest, 0) == 500
    assert ref.own_value(true_values, owner_lie, 0) == 800


# --------------------------------------------------------------------------------------
# Too many allocations: taking turns
# --------------------------------------------------------------------------------------


@SETTINGS
@given(value_matrices(min_people=2, max_people=4, max_items=8))
def test_turns_replace_the_search_above_the_limit_and_give_envy_freeness_up_to_one_item(rows):
    outcome = solve_turns(rows)
    assert outcome.fell_back and outcome.used == "round_robin" and outcome.nash is None
    owner = owners_of(outcome, rows)
    assert ref.is_ef1(rows, owner)
    assert owner == ref.round_robin_owner(rows, list(range(len(rows))))


def test_the_picks_follow_the_priority_order_and_take_every_item_once():
    rows = [[500, 100, 300], [400, 450, 100], [100, 200, 800]]
    outcome = solve_turns(rows, limit=5, random_source="（虚构）某一期")
    order = fc.seeded_order(ss.RULE_NAME, outcome.problem.people, 3, "（虚构）某一期").order
    assert [person for person, _ in outcome.picks] == order
    assert sorted(item for _, item in outcome.picks) == ["g0", "g1", "g2"]
    assert outcome.priority.method == "random_source"


def test_turns_are_not_promised_to_be_pareto_efficient():
    # The first person likes all three items alike and takes the first one by name. The second
    # person values that item twice as much as the others. Giving it to the second person and
    # the other two to the first leaves the first person as well off and the second better off.
    rows = [[100, 100, 100], [200, 100, 100]]
    outcome = solve_turns(rows)
    owner = owners_of(outcome, rows)
    assert owner == [0, 1, 0] and not ref.is_pareto_efficient(rows, owner)
    assert ref.is_ef1(rows, owner)
    assert ref.is_pareto_efficient(rows, owners_of(solve(rows), rows))


def test_the_fourteen_item_example_is_above_the_limit_and_says_so_everywhere():
    data = example("moving_out_14_items")
    outcome = ss.compute(ss.parse_problem(data))
    assert outcome.fell_back and outcome.allocations == 3**14 > ss.MAX_ALLOCATIONS
    result = ss.build_result(outcome, "zh")
    md = fc.render_md(result, "zh")
    group = fc.render_group(result)
    assert "东西太多" in md and "改用轮流挑" in md
    assert "东西太多" in group and "不保证帕累托有效" in group
    assert all("东西太多" in "\n".join(lines) for lines in result.person_lines.values())
    envelope = fc.envelope(result)
    assert envelope["result"]["fell_back"] is True
    assert envelope["result"]["method"] == "max_nash"
    assert envelope["result"]["method_used"] == "round_robin"
    assert envelope["certificate"]["recompute"]["allocations"] == str(3**14)
    english = fc.render_md(ss.build_result(outcome, "en"), "en")
    assert "Too many items" in english and "does not promise Pareto efficiency" in english


def test_the_limit_is_two_million_and_the_search_just_below_it_runs():
    assert ss.MAX_ALLOCATIONS == 2_000_000
    assert 3**13 <= ss.MAX_ALLOCATIONS < 3**14
    assert 2**20 <= ss.MAX_ALLOCATIONS < 2**21
    rows = [[(7 * p + 3 * j) % 11 + 1 for j in range(13)] for p in range(3)]
    started = time.time()
    outcome = solve([[x * 100 for x in row] for row in rows])
    assert not outcome.fell_back and outcome.allocations == 3**13
    assert all(step.status == ss.EF1_HOLDS for step in outcome.ef1.values())
    assert time.time() - started < 60


def test_two_people_and_twenty_items_are_searched_and_twenty_one_take_turns():
    for items, searched in ((20, True), (21, False)):
        row = [(5 * j) % 7 + 1 for j in range(items)]
        rows = [[x * 100 for x in row], [x * 100 for x in reversed(row)]]
        data = matrix_input(rows, "max_nash")
        # g10 sorts before g2, so the tie rule works on the sorted names. Only the mode matters.
        assert ss.compute(ss.parse_problem(data)).fell_back is (not searched)


def test_the_value_of_a_product_is_written_in_units():
    assert ss.product_text(4500 * 4000 * 4000, 3) == "72000"
    assert ss.product_text(150 * 250, 2) == "3.75"
    assert ss.product_text(1, 0) == "0"
    assert Fraction(ss.product_text(12345, 1)) == Fraction(12345, 100)
