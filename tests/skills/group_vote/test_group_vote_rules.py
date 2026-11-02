"""Each counting rule on small profiles whose answers were worked out by hand."""

from __future__ import annotations

from typing import ClassVar

import fsq_core as fc
import group_vote as gv
import pytest
from vote_support import make_input, run_json

# The 5-4-3 profile. By hand, with 12 ballots:
#   first choices   A 5, B 4, C 3
#   A over B: 5 against 7.  B over C: 9 against 3.  A over C: 5 against 7.  So B is the Condorcet winner.
#   Borda points    A 5*2 = 10, B 5*1 + 4*2 + 3*1 = 16, C 4*1 + 3*2 = 10.
PROFILE = [(5, ["A", "B", "C"]), (4, ["B", "C", "A"]), (3, ["C", "B", "A"])]
OPTIONS = ["A", "B", "C"]


def result(lines, method, options=OPTIONS, **kwargs) -> dict:
    partial = kwargs.pop("partial", None)
    remove = kwargs.pop("remove", ())
    all_rules = kwargs.pop("all_rules", False)
    data = make_input(options, lines, method, partial=partial, **kwargs)
    return fc.envelope(gv.solve(data, remove=remove, all_rules=all_rules))["result"]


def order_of(options, lines, method="plurality", source="a source"):
    """The tie-break order (option names, best first) that a source gives to these options."""
    election = gv.parse_election(make_input(options, lines, method, source=source))
    order, _ = gv.tie_order(election)
    return [options[i] for i in order]


class TestPlurality:
    def test_the_most_first_choices_win(self):
        out = result(PROFILE, "plurality")
        assert out["winner"] == "A"
        assert out["scores"] == {"A": 5, "B": 4, "C": 3}

    def test_one_name_is_a_whole_ballot(self):
        lines = [(3, ["A"]), (2, ["B"])]
        out = result(lines, "plurality")  # rules.partial stays at its default
        assert out["winner"] == "A"
        assert out["scores"] == {"A": 3, "B": 2, "C": 0}

    def test_a_tie_goes_to_the_option_earlier_in_the_order(self):
        lines = [(3, ["A", "B", "C"]), (3, ["B", "A", "C"]), (1, ["C", "A", "B"])]
        order = order_of(OPTIONS, lines)
        out = result(lines, "plurality", source="a source")
        assert out["winner"] == min(["A", "B"], key=order.index)
        assert out["tie_events"] == [
            {
                "stage": "winner",
                "tied": sorted(["A", "B"], key=order.index),
                "picked": [out["winner"]],
                "eliminated": False,
            }
        ]


class TestRunoff:
    def test_more_than_half_of_the_first_choices_wins_in_round_one(self):
        lines = [(7, ["A", "B", "C"]), (3, ["B", "A", "C"]), (2, ["C", "B", "A"])]
        out = result(lines, "runoff")
        assert out["winner"] == "A"
        assert out["round_1"] == {"votes": {"A": 7, "B": 3, "C": 2}, "decided": True}
        assert out["round_2"] is None

    def test_the_top_two_meet_and_the_winner_can_be_a_different_option(self):
        # first choices A 4, B 3, C 2: C goes out. A over B on 4 ballots, B over A on 3 + 2.
        lines = [(4, ["A", "B", "C"]), (3, ["B", "C", "A"]), (2, ["C", "B", "A"])]
        out = result(lines, "runoff")
        assert out["round_1"]["decided"] is False
        assert out["round_2"] == {"finalists": ["A", "B"], "votes": {"A": 4, "B": 5}, "abstain": 0}
        assert out["winner"] == "B"
        assert result(lines, "plurality")["winner"] == "A"

    def test_a_tie_for_second_place_is_settled_by_the_order(self):
        # first choices A 3, B 2, C 2 (and D 0). B or C meets A. Against A, B wins 4 to 3 and C 4 to 3.
        lines = [(3, list("ABCD")), (2, list("BCAD")), (2, list("CBAD"))]
        options = list("ABCD")
        order = order_of(options, lines)
        out = result(lines, "runoff", options)
        expected = min(["B", "C"], key=order.index)
        assert out["round_2"]["finalists"] == sorted(["A", expected])
        assert out["winner"] == expected
        assert out["tie_events"][0]["stage"] == "finalists"

    def test_a_tie_in_the_final_is_settled_by_the_order(self):
        lines = [(2, ["A", "B"]), (2, ["B", "A"])]
        order = order_of(["A", "B"], lines)
        out = result(lines, "runoff", ["A", "B"])
        assert out["round_2"]["votes"] == {"A": 2, "B": 2}
        assert out["winner"] == order[0]
        assert out["tie_events"][0]["stage"] == "final"

    def test_ballots_that_rank_neither_finalist_do_not_count_in_the_final(self):
        # A 3, B 3, C 1 first choices. The single C ballot ranks only C.
        lines = [(3, ["A", "B"]), (3, ["B", "A"]), (1, ["C"])]
        out = result(lines, "runoff", partial="tie_last")
        assert out["round_2"]["abstain"] == 1
        assert out["round_2"]["votes"] == {"A": 3, "B": 3}


