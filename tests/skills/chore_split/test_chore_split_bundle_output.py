"""Plan B, the output: every format in both languages, what is private and what is public, the
stored copies of the examples, and independence from the order in which the input is listed."""

from __future__ import annotations

import copy
import json
import os
import re
from fractions import Fraction
from typing import ClassVar

import chore_split as cs
import fsq_core as fc
import pytest
from bundle_reference import bundle_cases
from chore_support import (
    BUNDLE_SOURCE,
    CHORES6,
    EXAMPLES,
    GOLDEN_DIR,
    HARD3,
    PEOPLE3,
    PROPERTY,
    SOURCE,
    bundle_data,
    load_example,
    price_data,
    run_json,
    run_script,
    table_costs,
)
from hypothesis import given
from hypothesis import strategies as st

BUNDLE_EXAMPLES = ["bundle_three_roommates.json", "bundle_uneven_caps.json"]
FORMATS = ["md", "dm", "group"]
PLACEHOLDER = re.compile(r"\{[a-z_0-9]+\}")
TOUCHING = re.compile(r"[A-Za-z0-9][㐀-鿿]|[㐀-鿿][A-Za-z0-9]")
KNOWN_PLACEHOLDERS = {
    "people", "chores", "amount", "holder", "holders", "reason", "k", "cap", "n", "person",
    "text", "net", "cost", "formula", "star", "total", "names", "worst", "paid", "received",
    "seed", "order", "head",
}  # fmt: skip


def plan_of(data):
    return cs.compute(cs.parse_problem(data))


def hard_data(**extra):
    return bundle_data(PEOPLE3, CHORES6, table_costs(HARD3), {p: 2 for p in PEOPLE3}, **extra)


def rounding_data():
    """Two people with equal costs, 12.35 and 12.34: a tie in which one cent of envy remains."""
    row = {"洗碗": 12.35, "倒垃圾": 12.34}
    return bundle_data(
        ["阿明", "小红"], ["洗碗", "倒垃圾"], {"阿明": row, "小红": row}, {"阿明": 1, "小红": 1}
    )


class TestEveryOutputRenders:
    @pytest.mark.parametrize("name", BUNDLE_EXAMPLES)
    @pytest.mark.parametrize("fmt", FORMATS)
    @pytest.mark.parametrize("lang", ["zh", "en"])
    def test_each_format_in_each_language_exits_0_and_is_filled_in(self, name, fmt, lang):
        done = run_script("--input", str(EXAMPLES / name), "--format", fmt, "--lang", lang)
        assert done.returncode == 0, done.stderr
        assert done.stdout.strip() and done.stderr == ""
        assert not PLACEHOLDER.search(done.stdout), PLACEHOLDER.search(done.stdout).group(0)
        assert "Traceback" not in done.stdout

    @pytest.mark.parametrize("name", BUNDLE_EXAMPLES)
    @pytest.mark.parametrize("lang", ["zh", "en"])
    def test_json_is_valid_and_has_the_envelope(self, name, lang):
        done = run_script("--input", str(EXAMPLES / name), "--json", "--lang", lang)
        assert done.returncode == 0, done.stderr
        parsed = json.loads(done.stdout)
        assert set(parsed) == {"inputs_echo", "result", "certificate", "not_modeled", "reproduce"}
        assert parsed["not_modeled"] and parsed["reproduce"].startswith("python3 scripts/")

    def test_json_wins_over_format(self):
        done = run_script("--demo-bundle", "--json", "--format", "dm")
        assert json.loads(done.stdout)["result"]["plan"] == "bundle_pay"

    @pytest.mark.parametrize("name", BUNDLE_EXAMPLES)
    def test_the_json_lists_everything_a_program_needs(self, name):
        data = load_example(name)
        parsed = json.loads(run_script("--input", str(EXAMPLES / name), "--json").stdout)
        result, echo, cert = parsed["result"], parsed["inputs_echo"], parsed["certificate"]
        people = set(data["people"])
        assert echo["plan"] == result["plan"] == "bundle_pay"
        assert set(echo["participants"]) == people and set(echo["costs"]) == people
        assert (
            echo["caps"] == data["caps"] and echo["random_source"] == data["rules"]["random_source"]
        )
        for key in ("bundles", "cost_cents", "transfer_cents", "net_cents", "exact_net"):
            assert set(result[key]) == people, key
        assert set(cert["share_table"]) == people and set(cert["one_liner"]) == people
        assert cert["recompute"]["seed_hex"] == result["tie_break"]["seed_hex"]
        amounts = [
            result[k][p] for k in ("cost_cents", "transfer_cents", "net_cents") for p in people
        ]
        assert all(re.fullmatch(r"-?\d+\.\d\d", a) for a in amounts)
        transfers = [Fraction(result["transfer_cents"][p]) for p in people]
        assert sum(transfers) == 0
        assert result["paid_in_cents"] == result["taken_out_cents"]
        assert result["max_envy_cents"] in ("0.00", "0.01")

    def test_the_json_of_the_uneven_example_shows_what_a_person_cannot_take(self):
        parsed = json.loads(
            run_script("--input", str(EXAMPLES / "bundle_uneven_caps.json"), "--json").stdout
        )
        table = parsed["certificate"]["share_table"]
        assert table["小红"]["Coco"] is None and table["小红"]["小红"] == "-40.00"
        assert parsed["certificate"]["cannot_take"]["小红"] == ["Coco", "大刘", "阿明"]
        assert parsed["inputs_echo"]["cannot"] == {"小红": ["做饭"]}

    def test_the_json_names_how_the_tie_was_settled(self):
        with_source = json.loads(run_script("--demo-bundle", "--json").stdout)["result"][
            "tie_break"
        ]
        assert with_source["was_tie"] and with_source["method"] == "random_source"
        assert with_source["rule"] == "chore_bundle_tiebreak_v1" and with_source["order"]
        names = json.loads(run_json(price_data(), "--json").stdout)["result"]["tie_break"]
        assert names["was_tie"] and names["method"] == "sorted_names"
        assert names["seed_hex"] is None and names["order"] == sorted(PEOPLE3)
        none = json.loads(run_json(hard_data(), "--json").stdout)["result"]["tie_break"]
        assert not none["was_tie"] and none["method"] == "not_needed"

    def test_building_a_result_in_an_unknown_language_is_refused(self):
        with pytest.raises(ValueError):
            cs.build_result(plan_of(price_data()), "fr")


