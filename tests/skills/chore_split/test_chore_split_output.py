"""Every output format renders, says the right things, and keeps private numbers private."""

from __future__ import annotations

import json
import re

import chore_split as cs
import fsq_core as fc
import pytest
from chore_support import (
    EXAMPLES,
    PEOPLE3,
    PROPERTY,
    RANKINGS3,
    chore_cases,
    chore_data,
    load_example,
    recorded_data,
    run_json,
    run_script,
)
from hypothesis import assume, given

EXAMPLE_NAMES = ["three_roommates.json", "weekly_rota.json", "cannot_cook.json"]
FORMATS = ["md", "dm", "group"]
PLACEHOLDER = re.compile(r"\{[a-z_0-9]+\}")


def no_separator_in_names(data):
    """The ranking separator must not occur inside a name, or the checks below would be fooled."""
    sep = cs.TEXT["zh"]["rank_sep"]
    names = list(data["people"]) + [c["name"] if isinstance(c, dict) else c for c in data["chores"]]
    return not any(sep in name for name in names)


def ranking_text(lang, ranking):
    return cs.TEXT[lang]["rank_sep"].join(ranking)


class TestEveryOutputRenders:
    @pytest.mark.parametrize("name", EXAMPLE_NAMES)
    @pytest.mark.parametrize("fmt", FORMATS)
    @pytest.mark.parametrize("lang", ["zh", "en"])
    def test_each_format_in_each_language_exits_0_and_is_filled_in(self, name, fmt, lang):
        done = run_script("--input", str(EXAMPLES / name), "--format", fmt, "--lang", lang)
        assert done.returncode == 0, done.stderr
        assert done.stdout.strip()
        assert done.stderr == ""
        assert not PLACEHOLDER.search(done.stdout), PLACEHOLDER.search(done.stdout).group(0)
        assert "Traceback" not in done.stdout

    @pytest.mark.parametrize("name", EXAMPLE_NAMES)
    @pytest.mark.parametrize("lang", ["zh", "en"])
    def test_json_is_valid_and_has_the_envelope(self, name, lang):
        done = run_script("--input", str(EXAMPLES / name), "--json", "--lang", lang)
        assert done.returncode == 0, done.stderr
        parsed = json.loads(done.stdout)
        assert set(parsed) == {"inputs_echo", "result", "certificate", "not_modeled", "reproduce"}
        assert parsed["not_modeled"] and parsed["reproduce"].startswith("python3 scripts/")

    def test_json_wins_over_format(self):
        done = run_script("--demo", "--json", "--format", "dm")
        assert json.loads(done.stdout)["result"]["rule"] == "chore_pick_order_v1"

    @pytest.mark.parametrize("name", EXAMPLE_NAMES)
    def test_the_json_result_lists_everything_a_program_needs(self, name):
        data = load_example(name)
        parsed = json.loads(run_script("--input", str(EXAMPLES / name), "--json").stdout)
        result = parsed["result"]
        assert len(result["weeks"]) == data["weeks"]
        assert result["schedule"].keys() == set(data["people"])
        assert all(len(rows) == data["weeks"] for rows in result["schedule"].values())
        for week in result["weeks"]:
            assert [p["seq"] for p in week["picks"]] == list(range(1, len(week["picks"]) + 1))
            assert set(week["bundles"]) == set(data["people"])
        n = len(data["people"])
        assert len(parsed["certificate"]["pairs"]) == data["weeks"] * n * (n - 1)
        assert parsed["certificate"]["recompute"]["seed_hex"] == result["seed_hex"]
        assert result["comparisons_failed"] == 0
        assert set(parsed["certificate"]["one_liner"]) == set(data["people"])

    def test_the_json_status_of_the_cannot_example_lists_the_failures(self):
        parsed = json.loads(
            run_script("--input", str(EXAMPLES / "cannot_cook.json"), "--json").stdout
        )
        assert parsed["result"]["ef1_holds"] is False
        assert len(parsed["result"]["ef1_failures"]) == 6
        first = parsed["result"]["ef1_failures"][0]
        assert first["other"] == "小红" and first["witness"]["threshold"] == 1
        statuses = {p["status"] for p in parsed["certificate"]["pairs"]}
        assert statuses == {"envy_free", "ef1", "fails", "exempt"}

    def test_the_demo_prints_the_same_as_its_example(self):
        for fmt in FORMATS:
            demo = run_script("--demo", "--format", fmt).stdout
            example = run_script(
                "--input", str(EXAMPLES / "three_roommates.json"), "--format", fmt
            ).stdout
            assert demo.replace("--demo", "--input -") == example.replace("--demo", "--input -")

    def test_building_a_result_in_an_unknown_language_is_refused(self):
        plan = cs.compute(cs.parse_problem(recorded_data()))
        with pytest.raises(ValueError):
            cs.build_result(plan, "fr")

    def test_the_reproduce_line_follows_the_options(self):
        parsed = json.loads(run_script("--demo", "--json", "--lang", "en").stdout)
        assert parsed["reproduce"] == "python3 scripts/chore_split.py --demo --json --lang en"
        done = run_json(recorded_data(), "--format", "dm", "--lang", "en")
        assert done.returncode == 0
        result = cs.solve(recorded_data(), "en", cs.reproduce_command(_args("dm", "en")))
        assert result.reproduce == "python3 scripts/chore_split.py --input - --format dm --lang en"