class TestInstantRunoff:
    def test_the_weakest_option_goes_and_its_ballots_move_on(self):
        out = result(PROFILE, "irv")
        # C (3 first choices) goes, its ballots move to B, and B has 7 of 12.
        assert [r["counts"] for r in out["rounds"]] == [{"A": 5, "B": 4, "C": 3}, {"A": 5, "B": 7}]
        assert [r["eliminated"] for r in out["rounds"]] == [["C"], []]
        assert out["winner"] == "B"

    def test_options_without_any_vote_leave_together_and_need_no_tie_break(self):
        # A 2, B 2, C 0, D 0. C and D leave at once. Only then A and B are tied.
        lines = [(2, list("ABCD")), (2, list("BACD"))]
        options = list("ABCD")
        election = gv.parse_election(make_input(options, lines, "irv", source=None))
        with_no_order = gv.count_method(
            "irv", election, [0, 1, 2, 3], lines_of(election), None, None
        )
        assert with_no_order.winner is None
        assert with_no_order.stage == ("irv", 2)
        assert with_no_order.tied == (0, 1)

    def test_the_tied_option_later_in_the_order_is_the_one_that_goes(self):
        # A 2, B 2, C 3. If A goes, B gets 4 against 3 and wins. If B goes, C gets 5 and wins.
        lines = [(2, ["A", "B", "C"]), (2, ["B", "C", "A"]), (3, ["C", "A", "B"])]
        order = order_of(OPTIONS, lines)
        out = result(lines, "irv")
        later = max(["A", "B"], key=order.index)
        assert out["rounds"][0]["eliminated"] == [later]
        assert out["winner"] == ("B" if later == "A" else "C")
        assert out["tie_events"][0]["eliminated"] is True

    def test_a_ballot_stops_counting_when_every_option_it_ranks_is_out(self):
        lines = [(4, ["A"]), (3, ["B"]), (2, ["C"])]
        out = result(lines, "irv", partial="tie_last")
        # C goes first and its two ballots have nowhere to go. 7 ballots are left: A 4 of 7.
        assert [r["exhausted"] for r in out["rounds"]] == [0, 2]
        assert [r["continuing"] for r in out["rounds"]] == [9, 7]
        assert out["winner"] == "A"


def lines_of(election):
    return gv.restrict_lines(election.lines, list(range(len(election.options))))


