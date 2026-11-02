"""Output: every format renders for every mode, the private messages stay private."""

from __future__ import annotations

import json
import re

import fsq_core as fc
import pytest
import ride_split as rs
from ride_support import EXAMPLES, RIDERS, run_json, run_script, subset_costs_data

ENVELOPE_KEYS = ["certificate", "inputs_echo", "not_modeled", "reproduce", "result"]
EXAMPLE_FILES = [
    "meter_four_riders.json",
    "app_estimates.json",
    "general_detour.json",
    "audit_equal.json",
]
STAR = {
    "mode": "general",
    "riders": ["A", "B", "C"],
    "subset_costs": [
        {"riders": ["A"], "cost": 10},
        {"riders": ["B"], "cost": 10},
        {"riders": ["C"], "cost": 10},
        {"riders": ["A", "B"], "cost": 30},
        {"riders": ["A", "C"], "cost": 30},
        {"riders": ["B", "C"], "cost": 30},
        {"riders": ["A", "B", "C"], "cost": 50},
    ],
}


def example(name: str) -> dict:
    return fc.parse_input((EXAMPLES / name).read_text(encoding="utf-8"))


def all_inputs():
    """(label, data, audit flag) for every example and a few extra shapes."""
    cases = []
    for name in EXAMPLE_FILES:
        data = example(name)
        cases.append((name, data, False))
        cases.append((name + " --audit", {**data, "audit": {"current": "equal"}}, True))
    cases.append(("empty core", STAR, False))
    cases.append(("empty core --audit", {**STAR, "audit": {"current": "proportional"}}, True))
    cases.append(
        (
            "estimates with a payer and audit",
            {**example("app_estimates.json"), "audit": {"current": "equal"}},
            True,
        )
    )
    return cases


CASES = all_inputs()
IDS = [case[0] for case in CASES]


@pytest.mark.parametrize(("label", "data", "audit"), CASES, ids=IDS)
@pytest.mark.parametrize("lang", ["zh", "en"])
@pytest.mark.parametrize("fmt", ["md", "dm", "group", "json"])
def test_every_format_renders(label, data, audit, lang, fmt):
    flags = ["--audit"] if audit else []
    flags += ["--lang", lang]
    flags += ["--json"] if fmt == "json" else ["--format", fmt]
    done = run_json(data, *flags)
    assert done.returncode == 0, f"{label}: {done.stderr}"
    out = done.stdout
    assert out.strip(), "empty output"
    assert done.stderr == ""
    if fmt == "json":
        assert sorted(json.loads(out)) == ENVELOPE_KEYS
    else:
        for bad in ("None", "Fraction(", "{", "}"):
            assert bad not in out, bad
    for name in data["riders"]:
        assert name in out


def test_json_envelope_of_the_meter_example():
    done = run_script("--demo", "--json")
    parsed = json.loads(done.stdout)
    assert sorted(parsed) == ENVELOPE_KEYS
    result = parsed["result"]
    assert result["method"] == "shapley"
    assert result["in_core"] is True
    assert result["violations"] == []
    assert [seg["cost"] for seg in result["segments"]] == ["14.00", "12.00", "15.00", "22.00"]
    assert [len(seg["shared_by"]) for seg in result["segments"]] == [4, 3, 2, 1]
    assert result["solo_cents"]["老陈"] == "63.00"
    assert result["saved_percent"] == {"小周": 75, "阿杰": 71, "Mia": 63, "老陈": 41}
    equal = result["alternatives"]["equal"]
    assert equal["in_core"] is False and equal["violation_count"] == 3
    assert equal["violations"][0] == {
        "riders": ["小周"],
        "paid": "15.75",
        "alone": "14.00",
        "excess": "1.75",
    }
    assert parsed["inputs_echo"]["total"] == "63.00"
    assert parsed["reproduce"].startswith("python3 scripts/ride_split.py")
    assert parsed["not_modeled"]


def test_amounts_in_json_are_always_two_decimal_strings():
    done = run_script("--demo", "--json", "--audit")
    text = done.stdout
    assert not re.search(r'": -?\d+\.\d+[,\n]', text), "a bare decimal number was written"
    parsed = json.loads(text)
    audit = parsed["result"]["audit"]
    assert audit["difference_cents"]["老陈"] == "-21.25"
    assert audit["difference_cents"]["小周"] == "12.25"
    assert audit["in_core"] is False


