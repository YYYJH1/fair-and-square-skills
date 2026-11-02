"""Properties that hold for any ballots, checked against plain reference implementations."""

from __future__ import annotations

import itertools
import random
from fractions import Fraction

import fsq_core as fc
import group_vote as gv
import pytest
import vote_reference as ref
from hypothesis import assume, given
from hypothesis import strategies as st
from vote_support import (
    PROPERTY,
    RANKED_METHODS,
    SOURCE,
    input_for,
    make_input,
    option_lists,
    ranked_profiles,
)

COUNTED_BY_THE_REFERENCE = ["plurality", "runoff", "irv", "borda", "condorcet", "schulze"]


def solve(data, **kwargs) -> dict:
    return fc.envelope(gv.solve(data, **kwargs))


def tie_order_names(data) -> list[str]:
    election = gv.parse_election(data)
    order, _ = gv.tie_order(election)
    return [election.options[i] for i in order]


def expanded(lines):
    return ref.expand(lines)


class TestBallotCountsAreConserved:
    @PROPERTY
    @given(ranked_profiles(partial=True))
    def test_merged_lines_keep_every_ballot(self, profile):
        options, lines = profile
        data = input_for(options, lines, "plurality", partial=True)
        election = gv.parse_election(data)
        assert election.n_ballots == sum(count for count, _ in lines)
        assert sum(count for count, _ in election.lines) == election.n_ballots
        echo = solve(data)["inputs_echo"]
        assert echo["ballot_total"] == sum(count for count, _ in lines)
        assert sum(line["count"] for line in echo["ballot_lines"]) == echo["ballot_total"]

    @PROPERTY
    @given(ranked_profiles(partial=True))
    def test_first_choices_and_rounds_account_for_every_ballot(self, profile):
        options, lines = profile
        total = sum(count for count, _ in lines)
        plurality = solve(input_for(options, lines, "plurality", True))["result"]
        assert sum(plurality["scores"].values()) == total
        runoff = solve(input_for(options, lines, "runoff", True))["result"]
        assert sum(runoff["round_1"]["votes"].values()) == total
        if runoff["round_2"]:
            second = runoff["round_2"]
            assert sum(second["votes"].values()) + second["abstain"] == total
        irv = solve(input_for(options, lines, "irv", True))["result"]
        for entry in irv["rounds"]:
            assert sum(entry["counts"].values()) + entry["exhausted"] == total
            assert sum(entry["counts"].values()) == entry["continuing"]

    @PROPERTY
    @given(ranked_profiles(partial=True))
    def test_borda_points_add_up_to_what_the_ballots_hand_out(self, profile):
        options, lines = profile
        total = sum(count for count, _ in lines)
        out = solve(input_for(options, lines, "borda", True))["result"]
        size = len(options)
        got = sum(Fraction(score) for score in out["scores"].values())
        assert got == Fraction(total * size * (size - 1), 2)

    @PROPERTY
    @given(ranked_profiles(partial=True))
    def test_a_pair_is_never_counted_on_more_ballots_than_exist(self, profile):
        options, lines = profile
        total = sum(count for count, _ in lines)
        matrix = solve(input_for(options, lines, "schulze", True))["result"]["pairwise_matrix"]
        for a, b in itertools.permutations(options, 2):
            assert matrix[a][b] + matrix[b][a] <= total
            assert matrix[a][b] == sum(
                count for count, ranking in lines if ref.prefers(ranking, a, b)
            )

    @PROPERTY
    @given(ranked_profiles(partial=False))
    def test_complete_ballots_split_every_pair(self, profile):
        options, lines = profile
        total = sum(count for count, _ in lines)
        matrix = solve(input_for(options, lines, "schulze"))["result"]["pairwise_matrix"]
        for a, b in itertools.permutations(options, 2):
            assert matrix[a][b] + matrix[b][a] == total


