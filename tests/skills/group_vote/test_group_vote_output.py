"""Output: every format renders, private messages stay private, the JSON envelope is stable."""

from __future__ import annotations

import itertools
import json
import re
import string
from pathlib import Path

import fsq_core as fc
import group_vote as gv
import pytest
from vote_support import (
    DEMO_LINES,
    DEMO_OPTIONS,
    EXAMPLES,
    SOURCE,
    demo_input,
    make_input,
    run_json,
    run_script,
)

ENVELOPE_KEYS = ["certificate", "inputs_echo", "not_modeled", "reproduce", "result"]
CJK = re.compile("[　-〿㐀-䶿一-鿿＀-￯]")
ASCII_OPTIONS = ["fire pot", "hiking", "KTV", "escape room"]
ASCII_LINES = [
    (4, ["fire pot", "hiking", "KTV", "escape room"]),
    (3, ["hiking", "KTV", "escape room", "fire pot"]),
    (2, ["KTV", "escape room", "fire pot", "hiking"]),
    (2, ["escape room", "fire pot", "hiking", "KTV"]),
]
ASCII_SOURCE = "fictional draw 2026-11-08 03 11 19 24 33"


def example(name: str) -> dict:
    return fc.parse_input((EXAMPLES / name).read_text(encoding="utf-8"))


def named(options, lines, method="irv", **kwargs):
    """The same ballots, one named voter per ballot (the counts are dropped)."""
    data = make_input(options, lines, method, **kwargs)
    data["ballots"] = [
        {"voter": f"voter-{i}", "ranking": list(ranking)} for i, (_, ranking) in enumerate(lines)
    ]
    return data


def cases():
    """(label, data, flags) for the examples and for each branch of the output."""
    approvals = {
        "options": ["A", "B", "C"],
        "approvals": [
            {"voter": "Ann", "approve": ["A", "B"]},
            {"voter": "Bo", "approve": []},
            {"count": 3, "approve": ["B"]},
        ],
        "rules": {"method": "approval", "tie_break": {"random_source": "x"}},
    }
    partial = make_input(
        "ABC", [(2, ["A"]), (1, ["B", "C"]), (1, ["C", "B"])], "irv", partial="tie_last"
    )
    return [
        ("team outing", example("team_outing_27.json"), []),
        ("team outing, all rules", example("team_outing_27.json"), ["all_rules"]),
        ("cycle", example("cycle_three.json"), []),
        ("poll", example("poll_counts.json"), []),
        ("questionnaire", example("questionnaire.csv.json"), []),
        ("recount", demo_input("borda"), ["remove"]),
        ("recount with all rules", demo_input("irv"), ["all_rules", "remove"]),
        ("named voters", named(DEMO_OPTIONS, DEMO_LINES, "borda"), []),
        ("named voters, recount", named(DEMO_OPTIONS, DEMO_LINES, "borda"), ["remove"]),
        ("approvals", approvals, []),
        ("partial ballots, all rules", partial, ["all_rules"]),
        ("kemeny", demo_input("kemeny"), []),
        ("runoff in one round", make_input("AB", [(3, "AB"), (1, "BA")], "runoff"), []),
        ("runoff", demo_input("runoff"), []),
        ("plurality", demo_input("plurality"), []),
        ("no random source", make_input("AB", [(3, "AB"), (1, "BA")], "schulze", source=None), []),
    ]


CASES = cases()
IDS = [case[0] for case in CASES]


def solve(data, flags, lang="zh"):
    remove = [data["options"][0]] if "remove" in flags else []
    return gv.solve(data, lang=lang, all_rules="all_rules" in flags, remove=remove)