def _args(fmt, lang):
    parser = cs.build_parser()
    return parser.parse_args(["--format", fmt, "--lang", lang])


class TestTexts:
    def test_both_languages_have_the_same_keys(self):
        zh, en = cs.TEXT["zh"], cs.TEXT["en"]
        assert set(zh) == set(en)
        for key in zh:
            assert type(zh[key]) is type(en[key]), key
            if isinstance(zh[key], list):
                assert len(zh[key]) == len(en[key]), key

    def test_every_template_can_be_filled_with_the_names_the_script_knows(self):
        known = {
            "people", "chores", "weeks", "n", "k", "r", "r2", "c", "c2", "k2", "week", "pos",
            "order", "picks", "person", "other", "names", "rounds", "ranking", "reason", "a", "b",
            "x", "who", "whose", "theirs", "witness", "first", "last", "text", "seed", "ran",
            "chore", "rule",
        }  # fmt: skip
        for lang, table in cs.TEXT.items():
            for key, template in table.items():
                if isinstance(template, str):
                    used = set(re.findall(r"\{(\w+)\}", template))
                    assert used <= known, (lang, key, used - known)

    def test_english_quantities_use_the_singular_for_one(self):
        one = chore_data(["A", "B"], ["x"], {"A": ["x"], "B": ["x"]}, weeks=1)
        assert cs.solve(one, "en").title == "Chore split: 2 people, 1 chore, taking turns, 1 week"
        many = chore_data(["A", "B"], ["x", "y"], {"A": ["x", "y"], "B": ["y", "x"]}, weeks=3)
        assert cs.solve(many, "en").title.endswith("2 chores, taking turns, 3 weeks")
        assert cs.solve(many).title == "分家务结果：2 人分 2 件家务，轮流挑，共 3 周"

    def test_a_name_with_latin_letters_gets_a_space_next_to_chinese_text(self):
        assert cs.say("zh", "pc_free", other="Coco") == "你不羡慕 Coco"
        assert cs.say("zh", "pc_free", other="大刘") == "你不羡慕大刘"
        assert cs.say("zh", "pc_free", other="小A") == "你不羡慕小A"
        assert cs.say("en", "pc_free", other="Coco") == "so you do not envy Coco"

    def test_spacing_never_changes_the_value_itself(self):
        out = cs.say("zh", "pc_head_first", week=2, other="B2")
        assert "对 B2（" in out and "B2" in out

    def test_no_space_is_added_after_chinese_punctuation(self):
        out = cs.say("zh", "w_ran_out", other="Coco", r=2)
        assert out == "（Coco 从第 2 轮起没有自己能做的家务可挑）"


