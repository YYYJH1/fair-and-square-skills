"""Output formats, languages, the demo, the examples and the text tables of bill-split."""

from __future__ import annotations

import json
import re
import string

import bill_split as bs
import fsq_core as fc
import pytest
from bs_testlib import EXAMPLES, SCRIPT, SKILL_DIR, run_script

EXAMPLE_NAMES = sorted(path.stem for path in EXAMPLES.glob("*.json"))
CJK = re.compile("[" + chr(0x4E00) + "-" + chr(0x9FFF) + "]")
CJK_PUNCT = re.compile(
    "[" + chr(0x3000) + "-" + chr(0x303F) + chr(0xFF00) + "-" + chr(0xFFEF) + "]"
)
EXPECTED_EXAMPLES = [
    "audit_aa",
    "dinner_680",
    "fewest_transfers",
    "group_order_coupon",
    "group_order_takeout",
    "trip_five_bills",
]


def load(name: str):
    return fc.parse_input((EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))


def people_of(result: fc.Result) -> list[str]:
    return list(result.person_lines)


class TestExamples:
    def test_the_expected_example_files_exist(self):
        assert EXAMPLE_NAMES == EXPECTED_EXAMPLES

    @pytest.mark.parametrize("name", EXAMPLE_NAMES)
    def test_every_example_runs_with_and_without_audit(self, name):
        for audit in (False, True):
            result = bs.compute(load(name), audit=audit)
            assert result.result["total_cents"]

    @pytest.mark.parametrize(
        ("name", "demo"),
        [
            ("audit_aa", bs.DEMO_AUDIT_AA),
            ("trip_five_bills", bs.DEMO_TRIP),
            ("group_order_coupon", bs.DEMO_COUPON),
        ],
    )
    def test_the_demo_inputs_are_the_example_files(self, name, demo):
        assert fc.parse_input(demo) == load(name)

    def test_the_audit_example_is_the_dinner_plus_the_audit_block(self):
        dinner = load("dinner_680")
        audited = load("audit_aa")
        assert audited.pop("audit") == {"current": "aa"}
        assert audited == dinner

    def test_examples_use_only_documented_fields_and_invented_names(self):
        text = "".join(
            (EXAMPLES / f"{name}.json").read_text(encoding="utf-8") for name in EXAMPLE_NAMES
        )
        assert "/data" not in text and "@" not in text and "http" not in text


class TestFormats:
    @pytest.mark.parametrize("lang", ["zh", "en"])
    @pytest.mark.parametrize("fmt", ["md", "dm", "group"])
    @pytest.mark.parametrize("name", EXAMPLE_NAMES)
    def test_every_format_renders(self, name, fmt, lang):
        result = bs.compute(load(name), audit=True, lang=lang)
        text = fc.render(result, fmt, False, lang)
        assert text.strip() and text.endswith("\n")

    @pytest.mark.parametrize("lang", ["zh", "en"])
    @pytest.mark.parametrize("name", EXAMPLE_NAMES)
    def test_json_is_valid_and_has_the_five_keys(self, name, lang):
        result = bs.compute(load(name), audit=True, lang=lang)
        envelope = json.loads(fc.render(result, "md", True, lang))
        assert sorted(envelope) == [
            "certificate",
            "inputs_echo",
            "not_modeled",
            "reproduce",
            "result",
        ]

    @pytest.mark.parametrize("name", EXAMPLE_NAMES)
    def test_json_has_no_prose_and_no_floats(self, name):
        zh = json.loads(fc.render(bs.compute(load(name), audit=True, lang="zh"), "md", True))
        en = json.loads(fc.render(bs.compute(load(name), audit=True, lang="en"), "md", True, "en"))
        for key in ("inputs_echo", "result", "certificate"):
            assert zh[key] == en[key], key

        def walk(value, path="$"):
            assert not isinstance(value, float), path
            if isinstance(value, dict):
                for key, inner in value.items():
                    if key.endswith("_cents") or key in (
                        "amount",
                        "coupon_share",
                        "current_discount",
                    ):
                        assert isinstance(inner, (str, dict, list)), path + "." + key
                    walk(inner, f"{path}.{key}")
            elif isinstance(value, list):
                for index, inner in enumerate(value):
                    walk(inner, f"{path}[{index}]")

        walk(zh)

    @pytest.mark.parametrize("name", EXAMPLE_NAMES)
    def test_money_in_json_is_text_with_two_decimals(self, name):
        text = fc.render(bs.compute(load(name), audit=True), "md", True)
        for match in re.finditer(r'"([a-z_]*cents|amount|coupon_share)": "([^"]*)"', text):
            assert re.fullmatch(r"-?\d+\.\d\d", match.group(2)), match.group(0)

    @pytest.mark.parametrize("name", EXAMPLE_NAMES)
    def test_markdown_tables_are_well_formed(self, name):
        md = fc.render(bs.compute(load(name), audit=True), "md")
        block: list[str] = []
        for line in [*md.splitlines(), ""]:
            if line.startswith("|"):
                block.append(line)
                continue
            if block:
                widths = {len(re.findall(r"(?<!\\)\|", row)) for row in block}
                assert len(widths) == 1, block
            block = []


