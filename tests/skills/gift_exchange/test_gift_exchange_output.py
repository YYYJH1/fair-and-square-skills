"""Output: every format renders, private messages stay private, the card for the group holds back
what would give the pairing away, and the certificate is enough to recompute the draw."""

from __future__ import annotations

import hashlib
import json
import re

import fsq_core as fc
import gift_exchange as ge
import pytest
from gift_reference import enumeration_draw
from gift_support import (
    BLOCKED6,
    EXAMPLES,
    GOLDEN_COUNT,
    GOLDEN_NUMBER,
    GOLDEN_PLAN,
    GOLDEN_SEED,
    PEOPLE6,
    RING_CIRCLE,
    SOURCE,
    THREE,
    THREE_FORBIDDEN,
    exchange_data,
    load_example,
    run_json,
    run_script,
    six_people,
)

ENVELOPE_KEYS = ["certificate", "inputs_echo", "not_modeled", "reproduce", "result"]
FORMATS = ["md", "dm", "group", "json"]
CJK_RUN = re.compile(r"[㐀-鿿]+")
CJK = re.compile(r"[㐀-鿿，。：；（）「」、！？]")
TOUCHING = re.compile(r"[A-Za-z0-9][㐀-鿿]|[㐀-鿿][A-Za-z0-9]")
OVERCLAIMS = [
    "nobody can cheat",
    "cannot be rigged",
    "tamper-proof",
    "impossible to cheat",
    "谁也做不了手脚",
    "无法作弊",
    "不可能作弊",
]
LATIN = ["Ann", "Bob", "Cy", "Di", "Ed", "Flo", "Gus"]
SHORT_NAMES = {"two people", "a bar in a name"}  # inputs with names of one letter


def all_inputs():
    """(label, data) for every example and a few shapes that reach the other branches."""
    cases = [(path.name, load_example(path.name)) for path in sorted(EXAMPLES.glob("*.json"))]
    cases += [
        ("two people", exchange_data(["a", "b"], [])),
        ("no exclusions", exchange_data(PEOPLE6, [])),
        ("no exclusions in a circle", exchange_data(PEOPLE6, [], "ring")),
        ("one-way exclusions only", exchange_data(LATIN, [{"giver": "Ann", "receiver": "Bob"}])),
        ("a bar in a name", exchange_data(["a|b", "c", "d"], [])),
        (
            "twenty people in a circle",
            exchange_data([f"p{i:02d}" for i in range(20)], [{"pair": ["p00", "p01"]}], "ring"),
        ),
    ]
    return cases


CASES = all_inputs()
IDS = [case[0] for case in CASES]
# Inputs whose names can be told apart from the text around them (a name of one letter is found
# inside any English sentence).
DISTINCT = [case for case in CASES if case[0] not in SHORT_NAMES]
DISTINCT_IDS = [case[0] for case in DISTINCT]


@pytest.mark.parametrize(("label", "data"), CASES, ids=IDS)
@pytest.mark.parametrize("lang", ["zh", "en"])
@pytest.mark.parametrize("fmt", FORMATS)
def test_every_format_renders(label, data, lang, fmt):
    flags = ["--lang", lang]
    flags += ["--json"] if fmt == "json" else ["--format", fmt]
    done = run_json(data, *flags)
    assert done.returncode == 0, f"{label}: {done.stderr}"
    out = done.stdout
    assert out.strip(), "empty output"
    assert done.stderr == ""
    if fmt == "json":
        assert sorted(json.loads(out)) == ENVELOPE_KEYS
    else:
        for bad in ("None", "Fraction(", "Traceback", "{names}", "{receiver}", "{k}", "{total}"):
            assert bad not in out, bad
    for name in data["people"]:
        shown = name.replace("|", "\\|") if fmt == "md" else name  # md tables escape a bar
        assert shown in out, f"{name} is missing from the {fmt} output"


@pytest.mark.parametrize(("label", "data"), CASES, ids=IDS)
def test_text_output_is_the_same_on_every_run(label, data):
    for flags in ([], ["--json"], ["--format", "dm"], ["--format", "group"]):
        assert run_json(data, *flags).stdout == run_json(data, *flags).stdout


