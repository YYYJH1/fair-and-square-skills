"""Golden numbers: worked examples that were counted by hand, reproduced by the script."""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
from typing import ClassVar

import fsq_core as fc
import group_vote as gv
import pytest
from vote_support import (
    DEMO_LINES,
    DEMO_OPTIONS,
    EXAMPLES,
    GOLDEN_DIR,
    SCRIPT,
    SOURCE,
    demo_input,
    make_input,
    run_json,
    run_script,
)

# What every rule picks on the 27 ballots, counted by hand, with each option removed in turn.
ALL_OPTIONS = {
    None: {
        "plurality": "密室逃脱",
        "runoff": "剧本杀",
        "irv": "火锅",
        "borda": "KTV",
        "condorcet": "爬山",
        "schulze": "爬山",
    },
    "密室逃脱": dict.fromkeys(
        ["plurality", "runoff", "irv", "borda", "condorcet", "schulze"], "爬山"
    ),
    "爬山": {
        "plurality": "剧本杀",
        "runoff": "剧本杀",
        "irv": "火锅",
        "borda": "KTV",
        "condorcet": "KTV",
        "schulze": "KTV",
    },
    "剧本杀": dict.fromkeys(
        ["plurality", "runoff", "irv", "borda", "condorcet", "schulze"], "爬山"
    ),
    "火锅": {
        "plurality": "KTV",
        "runoff": "KTV",
        "irv": "KTV",
        "borda": "爬山",
        "condorcet": "爬山",
        "schulze": "爬山",
    },
    "KTV": {
        "plurality": "火锅",
        "runoff": "火锅",
        "irv": "火锅",
        "borda": "火锅",
        "condorcet": "爬山",
        "schulze": "爬山",
    },
}


def envelope(data: dict, **kwargs) -> dict:
    return fc.envelope(gv.solve(data, **kwargs))


def winners_of(result: dict) -> dict:
    return {rule: name for rule, name in result["per_rule_winners"].items() if rule != "kemeny"}


@pytest.fixture(scope="module")
def result() -> dict:
    return envelope(demo_input(), all_rules=True)["result"]