class TestBorda:
    def test_points_by_position(self):
        out = result(PROFILE, "borda")
        assert out["scores"] == {"A": "10", "B": "16", "C": "10"}
        assert out["winner"] == "B"

    def test_options_left_out_share_the_remaining_points(self):
        # One ballot ranking only A among three options: A 2 points, B and C 0.5 each.
        out = result([(1, ["A"])], "borda", partial="tie_last")
        assert out["scores"] == {"A": "2", "B": "0.5", "C": "0.5"}

    def test_a_longer_partial_ballot(self):
        # Four options, ranking A > B: 3 and 2 points, C and D share 1 + 0.
        out = result([(1, list("AB"))], "borda", list("ABCD"), partial="tie_last")
        assert out["scores"] == {"A": "3", "B": "2", "C": "0.5", "D": "0.5"}

    def test_a_tie_goes_to_the_option_earlier_in_the_order(self):
        lines = [(1, ["A", "B", "C"]), (1, ["B", "A", "C"])]
        order = order_of(OPTIONS, lines)
        out = result(lines, "borda")
        assert out["scores"] == {"A": "3", "B": "3", "C": "0"}
        assert out["winner"] == min(["A", "B"], key=order.index)


class TestCondorcet:
    def test_the_condorcet_winner_and_the_matrix(self):
        out = result(PROFILE, "condorcet")
        assert out["pairwise_matrix"] == {
            "A": {"B": 5, "C": 5},
            "B": {"A": 7, "C": 9},
            "C": {"A": 7, "B": 3},
        }
        assert out["condorcet_winner"] == "B"
        assert out["winner"] == "B"
        assert out["cycle"] is None

    def test_condorcet_and_schulze_always_agree(self):
        lines = [(3, ["A", "B", "C"]), (2, ["B", "C", "A"]), (2, ["C", "A", "B"])]
        assert result(lines, "condorcet")["winner"] == result(lines, "schulze")["winner"]

    def test_a_cycle_is_reported_with_the_margins(self):
        lines = [(4, ["A", "B", "C"]), (3, ["B", "C", "A"]), (2, ["C", "A", "B"])]
        out = result(lines, "schulze")
        # A over B 6 : 3, B over C 7 : 2, C over A 5 : 4
        assert out["condorcet_winner"] is None
        assert out["cycle"]["links"] == [
            {"winner": "A", "loser": "B", "for": 6, "against": 3, "margin": 3},
            {"winner": "B", "loser": "C", "for": 7, "against": 2, "margin": 5},
            {"winner": "C", "loser": "A", "for": 5, "against": 4, "margin": 1},
        ]

    def test_the_strongest_link_decides_a_cycle_without_a_tie(self):
        # In the cycle above the weakest link is C over A (5 : 4), so A is the Schulze winner.
        lines = [(4, ["A", "B", "C"]), (3, ["B", "C", "A"]), (2, ["C", "A", "B"])]
        out = result(lines, "schulze")
        assert out["schulze_winners"] == ["A"]
        assert out["winner"] == "A"
        assert out["tie_events"] == []

    def test_a_cycle_among_the_other_options_is_not_reported_when_one_option_beats_all(self):
        # A is first on every ballot. B, C and D beat each other in a circle: B over C, C over D
        # and D over B, each by 2 : 1. Since A wins, the circle does not matter and is not reported.
        lines = [(1, list("ABCD")), (1, list("ACDB")), (1, list("ADBC"))]
        out = result(lines, "schulze", list("ABCD"))
        assert out["condorcet_winner"] == "A"
        assert out["cycle"] is None
        assert out["winner"] == "A"
        assert out["pairwise_matrix"]["B"]["C"] == 2 and out["pairwise_matrix"]["C"]["D"] == 2
        assert out["pairwise_matrix"]["D"]["B"] == 2

    def test_pairs_that_tie_are_neither_a_win_nor_a_cycle(self):
        # A and B tie 1 : 1, both beat C. There is no Condorcet winner and no cycle.
        lines = [(1, ["A", "B", "C"]), (1, ["B", "A", "C"])]
        out = result(lines, "schulze")
        assert out["condorcet_winner"] is None
        assert out["cycle"] is None
        assert out["schulze_winners"] == ["A", "B"]