# The texts of the two languages


KNOWN_FOR_ERRORS = {"group", "gcount", "k", "others", "ocount", "m", "n", "total", "attempts"}


def test_both_languages_have_the_same_texts():
    assert set(ge.TEXT["zh"]) == set(ge.TEXT["en"])
    for key, zh in ge.TEXT["zh"].items():
        en = ge.TEXT["en"][key]
        assert type(zh) is type(en), key
        if isinstance(zh, list):
            assert len(zh) == len(en), key
        if isinstance(zh, str):
            zh_names = set(re.findall(r"\{([a-z_]+)\}", zh))
            en_names = set(re.findall(r"\{([a-z_]+)\}", en))
            if key.startswith("err_"):
                assert zh_names <= KNOWN_FOR_ERRORS and en_names <= KNOWN_FOR_ERRORS, key
            else:
                assert zh_names == en_names, key


def test_no_chinese_text_has_a_latin_letter_or_digit_touching_a_chinese_character():
    for key, value in ge.TEXT["zh"].items():
        for text in value if isinstance(value, list) else [value]:
            assert TOUCHING.search(text) is None, (key, text)


def test_every_method_and_way_of_giving_has_a_name_in_both_languages():
    for lang in ("zh", "en"):
        for mode in ge.MODES:
            assert ge.TEXT[lang][f"mode_{mode}"]
        for method in ge.METHODS:
            assert ge.TEXT[lang][f"method_{method}"]


# The JSON envelope and the certificate


def test_json_envelope_of_the_recorded_example():
    parsed = json.loads(run_script("--demo", "--json").stdout)
    assert sorted(parsed) == ENVELOPE_KEYS
    result = parsed["result"]
    assert result["assignments"] == GOLDEN_PLAN
    assert result["circle"] is None
    assert result["seed_hex"] == GOLDEN_SEED
    assert (result["plan_count"], result["plan_number"]) == (GOLDEN_COUNT, GOLDEN_NUMBER)
    assert result["attempts"] is None and result["method"] == "enumeration"
    assert result["source_text"] == SOURCE
    echo = parsed["inputs_echo"]
    assert echo["participants"] == sorted(PEOPLE6)
    assert echo["mode"] == "any" and echo["randomness"] == "public_source"
    assert echo["random_source"] == SOURCE
    assert echo["forbidden"] == [{"giver": a, "receiver": b} for a, b in sorted(BLOCKED6)]
    assert parsed["not_modeled"]
    assert parsed["reproduce"] == "python3 scripts/gift_exchange.py --demo --json"


def test_the_certificate_holds_what_is_needed_to_recompute():
    parsed = json.loads(run_script("--demo", "--json").stdout)
    recompute = parsed["certificate"]["recompute"]
    assert set(recompute) == {
        "source_text",
        "rule",
        "method",
        "seed_preimage",
        "seed_hex",
        "plan_count",
        "plan_number",
        "attempts",
        "max_attempts",
        "algorithm",
    }
    assert recompute["source_text"] == SOURCE
    assert recompute["rule"] == "gift_exchange_any_enum_v1"
    assert recompute["algorithm"] == ge.algorithm_certificate("enumeration")
    assert recompute["algorithm"].startswith(ge.seed_steps())
    assert "picks plan number k+1" in recompute["algorithm"]
    assert recompute["max_attempts"] is None


def test_anyone_can_recompute_the_plan_from_the_certificate_and_the_exclusions():
    """Only the JSON output is used: the preimage hashes to the seed, the first uniform number
    of the stream below the count gives the plan number, and the plan is that one of the list."""
    parsed = json.loads(run_script("--demo", "--json").stdout)
    recompute = parsed["certificate"]["recompute"]
    seed = hashlib.sha256(recompute["seed_preimage"].encode("utf-8")).hexdigest()
    assert seed == recompute["seed_hex"]
    assert (
        fc.SeedStream.from_hex(seed).below(recompute["plan_count"]) + 1 == recompute["plan_number"]
    )
    blocked = [(e["giver"], e["receiver"]) for e in parsed["inputs_echo"]["forbidden"]]
    plan, number, count = enumeration_draw(
        parsed["inputs_echo"]["participants"], blocked, False, recompute["source_text"]
    )
    assert (number, count) == (recompute["plan_number"], recompute["plan_count"])
    names = parsed["inputs_echo"]["participants"]
    assert {names[i]: names[j] for i, j in enumerate(plan)} == parsed["result"]["assignments"]