class TestTexts:
    def test_both_languages_have_the_same_keys_and_the_same_placeholders(self):
        zh, en = cs.BUNDLE_TEXT["zh"], cs.BUNDLE_TEXT["en"]
        assert set(zh) == set(en)
        for key in zh:
            assert type(zh[key]) is type(en[key]), key
            if isinstance(zh[key], list):
                assert len(zh[key]) == len(en[key]), key
            else:
                assert set(re.findall(r"\{(\w+)\}", zh[key])) == set(
                    re.findall(r"\{(\w+)\}", en[key])
                ), key

    def test_every_placeholder_is_one_the_script_fills(self):
        for lang, table in cs.BUNDLE_TEXT.items():
            for key, template in table.items():
                if isinstance(template, str):
                    used = set(re.findall(r"\{(\w+)\}", template))
                    assert used <= KNOWN_PLACEHOLDERS, (lang, key, used - KNOWN_PLACEHOLDERS)

    def test_every_text_key_is_used_by_the_script(self):
        source = (EXAMPLES.parent / "scripts" / "chore_split.py").read_text(encoding="utf-8")
        body = source.split("def bsay(")[1]
        unused = [
            key
            for key in cs.BUNDLE_TEXT["zh"]
            if f'"{key}"' not in body and f"'{key}'" not in body and "unit_{" not in body
        ]
        assert unused == []

    def test_english_units_use_the_singular_for_one(self):
        assert cs.units_text("en", 1) == "1 unit" and cs.units_text("en", 0) == "0 units"
        assert cs.units_text("en", 3) == "3 units" and cs.units_text("zh", 1) == "1 件"
        data = bundle_data(
            ["A", "B"], ["x", "y"], {"A": {"x": 1, "y": 9}, "B": {"x": 9, "y": 1}}, {"A": 1, "B": 2}
        )
        text = run_json(data, "--format", "dm", "--lang", "en").stdout
        assert "Your cap is 1 unit." in text and "Your cap is 2 units." in text
        group = run_json(data, "--format", "group", "--lang", "en").stdout
        assert "(1 unit, cap 1 unit)" not in group  # the cap is a bare number on the card
        assert re.search(r"\(1 unit, cap 1\)", group)

    def test_a_name_with_latin_letters_gets_a_space_next_to_chinese_text(self):
        assert cs.bsay("zh", "share_of", holder="Coco") == "Coco 那份"
        assert cs.bsay("zh", "share_of", holder="大刘") == "大刘那份"
        assert cs.bsay("zh", "g_comp_pay", person="Coco", amount="5.00") == "Coco 付 5.00"
        assert cs.bsay("en", "share_of", holder="Coco") == "Coco's share"

    @pytest.mark.parametrize("name", BUNDLE_EXAMPLES)
    def test_in_chinese_no_latin_letter_or_digit_touches_a_chinese_character(self, name):
        for fmt in FORMATS:
            text = run_script("--input", str(EXAMPLES / name), "--format", fmt).stdout
            hit = TOUCHING.search(text)
            assert hit is None, (fmt, text[max(hit.start() - 15, 0) : hit.end() + 15])