class TestSourceText:
    def test_a_pipe_in_the_source_is_escaped_in_the_tables_and_explained(self):
        data = recorded_data()
        data["rules"]["random_source"] = "03 11 | 19 24"
        zh = cs.solve(data)
        md = fc.render(zh, "md")
        assert "03 11 \\| 19 24" in md
        assert "表格里的竖线 | 前面被加了一个反斜杠" in md
        group = fc.render(zh, "group")
        assert "随机源原文：03 11 | 19 24" in group and "\\|" not in group
        en = fc.render(cs.solve(data, "en"), "md", lang="en")
        assert "A backslash was added before each |" in en

    def test_the_source_is_copied_into_the_group_card_exactly(self):
        source = "（虚构示例）  03  11\u00a019 "
        data = recorded_data()
        data["rules"]["random_source"] = source
        card = fc.render(cs.solve(data), "group")
        assert f"随机源原文：{source}" in card

    def test_the_description_of_the_source_is_optional(self):
        data = recorded_data()
        assert "source_description" not in data["rules"]
        card = fc.render(cs.solve(data), "group")
        assert "随机源说明" not in card
        data["rules"]["source_description"] = "虚构示例：某公开开奖"
        assert "随机源说明：虚构示例：某公开开奖" in fc.render(cs.solve(data), "group")


class TestPrivacy:
    @pytest.mark.parametrize("name", EXAMPLE_NAMES)
    @pytest.mark.parametrize("lang", ["zh", "en"])
    def test_the_group_card_holds_no_ranking_and_no_place_in_one(self, name, lang):
        data = load_example(name)
        card = run_script(
            "--input", str(EXAMPLES / name), "--format", "group", "--lang", lang
        ).stdout
        for ranking in data["rankings"].values():
            assert ranking_text(lang, ranking) not in card
            for first, second in zip(ranking, ranking[1:]):
                assert f"{first}{cs.TEXT[lang]['rank_sep']}{second}" not in card
        assert not re.search(r"第 \d+ 位|no\. \d+", card)

    @pytest.mark.parametrize("name", EXAMPLE_NAMES)
    @pytest.mark.parametrize("lang", ["zh", "en"])
    def test_a_private_message_holds_only_the_receivers_ranking(self, name, lang):
        data = load_example(name)
        text = run_script("--input", str(EXAMPLES / name), "--format", "dm", "--lang", lang).stdout
        blocks = re.split(r"^--- .* ---$", text, flags=re.MULTILINE)[1:]
        assert len(blocks) == len(data["people"])
        by_person = dict(zip(sorted_in_dm_order(text), blocks))
        for person, block in by_person.items():
            assert ranking_text(lang, data["rankings"][person]) in block
            for ranking in data["rankings"].values():
                if ranking != data["rankings"][person]:
                    assert ranking_text(lang, ranking) not in block

    def test_a_private_message_shows_places_only_in_the_receivers_own_ranking(self):
        plan = cs.compute(cs.parse_problem(recorded_data()))
        lines = cs.person_lines(plan, "zh")
        for person in PEOPLE3:
            own = {c: i for i, c in enumerate(RANKINGS3[person], 1)}
            text = "\n".join(lines[person])
            for chore, place in re.findall(r"「(.+?)」（(?:你的)?第 (\d+) 位）", text):
                assert own[chore] == int(place)

    def test_every_person_gets_a_message_and_it_names_them(self):
        text = run_script("--demo", "--format", "dm").stdout
        for person in PEOPLE3:
            assert f"--- 发给 {person} ---" in text
            assert f"{person}，这是只给你的分家务结果" in text

    def test_the_organizer_table_is_for_the_organizer_only(self):
        text = run_script("--demo").stdout
        assert "(1)" in text and "第 1 轮 倒垃圾(1) ≤ 对方同一轮 洗碗(5)" in text

    def test_json_echo_holds_the_rankings_for_programs(self):
        parsed = json.loads(run_script("--demo", "--json").stdout)
        assert parsed["inputs_echo"]["rankings"] == RANKINGS3