def test_the_certificate_of_a_big_group_has_the_attempt_and_the_limit():
    parsed = json.loads(run_json(load_example("office_twelve.json"), "--json").stdout)
    recompute = parsed["certificate"]["recompute"]
    assert recompute["method"] == "rejection" and recompute["attempts"] == 2
    assert recompute["max_attempts"] == ge.MAX_ATTEMPTS
    assert recompute["plan_count"] is None and recompute["plan_number"] is None
    assert recompute["algorithm"].startswith(fc.SEED_SPEC)
    assert "After 20000 proposals the script reports an error" in recompute["algorithm"]
    assert parsed["result"]["rule"] == "gift_exchange_any_reject_v1"


def test_the_one_liner_of_each_person_is_their_private_message():
    parsed = json.loads(run_script("--demo", "--json").stdout)
    for giver, receiver in GOLDEN_PLAN.items():
        line = parsed["certificate"]["one_liner"][giver]
        assert line == f"你要送礼物给：{receiver}。"


def test_the_circle_is_in_the_json_output_for_the_way_ring():
    parsed = json.loads(run_json(six_people("ring"), "--json").stdout)
    assert parsed["result"]["circle"] == RING_CIRCLE
    assert parsed["result"]["rule"] == "gift_exchange_ring_enum_v1"


# What each reader sees


def blocks(text: str, lang: str) -> dict:
    """The private messages of a dm output, by the name of the person they are for."""
    heading = "发给" if lang == "zh" else "To"
    found = re.split(rf"^--- {heading} (.+) ---$", text, flags=re.MULTILINE)
    return dict(zip(found[1::2], found[2::2]))


@pytest.mark.parametrize(("label", "data"), DISTINCT, ids=DISTINCT_IDS)
@pytest.mark.parametrize("lang", ["zh", "en"])
def test_a_private_message_names_only_the_receiver_of_its_person(label, data, lang):
    out = run_json(data, "--format", "dm", "--lang", lang).stdout
    result = json.loads(run_json(data, "--json").stdout)["result"]["assignments"]
    messages = blocks(out, lang)
    assert sorted(messages) == sorted(data["people"]), "one message per person"
    for giver, body in messages.items():
        named = {name for name in data["people"] if name in body}
        assert named == {result[giver]}, f"{giver}: {named}"


def group_text_without_the_names(data: dict, lang: str) -> str:
    out = run_json(data, "--format", "group", "--lang", lang).stdout
    prefix = "名单：" if lang == "zh" else "Names: "
    return "\n".join(line for line in out.splitlines() if not line.startswith(prefix))


@pytest.mark.parametrize(("label", "data"), DISTINCT, ids=DISTINCT_IDS)
@pytest.mark.parametrize("lang", ["zh", "en"])
def test_the_group_card_names_everybody_in_one_line_and_nobody_elsewhere(label, data, lang):
    rest = group_text_without_the_names(data, lang)
    for name in data["people"]:
        assert name not in rest, f"{name} is named outside the list of names"


@pytest.mark.parametrize(("label", "data"), CASES, ids=IDS)
@pytest.mark.parametrize("lang", ["zh", "en"])
def test_the_group_card_holds_back_what_would_let_a_reader_work_out_the_pairing(label, data, lang):
    out = run_json(data, "--format", "group", "--lang", lang).stdout
    result = json.loads(run_json(data, "--json").stdout)["result"]
    for held_back in (result["seed_hex"], result["seed_preimage"], result["source_text"]):
        assert held_back not in out
    if result["plan_number"] is not None:
        number = result["plan_number"]
        assert f"第 {number} 种" not in out and f"number {number}" not in out
    assert "→" not in out and "->" not in out, "no arrow from a giver to a receiver"