class TestPrivacy:
    """Costs are private. The split and the payments are for the whole group."""

    @staticmethod
    def distinct():
        """Costs that no payment or total can equal by chance."""
        table = {
            "阿明": [31.07, 7.13, 22.51, 63.89, 41.43, 26.61],
            "小红": [21.37, 11.29, 26.71, 52.17, 71.93, 19.47],
            "大刘": [36.59, 16.83, 11.41, 41.77, 29.31, 46.13],
        }
        return price_data(table=table)

    @staticmethod
    def amounts(cents):
        return {fc.fmt_cents(c) for c in cents}

    def test_the_group_card_holds_no_cost_and_no_net(self):
        plan = plan_of(self.distinct())
        card = run_json(self.distinct(), "--format", "group").stdout
        private = set()
        for person in plan.people:
            private |= self.amounts(plan.problem.costs[person].values())
            private |= self.amounts(c for c in plan.cost_of[person].values() if c is not None)
            private |= self.amounts(v for v in plan.shares[person].values() if v is not None)
            private |= self.amounts([plan.cost[person], plan.net[person]])
        public = self.amounts(plan.transfer.values()) | self.amounts(
            -t for t in plan.transfer.values()
        )
        for number in private - public:
            assert number not in card, number
        assert "代价" in card  # the rule is stated, with no one's number

    def test_a_private_message_holds_only_the_costs_of_its_receiver(self):
        plan = plan_of(self.distinct())
        text = run_json(self.distinct(), "--format", "dm").stdout
        blocks = re.split(r"^--- .* ---$", text, flags=re.MULTILINE)[1:]
        by_person = dict(zip(re.findall(r"^--- 发给 (.*) ---$", text, flags=re.MULTILINE), blocks))
        assert set(by_person) == set(plan.people)
        for person, block in by_person.items():
            shown = self.amounts(plan.problem.costs[person].values())
            shown |= self.amounts(c for c in plan.cost_of[person].values() if c is not None)
            shown |= self.amounts(v for v in plan.shares[person].values() if v is not None)
            shown |= self.amounts(plan.transfer.values()) | self.amounts(
                -t for t in plan.transfer.values()
            )
            shown |= self.amounts([plan.cost[person], plan.net[person]])
            for other in plan.people:
                if other == person:
                    continue
                theirs = self.amounts(plan.problem.costs[other].values())
                theirs |= self.amounts([plan.cost[other], plan.net[other]])
                for number in theirs - shown:
                    assert number not in block, (person, other, number)

    def test_a_private_message_names_the_receiver_and_nobody_elses_net(self):
        text = run_script("--demo-bundle", "--format", "dm").stdout
        for person in PEOPLE3:
            assert f"--- 发给 {person} ---" in text
            assert f"{person}，这是只给你的分家务结果" in text

    def test_the_group_card_does_hold_the_split_and_the_payments(self):
        card = run_script("--demo-bundle", "--format", "group").stdout
        assert "阿明：倒垃圾、拖地（2 件，上限 2）" in card
        assert "大刘收 25.00" in card and "小红付 5.00" in card and "阿明付 20.00" in card
        assert "付出合计 25.00，收入合计 25.00" in card

    def test_the_json_echo_holds_the_costs_for_programs(self):
        parsed = json.loads(run_script("--demo-bundle", "--json").stdout)
        assert parsed["inputs_echo"]["costs"]["阿明"]["倒垃圾"] == "5.00"