class TestPrivacy:
    @pytest.mark.parametrize("name", EXAMPLE_NAMES)
    def test_a_private_message_mentions_only_people_the_reader_deals_with(self, name):
        result = bs.compute(load(name), audit=True)
        data = result.inputs_echo
        everyone = data.get("people") or sorted({item["who"] for item in data["items"]})
        everyone = list(dict.fromkeys([*everyone, *result.person_lines]))
        transfers = result.result.get("transfers", [])
        for person, lines in result.person_lines.items():
            text = "\n".join(lines)
            assert text.startswith(person)
            partners = {t["to"] for t in transfers if t["from"] == person}
            partners |= {t["from"] for t in transfers if t["to"] == person}
            for other in everyone:
                if other != person and other not in partners:
                    assert other not in text, (person, other, text)

    @pytest.mark.parametrize("name", EXAMPLE_NAMES)
    def test_the_group_message_is_written_to_the_group(self, name):
        group = fc.render(bs.compute(load(name), audit=True), "group")
        assert "你" not in group and "项目合计" not in group and "给组织者" not in group
        english = fc.render(bs.compute(load(name), audit=True, lang="en"), "group")
        assert " you " not in english.lower()

    def test_dm_gives_everyone_in_people_a_block_even_if_they_share_nothing(self):
        data = load("dinner_680")
        data["people"].append("老王")
        data["expenses"][0]["items"][0] = {"name": "菜", "amount": 480, "among": data["people"][:4]}
        result = bs.compute(data)
        assert "老王" in result.person_lines
        assert "没有分摊也没有垫付" in "\n".join(result.person_lines["老王"])
        assert "老王" in fc.render(result, "dm")

    def test_dm_blocks_follow_the_order_of_people(self):
        result = bs.compute(load("dinner_680"))
        assert people_of(result) == ["阿明", "小红", "大刘", "Coco"]
        text = fc.render(result, "dm")
        positions = [text.index(f"发给 {name}") for name in people_of(result)]
        assert positions == sorted(positions)

    def test_the_owner_of_a_group_order_dm_sees_the_trap_warning(self):
        order = {
            "mode": "group_order",
            "items": [{"who": w, "name": "x", "amount": 100} for w in ("a", "b")],
            "coupons": [{"name": "deal", "tiers": [[100, 20]]}],
            "paid_by": "a",
        }
        lines = bs.compute(order).person_lines
        assert any("拆开下单" in line for line in lines["b"])


class TestDemo:
    def test_demo_prints_the_same_bytes_every_time(self):
        first = run_script("--demo")
        second = run_script("--demo")
        assert first.returncode == 0 and first.stdout == second.stdout and first.stderr == ""

    @pytest.mark.parametrize("fmt", ["md", "dm", "group"])
    def test_demo_in_every_format(self, fmt):
        done = run_script("--demo", "--format", fmt)
        assert done.returncode == 0, done.stderr
        assert done.stdout.count("=== demo ") == 3

    def test_demo_json_is_one_object_with_the_three_examples(self):
        done = run_script("--demo", "--json")
        assert done.returncode == 0, done.stderr
        demos = json.loads(done.stdout)
        assert sorted(demos) == ["audit_aa", "group_order_coupon", "trip_five_bills"]
        assert done.stdout == run_script("--demo", "--json").stdout

    def test_demo_in_english_is_stable_too(self):
        assert (
            run_script("--demo", "--lang", "en").stdout
            == run_script("--demo", "--lang", "en").stdout
        )

    def test_demo_reproduces_the_numbers_of_the_three_examples(self):
        out = run_script("--demo").stdout
        # a dinner of 680: 127.50 and 212.50 itemised against 170.00 each
        for text in ("127.50", "212.50", "170.00", "多掏 42.50", "少掏 42.50"):
            assert text in out
        # a trip with five bills: 16, 11, 5 and 5 transfers
        assert "每笔账各自还给垫付人 16 笔" in out and "抵消 11 笔" in out and "贪心 5 笔" in out
        assert "最少 5 笔" in out and "转账：最少 5 笔" in out
        # a coupon of 60 off 300: 20.00 each by Shapley, 29.03, 27.10 and 3.87 in proportion
        for text in (
            "20.00",
            "29.03",
            "27.10",
            "3.87",
            "130.00",
            "120.00",
            "120.97",
            "112.90",
            "16.13",
        ):
            assert text in out

    def test_demo_writes_no_files(self, tmp_path):
        run_script("--demo", cwd=tmp_path)
        assert list(tmp_path.iterdir()) == []


