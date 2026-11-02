"""The outputs of the stuff-split skill: privacy, the JSON certificate, both languages.

A private message holds the receiver's own values and the public result. The group summary holds
no value. The JSON carries what anyone needs to recompute the result from the values it echoes,
and the two languages print the same numbers.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from fractions import Fraction

import pytest
import stuff_split as ss
import stuff_split_reference as ref
from stuff_split_support import (
    EXAMPLES,
    SOURCE,
    dumps,
    example,
    make_input,
    piano,
    roommates,
    run_script,
)

fc = ss.fc
METHODS = ("envy_free", "knaster", "max_nash")
MONEY = re.compile(r"-?\d[\d,]*\.\d\d")
CJK = re.compile(r"[㐀-鿿]")
CJK_RUN = re.compile(r"[㐀-鿿]+")
TOUCHING = re.compile(r"[A-Za-z0-9][㐀-鿿]|[㐀-鿿][A-Za-z0-9]")

# Every value is unlike every other number the outputs print: person a gives small numbers,
# person b gives thousands, person c gives millions.
DISTINCT = {
    "a": [Fraction(101, 100), Fraction(307, 100), Fraction(509, 100), Fraction(711, 100)],
    "b": [
        Fraction(100113, 100),
        Fraction(200317, 100),
        Fraction(300519, 100),
        Fraction(400721, 100),
    ],
    "c": [
        Fraction(100000119, 100),
        Fraction(200000323, 100),
        Fraction(300000527, 100),
        Fraction(400000731, 100),
    ],
}


def distinct(method):
    return make_input(["a", "b", "c"], ["w", "x", "y", "z"], DISTINCT, method)


def run_all(data, lang="zh"):
    outputs = {}
    for flags in (["--format", "md"], ["--format", "dm"], ["--format", "group"], ["--json"]):
        done = run_script("--input", "-", *flags, "--lang", lang, stdin=dumps(data))
        assert done.returncode == 0, done.stderr
        outputs[flags[-1]] = done.stdout
    return outputs


def tokens_of(person):
    return [ss.fmt(int(value * 100)) for value in DISTINCT[person]]


# --------------------------------------------------------------------------------------
# Privacy
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("lang", ["zh", "en"])
def test_the_group_summary_holds_no_value(method, lang):
    group = run_all(distinct(method), lang)["group"]
    for person in DISTINCT:
        for token in tokens_of(person):
            assert token not in group, (person, token)


def test_the_group_summary_does_not_say_which_items_tied_but_the_organizer_table_does():
    path = str(EXAMPLES / "weighted_knaster.json")
    group = run_script("--input", path, "--format", "group").stdout
    md = run_script("--input", path).stdout
    assert "最高估值并列。" in group and "最高估值并列（" not in group
    assert "最高估值并列（书桌、旧收音机）" in md
    english = run_script("--input", path, "--format", "group", "--lang", "en").stdout
    assert "more than one person shares. Such an item" in english


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("lang", ["zh", "en"])
def test_a_private_message_holds_only_the_receivers_values(method, lang):
    result = ss.analyse(distinct(method), lang)
    assert sorted(result.person_lines) == sorted(DISTINCT)
    for receiver, lines in result.person_lines.items():
        text = "\n".join(lines)
        for person in DISTINCT:
            if person != receiver:
                for token in tokens_of(person):
                    assert token not in text, (receiver, person, token)
        assert sum(line.endswith(" *") for line in lines) == 1  # the receiver's own package


@pytest.mark.parametrize("method", METHODS)
def test_the_json_echoes_every_value_for_the_organizer(method):
    echo = json.loads(run_all(distinct(method))["--json"])["inputs_echo"]["values"]
    for person, row in DISTINCT.items():
        assert [echo[person][item] for item in "wxyz"] == [
            fc.cents_str(int(value * 100)) for value in row
        ]


@pytest.mark.parametrize("method", METHODS)
def test_every_private_message_names_only_its_receiver_in_the_greeting(method):
    result = ss.analyse(distinct(method), "en")
    for receiver, lines in result.person_lines.items():
        assert lines[0].startswith(f"{receiver}, this is your own result")
        assert sum(1 for line in lines if "this is your own result" in line) == 1


# --------------------------------------------------------------------------------------
# The JSON
# --------------------------------------------------------------------------------------


def no_floats(text):
    def refuse(value):
        raise AssertionError(f"a float in the JSON: {value}")

    return json.loads(text, parse_float=refuse)


@pytest.mark.parametrize("name", sorted(path.stem for path in EXAMPLES.glob("*.json")))
def test_the_json_has_the_envelope_keys_and_never_a_float(name):
    done = run_script("--input", str(EXAMPLES / f"{name}.json"), "--json")
    assert done.returncode == 0, done.stderr
    doc = no_floats(done.stdout)
    assert sorted(doc) == ["certificate", "inputs_echo", "not_modeled", "reproduce", "result"]
    assert done.stdout.endswith("}\n")
    for amount in doc["result"]["own_value_cents"].values():
        assert re.fullmatch(r"-?\d+\.\d\d", amount)


def exact(text):
    """The exact number of a *_exact field: a decimal or a fraction, in currency units."""
    return Fraction(text)


def recompute(doc):
    """Check a JSON document against the values it echoes, with the plain reference only."""
    echo, result, cert = doc["inputs_echo"], doc["result"], doc["certificate"]
    people, items = echo["people"], echo["items"]
    values = [[int(Fraction(echo["values"][p][g]) * 100) for g in items] for p in people]
    owner = [people.index(result["owner"][g]) for g in items]
    recompute_data = cert["recompute"]
    method = result["method_used"]
    n = len(people)
    if method in ("envy_free", "knaster"):
        best = ref.highest(values)
        assert all(values[owner[j]][j] == best[j] for j in range(len(items)))
        assert Fraction(recompute_data["total_best_cents"]) * 100 == ref.welfare(values)
        cash = [Fraction(result["cash_cents"][p]) * 100 for p in people]
        assert sum(cash) == 0
        exact_cash = [exact(recompute_data["cash_exact"][p]) * 100 for p in people]
        assert all(abs(cash[i] - exact_cash[i]) < 1 for i in range(n))
        if method == "envy_free":
            assert exact(recompute_data["worth_exact"]) * 100 == Fraction(ref.welfare(values), n)
            expected = ref.envy_free_exact_cash(values, owner)
        else:
            weights = [exact(echo["rules"].get("weights", {}).get(p, "1")) for p in people]
            fair, surplus, expected = ref.knaster_exact(values, owner, weights)
            assert exact(recompute_data["surplus_exact"]) * 100 == surplus
            assert [exact(recompute_data["fair_share_exact"][p]) * 100 for p in people] == fair
        assert exact_cash == expected
    else:
        key = ref.nash_key(values, owner)
        if method == "max_nash":
            assert key == ref.best_nash_key(values)
            assert int(recompute_data["product_cents"]) == key[1]
            assert recompute_data["people_with_positive_value"] == key[0]
            assert recompute_data["allocations"] == str(n ** len(items))
        else:
            assert ref.is_ef1(values, owner)
        for i, row in recompute_data["ef1"].items():
            for k, step in row.items():
                assert step["holds"] is True
                assert Fraction(step["theirs_cents"]) * 100 > Fraction(step["own_cents"]) * 100
                rest = Fraction(step["theirs_cents"]) - Fraction(step["set_aside_value_cents"])
                assert Fraction(step["rest_cents"]) == rest <= Fraction(step["own_cents"])
    envy_table = cert["envy_table"]
    for i, p in enumerate(people):
        for k, q in enumerate(people):
            theirs = ref.package_value(values, owner, i, k)
            if "cash_cents" in result:
                theirs += int(Fraction(result["cash_cents"][q]) * 100)
            assert Fraction(envy_table[p][q]) * 100 == theirs


@pytest.mark.parametrize("name", sorted(path.stem for path in EXAMPLES.glob("*.json")))
def test_the_json_certificate_lets_anyone_recompute_the_result(name):
    doc = json.loads(run_script("--input", str(EXAMPLES / f"{name}.json"), "--json").stdout)
    recompute(doc)


@pytest.mark.parametrize("method", METHODS)
def test_the_certificate_recomputes_on_a_case_with_ties_and_a_source(method):
    data = make_input(
        ["p0", "p1", "p2"],
        ["g0", "g1", "g2", "g3"],
        {"p0": [5, 5, 0, 7], "p1": [5, 5, 0, 7], "p2": [1, 9, 0, 7]},
        method,
        random_source=SOURCE,
    )
    doc = json.loads(run_script("--input", "-", "--json", stdin=dumps(data)).stdout)
    recompute(doc)
    assert doc["result"]["tie_break"]["method"] == "random_source"
    drawn = fc.seeded_order(ss.RULE_NAME, data["people"], 4, SOURCE)
    assert doc["result"]["tie_break"]["order"] == list(drawn.order)
    assert doc["result"]["tie_break"]["seed_hex"] == drawn.seed_hex
    assert doc["result"]["tie_break"]["preimage"] == drawn.preimage


def test_the_json_names_the_rule_asked_for_and_the_rule_used():
    asked = json.loads(
        run_script("--input", str(EXAMPLES / "three_roommates.json"), "--json").stdout
    )
    assert asked["result"]["method"] == asked["result"]["method_used"] == "max_nash"
    assert asked["result"]["fell_back"] is False and asked["result"]["money_moves"] is False
    assert "cash_cents" not in asked["result"]
    big = json.loads(
        run_script("--input", str(EXAMPLES / "moving_out_14_items.json"), "--json").stdout
    )
    assert big["result"]["method"] == "max_nash" and big["result"]["method_used"] == "round_robin"
    assert big["result"]["fell_back"] is True
    cash = json.loads(run_script("--input", str(EXAMPLES / "piano_knaster.json"), "--json").stdout)
    assert cash["result"]["money_moves"] is True
    assert cash["result"]["cash_cents"] == {"甲": "101.11", "乙": "-498.89", "丙": "397.78"}


# --------------------------------------------------------------------------------------
# Reproducible, and the same numbers in both languages
# --------------------------------------------------------------------------------------


def rendered(data, fmt, lang):
    """The text of one format in one language, built in this process."""
    result = ss.analyse(data, lang)
    return fc.render(result, fmt, False, lang)


EXAMPLE_NAMES = sorted(path.stem for path in EXAMPLES.glob("*.json"))


@pytest.mark.parametrize("name", EXAMPLE_NAMES)
def test_the_same_input_gives_the_same_bytes_in_every_format_and_language(name):
    for fmt in ("md", "dm", "group"):
        for lang in ("zh", "en"):
            first = rendered(example(name), fmt, lang)
            assert first == rendered(example(name), fmt, lang) != ""
    # The program prints what the library builds.
    done = run_script("--input", str(EXAMPLES / f"{name}.json"), "--format", "dm")
    assert done.returncode == 0 and done.stdout == rendered(example(name), "dm", "zh")


@pytest.mark.parametrize("name", EXAMPLE_NAMES)
def test_both_languages_print_the_same_amounts(name):
    for fmt in ("md", "dm", "group"):
        zh = rendered(example(name), fmt, "zh")
        en = rendered(example(name), fmt, "en")
        assert Counter(MONEY.findall(zh)) == Counter(MONEY.findall(en)), fmt


@pytest.mark.parametrize("method", METHODS)
def test_english_output_has_no_chinese_when_the_data_has_none(method):
    data = make_input(
        ["Ann", "Bob", "Cy"],
        ["fridge", "sofa", "tv"],
        {"Ann": [30, 15, 15], "Bob": [25, 10, 20], "Cy": [35, 25, 10]},
        method,
        random_source="a public draw",
    )
    for flags in (["--format", "md"], ["--format", "dm"], ["--format", "group"]):
        done = run_script("--input", "-", *flags, "--lang", "en", stdin=dumps(data))
        assert done.returncode == 0 and CJK.search(done.stdout) is None, flags
        chinese = run_script("--input", "-", *flags, stdin=dumps(data))
        assert CJK.search(chinese.stdout) is not None


def test_the_texts_of_the_two_languages_have_the_same_placeholders():
    for key, template in ss.TEXT["zh"].items():
        other = ss.TEXT["en"][key]
        if isinstance(template, str):
            assert set(re.findall(r"\{(\w+)\}", template)) == set(
                re.findall(r"\{(\w+)\}", other)
            ), key
        elif isinstance(template, list):
            assert len(template) == len(other), key


# --------------------------------------------------------------------------------------
# The tables
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["envy_free", "knaster"])
def test_the_first_table_adds_up_to_zero_cash_and_to_the_highest_values(method):
    out = ss.compute(ss.parse_problem(roommates(method)))
    table = ss.build_result(out, "en").tables[0]
    total = table.rows[-1]
    assert total[0] == "Total"
    assert total[3] == "0.00"
    assert total[2] == total[4] == ss.fmt(out.total_best)
    assert [row[0] for row in table.rows[:-1]] == ["阿明", "小红", "大刘"]


def test_the_envy_table_marks_exactly_one_package_per_row():
    out = ss.compute(ss.parse_problem(piano("knaster")))
    table = ss.build_result(out, "zh").tables[1]
    for row in table.rows[:3]:
        assert sum(cell.endswith("*") for cell in row[1:]) == 1
    assert table.rows[-1][0] == "现金"


def test_one_person_who_envies_is_written_in_the_singular_in_english():
    # Both want x: maximum Nash welfare gives each one item, and whoever gets y envies.
    data = make_input(["a", "b"], ["x", "y"], {"a": [10, 1], "b": [10, 1]}, "max_nash")
    outputs = run_all(data, "en")
    for fmt in ("md", "group"):
        assert "1 person envies another person's package" in outputs[fmt], outputs[fmt]
        assert "1 people" not in outputs[fmt]
    assert "有 1 人按自己的估值羡慕别人那一份" in run_all(data, "zh")["group"]


def test_the_md_output_names_the_rule_the_limits_and_how_to_rerun():
    text = run_script("--input", str(EXAMPLES / "piano_knaster.json")).stdout
    for needed in (
        "分法（事先定好，结果出来后不再改）",
        "## 本结果不包含",
        "## 复算命令",
        "--format md",
    ):
        assert needed in text, needed


# Latin names inside Chinese text. tests/test_shared_behaviour.py runs every example under its own
# rule. This test runs every example under each of the three rules.


def latinize(text: str) -> str:
    """The text with every run of Chinese characters turned into a Latin token (Qa, Qb, ...)."""
    tokens: dict[str, str] = {}

    def token(match: re.Match[str]) -> str:
        run = match.group(0)
        if run not in tokens:
            index = len(tokens)
            tokens[run] = "Q" + chr(97 + index % 26) + (str(index // 26) if index >= 26 else "")
        return tokens[run]

    return CJK_RUN.sub(token, text)


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("name", sorted(path.stem for path in EXAMPLES.glob("*.json")))
def test_latin_names_never_touch_a_chinese_character_under_any_rule(name, method):
    data = json.loads(latinize((EXAMPLES / f"{name}.json").read_text(encoding="utf-8")))
    data["rules"]["method"] = method
    if method != "knaster":
        data["rules"].pop("weights", None)
    result = ss.analyse(fc.parse_input(json.dumps(data)), "zh")
    for fmt in ("md", "dm", "group"):
        output = fc.render(result, fmt, False, "zh")
        found = TOUCHING.search(output)
        assert found is None, (fmt, output[max(found.start() - 20, 0) : found.end() + 20])
    # One run as a program confirms that the program prints the same text.
    done = run_script("--input", "-", "--format", "group", stdin=dumps(data))
    assert done.returncode == 0 and done.stdout == fc.render(result, "group", False, "zh")