def sorted_in_dm_order(text):
    return re.findall(r"^--- (?:发给|To) (.*) ---$", text, flags=re.MULTILINE)


class TestWhatTheOutputSays:
    def test_every_person_has_a_one_line_certificate_with_the_rounds_listed(self):
        parsed = json.loads(run_script("--demo", "--json").stdout)
        lines = parsed["certificate"]["one_liner"]
        assert set(lines) == set(PEOPLE3)
        assert "第 1 轮 倒垃圾，第 2 轮 做饭" in lines["阿明"]
        assert "第 1 轮 洗碗，第 2 轮 擦窗" in lines["小红"]
        assert "第 1 轮 拖地，第 2 轮 刷厕所" in lines["大刘"]
        for line in lines.values():
            assert "在你的排序里都不比别人紧接着挑的那件更讨厌" in line
            assert "最多只有一件家务例外" in line

    def test_several_weeks_list_the_rounds_of_every_week(self):
        parsed = json.loads(
            run_script("--input", str(EXAMPLES / "weekly_rota.json"), "--json").stdout
        )
        line = parsed["certificate"]["one_liner"]["阿明"]
        for week in (1, 2, 3, 4):
            assert f"第 {week} 周：" in line

    def test_the_md_says_the_guarantee_holds_or_where_it_fails(self):
        ok = run_script("--demo").stdout
        assert "EF1 状态（去掉一件家务后，没有人羡慕别人）：成立" in ok
        assert "逐轮比较共 9 项，全部成立" in ok
        bad = run_script("--input", str(EXAMPLES / "cannot_cook.json")).stdout
        assert "EF1 状态（去掉一件家务后，没有人羡慕别人）：不成立" in bad
        assert "第 1 周，大刘 对 小红：把所有家务都算作一样重" in bad
        assert "小红从第 2 轮起没有自己能做的家务可挑" in bad

    def test_a_person_who_cannot_envy_is_told_why(self):
        text = run_script("--input", str(EXAMPLES / "cannot_cook.json"), "--format", "dm").stdout
        block = text.split("--- 发给 小红 ---")[1].split("--- 发给")[0]
        assert "大刘手里有你做不了的「做饭」，你不会羡慕大刘" in block
        assert "你说做不了：做饭" in block

    def test_the_dm_of_a_person_with_a_failing_pair_names_the_other_person(self):
        text = run_script("--input", str(EXAMPLES / "cannot_cook.json"), "--format", "dm").stdout
        block = text.split("--- 发给 阿明 ---")[1].split("--- 发给")[0]
        assert "对小红，EF1 不成立，原因在下面" in block
        assert (
            "EF1 不成立：把所有家务都算作一样重，去掉你手里最重的一件后，你手里还有 2 件" in block
        )

    def test_the_group_card_names_the_counts_but_not_the_reason_in_rankings(self):
        card = run_script("--input", str(EXAMPLES / "cannot_cook.json"), "--format", "group").stdout
        assert "第 1 周，大刘 对 小红：大刘手里 3 件，小红手里 1 件" in card
        assert "保证（EF1）：下面列出的人对人除外，其余都成立" in card

    def test_the_heavy_threshold_names_a_chore_in_the_persons_own_ranking(self):
        # P1 holds c1 and c0, P0 holds c2 and cannot do c0. In P1's ranking c2, c1, c0 the
        # chore c1 and everything after it count as heavy: after setting aside the heaviest
        # chore (c0), P1 still holds one heavy chore (c1) and P0 none.
        data = {
            "people": ["P0", "P1"],
            "chores": ["c0", "c1", "c2"],
            "rankings": {"P0": ["c2", "c1"], "P1": ["c2", "c1", "c0"]},
            "cannot": {"P0": ["c0"]},
            "rules": {"random_source": "s", "rotate": "none"},
        }
        plan = cs.compute(cs.parse_problem(data))
        week = plan.weeks[0]
        assert week.bundles == {"P0": ["c2"], "P1": ["c1", "c0"]}
        (check,) = plan.failures
        assert (check.person, check.other) == ("P1", "P0")
        assert check.witness == {"threshold": 2, "chore": "c1", "own_heavy": 1, "other_heavy": 0}
        zh = cs.witness_text(check, "zh", True)
        assert zh.startswith(
            "把你排序里的「c1」和排在它后面的家务都算作重活，去掉你手里最重的一件后"
        )
        assert "你手里还有 1 件重活，P0 手里只有 0 件重活" in zh
        en = cs.witness_text(check, "en", False)
        assert 'treating "c1" and every chore ranked after it in P1\'s ranking as heavy' in en
        assert "P1's bundle still has 1 heavy chore and P0's has 0 heavy chores" in en

    def test_counting_every_chore_the_same_is_said_in_plain_words(self):
        plan = cs.compute(cs.parse_problem(load_example("cannot_cook.json")))
        zh = cs.witness_text(plan.failures[0], "zh", False)
        assert zh.startswith("把所有家务都算作一样重")
        assert "手里还有 2 件" in zh and "手里只有 1 件" in zh
        en = cs.witness_text(plan.failures[0], "en", True)
        assert en.startswith("counting every chore the same")
        assert "your bundle still has 2 chores and" in en and "has 1 chore" in en

    def test_the_not_modeled_list_states_the_limits(self):
        text = run_script("--demo").stdout.split("## 本结果不包含")[1]
        for needed in ("防策略", "几周之间", "喜欢做的任务", "花钱请人", "排序是否被如实录入"):
            assert needed in text, needed
        assert "做不了的家务" not in text  # only when somebody has a cannot list
        bad = run_script("--input", str(EXAMPLES / "cannot_cook.json")).stdout
        assert "做不了的家务：有 cannot 时 EF1 不一定成立" in bad

    def test_english_output_has_no_chinese_template_text(self):
        text = run_script("--demo", "--lang", "en").stdout
        template_text = re.sub(r"[一-鿿＀-￯]+", "", text)
        assert "EF1 status" in template_text and "Not modeled" in template_text
        assert "分家务" not in template_text