class TestKemeny:
    def test_the_best_ranking_and_its_score(self):
        out = result(PROFILE, "kemeny")
        # B > C > A: 9 + 7 + 7 = 23. The next best, B > A > C, scores 7 + 9 + 5 = 21.
        assert out["ranking"] == ["B", "C", "A"]
        assert out["score"] == 23
        assert out["optimal_rankings"] == 1
        assert out["winner"] == "B"

    def test_equally_good_rankings_are_settled_by_the_order(self):
        lines = [(1, ["A", "B"]), (1, ["B", "A"])]
        order = order_of(["A", "B"], lines)
        out = result(lines, "kemeny", ["A", "B"])
        assert out["optimal_rankings"] == 2
        assert out["ranking"] == order
        assert out["winner"] == order[0]

    def test_the_note_gives_the_score_and_the_number_of_best_rankings(self):
        data = make_input(OPTIONS, PROFILE, "kemeny")
        zh = fc.render(gv.solve(data), "md", False, "zh")
        en = fc.render(gv.solve(data, lang="en"), "md", False, "en")
        assert "Kemeny 总分 23，共有 1 种排名得分最高。" in zh
        assert "Kemeny score 23. 1 rankings reach the highest score." in en

    def test_more_than_eight_options_are_refused(self):
        options = [f"o{i}" for i in range(9)]
        data = make_input(options, [(1, options)], "kemeny")
        with pytest.raises(fc.InputError) as err:
            gv.solve(data)
        assert err.value.field == "rules.method"

    def test_eight_options_are_fine(self):
        options = [f"o{i}" for i in range(8)]
        out = result([(1, options)], "kemeny", options)
        assert out["ranking"] == options


class TestApproval:
    def test_the_option_with_most_approvals_wins(self):
        data = {
            "options": ["A", "B", "C"],
            "approvals": [
                {"count": 3, "approve": ["A", "B"]},
                {"count": 2, "approve": ["B"]},
                {"count": 2, "approve": ["C"]},
                {"count": 1, "approve": []},
            ],
            "rules": {"method": "approval"},
        }
        out = fc.envelope(gv.solve(data))["result"]
        assert out["scores"] == {"A": 3, "B": 5, "C": 2}
        assert out["winner"] == "B"
        assert out["pairwise_matrix"] is None

    def test_poll_totals_are_counted_as_approvals(self):
        data = {
            "options": ["A", "B", "C"],
            "approval_counts": {"A": 5, "B": 5, "C": 3},
            "rules": {"method": "approval", "tie_break": {"random_source": "x"}},
        }
        order = gv.tie_order(gv.parse_election(data))[0]
        out = fc.envelope(gv.solve(data))["result"]
        assert out["scores"] == {"A": 5, "B": 5, "C": 3}
        assert out["winner"] == ["A", "B", "C"][min([0, 1], key=order.index)]

    def test_poll_totals_can_be_counted_without_option_removed(self):
        data = {
            "options": ["A", "B", "C"],
            "approval_counts": {"A": 5, "B": 4, "C": 3},
            "rules": {"method": "approval"},
        }
        out = fc.envelope(gv.solve(data, remove=["A"]))["result"]
        assert out["winner"] == "B"
        assert out["recount"]["changed"] is True