@pytest.mark.parametrize(("label", "data", "flags"), CASES, ids=IDS)
@pytest.mark.parametrize("lang", ["zh", "en"])
@pytest.mark.parametrize("fmt", ["md", "dm", "group", "json"])
def test_every_format_renders(label, data, flags, lang, fmt):
    result = solve(data, flags, lang)
    text = fc.render(result, "md" if fmt == "json" else fmt, fmt == "json", lang)
    assert text.strip()
    if fmt == "json":
        assert sorted(json.loads(text)) == ENVELOPE_KEYS
    else:
        for bad in ("None", "Fraction(", "{", "}", "\\n"):
            assert bad not in text, f"{label}/{fmt}/{lang}: {bad!r}"
    assert result.title in text or fmt in ("dm", "json")


@pytest.mark.parametrize("fmt", ["md", "dm", "group"])
@pytest.mark.parametrize("lang", ["zh", "en"])
@pytest.mark.parametrize("name", ["team_outing_27.json", "cycle_three.json", "poll_counts.json"])
def test_the_command_line_prints_each_format_and_nothing_on_stderr(name, lang, fmt):
    done = run_script("--input", str(EXAMPLES / name), "--format", fmt, "--lang", lang)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip()
    assert done.stderr == ""


@pytest.fixture(scope="module")
def parsed():
    return json.loads(run_script("--demo", "--json").stdout)


class TestJsonEnvelope:
    def test_the_five_keys_of_the_shared_envelope(self, parsed):
        assert sorted(parsed) == ENVELOPE_KEYS

    def test_the_result_keys(self, parsed):
        result = parsed["result"]
        for key in (
            "method",
            "winner",
            "tie_break_order",
            "tie_events",
            "pairwise_matrix",
            "condorcet_winner",
            "schulze_winners",
            "cycle",
            "per_rule_winners",
            "per_rule",
        ):
            assert key in result, key
        assert result["method"] == "condorcet"
        assert result["winner"] == "爬山"
        assert result["cycle"] is None
        assert result["tie_events"] == []
        assert sorted(result["tie_break_order"]) == sorted(DEMO_OPTIONS)

    def test_the_echo_reads_the_input_back(self, parsed):
        echo = parsed["inputs_echo"]
        assert echo["options"] == DEMO_OPTIONS
        assert echo["ballot_total"] == 27
        assert echo["ballot_lines"][0] == {"count": 8, "ranking": DEMO_LINES[0][1]}
        assert echo["rules"]["method"] == "condorcet"
        assert echo["rules"]["partial"] == "reject"
        assert echo["rules"]["tie_break"] == {"random_source": SOURCE}
        assert echo["all_rules"] is True

    def test_the_certificate_lets_anyone_recompute_the_order(self, parsed):
        cert = parsed["certificate"]
        election = gv.parse_election(example("team_outing_27.json"))
        order, seed_hex = gv.tie_order(election)
        assert cert["seed_hex"] == seed_hex
        assert cert["tie_break_order"] == [DEMO_OPTIONS[i] for i in order]
        assert "n_slots is 1" in cert["how_to_verify"]
        assert "one_liner" not in cert

    def test_the_run_without_a_source_has_no_seed(self):
        data = make_input("AB", [(3, "AB"), (1, "BA")], "schulze", source=None)
        envelope = fc.envelope(gv.solve(data))
        assert envelope["certificate"]["seed_hex"] is None
        assert envelope["certificate"]["how_to_verify"] is None
        assert envelope["result"]["tie_break_order"] is None

    def test_no_number_is_written_as_a_float(self, parsed):
        text = json.dumps(parsed, ensure_ascii=False)
        assert not re.search(r"\d\.\d", re.sub(r'"[^"]*"', '""', text))

    def test_per_rule_is_only_there_with_all_rules(self):
        plain = fc.envelope(gv.solve(demo_input()))["result"]
        assert "per_rule" not in plain and "per_rule_winners" not in plain
        assert "recount" not in plain

    def test_a_recount_block_is_only_there_with_remove(self):
        out = fc.envelope(gv.solve(demo_input("plurality"), remove=["密室逃脱"]))
        assert out["result"]["recount"]["changed"] is True
        assert out["inputs_echo"]["removed"] == ["密室逃脱"]
        assert out["result"]["pairwise_matrix"].keys() == {"爬山", "剧本杀", "火锅", "KTV"}

    def test_the_reproduce_command_repeats_the_flags(self):
        done = run_script("--demo", "--json", "--lang", "en", "--remove", "KTV")
        assert json.loads(done.stdout)["reproduce"] == (
            "python3 scripts/group_vote.py --demo --json --remove KTV --lang en"
        )
        done = run_json(demo_input(), "--format", "group", "--all-rules")
        assert done.returncode == 0

    def test_borda_scores_are_exact_decimal_strings(self):
        data = make_input("ABC", [(1, "A")], "borda", partial="tie_last")
        scores = fc.envelope(gv.solve(data))["result"]["scores"]
        assert scores == {"A": "2", "B": "0.5", "C": "0.5"}


