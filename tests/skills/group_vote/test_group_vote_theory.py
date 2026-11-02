"""The textbook examples quoted in the theory notes, counted by the script."""

from __future__ import annotations

import fsq_core as fc
import group_vote as gv
import pytest
from vote_support import DEMO_LINES, DEMO_OPTIONS, make_input


def winner(options, lines, method, remove=(), source=None):
    data = make_input(options, lines, method, partial="tie_last", source=source)
    return fc.envelope(gv.solve(data, remove=remove))["result"]["winner"]


# Seventeen voters. Instant runoff and the two-round runoff both elect C.
MONOTONICITY_BEFORE = [
    (5, ["A", "C", "B"]),
    (4, ["B", "A", "C"]),
    (2, ["B", "C", "A"]),
    (6, ["C", "B", "A"]),
]
# Two of the voters who ranked B first and C second now rank C first. That is a gain for C.
MONOTONICITY_AFTER = [
    (5, ["A", "C", "B"]),
    (4, ["B", "A", "C"]),
    (8, ["C", "B", "A"]),
]


class TestMonotonicity:
    @pytest.mark.parametrize("method", ["irv", "runoff"])
    def test_an_option_can_lose_because_more_voters_rank_it_higher(self, method):
        assert winner("ABC", MONOTONICITY_BEFORE, method) == "C"
        assert winner("ABC", MONOTONICITY_AFTER, method) == "A"

    def test_instant_runoff_is_not_monotonic(self):
        # Before: A 5, B 6, C 6. A goes, its ballots help C: C 11 against B 6.
        # After:  A 5, B 4, C 8. B goes, its ballots help A: A 9 against C 8.
        assert winner("ABC", MONOTONICITY_BEFORE, "irv") == "C"
        assert winner("ABC", MONOTONICITY_AFTER, "irv") == "A"

    def test_two_round_runoff_is_not_monotonic(self):
        # Before: B and C meet and C wins 11 to 6. After: C and A meet and A wins 9 to 8.
        assert winner("ABC", MONOTONICITY_BEFORE, "runoff") == "C"
        assert winner("ABC", MONOTONICITY_AFTER, "runoff") == "A"

    @pytest.mark.parametrize("method", ["schulze", "condorcet", "borda", "kemeny"])
    def test_the_same_change_does_not_hurt_c_under_the_other_rules(self, method):
        before = winner("ABC", MONOTONICITY_BEFORE, method, source="s")
        after = winner("ABC", MONOTONICITY_AFTER, method, source="s")
        if before == "C":
            assert after == "C"


class TestClones:
    def test_borda_is_sensitive_to_clones(self):
        # A beats B 6 to 4 and wins with 2 options. B2 is a copy of B ranked right behind it.
        alone = [(6, ["A", "B"]), (4, ["B", "A"])]
        cloned = [(6, ["A", "B", "B2"]), (4, ["B", "B2", "A"])]
        assert winner(["A", "B"], alone, "borda") == "A"
        # Borda points are A 12, B 14 and B2 4: the clone lifts B above A.
        data = make_input(["A", "B", "B2"], cloned, "borda", source=None)
        out = fc.envelope(gv.solve(data))["result"]
        assert out["scores"] == {"A": "12", "B": "14", "B2": "4"}
        assert out["winner"] == "B"

    def test_schulze_ignores_the_clone(self):
        alone = [(6, ["A", "B"]), (4, ["B", "A"])]
        cloned = [(6, ["A", "B", "B2"]), (4, ["B", "B2", "A"])]
        for method in ("schulze", "condorcet", "kemeny"):
            assert winner(["A", "B"], alone, method) == "A"
            assert winner(["A", "B", "B2"], cloned, method) == "A"

    def test_plurality_splits_the_votes_of_similar_options(self):
        # B has 6 of 10 first choices. When 3 of them prefer the copy B2, A has the most.
        alone = [(4, ["A", "B"]), (6, ["B", "A"])]
        split = [(4, ["A", "B", "B2"]), (3, ["B", "B2", "A"]), (3, ["B2", "B", "A"])]
        assert winner(["A", "B"], alone, "plurality") == "B"
        assert winner(["A", "B", "B2"], split, "plurality") == "A"
        assert winner(["A", "B", "B2"], split, "schulze") == "B"

    def test_instant_runoff_does_not_split_the_votes_here(self):
        # B and B2 are tied for last, whichever goes, the other one collects both groups.
        split = [(4, ["A", "B", "B2"]), (3, ["B", "B2", "A"]), (3, ["B2", "B", "A"])]
        assert winner(["A", "B", "B2"], split, "irv", source="s") in ("B", "B2")


class TestMajority:
    def test_borda_can_pass_over_the_option_most_voters_rank_first(self):
        # A is first for 3 of 5 voters. Borda points: A 6, B 7, C 2.
        lines = [(3, ["A", "B", "C"]), (2, ["B", "C", "A"])]
        assert winner("ABC", lines, "plurality") == "A"
        assert winner("ABC", lines, "borda") == "B"
        for method in ("runoff", "irv", "condorcet", "schulze", "kemeny"):
            assert winner("ABC", lines, method) == "A"


class TestTheTwentySevenBallots:
    def test_four_rules_miss_the_condorcet_winner_that_the_pairwise_rules_find(self):
        picks = {
            m: winner(DEMO_OPTIONS, DEMO_LINES, m) for m in ("plurality", "runoff", "irv", "borda")
        }
        assert "爬山" not in picks.values()
        for method in ("condorcet", "schulze", "kemeny"):
            assert winner(DEMO_OPTIONS, DEMO_LINES, method) == "爬山"
