"""The English output of rent-split (--lang en), and Latin names inside Chinese text.

The recorded English demo is compared byte for byte in test_rent_split_cli.py. The tests here check what
the golden files cannot: that the two languages stay in step, that English output holds no Chinese
word of the script, and that the Chinese output is the same with --lang zh as without the option.
"""

from __future__ import annotations

import json
import re
import string
from fractions import Fraction

import pytest
from rent_split_support import (
    ASCII_PEOPLE,
    ASCII_ROOMS,
    EXAMPLES,
    ascii_roommates,
    dumps,
    four_roommates,
    load_script,
    make_input,
    run_script,
    storage_room,
)

rs = load_script()
fc = rs.fc

CJK = re.compile(r"[　-〿㐀-鿿＀-￯]")
CLOSE = re.compile(r"[A-Za-z0-9][㐀-鿿]|[㐀-鿿][A-Za-z0-9]")
NONCE = "00112233445566778899aabbccddeeff"
EXAMPLE_NAMES = ["four_roommates", "storage_room", "audit_equal_split"]


def run_en(data, *args):
    return run_script("--input", "-", "--lang", "en", *args, stdin=dumps(data))


def placeholders(template):
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def templates(table):
    """Every template of a language as (key, position, text); lists give one entry per item."""
    for key, value in table.items():
        for position, text in enumerate(value if isinstance(value, list) else [value]):
            yield key, position, text


# --------------------------------------------------------------------------------------
# The two languages say the same thing
# --------------------------------------------------------------------------------------


class TestTexts:
    def test_both_languages_have_the_same_keys(self):
        zh, en = rs.TEXT["zh"], rs.TEXT["en"]
        assert set(zh) == set(en)
        for key in zh:
            assert type(zh[key]) is type(en[key]), key
            if isinstance(zh[key], list):
                assert len(zh[key]) == len(en[key]), key

    def test_both_languages_fill_in_the_same_values(self):
        english = {(key, position): text for key, position, text in templates(rs.TEXT["en"])}
        for key, position, text in templates(rs.TEXT["zh"]):
            assert placeholders(text) == placeholders(english[key, position]), (key, position)

    @pytest.mark.parametrize("lang", ["zh", "en"])
    def test_every_template_can_be_filled(self, lang):
        for key, position, text in templates(rs.TEXT[lang]):
            values = dict.fromkeys(placeholders(text), "x")
            assert isinstance(fc.fill_text(lang, text, **values), str), (key, position)

    def test_the_english_texts_have_no_chinese_words_of_their_own(self):
        for key, position, text in templates(rs.TEXT["en"]):
            if key == "s_note":
                continue  # the storage example names its two people, 甲 and 乙
            assert not CJK.search(text), (key, position, text)


# --------------------------------------------------------------------------------------
# The option
# --------------------------------------------------------------------------------------


def test_an_unknown_language_is_a_usage_error():
    done = run_script("--demo", "--lang", "fr")
    assert done.returncode == 2
    assert "invalid choice" in done.stderr


def test_the_library_refuses_a_language_it_has_no_texts_for():
    with pytest.raises(ValueError, match="lang must be one of zh, en"):
        rs.analyse(four_roommates(), lang="fr")


@pytest.mark.parametrize("name", EXAMPLE_NAMES)
@pytest.mark.parametrize(
    "flags", [("--format", "md"), ("--format", "dm"), ("--format", "group"), ("--json",)]
)
def test_chinese_is_the_default_and_lang_zh_changes_nothing(name, flags):
    path = str(EXAMPLES / f"{name}.json")
    plain = run_script("--input", path, *flags)
    zh = run_script("--input", path, *flags, "--lang", "zh")
    assert plain.returncode == zh.returncode == 0
    assert zh.stdout == plain.stdout != ""