class TestPrivateMessages:
    def test_each_voter_gets_exactly_their_own_ballot(self):
        data = named(ASCII_OPTIONS, ASCII_LINES, "borda", source=ASCII_SOURCE)
        result = gv.solve(data, lang="en")
        messages = fc.render_dm_messages(result)
        assert list(messages) == [f"voter-{i}" for i in range(4)]
        for i, (_, ranking) in enumerate(ASCII_LINES):
            text = messages[f"voter-{i}"]
            assert "Your ballot was recorded as: " + " > ".join(ranking) in text
            assert "voter-" not in text
            for j, (_, other) in enumerate(ASCII_LINES):
                if j != i:
                    assert " > ".join(other) not in text

    def test_a_receipt_tells_where_the_winner_stood_on_the_ballot(self):
        data = named("ABC", [(1, "BAC"), (1, "CBA")], "plurality", source="s")
        data["ballots"].append({"voter": "late", "ranking": ["A"]})
        messages = fc.render_dm_messages(gv.solve(data, lang="en"))
        winner = fc.envelope(gv.solve(data))["result"]["winner"]
        for voter, ranking in (("voter-0", "BAC"), ("voter-1", "CBA")):
            assert f"You ranked {winner} number {ranking.index(winner) + 1}." in messages[voter]
        assert messages["late"].count("count as tied for last") == 1

    def test_the_unranked_options_are_named_in_the_receipt(self):
        data = make_input("ABC", [(1, "A")], "irv", partial="tie_last")
        data["ballots"] = [{"voter": "x", "ranking": ["A"]}]
        text = fc.render_dm_messages(gv.solve(data, lang="en"))["x"]
        assert "(B, C) count as tied for last" in text

    def test_voter_names_stay_out_of_the_organizers_tables_and_the_group_summary(self):
        data = named(ASCII_OPTIONS, ASCII_LINES, "irv", source=ASCII_SOURCE)
        result = gv.solve(data, lang="en")
        for fmt in ("md", "group"):
            assert "voter-" not in fc.render(result, fmt, False, "en")

    def test_voter_names_appear_in_json_only_as_receipts(self):
        data = named(ASCII_OPTIONS, ASCII_LINES, "irv", source=ASCII_SOURCE)
        text = fc.render(gv.solve(data, lang="en"), "md", True, "en")
        parsed = json.loads(text)
        assert sorted(parsed["certificate"]["one_liner"]) == [f"voter-{i}" for i in range(4)]
        without = dict(parsed)
        without["certificate"] = {}
        assert "voter-" not in json.dumps(without)

    def test_the_group_summary_holds_no_ballot(self):
        out = fc.render(gv.solve(demo_input("irv")), "group", False, "zh")
        assert " > " not in out
        for _, ranking in DEMO_LINES:
            assert "，".join(ranking) not in out and "、".join(ranking) not in out

    def test_without_voter_names_dm_is_one_block_for_everyone(self):
        out = fc.render(gv.solve(demo_input()), "dm", False, "zh")
        assert out.count("--- 发给 ") == 1
        assert "--- 发给 每位投票人 ---" in out
        out = fc.render(gv.solve(demo_input(), lang="en"), "dm", False, "en")
        assert "--- To Every voter ---" in out

    def test_approval_receipts_say_what_was_approved(self):
        data = {
            "options": ["A", "B"],
            "approvals": [{"voter": "x", "approve": ["A"]}, {"voter": "y", "approve": []}],
            "rules": {"method": "approval", "tie_break": {"random_source": "s"}},
        }
        messages = fc.render_dm_messages(gv.solve(data, lang="en"))
        assert "approving: A." in messages["x"]
        assert "approving nothing" in messages["y"] or "(approves nothing)" in messages["y"]