class TestWhatTheOutputSays:
    def test_the_recorded_example_in_the_organizer_table(self):
        text = run_json(price_data(), "--format", "md").stdout
        assert "| 大刘 | 做饭、刷厕所 | 2 / 2 | 70.00 | 收 25.00 | -45.00 |" in text
        assert "| 小红 | 擦窗、洗碗 | 2 / 2 | 40.00 | 付 5.00 | -45.00 |" in text
        assert "| 阿明 | 倒垃圾、拖地 | 2 / 2 | 25.00 | 付 20.00 | -45.00 |" in text
        assert "| 合计 |  | 6 | 135.00 | 0.00 | -135.00 |" in text
        assert "| 阿明 | -75.00 | -60.00 | -45.00* |" in text
        assert "折算后每个人每周都是 -45.00" in text

    def test_a_person_in_a_tie_between_two_shares_is_told_so(self):
        dm = run_json(price_data(), "--format", "dm").stdout
        block = dm.split("--- 发给 大刘 ---")[1].split("--- 发给")[0]
        assert "阿明那份对你来说一样划算（也是 -45.00），打平不算吃亏" in block
        assert "  阿明那份（倒垃圾、拖地）：-25.00 - 20.00 = -45.00" in block
        assert "  大刘那份（做饭、刷厕所）：-70.00 + 25.00 = -45.00*" in block

    def test_the_table_row_always_shows_both_terms(self):
        text = run_json(rounding_data(), "--format", "dm").stdout
        assert "-12.34 + 0.00 = -12.34*" in text

    def test_the_three_states_of_the_tie_note(self):
        both = run_json(price_data(), "--format", "md").stdout
        assert "按姓名排序打破平局" in both and "种子（SHA-256）" not in both
        seeded = run_json(price_data(source=BUNDLE_SOURCE), "--format", "md").stdout
        assert "已按规则里的公开随机源排出的顺序打破平局" in seeded
        assert (
            "种子（SHA-256）：922852d168b3779a289d51e88d895c7256c936dbe165ce8b600eb1dbb6dbb63f"
            in seeded
        )
        none = run_json(hard_data(), "--format", "md").stdout
        assert "只有一种，用不上平局规则" in none
        unused = run_json(hard_data(source=BUNDLE_SOURCE), "--format", "md").stdout
        assert "规则里给了公开随机源，但这次总代价最小的分法只有一种，用不上" in unused

    def test_the_note_names_the_worst_off_people_when_they_differ(self):
        text = run_json(hard_data(), "--format", "md").stdout
        assert "每周总代价（各人按自己填的代价算）：38.00。" in text
        assert "折算后每周最差的是 阿明：-18.34。" in text
        english = run_json(hard_data(), "--format", "md", "--lang", "en").stdout
        assert "The worst off after the compensation is 阿明, with -18.34 a week." in english

    def test_one_cent_of_rounded_envy_is_reported_as_rounding(self):
        plan = plan_of(rounding_data())
        assert plan.max_envy == 1
        dm = run_json(rounding_data(), "--format", "dm").stdout
        assert "取整到分后，小红那份比你的多 0.01，这是取整造成的误差" in dm
        md = run_json(rounding_data(), "--format", "md").stdout
        assert "取整到分后，最大羡慕是 0.01" in md
        card = run_json(rounding_data(), "--format", "group").stdout
        assert "取整到分后最多差 0.01" in card

    def test_a_person_who_cannot_take_a_share_is_told_why(self):
        dm = run_script(
            "--input", str(EXAMPLES / "bundle_uneven_caps.json"), "--format", "dm"
        ).stdout
        block = dm.split("--- 发给 小红 ---")[1].split("--- 发给")[0]
        assert (
            "  大刘那份（做饭 ×2、洗碗 ×2）：你接不了（含你做不了的「做饭」，有 4 件，超过你的上限 1 件）"
            in block
        )
        assert "  Coco 那份（刷厕所、擦窗）：你接不了（有 2 件，超过你的上限 1 件）" in block
        assert "Coco、大刘、阿明那份你接不了，不参与比较" in block
        assert "你说做不了：「做饭」" in block

    def test_the_organizer_table_marks_the_shares_nobody_could_take(self):
        md = run_script("--input", str(EXAMPLES / "bundle_uneven_caps.json")).stdout
        assert "| 小红 | 接不了 | 接不了 | -40.00* | 接不了 |" in md

    def test_every_person_has_a_one_line_certificate_in_the_notes(self):
        md = run_script("--demo-bundle").stdout
        for person in PEOPLE3:
            assert f"- {person}：按你自己填的代价，你这份每周的折算是 -45.00" in md

    def test_the_english_texts_say_the_same(self):
        md = run_json(price_data(), "--format", "md", "--lang", "en").stdout
        assert "| 大刘 | 做饭, 刷厕所 | 2 / 2 | 70.00 | receives 25.00 | -45.00 |" in md
        assert "After the compensation everybody comes to -45.00 a week." in md
        assert "settled by the order of the names" in md

    def test_the_pot_is_explained_in_every_format(self):
        for fmt in ("md", "group"):
            assert (
                "付出的人把钱放进公用的钱罐，收的人从里面拿"
                in run_json(price_data(), "--format", fmt).stdout
            )
        dm = run_json(price_data(), "--format", "dm").stdout
        assert dm.count("大家的补偿加起来是 0.00，不需要外人出钱。") == 3

    def test_big_amounts_get_thousands_separators(self):
        data = bundle_data(
            ["A", "B"],
            ["x", "y"],
            {"A": {"x": 1234.5, "y": 20000}, "B": {"x": 3000, "y": 40000}},
            {"A": 1, "B": 1},
        )
        text = run_json(data, "--format", "md").stdout
        assert "20,000.00" in text and "3,000.00" in text
        assert "| 合计 |  | 2 | 23,000.00 | 0.00 | -23,000.00 |" in text

    def test_a_pipe_in_the_source_is_escaped_in_the_tables_and_explained(self):
        md = run_json(price_data(source="03 11 | 19 24"), "--format", "md").stdout
        assert "03 11 \\| 19 24" in md and "表格里的竖线 | 前面被加了一个反斜杠" in md
        card = run_json(price_data(source="03 11 | 19 24"), "--format", "group").stdout
        assert "随机源原文：03 11 | 19 24" in card and "\\|" not in card

    def test_no_source_means_no_source_table_and_no_recompute_line(self):
        md = run_json(price_data(), "--format", "md").stdout
        card = run_json(price_data(), "--format", "group").stdout
        assert "随机源原文" not in md and "随机源原文" not in card and "复算" not in card
        assert "recompute" not in json.loads(run_json(price_data(), "--json").stdout)["certificate"]

    def test_the_source_and_the_seed_are_on_the_card_when_there_is_one(self):
        card = run_json(
            price_data(source=SOURCE, description="虚构示例"), "--format", "group"
        ).stdout
        assert f"随机源原文：{SOURCE}" in card and "随机源说明：虚构示例" in card
        plan = plan_of(price_data(source=SOURCE))
        assert f"种子（SHA-256）：{plan.seed_hex}" in card
        assert "平局顺序：小红、阿明、大刘。" in card