@pytest.mark.parametrize("name", EXAMPLE_NAMES)
@pytest.mark.parametrize("fmt", ["md", "dm", "group"])
def test_every_example_renders_in_english(name, fmt):
    done = run_script("--input", str(EXAMPLES / f"{name}.json"), "--format", fmt, "--lang", "en")
    assert done.returncode == 0, done.stderr
    assert done.stderr == ""
    assert done.stdout.endswith("\n")
    assert "Traceback" not in done.stdout


# --------------------------------------------------------------------------------------
# English output
# --------------------------------------------------------------------------------------


class TestEnglishOutput:
    @pytest.mark.parametrize(
        "flags", [("--format", "md"), ("--format", "dm"), ("--format", "group"), ("--json",)]
    )
    def test_nothing_is_left_in_chinese_when_the_names_are_ascii(self, flags):
        done = run_en(ascii_roommates(), "--audit", *flags)
        assert done.returncode == 0, done.stderr
        assert done.stderr == ""
        assert not CJK.search(done.stdout), CJK.search(done.stdout)

    def test_the_audit_of_a_wrong_assignment_has_no_chinese_either(self):
        data = ascii_roommates()
        data["audit"]["assignment"] = dict(zip(ASCII_PEOPLE, ["Main", "South", "North", "Study"]))
        for fmt in ("md", "dm", "group"):
            done = run_en(data, "--audit", "--format", fmt)
            assert done.returncode == 0, done.stderr
            assert not CJK.search(done.stdout), fmt
        md = run_en(data, "--audit").stdout
        assert "not the ones with the highest total of bids" in md
        assert "they add up to 8,300.00, below the best total of 9,100.00" in md

    def test_the_certificate_lines_of_the_four_roommates(self):
        lines = rs.analyse(ascii_roommates(), lang="en").certificate["one_liner"]
        assert lines["Ann"] == (
            "By your bids, Study is 250.00 cheaper than the price you had in mind, and no other "
            "room is a better deal."
        )
        assert lines["Bob"] == (
            "By your bids, South is 250.00 cheaper than the price you had in mind, and no other "
            "room is a better deal. Study would be exactly as good a deal for you (also 250.00 "
            "cheaper than your price), and a tie is not a loss."
        )

    def test_one_cent_of_rounded_envy_is_reported_as_rounding(self):
        bids = {
            "p0": ["0.13", "0.12", "0.05"],
            "p1": ["0.10", "0.09", "0.11"],
            "p2": ["0.12", "0.00", "0.18"],
        }
        result = rs.analyse(make_input("0.30", ["r0", "r1", "r2"], bids, "allow"), lang="en")
        assert result.certificate["one_liner"]["p0"] == (
            "By your bids, r0 is 0.04 cheaper than the price you had in mind. After rounding to "
            "the cent, r1 would be 0.01 better for you than this room. That is a rounding error "
            "(at the exact values no other room is a better deal)."
        )
        assert "the largest envy is 0.01" in fc.render_md(result, "en")
        assert "the difference is at most 0.01" in fc.render_group(result)

    def test_a_flat_room_reads_as_the_rent_equal_to_the_bid(self):
        flat = {name: [Fraction(100)] * 3 for name in ("x", "y", "z")}
        result = rs.analyse(make_input(300, ["a", "b", "c"], flat, "allow"), lang="en")
        assert result.certificate["one_liner"]["x"] == (
            "By your bids, the rent of a is exactly the price you had in mind, and no other room "
            "is a better deal. b, c would be exactly as good a deal for you (also exactly your "
            "price), and a tie is not a loss."
        )

    def test_a_negative_rent_reads_as_money_received(self):
        result = rs.analyse(storage_room("allow"), lang="en")
        assert "丙 lives in 储物间改的小间 and is paid 1,066.66 a month" in fc.render_group(result)
        assert "You live in 储物间改的小间 and are paid 1,066.66 a month." in "\n".join(
            result.person_lines["丙"]
        )
        assert "-1,066.66 (paid to live there)" in fc.render_md(result, "en")

    def test_bids_that_do_not_add_up_are_explained_in_english(self):
        bids = {"A": [3800, 1400, 2000], "B": [2900, 3000, 100], "C": [2600, 2800, 600]}
        result = rs.analyse(make_input(6000, ["r1", "r2", "r3"], bids), lang="en")
        text = "\n".join(result.person_lines["A"])
        assert "Your bids add up to 7,200.00, which is 1,200.00 more than the total rent" in text
        assert "subtracting 400.00" in text
        assert "(adjusted)" in fc.render_md(result, "en")
        assert "\n".join(result.person_lines["B"]).count("add up") == 0

    def test_ties_are_broken_by_name_or_by_the_public_source(self):
        flat = {name: [100, 100, 100] for name in ("x", "y", "z")}
        plain = fc.render_md(
            rs.analyse(make_input(300, ["a", "b", "c"], flat, "allow"), lang="en"), "en"
        )
        assert "broken by sorting the names" in plain
        seeded = make_input(300, ["a", "b", "c"], flat, "allow", random_source="public text")
        assert "Seed (SHA-256): " in fc.render_md(rs.analyse(seeded, lang="en"), "en")

    def test_the_group_summary_holds_no_bid_and_a_message_only_its_own(self):
        bids = {
            "Ann": [Fraction("3017.23"), Fraction("2211.07"), Fraction("1771.70")],
            "Bob": [Fraction("1903.41"), Fraction("3511.19"), Fraction("1585.40")],
            "Cy": [Fraction("2301.37"), Fraction("2419.13"), Fraction("2279.50")],
        }
        result = rs.analyse(make_input(Fraction(7000), ["East", "West", "South"], bids), lang="en")
        group = fc.render_group(result)

        def shown(amount):
            return fc.fmt_cents(int(amount * 100))

        for row in bids.values():
            assert not any(shown(bid) in group for bid in row)
        for name, row in bids.items():
            message = "\n".join(result.person_lines[name])
            others = [shown(bid) for other, r in bids.items() if other != name for bid in r]
            assert not any(text in message for text in others)
            assert all(shown(bid) in message for bid in row)

    def test_the_json_envelope_differs_only_in_prose(self):
        zh = json.loads(run_script("--input", "-", "--json", stdin=dumps(ascii_roommates())).stdout)
        en = json.loads(run_en(ascii_roommates(), "--json").stdout)
        assert en["inputs_echo"] == zh["inputs_echo"]
        assert en["result"] == zh["result"]
        for key in ("envy_table", "ties", "rent_within_own_bid"):
            assert en["certificate"][key] == zh["certificate"][key]
        assert en["certificate"]["one_liner"] != zh["certificate"]["one_liner"]
        assert len(en["not_modeled"]) == len(zh["not_modeled"]) == 3
        assert en["reproduce"] == zh["reproduce"] + " --lang en"

    def test_the_reproduce_line_names_the_language_only_when_it_is_not_chinese(self):
        zh = rs.analyse(four_roommates()).reproduce
        en = rs.analyse(four_roommates(), lang="en").reproduce
        assert "--lang" not in zh
        assert en.startswith("python3 scripts/rent_split.py --input - --format md --lang en")


