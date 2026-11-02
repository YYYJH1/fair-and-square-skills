"""Reading the input: exit code 2 names the field, and the other input shapes work."""

from __future__ import annotations

import copy
import json
from typing import ClassVar

import fsq_core as fc
import group_vote as gv
import pytest
from vote_support import SOURCE, make_input, run_json, run_script

BASE = {
    "options": ["A", "B", "C"],
    "ballots": [{"count": 2, "ranking": ["A", "B", "C"]}],
    "rules": {"method": "irv"},
}


def changed(**changes) -> dict:
    data = copy.deepcopy(BASE)
    data.update(changes)
    return data


def without(key: str) -> dict:
    data = copy.deepcopy(BASE)
    del data[key]
    return data


def poll(counts, **extra) -> dict:
    data = {
        "options": ["A", "B"],
        "approval_counts": counts,
        "rules": {"method": "approval", "tie_break": {"random_source": "x"}},
    }
    data.update(extra)
    return data


INVALID = [
    ("unknown top-level field", changed(extra=1), "extra"),
    ("one option", changed(options=["A"]), "options"),
    ("too many options", changed(options=[f"o{i}" for i in range(21)]), "options"),
    ("duplicate option", changed(options=["A", "A"]), "options[1]"),
    ("blank option", changed(options=["A", " "]), "options[1]"),
    ("padded option", changed(options=["A", " B"]), "options[1]"),
    ("option with a line break", changed(options=["A", "B\nC"]), "options[1]"),
    ("option that is not text", changed(options=["A", 3]), "options[1]"),
    ("long option", changed(options=["A", "x" * 81]), "options[1]"),
    ("topic that is not text", changed(topic=5), "topic"),
    ("no rules", without("rules"), "rules"),
    ("rules that are not an object", changed(rules="irv"), "rules"),
    ("no method", changed(rules={}), "rules.method"),
    ("unknown method", changed(rules={"method": "coin"}), "rules.method"),
    (
        "unknown partial policy",
        changed(rules={"method": "irv", "partial": "maybe"}),
        "rules.partial",
    ),
    ("unknown rule field", changed(rules={"method": "irv", "seed": 1}), "rules.seed"),
    (
        "tie_break that is a word",
        changed(rules={"method": "irv", "tie_break": "coin"}),
        "rules.tie_break",
    ),
    (
        "tie_break that names a source but gives none",
        changed(rules={"method": "irv", "tie_break": "random_source"}),
        "rules.tie_break",
    ),
    (
        "tie_break with an unknown key",
        changed(rules={"method": "irv", "tie_break": {"coin": 1}}),
        "rules.tie_break.coin",
    ),
    (
        "blank random source",
        changed(rules={"method": "irv", "tie_break": {"random_source": "   "}}),
        "rules.tie_break.random_source",
    ),
    (
        "random source with a line break",
        changed(rules={"method": "irv", "tie_break": {"random_source": "a\nb"}}),
        "rules.tie_break.random_source",
    ),
    (
        "random source that is too long",
        changed(rules={"method": "irv", "tie_break": {"random_source": "x" * 501}}),
        "rules.tie_break.random_source",
    ),
    (
        "two different sources",
        changed(rules={"method": "irv", "random_source": "a", "tie_break": {"random_source": "b"}}),
        "rules.random_source",
    ),
    ("no ballots of any kind", without("ballots"), "ballots"),
    ("two kinds of ballots", changed(approvals=[{"approve": ["A"]}]), "ballots"),
    ("empty ballots", changed(ballots=[]), "ballots"),
    ("a ballot that is a list", changed(ballots=[["A", "B", "C"]]), "ballots[0]"),
    (
        "unknown ballot field",
        changed(ballots=[{"ranking": ["A"], "weight": 2}]),
        "ballots[0].weight",
    ),
    ("ballot without ranking", changed(ballots=[{"count": 1}]), "ballots[0].ranking"),
    ("empty ranking", changed(ballots=[{"ranking": []}]), "ballots[0].ranking"),
    (
        "ranking with an unknown option",
        changed(ballots=[{"ranking": ["A", "Z"]}]),
        "ballots[0].ranking[1]",
    ),
    (
        "ranking with a repeat",
        changed(ballots=[{"ranking": ["A", "A", "B", "C"]}]),
        "ballots[0].ranking[1]",
    ),
    (
        "ranking entry that is a number",
        changed(ballots=[{"ranking": ["A", 1]}]),
        "ballots[0].ranking[1]",
    ),
    ("zero count", changed(ballots=[{"count": 0, "ranking": ["A", "B", "C"]}]), "ballots[0].count"),
    (
        "fractional count",
        changed(ballots=[{"count": 1.5, "ranking": ["A", "B", "C"]}]),
        "ballots[0].count",
    ),
    (
        "true as a count",
        changed(ballots=[{"count": True, "ranking": ["A", "B", "C"]}]),
        "ballots[0].count",
    ),
    (
        "count above the limit",
        changed(ballots=[{"count": 10**7, "ranking": ["A", "B", "C"]}]),
        "ballots[0].count",
    ),
    (
        "voter with a count",
        changed(ballots=[{"voter": "x", "count": 2, "ranking": ["A", "B", "C"]}]),
        "ballots[0].count",
    ),
    (
        "voter used twice",
        changed(
            ballots=[
                {"voter": "x", "ranking": ["A", "B", "C"]},
                {"voter": "x", "ranking": ["B", "A", "C"]},
            ]
        ),
        "ballots[1].voter",
    ),
    (
        "blank voter",
        changed(ballots=[{"voter": " ", "ranking": ["A", "B", "C"]}]),
        "ballots[0].voter",
    ),
    ("partial ballot under reject", changed(ballots=[{"ranking": ["A", "B"]}]), "ballots[0]"),
    ("approval method with rankings", changed(rules={"method": "approval"}), "rules.method"),
    (
        "approvals under a ranking method",
        {"options": ["A", "B"], "approvals": [{"approve": ["A"]}], "rules": {"method": "irv"}},
        "rules.method",
    ),
    (
        "approval ballot with an unknown option",
        {"options": ["A", "B"], "approvals": [{"approve": ["Z"]}], "rules": {"method": "approval"}},
        "approvals[0].approve[0]",
    ),
    ("poll that misses an option", poll({"A": 3}), "approval_counts.B"),
    ("poll with an unknown option", poll({"A": 3, "B": 1, "C": 2}), "approval_counts.C"),
    ("poll with a negative count", poll({"A": 3, "B": -1}), "approval_counts.B"),
    ("poll with a fractional count", poll({"A": 3, "B": 1.5}), "approval_counts.B"),
    ("poll that is a list", poll([3, 1]), "approval_counts"),
    (
        "participants below the largest count",
        poll({"A": 3, "B": 1}, participants=2),
        "participants",
    ),
    ("participants without a poll", changed(participants=3), "participants"),
    (
        "kemeny with nine options",
        make_input([f"o{i}" for i in range(9)], [(1, [f"o{i}" for i in range(9)])], "kemeny"),
        "rules.method",
    ),
]