class TestPartialBallots:
    """Options a ballot leaves out tie for last on that ballot (rules.partial is tie_last)."""

    def test_the_pairwise_counts(self):
        # 2 ballots rank only A, 1 ballot ranks B above C. By hand:
        #   A over B: 2   A over C: 2   B over A: 1   C over A: 1   B over C: 1   C over B: 0
        lines = [(2, ["A"]), (1, ["B", "C"])]
        out = result(lines, "condorcet", partial="tie_last")
        assert out["pairwise_matrix"] == {
            "A": {"B": 2, "C": 2},
            "B": {"A": 1, "C": 1},
            "C": {"A": 1, "B": 0},
        }
        assert out["condorcet_winner"] == "A"

    def test_borda_points_are_shared_out_exactly(self):
        # Doubled points add up to ballots * m * (m - 1), whatever the ballots look like.
        lines = [(2, list("A")), (1, list("BC")), (3, list("DCBA")), (1, list("CA"))]
        out = result(lines, "borda", list("ABCD"), partial="tie_last")
        assert sum(float(v) for v in out["scores"].values()) * 2 == 7 * 4 * 3

    def test_without_the_policy_a_short_ballot_is_refused(self):
        data = make_input(OPTIONS, [(1, ["A", "B"])], "irv")
        with pytest.raises(fc.InputError) as err:
            gv.solve(data)
        assert err.value.field == "ballots[0]"
        assert "tie_last" in err.value.message

    def test_plurality_needs_no_policy(self):
        assert result([(1, ["A"])], "plurality")["winner"] == "A"

    def test_all_rules_needs_the_policy_even_for_plurality(self):
        data = make_input(OPTIONS, [(1, ["A"])], "plurality")
        with pytest.raises(fc.InputError):
            gv.solve(data, all_rules=True)


class TestRemoval:
    def test_plurality_changes_when_c_is_removed(self):
        # Without C the ballots read A > B, B > A and B > A: B has 7 first choices, A has 5.
        out = result(PROFILE, "plurality", remove=["C"])
        assert out["scores"] == {"A": 5, "B": 7}
        assert out["recount"] == {
            "removed": ["C"],
            "original_winner": "A",
            "winner": "B",
            "changed": True,
        }

    def test_removing_a_ballots_only_option_drops_that_ballot(self):
        lines = [(2, ["A"]), (1, ["B", "C"]), (1, ["C", "B"])]
        out = result(lines, "plurality", partial="tie_last", remove=["A"])
        assert out["removed_ballots"] == 2
        assert out["scores"] == {"B": 1, "C": 1} or out["winner"] in ("B", "C")

    def test_removing_the_winner_picks_a_new_one(self):
        out = result(PROFILE, "condorcet", remove=["B"])
        assert out["winner"] == "C"
        assert out["recount"]["changed"] is True

    def test_removal_applies_to_the_tie_break_order_unchanged(self):
        lines = [(1, ["A", "B", "C"]), (1, ["B", "A", "C"]), (1, ["C", "B", "A"])]
        out = result(lines, "borda")  # A 3, B 5, C 1: no tie, just read the order
        full = out["tie_break_order"]
        part = result(lines, "borda", remove=["C"])["tie_break_order"]
        assert part == [name for name in full if name != "C"]

    @pytest.mark.parametrize(
        "method", ["plurality", "runoff", "irv", "borda", "condorcet", "kemeny"]
    )
    def test_a_recount_equals_counting_the_reduced_ballots(self, method):
        reduced = [(5, ["A", "B"]), (4, ["B", "A"]), (3, ["B", "A"])]
        counted = result(reduced, method, ["A", "B"], source=None)
        recount = result(PROFILE, method, source=None, remove=["C"])
        assert recount["winner"] == counted["winner"]