class TestSchulzeAndTheCondorcetWinner:
    @PROPERTY
    @given(ranked_profiles(partial=True))
    def test_the_condorcet_winner_wins_under_schulze_condorcet_and_kemeny(self, profile):
        options, lines = profile
        winner = ref.condorcet_winner(expanded(lines), options)
        assume(winner is not None)
        for method in ("schulze", "condorcet", "kemeny"):
            assert solve(input_for(options, lines, method, True))["result"]["winner"] == winner
        out = solve(input_for(options, lines, "schulze", True))["result"]
        assert out["condorcet_winner"] == winner
        assert out["schulze_winners"] == [winner]
        assert out["cycle"] is None
        assert out["tie_events"] == []

    @PROPERTY
    @given(ranked_profiles(partial=True))
    def test_the_floyd_warshall_set_equals_the_path_enumeration(self, profile):
        options, lines = profile
        out = solve(input_for(options, lines, "schulze", True))["result"]
        assert set(out["schulze_winners"]) == set(ref.schulze_set(expanded(lines), options))

    @PROPERTY
    @given(ranked_profiles(partial=False), st.data())
    def test_schulze_is_monotonic(self, profile, data):
        """Raising an option on a ballot never removes it from the set of potential winners."""
        options, lines = profile
        ballots = expanded(lines)
        before = set(ref.schulze_set(ballots, options))
        choice = data.draw(st.sampled_from(sorted(before)))
        movable = [i for i, ballot in enumerate(ballots) if ballot.index(choice) > 0]
        assume(movable)
        at = data.draw(st.sampled_from(movable))
        ballot = list(ballots[at])
        place = ballot.index(choice)
        ballot[place - 1], ballot[place] = ballot[place], ballot[place - 1]
        raised = ballots[:at] + [ballot] + ballots[at + 1 :]
        assert choice in ref.schulze_set(raised, options)


class TestOrderOfBallotsAndOptions:
    @pytest.mark.parametrize("method", RANKED_METHODS)
    @PROPERTY
    @given(profile=ranked_profiles(partial=True), rnd=st.randoms(use_true_random=False))
    def test_the_whole_result_is_the_same_whatever_the_order_of_ballots(self, method, profile, rnd):
        options, lines = profile
        assume(method != "kemeny" or len(options) <= 5)
        unit = [(1, ranking) for count, ranking in lines for _ in range(count)]
        shuffled = list(lines)
        rnd.shuffle(shuffled)
        rnd.shuffle(unit)
        base = solve(input_for(options, lines, method, True))
        assert solve(input_for(options, shuffled, method, True)) == base
        assert solve(input_for(options, unit, method, True)) == base

    @pytest.mark.parametrize("method", RANKED_METHODS)
    @PROPERTY
    @given(profile=ranked_profiles(partial=True), rnd=st.randoms(use_true_random=False))
    def test_the_winner_does_not_depend_on_how_the_options_are_listed(self, method, profile, rnd):
        options, lines = profile
        listed = list(options)
        rnd.shuffle(listed)
        base = solve(input_for(options, lines, method, True))["result"]
        other = solve(input_for(listed, lines, method, True))["result"]
        assert other["winner"] == base["winner"]
        assert other["tie_break_order"] == base["tie_break_order"]

    @PROPERTY
    @given(ranked_profiles(partial=True))
    def test_a_name_in_the_ballot_matters_not_its_position_in_the_options(self, profile):
        options, lines = profile
        base = solve(input_for(options, lines, "irv", True))["result"]["winner"]
        reverse = solve(input_for(list(reversed(options)), lines, "irv", True))["result"]["winner"]
        assert base == reverse