@pytest.mark.parametrize(("label", "data", "field"), INVALID, ids=[case[0] for case in INVALID])
def test_invalid_input_exits_with_code_2_and_names_the_field(label, data, field):
    done = run_json(data)
    assert done.returncode == 2, f"{label}: {done.stderr}"
    assert done.stdout == ""
    assert f'field "{field}"' in done.stderr, done.stderr
    assert "Traceback" not in done.stderr


@pytest.mark.parametrize(("label", "data", "field"), INVALID, ids=[case[0] for case in INVALID])
def test_the_library_raises_the_same_error(label, data, field):
    with pytest.raises(fc.InputError) as err:
        gv.solve(data)
    assert err.value.field == field


class TestRawInput:
    def test_text_that_is_not_json(self):
        done = run_script("--input", "-", stdin="{oops")
        assert done.returncode == 2
        assert 'field "input"' in done.stderr

    def test_json_that_is_not_an_object(self):
        done = run_script("--input", "-", stdin="[1, 2]")
        assert done.returncode == 2

    def test_empty_standard_input(self):
        done = run_script("--input", "-", stdin="")
        assert done.returncode == 2

    def test_a_lone_surrogate_in_a_name(self):
        text = '{"options": ["A", "\\ud800"], "ballots": [{"ranking": ["A"]}], "rules": {"method": "plurality"}}'
        done = run_script("--input", "-", stdin=text)
        assert done.returncode == 2
        assert "options[1]" in done.stderr

    def test_duplicate_keys_are_refused(self):
        text = '{"options": ["A", "B"], "options": ["A", "C"], "ballots": [], "rules": {}}'
        assert run_script("--input", "-", stdin=text).returncode == 2

    def test_a_missing_file(self):
        done = run_script("--input", "no-such-file.json")
        assert done.returncode == 2
        assert "cannot read" in done.stderr

    def test_more_ballot_lines_than_the_limit(self):
        lines = [{"ranking": ["A", "B"], "voter": f"v{i}"} for i in range(gv.MAX_BALLOT_LINES + 1)]
        data = {"options": ["A", "B"], "ballots": lines, "rules": {"method": "plurality"}}
        done = run_json(data)
        assert done.returncode == 2
        assert "ballots" in done.stderr

    def test_a_count_that_is_a_whole_decimal_is_fine(self):
        text = (
            '{"options": ["A", "B"], "ballots": [{"count": 2.0, "ranking": ["A", "B"]}],'
            ' "rules": {"method": "plurality"}}'
        )
        done = run_script("--input", "-", "--json", stdin=text)
        assert done.returncode == 0, done.stderr
        assert json.loads(done.stdout)["result"]["scores"] == {"A": 2, "B": 0}