def test_the_group_card_says_the_way_of_drawing_is_public_and_can_be_recomputed():
    zh = run_script("--demo", "--format", "group").stdout
    en = run_script("--demo", "--format", "group", "--lang", "en").stdout
    assert "抽法公开、可复算" in zh
    assert "public and can be recomputed" in en
    assert "等礼物交换完再公布" in zh
    assert "published after the exchange" in en


def test_the_group_card_gives_the_number_of_legal_plans_and_the_count_of_exclusions():
    zh = run_script("--demo", "--format", "group").stdout
    assert "合法方案共 96 种" in zh
    assert "不能互送的规则：共 5 条" in zh
    en = run_script("--demo", "--format", "group", "--lang", "en").stdout
    assert "There are 96 legal plans" in en and "Exclusions: 5 in all" in en


def test_the_group_card_leaves_out_the_exclusion_line_when_there_are_none():
    zh = run_json(exchange_data(PEOPLE6, []), "--format", "group").stdout
    assert "不能互送的规则：共" not in zh


def test_the_group_card_of_a_big_group_says_plans_are_proposed_not_listed():
    zh = run_script("--input", str(EXAMPLES / "office_twelve.json"), "--format", "group").stdout
    assert "人数超过 9，不逐个枚举" in zh and "合法方案共" not in zh


def test_the_md_output_holds_the_whole_table_and_everything_for_recomputing():
    out = run_script("--demo").stdout
    for giver, receiver in GOLDEN_PLAN.items():
        assert f"| {giver} | {receiver} |" in out
    for needed in (SOURCE, GOLDEN_SEED, "gift_exchange_any_enum_v1", "第 13 种（共 96 种）"):
        assert needed in out
    assert "运行这个脚本的人（包括这次会话）会看到全表" in out
    assert "礼物交换完之后再公布" in out


def test_the_md_output_of_a_circle_shows_the_order_of_the_circle():
    out = run_json(six_people("ring")).stdout
    assert " → ".join([*RING_CIRCLE, RING_CIRCLE[0]]) in out
    assert "任意错排允许两个人互送" not in out, "the warning about swaps is for the way any"


def test_the_md_output_warns_that_two_people_may_give_to_each_other_in_the_way_any():
    out = run_script("--demo").stdout
    assert "任意错排允许两个人互送" in out
    two = run_json(exchange_data(["a", "b"], [])).stdout
    assert "任意错排允许两个人互送" not in two, "with two people there is nothing to warn about"
    three = run_json(exchange_data(THREE, [])).stdout
    assert "任意错排允许两个人互送" not in three, "three people cannot split into a pair"


def test_the_dm_output_has_a_note_for_the_organizer_and_one_block_per_person():
    out = run_script("--demo", "--format", "dm").stdout
    assert out.startswith("（给组织者：下面每一段只私发给对应的人，不要贴到群里。）")
    assert out.count("--- 发给 ") == 6
    for giver, receiver in GOLDEN_PLAN.items():
        assert f"--- 发给 {giver} ---\n你要送礼物给：{receiver}。\n" in out


def test_the_dm_text_of_a_circle_says_that_everybody_is_in_one_circle_without_names():
    out = run_json(six_people("ring"), "--format", "dm").stdout
    assert out.count("这次是「一圈传下去」") == 6
    assert "这次是「一圈传下去」：所有人连成一个圈，每个人只送给圈里的下一个人。" in out


def test_the_english_dm_text():
    out = run_script("--demo", "--format", "dm", "--lang", "en").stdout
    assert "--- To Coco ---\nYou give a gift to: Yuki." in out
    assert "Do not tell anyone before the exchange." in out


@pytest.mark.parametrize("lang", ["zh", "en"])
@pytest.mark.parametrize("fmt", ["md", "dm", "group"])
def test_nothing_overclaims(lang, fmt):
    out = run_script("--demo", "--format", fmt, "--lang", lang).stdout.lower()
    for phrase in OVERCLAIMS:
        assert phrase.lower() not in out, phrase


def test_the_not_modeled_list_says_who_sees_the_table_and_what_cannot_be_checked():
    parsed = json.loads(run_script("--demo", "--json").stdout)
    text = " ".join(parsed["not_modeled"])
    assert "脚本核对不了" in text and "运行脚本的人看到全表" in text
    assert "任意错排允许两个人互送" in text