class TestSameInputSameBytes:
    @pytest.mark.parametrize("name", BUNDLE_EXAMPLES)
    @pytest.mark.parametrize("fmt", FORMATS)
    @pytest.mark.parametrize("lang", ["zh", "en"])
    def test_two_runs_are_identical(self, name, fmt, lang):
        args = ("--input", str(EXAMPLES / name), "--format", fmt, "--lang", lang)
        assert run_script(*args).stdout == run_script(*args).stdout

    def test_the_demo_prints_the_same_as_its_example(self):
        for fmt in FORMATS:
            demo = run_script("--demo-bundle", "--format", fmt).stdout
            example = run_script(
                "--input", str(EXAMPLES / "bundle_three_roommates.json"), "--format", fmt
            ).stdout
            assert demo.replace("--demo-bundle", "--input -") == example

    @staticmethod
    def reversed_listing(data):
        out = copy.deepcopy(data)
        out["people"] = list(reversed(out["people"]))
        out["chores"] = list(reversed(out["chores"]))
        out["costs"] = {
            p: dict(reversed(list(row.items()))) for p, row in reversed(list(out["costs"].items()))
        }
        out["caps"] = dict(reversed(list(out["caps"].items())))
        if "cannot" in out:
            out["cannot"] = dict(reversed(list(out["cannot"].items())))
        return out

    @pytest.mark.parametrize("name", BUNDLE_EXAMPLES)
    def test_listing_the_input_in_another_order_changes_no_output(self, name):
        data = load_example(name)
        other = self.reversed_listing(data)
        assert other != data
        for lang in fc.LANGS:
            first, second = cs.solve(data, lang), cs.solve(other, lang)
            assert fc.envelope(first) == fc.envelope(second)
            for fmt in FORMATS:
                assert fc.render(first, fmt, False, lang) == fc.render(second, fmt, False, lang)

    @PROPERTY
    @given(bundle_cases(), st.randoms(use_true_random=False))
    def test_listing_a_random_input_in_another_order_changes_no_output(self, data, shuffler):
        try:
            first = cs.solve(data)
        except fc.NoSolution:
            return
        other = copy.deepcopy(data)
        for key in ("people", "chores"):
            shuffler.shuffle(other[key])
        other["costs"] = {
            p: dict(sorted(row.items(), key=lambda _: shuffler.random()))
            for p, row in other["costs"].items()
        }
        second = cs.solve(other)
        assert fc.envelope(first) == fc.envelope(second)
        for fmt in FORMATS:
            assert fc.render(first, fmt) == fc.render(second, fmt)