class TestTwentySevenBallots:
    """Five rules, five winners."""

    def test_the_five_rules_name_five_different_winners(self, result):
        winners = winners_of(result)
        assert winners == ALL_OPTIONS[None]
        assert len({winners[r] for r in ("plurality", "runoff", "irv", "borda", "condorcet")}) == 5

    def test_schulze_and_kemeny_agree_with_the_condorcet_winner(self, result):
        assert result["condorcet_winner"] == "爬山"
        assert result["schulze_winners"] == ["爬山"]
        assert result["per_rule_winners"]["kemeny"] == "爬山"
        assert result["cycle"] is None

    def test_plurality_counts_first_choices(self):
        scores = envelope(demo_input("plurality"))["result"]["scores"]
        assert scores == {"密室逃脱": 8, "爬山": 2, "剧本杀": 7, "火锅": 6, "KTV": 4}

    def test_the_runoff_is_decided_15_to_12(self):
        result = envelope(demo_input("runoff"))["result"]
        assert result["winner"] == "剧本杀"
        assert result["round_1"]["decided"] is False
        assert result["round_2"] == {
            "finalists": ["密室逃脱", "剧本杀"],
            "votes": {"密室逃脱": 12, "剧本杀": 15},
            "abstain": 0,
        }

    def test_instant_runoff_goes_through_four_rounds(self):
        rounds = envelope(demo_input("irv"))["result"]["rounds"]
        assert [r["counts"] for r in rounds] == [
            {"密室逃脱": 8, "爬山": 2, "剧本杀": 7, "火锅": 6, "KTV": 4},
            {"密室逃脱": 8, "剧本杀": 9, "火锅": 6, "KTV": 4},
            {"密室逃脱": 8, "剧本杀": 9, "火锅": 10},
            {"剧本杀": 9, "火锅": 18},
        ]
        assert [r["eliminated"] for r in rounds] == [["爬山"], ["KTV"], ["密室逃脱"], []]
        assert rounds[-1]["winner"] == "火锅"
        assert all(r["exhausted"] == 0 and r["continuing"] == 27 for r in rounds)

    def test_borda_is_64_to_63(self):
        result = envelope(demo_input("borda"))["result"]
        assert result["winner"] == "KTV"
        assert result["scores"] == {
            "密室逃脱": "42",
            "爬山": "63",
            "剧本杀": "46",
            "火锅": "55",
            "KTV": "64",
        }
        assert sum(int(score) for score in result["scores"].values()) == 27 * 10

    def test_the_pairwise_matrix(self, result):
        matrix = result["pairwise_matrix"]
        rows = {a: [matrix[a].get(b) for b in DEMO_OPTIONS] for a in DEMO_OPTIONS}
        assert rows == {
            "密室逃脱": [None, 12, 12, 8, 10],
            "爬山": [15, None, 14, 17, 17],
            "剧本杀": [15, 13, None, 9, 9],
            "火锅": [19, 10, 18, None, 8],
            "KTV": [17, 10, 18, 19, None],
        }

    def test_the_kemeny_ranking(self):
        result = envelope(demo_input("kemeny"))["result"]
        assert result["ranking"] == ["爬山", "KTV", "火锅", "剧本杀", "密室逃脱"]
        assert result["score"] == 169
        assert result["optimal_rankings"] == 1

    def test_the_demo_prints_the_same_numbers(self):
        done = run_script("--demo", "--json")
        assert done.returncode == 0, done.stderr
        result = json.loads(done.stdout)["result"]
        assert winners_of(result) == ALL_OPTIONS[None]
        assert result["per_rule"]["runoff"]["round_2"]["votes"] == {"密室逃脱": 12, "剧本杀": 15}
        borda = result["per_rule"]["borda"]["scores"]
        assert (borda["KTV"], borda["爬山"]) == ("64", "63")

    def test_the_example_file_is_the_demo(self):
        data = fc.parse_input((EXAMPLES / "team_outing_27.json").read_text(encoding="utf-8"))
        assert data == fc.parse_input(gv.DEMO_JSON)
        by_file = envelope(data, all_rules=True)["result"]
        assert by_file == envelope(demo_input(), all_rules=True)["result"]


class TestRemovingAnOption:
    """Remove one option and count again."""

    @pytest.mark.parametrize("gone", [k for k in ALL_OPTIONS if k is not None])
    def test_every_rule_after_a_removal(self, gone):
        result = envelope(demo_input(), all_rules=True, remove=[gone])["result"]
        assert winners_of(result) == ALL_OPTIONS[gone]

    @pytest.mark.parametrize("gone", ["剧本杀", "密室逃脱"])
    def test_removing_either_makes_all_five_rules_pick_爬山(self, gone):
        done = run_json(demo_input(), "--all-rules", "--remove", gone, "--json")
        assert done.returncode == 0, done.stderr
        result = json.loads(done.stdout)["result"]
        assert set(winners_of(result).values()) == {"爬山"}
        assert result["recount"]["original_winner"] == "爬山"

    def test_the_recount_says_when_the_winner_changes(self):
        recount = envelope(demo_input("plurality"), remove=["密室逃脱"])["result"]["recount"]
        assert recount == {
            "removed": ["密室逃脱"],
            "original_winner": "密室逃脱",
            "winner": "爬山",
            "changed": True,
        }

    def test_the_recount_says_when_the_winner_stays(self):
        recount = envelope(demo_input("condorcet"), remove=["火锅"])["result"]["recount"]
        assert (recount["winner"], recount["changed"]) == ("爬山", False)

    def test_the_tie_break_order_is_the_original_one_without_the_removed_option(self):
        full = envelope(demo_input())["result"]["tie_break_order"]
        part = envelope(demo_input(), remove=["火锅"])["result"]["tie_break_order"]
        assert part == [name for name in full if name != "火锅"]