# --------------------------------------------------------------------------------------
# Commitments in English
# --------------------------------------------------------------------------------------

ORGANIZER_ROW = {
    "total_rent": 8000,
    "rooms": ASCII_ROOMS,
    "bids": {"Ann": [3000, 2200, 1600, 1200]},
}


class TestCommitments:
    def test_the_commitment_code_does_not_depend_on_the_language(self):
        zh = run_script("--commit", "--nonce", NONCE, "--input", "-", stdin=dumps(ORGANIZER_ROW))
        en = run_script(
            "--commit", "--nonce", NONCE, "--input", "-", "--lang", "en", stdin=dumps(ORGANIZER_ROW)
        )
        assert zh.returncode == en.returncode == 0
        digest = re.search(r"[0-9a-f]{64}", zh.stdout).group(0)
        assert digest in en.stdout and NONCE in en.stdout
        assert en.stdout.startswith("Commitment code (post it in the group now): ")
        assert not CJK.search(en.stdout)
        assert en.stdout.endswith("newline + text).\n")

    def test_a_matching_row_passes_and_a_changed_one_fails(self):
        full = dict(
            ORGANIZER_ROW, bids={name: row for name, row in ascii_roommates()["bids"].items()}
        )
        full["rules"] = {"negative_rent": "spliddit"}
        code = json.loads(
            run_script(
                "--commit", "--nonce", NONCE, "--json", "--input", "-", stdin=dumps(ORGANIZER_ROW)
            ).stdout
        )["digest"]
        args = ("--verify-commit", code, "--nonce", NONCE, "--person", "Ann", "--lang", "en")
        good = run_script(*args, "--input", "-", stdin=dumps(full))
        assert good.returncode == 0
        assert (
            good.stdout
            == "Check passed: the bids of Ann and the nonce match the commitment code.\n"
        )
        full["bids"]["Ann"] = [3000, 2200, 1601, 1199]
        bad = run_script(*args, "--input", "-", stdin=dumps(full))
        assert bad.returncode == 1
        assert bad.stdout.startswith("Check failed: the bids of Ann or the nonce do not match")