class TestTieBreakOrder:
    @PROPERTY
    @given(option_lists(2, 6), st.text(min_size=1, max_size=40).filter(lambda s: s.strip()))
    def test_the_same_source_gives_the_same_order_every_time(self, options, source):
        assume(source == source.strip() and "\n" not in source and source.isprintable())
        lines = [(1, options)]
        data = make_input(options, lines, "plurality", source=source)
        first = tie_order_names(data)
        assert tie_order_names(data) == first
        assert sorted(first) == sorted(options)
        reordered = make_input(list(reversed(options)), lines, "plurality", source=source)
        assert tie_order_names(reordered) == first

    def test_different_sources_give_different_orders(self):
        options = ["火锅", "爬山", "KTV", "剧本杀", "密室逃脱"]
        orders = {
            tuple(
                tie_order_names(
                    make_input(options, [(1, options)], "plurality", source=f"draw {n}")
                )
            )
            for n in range(40)
        }
        assert len(orders) > 20  # 120 orders are possible, 40 sources should seldom repeat

    def test_two_sources_differ_for_two_options_about_half_of_the_time(self):
        options = ["A", "B"]
        firsts = [
            tie_order_names(make_input(options, [(1, options)], "plurality", source=f"s{n}"))[0]
            for n in range(60)
        ]
        assert 10 < firsts.count("A") < 50

    @PROPERTY
    @given(ranked_profiles(partial=True), st.sampled_from(COUNTED_BY_THE_REFERENCE))
    def test_a_different_source_changes_the_result_only_through_ties(self, profile, method):
        options, lines = profile
        ballots = expanded(lines)
        alive = list(options)
        try:
            ref.RULES[method](ballots, alive, None)
        except ref.ReferenceTie:
            assume(False)
        winners = {
            solve(input_for(options, lines, method, True, source=f"source {n}"))["result"]["winner"]
            for n in range(4)
        }
        assert len(winners) == 1

    @PROPERTY
    @given(ranked_profiles(partial=True), st.sampled_from(COUNTED_BY_THE_REFERENCE))
    def test_a_tie_event_is_recorded_exactly_when_the_order_was_needed(self, profile, method):
        options, lines = profile
        out = solve(input_for(options, lines, method, True))["result"]
        try:
            ref.RULES[method](expanded(lines), list(options), None)
            needed = False
        except ref.ReferenceTie:
            needed = True
        assert bool(out["tie_events"]) == needed
        for event in out["tie_events"]:
            order = out["tie_break_order"]
            assert event["tied"] == sorted(event["tied"], key=order.index)
            expected = event["tied"][-1] if event["eliminated"] else event["tied"][0]
            assert event["picked"][0] == expected or event["stage"] == "finalists"


class TestAgreementWithTheReference:
    @PROPERTY
    @given(ranked_profiles(partial=True), st.sampled_from(COUNTED_BY_THE_REFERENCE))
    def test_every_rule_matches_the_plain_implementation(self, profile, method):
        options, lines = profile
        data = input_for(options, lines, method, True)
        order = tie_order_names(data)
        expected = ref.RULES[method](expanded(lines), list(options), order)
        assert solve(data)["result"]["winner"] == expected

    @PROPERTY
    @given(ranked_profiles(partial=True), st.sampled_from(COUNTED_BY_THE_REFERENCE))
    def test_every_rule_matches_after_an_option_is_removed(self, profile, method):
        options, lines = profile
        assume(len(options) >= 3)
        gone = options[0]
        data = input_for(options, lines, method, True)
        order = [o for o in tie_order_names(data) if o != gone]
        alive = [o for o in options if o != gone]
        ballots = ref.restrict(expanded(lines), alive)
        assume(ballots)
        expected = ref.RULES[method](ballots, alive, order)
        assert solve(data, remove=[gone])["result"]["winner"] == expected

    @PROPERTY
    @given(
        ranked_profiles(partial=True), st.lists(st.sets(st.integers(0, 4)), min_size=1, max_size=6)
    )
    def test_approval_matches_the_plain_count(self, profile, sets):
        options, _ = profile
        approvals = [sorted(options[i] for i in chosen if i < len(options)) for chosen in sets]
        data = {
            "options": options,
            "approvals": [{"approve": names} for names in approvals],
            "rules": {"method": "approval", "tie_break": {"random_source": SOURCE}},
        }
        order = tie_order_names(data)
        assert solve(data)["result"]["winner"] == ref.approval(approvals, list(options), order)