def test_every_text_key_is_used_by_the_script():
    body = Path(gv.__file__).read_text(encoding="utf-8").split("# Data classes")[1]
    dynamic_prefixes = ("st_",)
    for key in gv.TEXT["zh"]:
        used = f'"{key}"' in body or f"'{key}'" in body or key.startswith(dynamic_prefixes)
        assert used, f"TEXT has an unused key: {key}"


class TestLanguages:
    def flat(self, value, prefix=""):
        if isinstance(value, dict):
            for key, item in value.items():
                yield from self.flat(item, f"{prefix}{key}.")
        else:
            yield prefix.rstrip("."), value

    def test_both_languages_have_the_same_keys(self):
        zh = dict(self.flat(gv.TEXT["zh"]))
        en = dict(self.flat(gv.TEXT["en"]))
        assert set(zh) == set(en)

    def test_both_languages_use_the_same_placeholders(self):
        zh = dict(self.flat(gv.TEXT["zh"]))
        en = dict(self.flat(gv.TEXT["en"]))
        formatter = string.Formatter()

        def names(text):
            if not isinstance(text, str):
                return None
            return {field for _, field, _, _ in formatter.parse(text) if field is not None}

        for key, zh_value in zh.items():
            assert names(zh_value) == names(en[key]), key

    def test_header_lists_have_the_same_width(self):
        for key, zh in gv.TEXT["zh"].items():
            if isinstance(zh, list):
                assert len(zh) == len(gv.TEXT["en"][key]), key

    def test_english_output_has_no_chinese_when_the_names_are_in_english(self):
        data = make_input(ASCII_OPTIONS, ASCII_LINES, "irv", source=ASCII_SOURCE)
        result = gv.solve(data, lang="en", all_rules=True, remove=["hiking"])
        for fmt in ("md", "dm", "group"):
            text = fc.render(result, fmt, False, "en")
            assert not CJK.search(text), (fmt, CJK.search(text).group(0))

    def test_chinese_output_is_chinese(self):
        data = make_input(ASCII_OPTIONS, ASCII_LINES, "irv", source=ASCII_SOURCE)
        text = fc.render(gv.solve(data, lang="zh"), "md", False, "zh")
        assert "赢家" in text and "两两比较矩阵" in text

    def test_the_winner_and_the_numbers_do_not_depend_on_the_language(self):
        data = demo_input("irv")
        zh = fc.envelope(gv.solve(data, lang="zh"))["result"]
        en = fc.envelope(gv.solve(data, lang="en"))["result"]
        assert zh == en