class TestRulesMessage:
    def test_the_rent_split_spelling_of_the_random_source_is_accepted(self):
        nested = make_input("ABC", [(1, "ABC"), (1, "BAC")], "plurality", source="the draw")
        flat = make_input("ABC", [(1, "ABC"), (1, "BAC")], "plurality", source=None)
        flat["rules"]["random_source"] = "the draw"
        assert gv.tie_order(gv.parse_election(nested)) == gv.tie_order(gv.parse_election(flat))

    def test_tie_break_may_name_the_kind_and_the_source_may_sit_beside_it(self):
        data = make_input("ABC", [(1, "ABC"), (1, "BAC")], "plurality", source=None)
        data["rules"].update(tie_break="random_source", random_source="the draw")
        assert gv.parse_election(data).source == "the draw"

    def test_the_same_source_twice_is_fine(self):
        data = make_input("ABC", [(1, "ABC")], "plurality", source="s")
        data["rules"]["random_source"] = "s"
        assert gv.parse_election(data).source == "s"

    def test_the_source_is_used_exactly_as_written(self):
        a = make_input("ABC", [(1, "ABC")], "plurality", source="draw 1")
        b = make_input("ABC", [(1, "ABC")], "plurality", source="draw  1")
        assert gv.tie_order(gv.parse_election(a))[1] != gv.tie_order(gv.parse_election(b))[1]

    def test_the_partial_policy_defaults_to_reject(self):
        assert gv.parse_election(changed()).partial == "reject"