class TestCycles:
    @PROPERTY
    @given(ranked_profiles(max_options=5, partial=True))
    def test_a_cycle_is_reported_exactly_when_there_is_no_condorcet_winner_and_a_cycle(
        self, profile
    ):
        options, lines = profile
        ballots = expanded(lines)
        winner = ref.condorcet_winner(ballots, list(options))
        expected = winner is None and ref.has_cycle(ballots, list(options))
        out = solve(input_for(options, lines, "schulze", True))["result"]
        assert (out["cycle"] is not None) == expected
        assert (out["condorcet_winner"] is None) == (winner is None)

    @PROPERTY
    @given(ranked_profiles(max_options=5, partial=True))
    def test_a_reported_cycle_is_a_closed_chain_of_strict_wins(self, profile):
        options, lines = profile
        matrix = solve(input_for(options, lines, "schulze", True))["result"]
        cycle = matrix["cycle"]
        assume(cycle is not None)
        links = cycle["links"]
        assert len(links) >= 3
        assert len({link["winner"] for link in links}) == len(links)
        for here, nxt in zip(links, links[1:] + links[:1]):
            assert here["loser"] == nxt["winner"]
        pairs = matrix["pairwise_matrix"]
        for link in links:
            assert link["for"] == pairs[link["winner"]][link["loser"]]
            assert link["against"] == pairs[link["loser"]][link["winner"]]
            assert link["margin"] == link["for"] - link["against"] > 0

    @PROPERTY
    @given(ranked_profiles(max_options=5, partial=True))
    def test_the_cycle_is_a_shortest_one(self, profile):
        options, lines = profile
        out = solve(input_for(options, lines, "schulze", True))["result"]
        assume(out["cycle"] is not None)
        matrix = out["pairwise_matrix"]
        beats = {a: [b for b in options if b != a and matrix[a][b] > matrix[b][a]] for a in options}
        shortest = None
        for size in range(3, len(options) + 1):
            for chain in itertools.permutations(options, size):
                if all(chain[(i + 1) % size] in beats[chain[i]] for i in range(size)):
                    shortest = size
                    break
            if shortest:
                break
        assert shortest == len(out["cycle"]["links"])


class TestKemeny:
    @PROPERTY
    @given(ranked_profiles(max_options=4, partial=True))
    def test_the_result_equals_a_search_over_all_rankings_of_four_options(self, profile):
        options, lines = profile
        data = input_for(options, lines, "kemeny", True)
        order = tie_order_names(data)
        best, ranking = ref.kemeny_pick(expanded(lines), list(options), order)
        found = ref.kemeny_rankings(expanded(lines), list(options))[1]
        out = solve(data)["result"]
        assert out["score"] == best
        assert out["ranking"] == ranking
        assert out["optimal_rankings"] == len(found)
        assert out["winner"] == ranking[0]

    @PROPERTY
    @given(ranked_profiles(max_options=6, partial=False))
    def test_the_score_is_the_best_possible_for_up_to_six_options(self, profile):
        options, lines = profile
        out = solve(input_for(options, lines, "kemeny"))["result"]
        assert out["score"] == ref.kemeny_rankings(expanded(lines), list(options))[0]