class TestWhatTheTextSays:
    def test_all_rules_says_it_is_for_explaining_after_the_fact(self):
        zh = fc.render(gv.solve(demo_input(), all_rules=True), "md", False, "zh")
        en = fc.render(gv.solve(demo_input(), lang="en", all_rules=True), "md", False, "en")
        assert "事后讲解" in zh and "不能看了结果再挑" in zh
        assert "after the fact" in en and "must not be chosen after seeing results" in en
        group = fc.render(gv.solve(demo_input(), all_rules=True), "group", False, "zh")
        assert "事后对照" in group and "规则不能事后改" in group

    def test_the_help_says_the_same(self):
        assert "after the fact" in run_script("--help").stdout.replace("\n", " ")

    def test_the_agreed_rule_is_marked_in_the_table(self):
        text = fc.render(
            gv.solve(demo_input("borda"), lang="en", all_rules=True), "md", False, "en"
        )
        assert "| Borda (the agreed rule) | KTV |" in text
        assert "(the agreed rule)" not in text.replace("| Borda (the agreed rule) |", "")

    def test_kemeny_is_listed_as_not_available_for_more_than_eight_options(self):
        options = [f"o{i}" for i in range(9)]
        lines = [(2, options), (1, list(reversed(options)))]
        data = make_input(options, lines, "plurality")
        out = fc.envelope(gv.solve(data, all_rules=True))["result"]
        assert "kemeny" not in out["per_rule"]
        text = fc.render(gv.solve(data, lang="en", all_rules=True), "md", False, "en")
        assert "| Kemeny | not available (more than 8 options) |  |" in text
        assert (
            "kemeny"
            not in fc.render(
                gv.solve(data, lang="en", all_rules=True), "group", False, "en"
            ).lower()
        )

    def test_the_count_of_different_winners_is_stated(self):
        zh = fc.render(gv.solve(demo_input(), all_rules=True), "md", False, "zh")
        assert "这 7 种规则里，一共出现了 5 个不同的赢家。" in zh
        same = fc.render(
            gv.solve(demo_input(), all_rules=True, remove=["剧本杀"]), "md", False, "zh"
        )
        assert "这 7 种规则选出的赢家相同。" in same

    def test_the_table_with_a_removal_has_a_before_and_after_column(self):
        text = fc.render(
            gv.solve(demo_input(), lang="en", all_rules=True, remove=["火锅"]), "md", False, "en"
        )
        assert "| Rule | All options | Without 火锅 | Changed? |" in text
        assert "| Plurality | 密室逃脱 | KTV | Changed |" in text
        assert "| Condorcet (the agreed rule) | 爬山 | 爬山 | Unchanged |" in text

    def test_a_recount_says_what_happened_to_the_winner(self):
        changed = fc.render(
            gv.solve(demo_input("plurality"), remove=["密室逃脱"]), "group", False, "zh"
        )
        assert "去掉密室逃脱后按同一规则重新计票：赢家从 密室逃脱 变成 爬山。" in changed
        same = fc.render(gv.solve(demo_input(), remove=["火锅"]), "group", False, "zh")
        assert "赢家没变，仍是 爬山。" in same
        md = fc.render(
            gv.solve(demo_input("plurality"), lang="en", remove=["密室逃脱"]), "md", False, "en"
        )
        assert "| Did the winner change | Changed |" in md

    def test_a_latin_name_is_set_off_from_the_chinese_words_in_a_recount(self):
        data = make_input(ASCII_OPTIONS, ASCII_LINES, "borda", source=ASCII_SOURCE)
        result = gv.solve(data, all_rules=True, remove=["KTV"])
        md = fc.render(result, "md", False, "zh")
        assert md.startswith("# 投票：去掉 KTV 后重新计票，按博达计分\n")
        assert "| 去掉 KTV 后的赢家 | fire pot |" in md
        assert "| 规则 | 全部选项 | 去掉 KTV 后 | 变了吗 |" in md
        assert "去掉 KTV 后按同一规则重新计票，赢家从 hiking 变成 fire pot。" in md
        assert "事先说好的规则是博达计分，赢家是 fire pot。" in md
        group = fc.render(result, "group", False, "zh")
        assert "去掉 KTV 后按同一规则重新计票：赢家从 hiking 变成 fire pot。" in group

    def test_every_removed_name_is_set_off_and_the_names_keep_their_separator(self):
        data = make_input(ASCII_OPTIONS, ASCII_LINES, "borda", source=ASCII_SOURCE)
        result = gv.solve(data, remove=["fire pot", "KTV"])
        assert "去掉 fire pot、KTV 后按同一规则重新计票" in fc.render(result, "group", False, "zh")

    def test_a_private_message_sets_off_a_latin_name_after_a_recount(self):
        data = named(ASCII_OPTIONS, ASCII_LINES, "borda", source=ASCII_SOURCE)
        messages = fc.render_dm_messages(gv.solve(data, remove=["KTV"]))
        assert "去掉 KTV 后按同一规则重新计票：escape room 当选。" in messages["voter-0"]

    def test_a_private_message_sets_off_a_latin_rule_name(self):
        data = named(ASCII_OPTIONS, ASCII_LINES, "schulze", source=ASCII_SOURCE)
        message = fc.render_dm_messages(gv.solve(data))["voter-0"]
        assert "规则是 Schulze 法。" in message and "：" in message

    def test_a_chinese_name_gets_no_space_in_a_recount(self):
        result = gv.solve(demo_input(), all_rules=True, remove=["剧本杀"])
        md = fc.render(result, "md", False, "zh")
        assert "去掉剧本杀后重新计票" in md and "| 去掉剧本杀后的赢家 |" in md
        assert "| 规则 | 全部选项 | 去掉剧本杀后 | 变了吗 |" in md
        assert "事先说好的规则是孔多塞（Schulze 补全），赢家是爬山。" in md

    def test_ties_are_listed_with_where_and_who(self):
        text = fc.render(gv.solve(example("poll_counts.json")), "md", False, "zh")
        assert "| 选赢家 | 烤肉店、海底捞 | 烤肉店 当选 |" in text

    def test_a_cycle_is_listed_with_its_margins(self):
        text = fc.render(gv.solve(example("cycle_three.json"), lang="en"), "md", False, "en")
        assert "| 火锅 | 烧烤 | 8 : 4 | 4 |" in text
        assert "No Condorcet winner" in text

    def test_ballots_removed_with_the_option_are_counted_in_the_table(self):
        data = make_input(
            "ABC", [(2, ["A"]), (1, ["B", "C"]), (1, ["C", "B"])], "plurality", partial="tie_last"
        )
        text = fc.render(gv.solve(data, remove=["A"]), "md", False, "zh")
        assert "| 不再计入的选票 | 2 张（排的选项都被去掉了） |" in text

    def test_the_long_list_of_ballot_lines_is_cut_in_the_organizers_table_only(self):
        many = [(1, list(ranking)) for ranking in itertools.permutations("ABCDE")]
        assert len(many) == 120
        data = make_input(list("ABCDE"), many, "borda")
        text = fc.render(gv.solve(data, lang="en"), "md", False, "en")
        table = text.split("## Ballots (equal ones merged)")[1].split("\n\n")[1]
        assert len(table.splitlines()) == 2 + gv.MAX_SHOWN_LINES
        assert (
            f"({120 - gv.MAX_SHOWN_LINES} more are not listed; see --json for the full list.)"
            in text
        )
        parsed_json = json.loads(fc.render(gv.solve(data), "md", True, "zh"))
        assert len(parsed_json["inputs_echo"]["ballot_lines"]) == 120

    def test_a_title_comes_from_the_topic(self):
        zh = gv.solve(example("team_outing_27.json"), lang="zh")
        assert zh.title.startswith("团建去哪儿：")
        data = demo_input()
        assert gv.solve(data, lang="zh").title.startswith("投票：")
        assert gv.solve(data, lang="en").title.startswith("Vote: ")

    def test_the_organizers_table_shows_the_order_and_the_seed(self):
        text = fc.render(gv.solve(demo_input()), "md", False, "zh")
        election = gv.parse_election(demo_input())
        order, seed_hex = gv.tie_order(election)
        assert " > ".join(DEMO_OPTIONS[i] for i in order) in text
        assert seed_hex[:16] in text

    def test_ballot_order_does_not_change_a_single_byte_of_the_report(self):
        shuffled = list(reversed(DEMO_LINES))
        one = fc.render(gv.solve(demo_input("irv"), all_rules=True), "md", False, "zh")
        two = fc.render(
            gv.solve(make_input(DEMO_OPTIONS, shuffled, "irv"), all_rules=True), "md", False, "zh"
        )
        assert one == two