class TestQuestionnaireText:
    OPTIONS: ClassVar[list] = ["A", "B", "C"]

    def run(self, csv_text, method="irv", **rules):
        data = {
            "options": self.OPTIONS,
            "csv": csv_text,
            "rules": {"method": method, "partial": "tie_last", **rules},
        }
        return gv.parse_election(data)

    def test_ranks_become_rankings(self):
        election = self.run("A,B,C\n1,2,3\n3,1,2\n1,2,3\n")
        assert election.kind == "ranked"
        assert election.n_ballots == 3
        assert election.lines == [(2, (0, 1, 2)), (1, (1, 2, 0))]

    def test_other_columns_are_ignored_and_the_column_order_does_not_matter(self):
        election = self.run("time,C,name,A,B\n09:00,3,x,1,2\n09:05,1,y,2,3\n")
        assert sorted(election.lines) == [(1, (0, 1, 2)), (1, (2, 0, 1))]

    def test_blank_cells_leave_options_unranked(self):
        election = self.run("A,B,C\n,1,\n2,,1\n")
        assert sorted(election.lines) == [(1, (1,)), (1, (2, 0))]
        assert election.first_partial is not None

    def test_gaps_in_the_numbers_only_matter_for_the_order(self):
        election = self.run("A,B,C\n5,1,9\n")
        assert election.lines == [(1, (1, 0, 2))]

    def test_tabs_and_quotes_and_windows_line_endings_and_a_byte_order_mark(self):
        text = '﻿"A"\t"B"\t"C"\r\n1\t2\t3\r\n\r\n3\t2\t1\r\n'
        election = self.run(text)
        assert election.n_ballots == 2

    def test_blank_lines_are_skipped(self):
        assert self.run("A,B,C\n\n1,2,3\n\n,,\n").n_ballots == 1

    def test_a_row_that_ranks_nothing_is_refused_with_its_line_number(self):
        with pytest.raises(fc.InputError) as err:
            self.run("time,A,B,C\n09:00,1,2,3\n09:05,,,\n")
        assert err.value.field == "csv line 3"

    def test_two_options_with_one_rank_are_refused(self):
        with pytest.raises(fc.InputError) as err:
            self.run("A,B,C\n1,1,2\n")
        assert err.value.field == "csv line 2"
        assert "rank 1" in err.value.message

    @pytest.mark.parametrize("cell", ["x", "0", "-1", "1.5", "二", "1st"])
    def test_a_rank_must_be_a_whole_number_from_1(self, cell):
        with pytest.raises(fc.InputError) as err:
            self.run(f"A,B,C\n1,{cell},3\n")
        assert err.value.field == "csv line 2"

    def test_the_header_must_name_every_option(self):
        with pytest.raises(fc.InputError) as err:
            self.run("A,B\n1,2\n")
        assert err.value.field == "csv"
        assert "'C'" in err.value.message

    def test_an_option_named_twice_in_the_header_is_refused(self):
        with pytest.raises(fc.InputError):
            self.run("A,B,C,A\n1,2,3,4\n")

    def test_a_table_needs_a_row_of_ballots(self):
        with pytest.raises(fc.InputError):
            self.run("A,B,C\n")

    def test_the_csv_must_be_text(self):
        with pytest.raises(fc.InputError) as err:
            self.run(["A,B,C"])
        assert err.value.field == "csv"

    def test_ticks_become_approvals(self):
        election = self.run("who,A,B,C\nx,1,1,\ny,,1,0\nz,1,,\n", method="approval")
        assert election.kind == "approval"
        assert sorted(election.lines) == [(1, (0,)), (1, (0, 1)), (1, (1,))]
        out = fc.envelope(
            gv.solve(
                {
                    "options": self.OPTIONS,
                    "csv": "A,B,C\n1,1,\n,1,0\n1,,\n",
                    "rules": {"method": "approval", "tie_break": {"random_source": "s"}},
                }
            )
        )["result"]
        assert out["scores"] == {"A": 2, "B": 2, "C": 0}

    def test_a_tick_must_be_a_1(self):
        with pytest.raises(fc.InputError) as err:
            self.run("A,B,C\n1,2,\n", method="approval")
        assert err.value.field == "csv line 2"

    def test_the_questionnaire_gives_the_same_result_as_the_same_ballots_in_json(self):
        csv_text = "A,B,C\n1,2,3\n1,2,3\n2,1,3\n3,2,1\n"
        rules = {"method": "irv", "tie_break": {"random_source": SOURCE}}
        by_csv = {"options": self.OPTIONS, "csv": csv_text, "rules": rules}
        by_json = make_input(self.OPTIONS, [(2, "ABC"), (1, "BAC"), (1, "CBA")], "irv")
        assert fc.envelope(gv.solve(by_csv))["result"] == fc.envelope(gv.solve(by_json))["result"]