class TestReproduce:
    def test_every_block_of_the_demo_prints_the_command_of_the_demo(self):
        done = run_script("--demo", "--lang", "en")
        assert (
            done.stdout.count("\npython3 scripts/bill_split.py --demo --format md --lang en\n") == 3
        )
        demos = json.loads(run_script("--demo", "--json").stdout)
        for demo in demos.values():
            assert demo["reproduce"] == "python3 scripts/bill_split.py --demo --json"

    @pytest.mark.parametrize(
        ("args", "command"),
        [
            ([], "python3 scripts/bill_split.py --input - --format md"),
            (["--audit"], "python3 scripts/bill_split.py --input - --format md --audit"),
            (
                ["--audit", "--lang", "en"],
                "python3 scripts/bill_split.py --input - --format md --audit --lang en",
            ),
        ],
    )
    def test_a_run_on_a_file_names_its_options(self, args, command):
        done = run_script("--input", str(EXAMPLES / "audit_aa.json"), *args)
        assert done.returncode == 0, done.stderr
        assert f"```\n{command}\n```" in done.stdout


class TestSelfTest:
    def test_selftest_passes(self):
        done = run_script("--selftest")
        assert done.returncode == 0, done.stdout + done.stderr
        assert "0 failed" in done.stdout and "FAIL" not in done.stdout

    def test_help_lists_every_option(self):
        text = run_script("--help").stdout
        for flag in ("--input", "--format", "--json", "--audit", "--lang", "--demo", "--selftest"):
            assert flag in text

    def test_script_has_no_side_effects_on_import(self):
        assert callable(bs.main) and bs.__name__ == "bill_split"
        assert SCRIPT.exists()


class TestTextTables:
    def test_both_languages_have_the_same_keys(self):
        assert set(bs.TEXT["zh"]) == set(bs.TEXT["en"])

    def test_both_languages_use_the_same_placeholders(self):
        formatter = string.Formatter()
        for key in bs.TEXT["zh"]:
            fields = {}
            for lang in ("zh", "en"):
                fields[lang] = {
                    name for _, name, _, _ in formatter.parse(bs.TEXT[lang][key]) if name
                }
            assert fields["zh"] == fields["en"], key

    def test_every_note_code_has_text_in_both_languages(self):
        codes = {
            "zero_item",
            "zero_extra",
            "payer_not_sharing",
            "negative_share",
            "greedy_fallback",
            "greedy_chosen",
            "zero_order_item",
            "tier_not_reached",
            "negative_payer",
            "payer_outside",
        }
        for lang in ("zh", "en"):
            for code in codes:
                assert "note_" + code in bs.TEXT[lang]

    def test_not_modeled_lists_have_the_same_length_in_both_languages(self):
        for key in ("not_modeled_expenses", "not_modeled_order"):
            assert len(bs._not_modeled(key, "zh")) == len(bs._not_modeled(key, "en"))

    def test_english_output_has_no_chinese_text_outside_the_input(self):
        order = {
            "mode": "group_order",
            "items": [{"who": "a", "name": "x", "amount": 28, "packaging": 1}],
            "fees": [{"name": "delivery", "amount": 5}],
            "coupons": [{"name": "deal", "tiers": [[20, 5]]}, {"name": "packet", "amount": 3}],
            "paid_by": "a",
        }
        result = bs.compute(order, audit=True, lang="en")
        for fmt in ("md", "dm", "group"):
            assert not CJK.search(fc.render(result, fmt, False, "en")), fmt
        ledger = bs.compute(load("fewest_transfers"), audit=True, lang="en")
        text = "".join(fc.render(ledger, fmt, False, "en") for fmt in ("md", "dm", "group"))
        assert CJK.search(text) is not None  # only the invented names
        stripped = CJK.sub("", text)
        assert not CJK_PUNCT.search(stripped)

    def test_language_must_be_zh_or_en(self):
        with pytest.raises(ValueError):
            bs.compute(load("dinner_680"), lang="fr")