class TestStoredCopies:
    """The demo and the examples have stored md, dm, group and json copies."""

    DEMO: ClassVar[dict] = {
        "bundle_demo_md_zh.txt": ["--demo-bundle"],
        "bundle_demo_dm_zh.txt": ["--demo-bundle", "--format", "dm"],
        "bundle_demo_group_zh.txt": ["--demo-bundle", "--format", "group"],
        "bundle_demo_json.txt": ["--demo-bundle", "--json"],
        "bundle_demo_md_en.txt": ["--demo-bundle", "--lang", "en"],
        "bundle_demo_dm_en.txt": ["--demo-bundle", "--format", "dm", "--lang", "en"],
        "bundle_demo_group_en.txt": ["--demo-bundle", "--format", "group", "--lang", "en"],
    }
    UNEVEN: ClassVar[dict] = {
        "bundle_uneven_md_zh.txt": [],
        "bundle_uneven_dm_zh.txt": ["--format", "dm"],
        "bundle_uneven_group_zh.txt": ["--format", "group"],
        "bundle_uneven_json.txt": ["--json"],
        "bundle_uneven_md_en.txt": ["--lang", "en"],
        "bundle_uneven_dm_en.txt": ["--format", "dm", "--lang", "en"],
        "bundle_uneven_group_en.txt": ["--format", "group", "--lang", "en"],
    }
    INLINE: ClassVar[dict] = {
        "bundle_hard_md_zh.txt": (hard_data, []),
        "bundle_hard_dm_zh.txt": (hard_data, ["--format", "dm"]),
        "bundle_hard_md_en.txt": (hard_data, ["--lang", "en"]),
        "bundle_rounding_dm_zh.txt": (rounding_data, ["--format", "dm"]),
        "bundle_rounding_md_en.txt": (rounding_data, ["--lang", "en"]),
    }

    @staticmethod
    def check(name, done):
        assert done.returncode == 0, done.stderr
        stored = GOLDEN_DIR / name
        if os.environ.get("FSQ_UPDATE_GOLDEN") == "1":
            GOLDEN_DIR.mkdir(exist_ok=True)
            stored.write_text(done.stdout, encoding="utf-8", newline="\n")
        assert done.stdout == stored.read_text(encoding="utf-8"), (
            f"{name} differs from the stored copy. If the change is intended, rerun with "
            "FSQ_UPDATE_GOLDEN=1 and review the diff."
        )

    @pytest.mark.parametrize("name", sorted(DEMO))
    def test_the_demo_matches_the_stored_copy(self, name):
        self.check(name, run_script(*self.DEMO[name]))

    @pytest.mark.parametrize("name", sorted(UNEVEN))
    def test_the_uneven_example_matches_the_stored_copy(self, name):
        done = run_script("--input", str(EXAMPLES / "bundle_uneven_caps.json"), *self.UNEVEN[name])
        self.check(name, done)

    @pytest.mark.parametrize("name", sorted(INLINE))
    def test_the_inline_cases_match_the_stored_copies(self, name):
        build, flags = self.INLINE[name]
        self.check(name, run_json(build(), *flags))