class TestOutputOnArbitraryInputs:
    @PROPERTY
    @given(chore_cases(with_cannot=True, max_units=3))
    def test_every_format_renders_for_any_valid_input_in_both_languages(self, data):
        for lang in fc.LANGS:
            result = cs.solve(data, lang)
            for fmt in FORMATS:
                text = fc.render(result, fmt, lang=lang)
                assert text.strip()
            assert fc.render(result, "md", True, lang)
            assert set(result.person_lines) == set(data["people"])

    @PROPERTY
    @given(chore_cases(with_cannot=True, max_units=3))
    def test_the_group_card_never_holds_a_ranking(self, data):
        assume(no_separator_in_names(data))
        card = fc.render(cs.solve(data), "group")
        assert cs.TEXT["zh"]["rank_sep"] not in card

    @PROPERTY
    @given(chore_cases(with_cannot=True, max_units=3))
    def test_a_private_message_holds_exactly_one_ranking_and_it_is_the_receivers(self, data):
        assume(no_separator_in_names(data))
        sep = cs.TEXT["zh"]["rank_sep"]
        for person, lines in cs.solve(data).person_lines.items():
            with_ranking = [line for line in lines if sep in line]
            assert len(with_ranking) == (1 if len(data["rankings"][person]) >= 2 else 0)
            for line in with_ranking:
                assert ranking_text("zh", data["rankings"][person]) in line