class TestSchulzeLiteratureExample:
    """The five-candidate, 45-voter example used to explain the Schulze method."""

    NAMES = "ABCDE"
    LINES = (
        (5, "ACBED"),
        (5, "ADECB"),
        (8, "BEDAC"),
        (3, "CABED"),
        (7, "CAEBD"),
        (2, "CBADE"),
        (7, "DCEBA"),
        (8, "EBADC"),
    )

    def result(self) -> dict:
        data = make_input(list(self.NAMES), [(c, list(r)) for c, r in self.LINES], "schulze")
        return envelope(data)["result"]

    def test_the_pairwise_matrix_counted_by_hand(self):
        matrix = self.result()["pairwise_matrix"]
        assert {a: [matrix[a].get(b) for b in self.NAMES] for a in self.NAMES} == {
            "A": [None, 20, 26, 30, 22],
            "B": [25, None, 16, 33, 18],
            "C": [19, 29, None, 17, 24],
            "D": [15, 12, 28, None, 14],
            "E": [23, 27, 21, 31, None],
        }

    def test_e_wins_although_there_is_no_condorcet_winner(self):
        result = self.result()
        assert result["condorcet_winner"] is None
        assert result["schulze_winners"] == ["E"]
        assert result["winner"] == "E"
        assert result["tie_events"] == []

    def test_the_cycle_is_reported_with_its_margins(self):
        links = self.result()["cycle"]["links"]
        assert [(x["winner"], x["loser"]) for x in links] == [("A", "C"), ("C", "B"), ("B", "A")]
        # 26 : 19 for A over C, 29 : 16 for C over B and 25 : 20 for B over A
        assert [(x["for"], x["against"], x["margin"]) for x in links] == [
            (26, 19, 7),
            (29, 16, 13),
            (25, 20, 5),
        ]


class TestSchulzeTies:
    def test_a_three_way_cycle_ties_all_three_options(self):
        lines = [(1, ["A", "B", "C"]), (1, ["B", "C", "A"]), (1, ["C", "A", "B"])]
        result = envelope(make_input("ABC", lines, "schulze"))["result"]
        assert result["schulze_winners"] == ["A", "B", "C"]
        assert result["cycle"]["links"] == [
            {"winner": "A", "loser": "B", "for": 2, "against": 1, "margin": 1},
            {"winner": "B", "loser": "C", "for": 2, "against": 1, "margin": 1},
            {"winner": "C", "loser": "A", "for": 2, "against": 1, "margin": 1},
        ]
        assert [e["stage"] for e in result["tie_events"]] == ["winner"]
        assert result["winner"] == result["tie_events"][0]["picked"][0]

    def test_the_random_statistic_reproduces(self):
        """Random 4-option profiles: Schulze names more than one potential winner in 11.2%."""
        rng = random.Random(5)
        many = 0
        for _ in range(20000):
            lines = [
                (rng.randint(1, 5), tuple(rng.sample(range(4), 4)))
                for _ in range(rng.randint(3, 6))
            ]
            matrix = gv.pairwise_matrix(lines, [0, 1, 2, 3], 4)
            many += len(gv.schulze_winners(matrix, [0, 1, 2, 3])) > 1
        assert many == 2248