class TestPrivateMessages:
    """A message in --format dm holds only the numbers of the rider it is sent to."""

    def messages(self, data, *flags):
        result = rs.solve(data, audit="--audit" in flags)
        return fc.render_dm_messages(result)

    def test_no_message_names_another_rider(self):
        data = example("meter_four_riders.json")
        for rider, text in self.messages(data).items():
            for other in RIDERS:
                if other != rider:
                    assert other not in text

    def test_audit_messages_do_not_name_other_riders_either(self):
        data = example("audit_equal.json")
        for rider, text in self.messages(data, "--audit").items():
            for other in RIDERS:
                if other != rider:
                    assert other not in text

    def test_each_message_starts_with_what_that_rider_pays(self):
        data = example("meter_four_riders.json")
        pays = {"小周": "3.50", "阿杰": "7.50", "Mia": "15.00", "老陈": "37.00"}
        for rider, text in self.messages(data).items():
            assert text.splitlines()[0] == f"这次拼车你付 {pays[rider]}。"

    def test_group_summary_has_no_per_rider_explanations(self):
        done = run_script("--demo", "--format", "group")
        assert "你" not in done.stdout
        assert "3.50" in done.stdout and "37.00" in done.stdout

    def test_payer_and_others_get_different_last_lines(self):
        data = example("app_estimates.json")
        messages = self.messages(data)
        assert messages["小周"].splitlines()[-1] == "请转给 老陈 3.58。"
        assert messages["老陈"].splitlines()[-1].startswith("你先垫付了全部车费 63.00")

    def test_a_rider_who_owes_nothing_gets_no_transfer_request(self):
        data = {**example("app_estimates.json"), "solo_estimate": [0, 27, 40, 66]}
        messages = self.messages(data)
        assert messages["小周"].splitlines() == [
            "这次拼车你付 0.00。",
            "你下车时没有产生任何车费，所以不用付。",
        ]
        assert all("请转给" in messages[name] for name in ("阿杰", "Mia"))
        result = fc.envelope(rs.solve(data))["result"]
        assert [item["from"] for item in result["transfers"]] == ["阿杰", "Mia"]

    def test_english_messages_use_the_same_amounts(self):
        data = example("app_estimates.json")
        zh = fc.render_dm_messages(rs.solve(data, lang="zh"))
        en = fc.render_dm_messages(rs.solve(data, lang="en"))
        amount = re.compile(r"\d[\d,]*\.\d\d")
        for rider in RIDERS:
            assert amount.findall(zh[rider]) == amount.findall(en[rider]), rider