class TestExitCodeThreeOnAnUnbreakableTie:
    """No random source and a tie: exit code 3, and the message asks for a source."""

    TIES: ClassVar[dict] = {
        "plurality": (OPTIONS, [(1, ["A", "B", "C"]), (1, ["B", "A", "C"])]),
        "runoff": (["A", "B"], [(2, ["A", "B"]), (2, ["B", "A"])]),
        "irv": (OPTIONS, [(2, ["A", "B", "C"]), (2, ["B", "C", "A"]), (3, ["C", "A", "B"])]),
        "borda": (OPTIONS, [(1, ["A", "B", "C"]), (1, ["B", "A", "C"])]),
        "condorcet": (
            OPTIONS,
            [(1, ["A", "B", "C"]), (1, ["B", "C", "A"]), (1, ["C", "A", "B"])],
        ),
        "schulze": (
            OPTIONS,
            [(1, ["A", "B", "C"]), (1, ["B", "C", "A"]), (1, ["C", "A", "B"])],
        ),
        "kemeny": (["A", "B"], [(1, ["A", "B"]), (1, ["B", "A"])]),
    }

    @pytest.mark.parametrize("method", sorted(TIES))
    def test_the_run_stops_with_exit_code_3(self, method):
        options, lines = self.TIES[method]
        done = run_json(make_input(options, lines, method, source=None))
        assert done.returncode == 3, done.stderr
        assert done.stdout == ""
        assert "random source" in done.stderr
        assert "before counting" in done.stderr
        assert "rules.tie_break.random_source" in done.stderr

    def test_a_recount_can_run_into_a_tie_too(self):
        # A leads with 2 first choices against 1 and 1. Without A, the two ballots that named
        # only A are gone, B and C are tied, and no source can break it.
        lines = [(2, ["A"]), (1, ["B"]), (1, ["C"])]
        data = make_input(OPTIONS, lines, "plurality", source=None)
        assert fc.envelope(gv.solve(data))["result"]["winner"] == "A"
        done = run_json(data, "--remove", "A")
        assert done.returncode == 3
        assert "B, C are tied" in done.stderr

    def test_approval_polls_stop_too(self):
        data = {
            "options": ["A", "B"],
            "approval_counts": {"A": 3, "B": 3},
            "rules": {"method": "approval"},
        }
        done = run_json(data)
        assert done.returncode == 3
        assert "A, B are tied" in done.stderr

    @pytest.mark.parametrize("method", sorted(TIES))
    def test_the_same_input_with_a_source_succeeds(self, method):
        options, lines = self.TIES[method]
        done = run_json(make_input(options, lines, method), "--json")
        assert done.returncode == 0, done.stderr

    def test_a_tie_that_never_decides_anything_needs_no_source(self):
        # B and C tie for last place only, which plurality never looks at.
        lines = [(3, ["A", "B", "C"]), (1, ["B", "A", "C"]), (1, ["C", "A", "B"])]
        done = run_json(make_input(OPTIONS, lines, "plurality", source=None))
        assert done.returncode == 0, done.stderr

    def test_all_rules_shows_the_rules_that_cannot_decide_and_still_succeeds(self):
        # Plurality is clear, but Borda is tied between A and B, and nothing breaks that tie.
        lines = [(1, ["A", "B", "C"]), (1, ["B", "A", "C"]), (1, ["A", "C", "B"])]
        data = make_input(OPTIONS, lines, "plurality", source=None)
        out = fc.envelope(gv.solve(data, all_rules=True))["result"]
        assert out["winner"] == "A"
        assert out["per_rule_winners"]["plurality"] == "A"
        assert out["per_rule_winners"]["borda"] == "A"
        tied = {m: v["tied"] for m, v in out["per_rule"].items() if v["winner"] is None}
        assert all(len(names) >= 2 for names in tied.values())


class TestEveryTieUsesTheSameOrder:
    def test_one_order_serves_every_rule(self):
        data = make_input(OPTIONS, [(1, ["A", "B", "C"]), (1, ["B", "A", "C"])], "plurality")
        election = gv.parse_election(data)
        order, seed_hex = gv.tie_order(election)
        assert sorted(order) == [0, 1, 2]
        assert len(seed_hex) == 64
        seed = fc.make_seed(
            gv.TIE_RULE_NAME, OPTIONS, gv.TIE_SLOTS, data["rules"]["tie_break"]["random_source"]
        )
        assert seed.hex() == seed_hex
        names = fc.shuffle(OPTIONS, fc.SeedStream(seed))
        assert [OPTIONS[i] for i in order] == names

    def test_the_order_is_in_the_json_certificate(self):
        data = make_input(OPTIONS, PROFILE, "irv")
        envelope = fc.envelope(gv.solve(data))
        cert = envelope["certificate"]
        assert cert["seed_hex"] and cert["tie_break_order"]
        assert "SHA-256" in cert["how_to_verify"]
        assert gv.TIE_RULE_NAME in cert["how_to_verify"]
        assert envelope["result"]["tie_break_order"] == cert["tie_break_order"]