class TestExamplesFolder:
    """Every example file runs, and the numbers in the skill's text come out."""

    @staticmethod
    def load(name: str) -> dict:
        return fc.parse_input((EXAMPLES / name).read_text(encoding="utf-8"))

    def test_the_cycle_example(self):
        result = envelope(self.load("cycle_three.json"))["result"]
        assert result["condorcet_winner"] is None
        assert result["schulze_winners"] == ["火锅", "烧烤", "日料"]
        assert [x["margin"] for x in result["cycle"]["links"]] == [4, 4, 4]
        assert result["winner"] == "烧烤"
        assert result["tie_events"][0]["picked"] == ["烧烤"]

    def test_the_poll_example_ends_in_a_tie_that_the_order_breaks(self):
        result = envelope(self.load("poll_counts.json"))["result"]
        assert result["scores"] == {"海底捞": 12, "烤肉店": 12, "日料店": 9, "川菜馆": 7}
        assert result["winner"] == "烤肉店"
        assert result["tie_events"][0]["tied"] == ["烤肉店", "海底捞"]
        assert result["pairwise_matrix"] is None

    def test_the_questionnaire_example_reads_the_csv(self):
        election = gv.parse_election(self.load("questionnaire.csv.json"))
        assert election.n_ballots == 11
        assert election.partial == "tie_last"
        result = envelope(self.load("questionnaire.csv.json"))["result"]
        assert result["winner"] == "烤肉店"
        assert [r["eliminated"] for r in result["rounds"]] == [["日料店"], ["川菜馆"], []]
        assert [r["counts"] for r in result["rounds"]] == [
            {"海底捞": 4, "烤肉店": 4, "日料店": 1, "川菜馆": 2},
            {"海底捞": 4, "烤肉店": 5, "川菜馆": 2},
            {"海底捞": 4, "烤肉店": 6},
        ]
        assert [r["exhausted"] for r in result["rounds"]] == [0, 0, 1]
        assert result["tie_events"] == []

    @pytest.mark.parametrize(
        "name",
        ["team_outing_27.json", "cycle_three.json", "poll_counts.json", "questionnaire.csv.json"],
    )
    def test_each_example_runs_from_the_command_line(self, name):
        done = run_script("--input", str(EXAMPLES / name))
        assert done.returncode == 0, done.stderr
        assert done.stdout.startswith("# ")


class TestDemoIsByteStable:
    """The demo prints the same bytes on every run and matches the stored copies."""

    CASES: ClassVar[dict] = {
        "demo_md_zh.txt": ["--demo"],
        "demo_md_en.txt": ["--demo", "--lang", "en"],
        "demo_dm_zh.txt": ["--demo", "--format", "dm"],
        "demo_group_zh.txt": ["--demo", "--format", "group"],
        "demo_json.txt": ["--demo", "--json"],
        "demo_remove_md_zh.txt": ["--demo", "--remove", "剧本杀"],
    }

    @pytest.mark.parametrize("name", sorted(CASES))
    def test_two_runs_are_identical(self, name):
        first = run_script(*self.CASES[name])
        second = run_script(*self.CASES[name])
        assert first.returncode == 0, first.stderr
        assert first.stdout == second.stdout

    @pytest.mark.parametrize("name", sorted(CASES))
    def test_output_matches_the_stored_copy(self, name):
        done = run_script(*self.CASES[name])
        assert done.returncode == 0, done.stderr
        stored = GOLDEN_DIR / name
        if os.environ.get("FSQ_UPDATE_GOLDEN") == "1":
            GOLDEN_DIR.mkdir(exist_ok=True)
            stored.write_text(done.stdout, encoding="utf-8", newline="\n")
        assert done.stdout == stored.read_text(encoding="utf-8"), (
            f"{name} differs from the stored copy. If the change is intended, rerun with "
            "FSQ_UPDATE_GOLDEN=1 and review the diff."
        )

    def test_the_demo_does_not_depend_on_the_python_hash_seed(self):
        outputs = set()
        for seed in ("0", "1", "12345"):
            env = {**os.environ, "PYTHONHASHSEED": seed}
            done = subprocess.run(
                [sys.executable, "-B", "-S", str(SCRIPT), "--demo"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=env,
                check=False,
            )
            assert done.returncode == 0, done.stderr
            outputs.add(done.stdout)
        assert len(outputs) == 1


def test_the_demo_profile_in_the_support_module_matches_the_script_demo():
    data = fc.parse_input(gv.DEMO_JSON)
    assert data["options"] == DEMO_OPTIONS
    assert [(b["count"], b["ranking"]) for b in data["ballots"]] == DEMO_LINES
    assert data["rules"]["tie_break"]["random_source"] == SOURCE