class TestPollTotals:
    def test_totals_are_counted_as_approval_voting(self):
        out = fc.envelope(gv.solve(poll({"A": 7, "B": 4}, participants=9)))
        assert out["result"]["winner"] == "A"
        assert out["inputs_echo"]["participants"] == 9
        assert out["inputs_echo"]["approval_counts"] == {"A": 7, "B": 4}
        assert out["inputs_echo"]["kind"] == "poll"

    def test_participants_are_optional(self):
        assert "participants" not in fc.envelope(gv.solve(poll({"A": 7, "B": 4})))["inputs_echo"]

    def test_all_rules_needs_rankings(self):
        done = run_json(poll({"A": 7, "B": 4}), "--all-rules")
        assert done.returncode == 2
        assert "--all-rules" in done.stderr


class TestCommandLine:
    def test_remove_names_must_be_options(self):
        done = run_json(changed(), "--remove", "Z")
        assert done.returncode == 2
        assert 'field "--remove"' in done.stderr

    def test_at_least_two_options_must_stay(self):
        done = run_json(changed(), "--remove", "A", "--remove", "B")
        assert done.returncode == 2
        assert "two options" in done.stderr

    def test_remove_may_be_repeated_and_names_may_repeat(self):
        data = make_input(list("ABCD"), [(2, list("ABCD")), (1, list("DCBA"))], "plurality")
        done = run_json(data, "--remove", "A", "--remove", "A", "--remove", "B", "--json")
        assert done.returncode == 0, done.stderr
        assert json.loads(done.stdout)["inputs_echo"]["removed"] == ["A", "B"]

    def test_remove_works_with_names_that_contain_spaces(self):
        data = make_input(
            ["fire pot", "hike", "KTV"], [(2, ["fire pot", "hike", "KTV"])], "plurality"
        )
        done = run_json(data, "--remove", "fire pot", "--json")
        assert done.returncode == 0, done.stderr
        assert json.loads(done.stdout)["result"]["winner"] == "hike"
        assert "'fire pot'" in json.loads(done.stdout)["reproduce"]

    def test_an_unknown_flag_is_an_argparse_error(self):
        assert run_script("--bogus").returncode == 2

    def test_help_lists_the_flags(self):
        text = run_script("--help").stdout
        for flag in (
            "--input",
            "--format",
            "--json",
            "--demo",
            "--selftest",
            "--lang",
            "--all-rules",
            "--remove",
        ):
            assert flag in text

    def test_the_lang_must_be_zh_or_en(self):
        assert run_script("--demo", "--lang", "fr").returncode == 2

    def test_selftest_passes(self):
        done = run_script("--selftest")
        assert done.returncode == 0, done.stdout
        assert "0 failed" in done.stdout


class TestTheRulesAreRequired:
    @pytest.mark.parametrize("method", gv.METHODS)
    def test_every_method_name_is_known(self, method):
        key = "approvals" if method == "approval" else "ballots"
        ballot = {"approve": ["A"]} if method == "approval" else {"ranking": ["A", "B"]}
        data = {"options": ["A", "B"], key: [ballot], "rules": {"method": method}}
        assert fc.envelope(gv.solve(data))["result"]["method"] == method