class TestReportContent:
    def test_the_empty_core_is_reported(self):
        done = run_json(STAR)
        assert "核心是空的" in done.stdout
        done = run_json(STAR, "--lang", "en")
        assert "The core is empty" in done.stdout
        parsed = json.loads(run_json(STAR, "--json").stdout)
        assert parsed["result"]["core_is_empty"] is True
        assert parsed["result"]["in_core"] is False

    def test_a_non_empty_core_is_reported_when_shapley_falls_outside(self):
        # B and C can share one car for free, but Shapley still charges them 17.50 for it
        prices = [0, 1000, 1500, 1500, 1500, 2000, 1500, 2500]
        data = subset_costs_data(prices, ["A", "B", "C"])
        ride = rs.parse_ride(data)
        out = rs.compute(ride)
        assert [fc.fmt_cents(c) for c in out.shapley.cents] == ["7.50", "7.50", "10.00"]
        assert [item.members for item in out.shapley.violations] == [(1, 2)]
        assert out.core_empty is False
        done = run_json(data)
        assert "核心不是空的" in done.stdout
        assert "| Shapley 值 | B、C | 17.50 | 15.00 | 2.50 |" in done.stdout
        en = run_json(data, "--lang", "en")
        assert "The core is not empty" in en.stdout

    def test_core_emptiness_is_not_computed_when_it_is_obvious(self):
        out = rs.compute(rs.parse_ride(example("general_detour.json")))
        assert out.core_empty is None

    def test_only_the_first_violations_are_listed_in_markdown(self):
        data = {
            "mode": "meter",
            "riders": [f"r{i}" for i in range(12)],
            "meter_at_dropoff": [10] * 11 + [1200],
        }
        md = run_json(data).stdout
        assert "完整列表见 --json" in md
        listed = [line for line in md.splitlines() if line.startswith("| 平均分 |")]
        assert len(listed) == rs.MAX_SHOWN
        parsed = json.loads(run_json(data, "--json").stdout)
        equal = parsed["result"]["alternatives"]["equal"]
        assert len(equal["violations"]) == equal["violation_count"] == 2**11 - 1
        assert parsed["result"]["in_core"] is True

    def test_estimates_report_states_the_scale(self):
        md = run_json(example("app_estimates.json")).stdout
        assert "21/22" in md
        en = run_json(example("app_estimates.json"), "--lang", "en").stdout
        assert "21/22" in en

    def test_the_rounding_note_names_the_ride_id(self):
        md = run_json({**example("meter_four_riders.json"), "ride_id": "airport-run"}).stdout
        assert "airport-run" in md

    def test_the_audit_titles(self):
        md = run_script("--demo", "--audit").stdout
        assert md.startswith("# 拼车分摊审计")
        en = run_script("--demo", "--audit", "--lang", "en").stdout
        assert en.startswith("# Ride split audit")

    def test_the_audit_lists_the_losers_in_their_own_numbers(self):
        md = run_script("--demo", "--audit").stdout
        assert "| 小周 | 15.75 | 3.50 | +12.25 | 14.00 | 多掏 12.25，比单独打车还多 1.75 |" in md
        assert "| 老陈 | 15.75 | 37.00 | -21.25 | 63.00 | 少掏 21.25 |" in md

    def test_proportional_audit_shortcut(self):
        data = {**example("meter_four_riders.json"), "audit": {"current": "proportional"}}
        parsed = json.loads(run_json(data, "--audit", "--json").stdout)
        assert parsed["result"]["audit"]["current_cents"] == {
            "小周": "6.13",
            "阿杰": "11.37",
            "Mia": "17.94",
            "老陈": "27.56",
        }
        assert parsed["result"]["audit"]["in_core"] is True


class TestCommandLine:
    def test_help_lists_every_option(self):
        text = run_script("--help").stdout
        for flag in ("--input", "--format", "--json", "--demo", "--selftest", "--audit", "--lang"):
            assert flag in text
        assert "12" in text and "6" in text

    def test_selftest_passes(self):
        done = run_script("--selftest")
        assert done.returncode == 0, done.stdout + done.stderr
        assert "0 failed" in done.stdout

    def test_unknown_language_is_refused_by_argparse(self):
        done = run_script("--demo", "--lang", "fr")
        assert done.returncode == 2

    def test_reproduce_command_follows_the_options(self):
        text = run_script("--demo", "--format", "dm").stdout
        assert text  # dm has no reproduce line, md does
        md = run_script("--demo", "--audit", "--lang", "en").stdout
        assert "python3 scripts/ride_split.py --demo --format md --audit --lang en" in md


class TestLatinNames:
    def test_a_name_with_latin_letters_gets_a_space_next_to_chinese_text(self):
        assert rs.say("zh", "note_alone", name="Mia", cost="22.00") == (
            "Mia 付得最多：最后那段 22.00 元只有 Mia 一个人坐。"
        )
        assert rs.say("zh", "note_alone", name="老陈", cost="22.00") == (
            "老陈付得最多：最后那段 22.00 元只有老陈一个人坐。"
        )

    def test_english_is_filled_without_any_extra_space(self):
        assert rs.say("en", "note_alone", name="Mia", cost="22.00") == (
            "Mia pays the most: nobody else is in the car for the last stretch of 22.00."
        )

    def test_a_label_that_starts_with_latin_letters_is_spaced_too(self):
        label = rs.TEXT["zh"]["m_shapley_general"]
        assert label == "Shapley 值"
        assert rs.say("zh", "note_prop_in_core", method=label) == (
            "按比例分在这里也在核心里。它和 Shapley 值的分歧是规则选择，要事先定。"
        )
        text = run_script("--input", str(EXAMPLES / "general_detour.json")).stdout
        assert "它和 Shapley 值的分歧" in text

    def test_the_last_rider_with_a_latin_name_in_the_notes(self):
        data = {
            "mode": "meter",
            "riders": ["小周", "Mia"],
            "meter_at_dropoff": [10, 30],
        }
        text = fc.render_md(rs.solve(data))
        assert "Mia 付得最多：最后那段 20.00 元只有 Mia 一个人坐。" in text