# Language


def test_english_output_has_no_chinese_text_when_the_input_has_none():
    data = exchange_data(
        LATIN,
        [{"pair": ["Ann", "Bob"]}],
        source="published numbers of the draw on 8 November (made up)",
        rules={"source_description": "a made-up public draw", "deadline": "7 November, 8 pm"},
    )
    for flags in ([], ["--format", "dm"], ["--format", "group"], ["--check"]):
        out = run_json(data, "--lang", "en", *flags).stdout
        assert CJK.search(out) is None, (flags, CJK.search(out))


def latinize(text: str) -> str:
    """The text with every run of Chinese characters turned into a Latin token (Qa, Qb, ...)."""
    tokens: dict[str, str] = {}

    def token(match: re.Match) -> str:
        run = match.group(0)
        if run not in tokens:
            index = len(tokens)
            tokens[run] = "Q" + chr(97 + index % 26) + (str(index // 26) if index >= 26 else "")
        return tokens[run]

    return CJK_RUN.sub(token, text)


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.json")), ids=lambda path: path.name)
def test_latin_names_never_touch_a_chinese_character_in_the_check_output(path):
    """The plain runs of every example are covered by tests/test_shared_behaviour.py."""
    text = latinize(path.read_text(encoding="utf-8"))
    done = run_script("--input", "-", "--check", stdin=text)
    assert done.returncode == 0, done.stderr
    found = TOUCHING.search(done.stdout)
    assert found is None, done.stdout[max(found.start() - 20, 0) : found.end() + 20]


def test_latin_names_do_not_touch_a_chinese_character_in_the_error_message_either():
    data = exchange_data(["Qa", "Qb", "Qc"], [{"pair": ["Qa", "Qb"]}])
    done = run_json(data)
    assert done.returncode == 3
    assert TOUCHING.search(done.stderr) is None, done.stderr
    assert "Qa、Qb 这 2 个人能送的只有 Qc（1 人）" in done.stderr


# --check


def test_check_prints_the_conclusion_and_the_count_in_both_languages():
    zh = run_script("--demo", "--check").stdout
    assert "有合法方案" in zh and "| 合法方案总数 | 96 |" in zh
    assert "不需要随机源" in zh
    en = run_script("--demo", "--check", "--lang", "en").stdout
    assert "a legal plan exists" in en and "| Number of legal plans | 96 |" in en


def test_check_of_the_recorded_three_people_is_a_failure_with_no_output():
    done = run_json(exchange_data(THREE, THREE_FORBIDDEN), "--check")
    assert done.returncode == 3 and done.stdout == ""


def test_the_reproduce_line_names_the_options_that_were_used():
    parsed = json.loads(run_script("--demo", "--check", "--json", "--lang", "en").stdout)
    assert parsed["reproduce"] == "python3 scripts/gift_exchange.py --demo --check --json --lang en"
    done = run_json(six_people())
    assert done.stdout.rstrip().endswith(
        "python3 scripts/gift_exchange.py --input - --format md\n```"
    )


# --delete-input


def write(folder, data):
    path = folder / "input.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_an_input_with_no_legal_draw_is_deleted_too(tmp_path):
    path = write(tmp_path, exchange_data(THREE, THREE_FORBIDDEN))
    done = run_script("--input", str(path), "--delete-input")
    assert done.returncode == 3
    assert not path.exists()


def test_check_deletes_the_file_as_well(tmp_path):
    path = write(tmp_path, six_people())
    done = run_script("--input", str(path), "--delete-input", "--check")
    assert done.returncode == 0 and not path.exists()


def test_help_lists_the_options_and_the_exit_codes():
    text = " ".join(run_script("--help").stdout.split())
    for option in ("--input", "--delete-input", "--format", "--json", "--demo", "--selftest"):
        assert option in text
    for option in ("--lang", "--check"):
        assert option in text
    assert (
        "Exit code 0 means success" in text and "3 no legal draw exists or none was found" in text
    )


def test_selftest_passes_and_names_the_recorded_checks():
    done = run_script("--selftest")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "0 failed" in done.stdout
    assert "golden draw" in done.stdout and "96 legal plans and 40 circles" in done.stdout