class TestSkillFile:
    """The commands and JSON examples in SKILL.md must run."""

    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")

    def blocks(self, fence: str) -> list[str]:
        """The contents of the fenced code blocks whose opening line is ``` plus `fence`."""
        found: list[str] = []
        current: list[str] | None = None
        wanted = False
        for line in self.text.splitlines():
            if line.startswith("```"):
                if current is None:
                    current, wanted = [], line[3:].strip() == fence
                else:
                    if wanted:
                        found.append("\n".join(current) + "\n")
                    current = None
            elif current is not None:
                current.append(line)
        return found

    def test_every_json_example_is_a_valid_input(self):
        examples = self.blocks("json")
        assert len(examples) >= 2
        for block in examples:
            result = bs.compute(fc.parse_input(block), audit=True)
            assert result.result["total_cents"]

    def test_the_command_example_runs(self):
        (block,) = [b for b in self.blocks("bash") if "<<'EOF'" in b]
        command, _, rest = block.partition(" <<'EOF'\n")
        body = rest.rsplit("EOF", 1)[0]
        args = command.replace("${CLAUDE_SKILL_DIR}/scripts/bill_split.py", "").split()
        assert args[0] == "python3"
        done = run_script(*args[1:], text=body)
        assert done.returncode == 0, done.stderr
        assert "30.00" in done.stdout

    def test_the_description_and_size_follow_the_repository_rules(self):
        front = self.text.split("---")[1]
        description = re.search(r"^description: (.*)$", front, flags=re.MULTILINE).group(1)
        assert len(description) <= 1024 and "<" not in description and ">" not in description
        assert len(self.text.splitlines()) < 500
        for trigger in (
            "AA",
            "分账",
            "聚餐怎么分钱",
            "外卖拼单",
            "凑满减",
            "settle up",
            "who owes whom",
        ):
            assert trigger in description
        assert "ride-split" in description and "rent-split" in description

    def test_it_points_to_the_script_the_documented_way(self):
        assert "python3 ${CLAUDE_SKILL_DIR}/scripts/bill_split.py" in self.text
        assert "the script is in the `scripts/` folder next to this file" in self.text
        tools = "allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/bill_split.py *)"
        assert tools in self.text

    def test_every_option_it_mentions_exists(self):
        helptext = run_script("--help").stdout
        for flag in set(re.findall(r"`(--[a-z-]+)`", self.text)):
            assert flag in helptext, flag

    def test_the_input_fields_table_lists_every_top_level_field_the_script_accepts(self):
        table = self.text.split("| Field | Meaning |")[1].split("\n\n")[0]
        for field in sorted({*bs.LEDGER_FIELDS, *bs.ORDER_FIELDS}):
            if field == "rules":
                field = "rules.settle"  # described field by field
            assert f"`{field}`" in table, field

    def test_every_example_file_is_listed(self):
        listed = set(re.findall(r"`examples/([A-Za-z0-9_.-]+\.json)`", self.text))
        assert listed == {path.name for path in (SKILL_DIR / "examples").glob("*.json")}
        assert "holds six complete inputs" in self.text


class TestLatinNames:
    def test_a_name_with_latin_letters_gets_a_space_next_to_chinese_text(self):
        assert bs.say("zh", "g_diff_more", name="Coco", amount="42.50") == "Coco 多掏 42.50"
        assert bs.say("zh", "g_diff_more", name="阿明", amount="42.50") == "阿明多掏 42.50"
        assert bs.say("zh", "rule_fee_proportional", name="Delivery") == "Delivery 按菜价比例分"
        assert bs.say("zh", "leftover", id="x-1", names="Coco、阿明") == (
            "零头：x-1 里各多出的 1 分给了 Coco、阿明；余数相同时按账目编号轮换。"
        )

    def test_english_is_filled_without_any_extra_space(self):
        assert bs.say("en", "g_diff_more", name="Coco", amount="42.50") == "Coco pays 42.50 more"

    def test_the_group_card_of_the_dinner_audit_spaces_the_latin_name(self):
        result = bs.compute(load("dinner_680"), audit=True)
        card = fc.render_group(result)
        assert "大刘少掏 42.50，Coco 少掏 42.50。" in card
        assert "Coco少掏" not in card