class TestRemovingAnOption:
    @PROPERTY
    @given(ranked_profiles(max_options=5, partial=True), st.data())
    def test_removing_a_non_winner_never_changes_the_condorcet_winner(self, profile, data):
        options, lines = profile
        assume(len(options) >= 3)
        winner = ref.condorcet_winner(expanded(lines), list(options))
        assume(winner is not None)
        gone = data.draw(st.sampled_from([o for o in options if o != winner]))
        for method in ("schulze", "condorcet", "kemeny"):
            out = solve(input_for(options, lines, method, True), remove=[gone])["result"]
            assert out["winner"] == winner
            assert out["recount"]["changed"] is False
            assert out["condorcet_winner"] == winner

    @PROPERTY
    @given(ranked_profiles(max_options=5, partial=False), st.sampled_from(COUNTED_BY_THE_REFERENCE))
    def test_a_recount_equals_a_fresh_count_of_the_reduced_ballots(self, profile, method):
        options, lines = profile
        assume(len(options) >= 3)
        gone = options[-1]
        data = make_input(options, lines, method, source=None)
        try:
            solve(data)
        except fc.NoSolution:
            assume(False)
        reduced = [(count, [o for o in ranking if o != gone]) for count, ranking in lines]
        fresh = make_input([o for o in options if o != gone], reduced, method, source=None)
        try:
            expected = solve(fresh)["result"]["winner"]
        except fc.NoSolution:
            with pytest.raises(fc.NoSolution):
                solve(data, remove=[gone])
            return
        assert solve(data, remove=[gone])["result"]["winner"] == expected


class TestMajorityOfFirstChoices:
    @PROPERTY
    @given(ranked_profiles(max_options=5, partial=False), st.integers(1, 3))
    def test_a_majority_winner_wins_under_every_rule_except_possibly_borda(self, profile, extra):
        options, lines = profile
        top = options[0]
        total = sum(count for count, _ in lines)
        # add enough ballots that rank the first option first to give it a majority
        boost = (total + 1) + extra
        lines = [*lines, (boost, [top, *[o for o in options if o != top]])]
        for method in ("plurality", "runoff", "irv", "condorcet", "schulze", "kemeny"):
            out = solve(input_for(options, lines, method))["result"]
            assert out["winner"] == top, method


class TestEveryFormatRendersForRandomBallots:
    @PROPERTY
    @given(
        ranked_profiles(max_options=5, partial=True),
        st.sampled_from(RANKED_METHODS),
        st.booleans(),
        st.booleans(),
    )
    def test_all_formats_and_languages(self, profile, method, named, recount):
        options, lines = profile
        data = input_for(options, lines, method, True)
        if named:
            data["ballots"] = [
                {"voter": f"voter{i}", "ranking": ranking} for i, (_, ranking) in enumerate(lines)
            ]
        remove = [options[-1]] if recount and len(options) >= 3 else []
        try:
            result = gv.solve(data, remove=remove, all_rules=True)
        except fc.NoSolution:
            assume(False)
        for lang in ("zh", "en"):
            result = gv.solve(data, lang=lang, remove=remove, all_rules=True)
            for fmt in ("md", "dm", "group"):
                text = fc.render(result, fmt, False, lang)
                assert text.strip()
                assert "{" not in text and "}" not in text and "None" not in text
            assert fc.render(result, "md", True, lang).startswith("{")


@PROPERTY
@given(ranked_profiles(max_options=5, partial=True))
def test_runs_are_repeatable(profile):
    options, lines = profile
    data = input_for(options, lines, "irv", True)
    one = fc.render(gv.solve(data, all_rules=True), "md", False, "zh")
    two = fc.render(gv.solve(data, all_rules=True), "md", False, "zh")
    assert one == two


def test_a_random_walk_over_many_inputs_never_crashes():
    """Smoke test with the standard library generator: valid inputs never raise."""
    rng = random.Random(7)
    pool = ["火锅", "爬山", "KTV", "剧本杀", "密室逃脱", "烧烤"]
    for _ in range(300):
        size = rng.randint(2, 6)
        options = rng.sample(pool, size)
        lines = []
        for _ in range(rng.randint(1, 5)):
            length = rng.randint(1, size)
            lines.append((rng.randint(1, 5), rng.sample(options, length)))
        method = rng.choice(RANKED_METHODS)
        data = input_for(options, lines, method, True)
        try:
            gv.solve(data, all_rules=True)
        except fc.NoSolution:
            raise AssertionError("a source is set, so a tie can always be broken") from None