# --------------------------------------------------------------------------------------
# Latin names inside Chinese text
# --------------------------------------------------------------------------------------


class TestLatinNames:
    def test_a_latin_room_gets_a_space_next_to_chinese_text(self):
        assert rs.say("zh", "cert_gain", room="Qd", amount="250.00") == (
            "按你报的价，Qd 比你心里价位便宜 250.00"
        )
        assert rs.say("zh", "cert_gain", room="小书房", amount="250.00") == (
            "按你报的价，小书房比你心里价位便宜 250.00"
        )
        assert rs.say("zh", "cert_gain", room="小A", amount="1.00") == (
            "按你报的价，小A 比你心里价位便宜 1.00"
        )

    def test_english_text_is_filled_without_any_extra_space(self):
        assert rs.say("en", "cert_gain", room="Qd", amount="250.00") == (
            "By your bids, Qd is 250.00 cheaper than the price you had in mind"
        )

    def test_a_list_of_latin_rooms_is_spaced_at_both_ends(self):
        line = rs.certificate_line("a", 0, ["b", "c"], [], 0)
        assert line == (
            "按你报的价，a 的房租正好等于你心里的价位，换哪间都不会更划算；"
            "b、c 对你来说一样划算（也正好等于你的报价），打平不算吃亏。"
        )

    def test_the_audit_lines_keep_latin_rooms_apart_from_chinese_words(self):
        data = ascii_roommates()
        data["bids"] = {
            name: row for name, row in zip(["阿明", "小红", "大刘", "Coco"], data["bids"].values())
        }
        data["audit"]["assignment"] = dict(zip(data["bids"], ["Study", "South", "Main", "North"]))
        data["audit"]["rent"] = dict.fromkeys(data["bids"], 2000)
        text = fc.render_md(rs.analyse(data, want_audit=True))
        assert (
            "- 阿明 住 Study：按自己的报价羡慕 Main 1,800.00；按规则该付 950.00，现在每月多掏 1,050.00"
        ) in text
        assert "| 阿明 | Study | 2,000.00 | 羡慕 Main 1,800.00 | 950.00 | 多掏 1,050.00 |" in text
        assert (
            "- Coco：按你报的价，North 比你心里价位便宜 350.00，换哪间都不会更划算；Study 对你来说"
            in text
        )

    @pytest.mark.parametrize("fmt", ["md", "dm", "group"])
    def test_ascii_names_never_touch_a_chinese_character(self, fmt):
        done = run_script(
            "--input", "-", "--audit", "--format", fmt, stdin=dumps(ascii_roommates())
        )
        assert done.returncode == 0, done.stderr
        assert CLOSE.search(done.stdout) is None, CLOSE.search(done.stdout)
