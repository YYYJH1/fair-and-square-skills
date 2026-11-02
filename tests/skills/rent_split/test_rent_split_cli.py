"""The rent-split script as a program: options, exit codes, formats, demo, examples, commitments.

Every run uses ``python -B -S``, so the script must work without any installed package.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time

import pytest
from rent_split_support import (
    EXAMPLES,
    GOLDEN,
    NO_NON_NEGATIVE_BIDS,
    NO_NON_NEGATIVE_ROOMS,
    SCRIPT,
    dumps,
    four_roommates,
    load_script,
    make_input,
    run_script,
)

rs = load_script()
fc = rs.fc

NONCE = "00112233445566778899aabbccddeeff"
ORGANIZER_DIGEST = "6ea1ffc78ecc8af6f20b004156b7815d7554f3ac5bbccd704222e26123a30227"


def run_json(data, *args):
    return run_script(*args, "--input", "-", stdin=dumps(data))


def example(name):
    return (EXAMPLES / f"{name}.json").read_text(encoding="utf-8")


# --------------------------------------------------------------------------------------
# Options and help
# --------------------------------------------------------------------------------------


def test_help_lists_every_option():
    done = run_script("--help")
    assert done.returncode == 0
    for option in (
        "--input",
        "--format",
        "--json",
        "--demo",
        "--selftest",
        "--audit",
        "--lang",
        "--commit",
        "--verify-commit",
        "--person",
        "--nonce",
    ):
        assert re.search(rf"(?<![\w-]){re.escape(option)}(?![\w-])", done.stdout), option
    assert "Exit code 0 means success" in done.stdout


def test_selftest_passes_and_says_so():
    done = run_script("--selftest")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "0 failed" in done.stdout
    assert "ok   rent: four roommates" in done.stdout


def test_running_without_input_is_an_input_error():
    done = run_script()
    assert done.returncode == 2
    assert 'field "input"' in done.stderr


@pytest.mark.parametrize(
    "args",
    [
        ("--demo", "--selftest"),
        ("--commit", "--verify-commit", "x"),
        ("--person", "阿明"),
        ("--nonce", NONCE),
    ],
)
def test_conflicting_options_are_rejected(args):
    done = run_script(*args)
    assert done.returncode == 2
    assert 'field "options"' in done.stderr


def test_an_unknown_format_is_a_usage_error():
    done = run_script("--format", "html", "--demo")
    assert done.returncode == 2
    assert "invalid choice" in done.stderr


# --------------------------------------------------------------------------------------
# Exit code 2: invalid input names the field
# --------------------------------------------------------------------------------------


def bad(change):
    data = four_roommates()
    change(data)
    return data


INVALID = [
    ("no rules", lambda d: d.pop("rules"), "rules.negative_rent"),
    ("no negative_rent", lambda d: d["rules"].clear(), "rules.negative_rent"),
    ("bad rule", lambda d: d["rules"].update(negative_rent="maybe"), "rules.negative_rent"),
    ("unknown rule field", lambda d: d["rules"].update(tie="x"), "rules.tie"),
    ("blank source", lambda d: d["rules"].update(random_source="  "), "rules.random_source"),
    ("unknown field", lambda d: d.update(bid=1), "bid"),
    ("no total", lambda d: d.pop("total_rent"), "total_rent"),
    ("zero total", lambda d: d.update(total_rent=0), "total_rent"),
    ("three decimals", lambda d: d.update(total_rent="8000.005"), "total_rent"),
    ("one room", lambda d: d.update(rooms=["only"]), "rooms"),
    ("duplicate room", lambda d: d.update(rooms=["a", "a", "b", "c"]), "rooms[1]"),
    ("21 rooms", lambda d: d.update(rooms=[f"r{k}" for k in range(21)]), "rooms"),
    ("no bids", lambda d: d.pop("bids"), "bids"),
    ("too many people", lambda d: d["bids"].update(Zed=[1, 2, 3, 4]), "bids"),
    ("short row", lambda d: d["bids"].update(阿明=[3000, 2200, 1600]), "bids.阿明"),
    ("negative bid", lambda d: d["bids"]["阿明"].__setitem__(1, -5), "bids.阿明[1]"),
    ("cent fraction", lambda d: d["bids"]["小红"].__setitem__(0, "12.345"), "bids.小红[0]"),
    ("text bid", lambda d: d["bids"]["大刘"].__setitem__(2, "lots"), "bids.大刘[2]"),
    ("true bid", lambda d: d["bids"]["Coco"].__setitem__(3, True), "bids.Coco[3]"),
    ("padded name", lambda d: d["bids"].update({" 老王": [1, 2, 3, 4]}), "bids"),
    (
        "audit room missing",
        lambda d: d.update(audit={"assignment": {}, "rent": {}}),
        "audit.assignment.阿明",
    ),
    (
        "audit unknown room",
        lambda d: d.update(
            audit={
                "assignment": dict.fromkeys(["阿明", "小红", "大刘", "Coco"], "阁楼"),
                "rent": dict.fromkeys(["阿明", "小红", "大刘", "Coco"], 2000),
            }
        ),
        "audit.assignment.阿明",
    ),
    (
        "audit room twice",
        lambda d: d.update(
            audit={
                "assignment": dict.fromkeys(["阿明", "小红", "大刘", "Coco"], "小书房"),
                "rent": dict.fromkeys(["阿明", "小红", "大刘", "Coco"], 2000),
            }
        ),
        "audit.assignment",
    ),
    (
        "audit rents do not add up",
        lambda d: d.update(
            audit={
                "assignment": {
                    "阿明": "小书房",
                    "小红": "南次卧",
                    "大刘": "主卧带卫",
                    "Coco": "北次卧",
                },
                "rent": dict.fromkeys(["阿明", "小红", "大刘", "Coco"], 1999),
            }
        ),
        "audit.rent",
    ),
    (
        "audit unknown field",
        lambda d: d.update(audit={"assignment": {}, "rent": {}, "note": 1}),
        "audit.note",
    ),
]


@pytest.mark.parametrize(("label", "change", "field"), INVALID, ids=[row[0] for row in INVALID])
def test_invalid_input_exits_2_and_names_the_field(label, change, field):
    done = run_json(bad(change), "--audit")
    assert done.returncode == 2, label
    assert done.stdout == ""
    assert f'field "{field}"' in done.stderr, done.stderr


@pytest.mark.parametrize("text", ["", "hello", "[1, 2]", "null", '{"total_rent": NaN}', "{'a': 1}"])
def test_text_that_is_not_a_json_object_exits_2(text):
    done = run_script("--input", "-", stdin=text)
    assert done.returncode == 2
    assert 'field "input"' in done.stderr or 'field "total_rent"' in done.stderr


def test_a_duplicate_key_is_rejected():
    text = '{"total_rent": 8000, "total_rent": 9000}'
    done = run_script("--input", "-", stdin=text)
    assert done.returncode == 2
    assert "duplicate key" in done.stderr


def test_a_missing_input_file_is_an_input_error(tmp_path):
    done = run_script("--input", str(tmp_path / "nope.json"))
    assert done.returncode == 2
    assert "cannot read" in done.stderr


def test_audit_flag_without_a_block_exits_2():
    done = run_json(four_roommates(), "--audit")
    assert done.returncode == 2
    assert 'field "audit"' in done.stderr


SURROGATE_INPUT = (
    '{"total_rent": 100, "rooms": ["a", "%s"], "bids": {"x": [50, 50], "%s": [60, 40]},'
    ' "rules": {"negative_rent": "allow"}}'
)


@pytest.mark.parametrize(
    ("room", "person", "field"),
    [
        ("\\ud800", "y", "rooms[1]"),
        ("b", "y\\ud800", r"bids.y\ud800"),
    ],
    ids=["room", "person"],
)
def test_a_lone_surrogate_in_a_name_is_rejected_not_a_crash(room, person, field):
    done = run_script("--input", "-", stdin=SURROGATE_INPUT % (room, person))
    assert done.returncode == 2
    assert done.stdout == ""
    assert done.stderr == (
        f'error: invalid input, field "{field}": contains an invalid character (unpaired surrogate)\n'
    )


# --------------------------------------------------------------------------------------
# Exit code 3: the agreed rule has no solution
# --------------------------------------------------------------------------------------


def no_split_input(rule):
    return make_input(6000, NO_NON_NEGATIVE_ROOMS, NO_NON_NEGATIVE_BIDS, rule)


def test_forbid_without_a_solution_exits_3_with_both_languages():
    done = run_json(no_split_input("forbid"))
    assert done.returncode == 3
    assert done.stdout == ""
    assert "no solution" in done.stderr
    assert "forbid" in done.stderr
    assert "请全体重新报价" in done.stderr


def test_spliddit_falls_back_to_allow_on_the_same_bids():
    done = run_json(no_split_input("spliddit"), "--format", "group")
    assert done.returncode == 0
    assert "按规则改用允许倒贴" in done.stdout
    assert "甲 住 储物间，每月倒收 1,750.00" in done.stdout
    allowed = run_json(no_split_input("allow"), "--json")
    assert json.loads(allowed.stdout)["result"]["rule_applied"] == "negative_allowed"
    fallback = run_json(no_split_input("spliddit"), "--json")
    parsed = json.loads(fallback.stdout)["result"]
    assert parsed["rule_applied"] == "negative_allowed_after_no_non_negative_solution"
    assert parsed["rent_cents"] == json.loads(allowed.stdout)["result"]["rent_cents"]


# --------------------------------------------------------------------------------------
# Formats
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["four_roommates", "storage_room", "audit_equal_split"])
@pytest.mark.parametrize("fmt", ["md", "dm", "group"])
def test_every_example_renders_in_every_format(name, fmt):
    done = run_script("--input", str(EXAMPLES / f"{name}.json"), "--format", fmt)
    assert done.returncode == 0, done.stderr
    assert done.stderr == ""
    assert done.stdout.endswith("\n")
    assert "Traceback" not in done.stdout
    assert "000000" not in done.stdout  # no stray unformatted amounts


@pytest.mark.parametrize("name", ["four_roommates", "storage_room", "audit_equal_split"])
def test_every_example_has_the_json_envelope(name):
    done = run_script("--input", str(EXAMPLES / f"{name}.json"), "--json")
    assert done.returncode == 0
    parsed = json.loads(done.stdout, parse_float=lambda text: pytest.fail(text))
    assert sorted(parsed) == ["certificate", "inputs_echo", "not_modeled", "reproduce", "result"]
    for key in ("assignment", "rent_cents", "surplus_cents", "rule_applied", "shifted"):
        assert key in parsed["result"]
    for key in ("envy_table", "one_liner", "ties"):
        assert key in parsed["certificate"]
    assert all(isinstance(text, str) for text in parsed["not_modeled"])


@pytest.mark.parametrize(
    ("args", "command"),
    [
        (["--demo"], "python3 scripts/rent_split.py --demo --json"),
        (["--demo", "--lang", "en"], "python3 scripts/rent_split.py --demo --json --lang en"),
        (["--input", "-"], "python3 scripts/rent_split.py --input - --json"),
        (["--input", "-", "--audit"], "python3 scripts/rent_split.py --input - --json --audit"),
    ],
)
def test_the_reproduce_command_names_the_options_of_the_run(args, command):
    done = run_script(*args, "--json", stdin=example("audit_equal_split"))
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["reproduce"] == command


def test_the_reproduce_section_of_the_markdown_shows_the_command_of_the_run():
    done = run_script("--demo")
    assert "```\npython3 scripts/rent_split.py --demo --format md\n```" in done.stdout


def test_the_stdin_form_and_the_file_form_print_the_same_bytes():
    path = EXAMPLES / "four_roommates.json"
    from_file = run_script("--input", str(path))
    from_stdin = run_script("--input", "-", stdin=path.read_text(encoding="utf-8"))
    assert from_file.stdout == from_stdin.stdout != ""


def test_decimal_strings_numbers_and_trailing_zeros_all_mean_the_same_bid():
    plain = run_json(four_roommates(), "--json")
    text = json.dumps(four_roommates(), ensure_ascii=False)
    text = text.replace("3000", '"3000.00"').replace("8000", "8000.0")
    other = run_script("--input", "-", "--json", stdin=text)
    assert plain.returncode == other.returncode == 0
    assert json.loads(plain.stdout)["result"] == json.loads(other.stdout)["result"]


def test_chinese_output_survives_a_c_locale():
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    env.update({"LC_ALL": "C", "LANG": "C", "PYTHONDONTWRITEBYTECODE": "1"})
    env.pop("PYTHONIOENCODING", None)
    done = subprocess.run(
        [sys.executable, "-B", "-S", str(SCRIPT), "--demo", "--format", "group"],
        env=env,
        capture_output=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert "阿明 住 小书房，每月付 950.00".encode() in done.stdout


def test_the_markdown_output_keeps_to_the_documented_sections():
    done = run_script("--input", str(EXAMPLES / "four_roommates.json"))
    headings = re.findall(r"^#+ .*$", done.stdout, re.MULTILINE)
    assert headings == [
        "# 分房租结果（总租金 8,000.00）",
        "## 谁住哪间、付多少",
        "## 羡慕表（报价 - 房租，带 * 的是本人房间，数越大越划算）",
        "## 本结果不包含",
        "## 复算命令",
    ]


def test_twenty_people_are_solved_quickly_and_exactly():
    n = 20
    rooms = [f"room{k:02d}" for k in range(n)]
    bids = {}
    for i in range(n):
        weights = [((i * 7 + k * 13) % 11) ** 2 + 1 for k in range(n)]
        row = [200000 * w // sum(weights) for w in weights]
        row[0] += 200000 - sum(row)
        bids[f"person{i:02d}"] = row
    start = time.monotonic()
    done = run_json(make_input(200000, rooms, bids, "spliddit"), "--json")
    assert done.returncode == 0, done.stderr
    assert time.monotonic() - start < 60
    parsed = json.loads(done.stdout)
    assert sum(float(v) for v in parsed["result"]["rent_cents"].values()) == pytest.approx(200000)
    assert float(parsed["result"]["max_envy_cents"]) <= 0.01


# --------------------------------------------------------------------------------------
# The demo
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("flags", "name"),
    [
        ((), "demo_md_zh.txt"),
        (("--format", "dm"), "demo_dm_zh.txt"),
        (("--format", "group"), "demo_group_zh.txt"),
        (("--json",), "demo_json.txt"),
        (("--lang", "en"), "demo_md_en.txt"),
        (("--format", "dm", "--lang", "en"), "demo_dm_en.txt"),
        (("--format", "group", "--lang", "en"), "demo_group_en.txt"),
        (("--json", "--lang", "en"), "demo_json_en.txt"),
    ],
)
def test_the_demo_is_byte_stable_and_matches_the_recorded_output(flags, name):
    first = run_script("--demo", *flags)
    second = run_script("--demo", *flags)
    assert first.returncode == 0
    assert first.stdout == second.stdout
    if os.environ.get("FSQ_UPDATE_GOLDEN") == "1":
        (GOLDEN / name).write_text(first.stdout, encoding="utf-8", newline="\n")
    assert first.stdout == (GOLDEN / name).read_text(encoding="utf-8"), (
        f"{name} differs from the stored copy. If the change is intended, rerun with "
        "FSQ_UPDATE_GOLDEN=1 and review the diff."
    )


def test_the_demo_reproduces_the_numbers_of_the_worked_examples():
    text = run_script("--demo").stdout
    for line in (
        "| 阿明 | 小书房 | 950.00 | 1,200.00 | 250.00 |",
        "| 小红 | 南次卧 | 2,250.00 | 2,500.00 | 250.00 |",
        "| 大刘 | 主卧带卫 | 3,150.00 | 3,400.00 | 250.00 |",
        "| Coco | 北次卧 | 1,650.00 | 2,000.00 | 350.00 |",
        "现在每月多掏 1,050.00",
        "| 甲 | 大主卧，付 3,533.33，赚 1,266.67 | 大主卧，付 3,000.00，赚 1,800.00 |",
        "| 丙 | 储物间改的小间，付 -1,066.66，赚 1,266.66 | 储物间改的小间，付 0.00，赚 200.00 |",
    ):
        assert line in text, line


def test_the_demo_input_is_the_audit_example_and_the_storage_example():
    assert json.loads(rs.DEMO_JSON) == json.loads(example("audit_equal_split"))
    assert json.loads(rs.STORAGE_JSON) == json.loads(example("storage_room"))
    plain = json.loads(example("audit_equal_split"))
    plain.pop("audit")
    assert plain == json.loads(example("four_roommates"))


def test_the_demo_ignores_standard_input():
    assert run_script("--demo", stdin='{"not": "used"}').stdout == run_script("--demo").stdout


# --------------------------------------------------------------------------------------
# Commitments: the organizer goes first
# --------------------------------------------------------------------------------------

ORGANIZER_ROW = {
    "total_rent": 8000,
    "rooms": ["主卧带卫", "南次卧", "北次卧", "小书房"],
    "bids": {"阿明": [3000, 2200, 1600, 1200]},
}


def commit(data=None, *args):
    return run_json(ORGANIZER_ROW if data is None else data, "--commit", *args)


def test_a_commitment_with_a_fixed_nonce_has_a_fixed_code():
    done = commit(None, "--nonce", NONCE, "--json")
    assert done.returncode == 0
    parsed = json.loads(done.stdout)
    assert parsed["digest"] == ORGANIZER_DIGEST
    assert parsed["nonce"] == NONCE
    assert parsed["payload"] == {
        "bids": {"主卧带卫": 3000, "北次卧": 1600, "南次卧": 2200, "小书房": 1200},
        "person": "阿明",
        "total_rent": 8000,
    }
    # The digest can be recomputed by hand from the printed text, as the output explains.
    import hashlib

    body = json.dumps(parsed["payload"], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert (
        hashlib.sha256(f"fsq-commit-v1\n{NONCE}\n{body}".encode()).hexdigest() == ORGANIZER_DIGEST
    )


def test_each_commitment_gets_a_fresh_random_nonce_and_prints_three_lines_to_keep():
    first, second = commit(), commit()
    assert first.returncode == second.returncode == 0
    codes = [
        re.search(r"：([0-9a-f]{64})$", out.stdout, re.MULTILINE).group(1)
        for out in (first, second)
    ]
    nonces = [
        re.search(r"：([0-9a-f]{32})$", out.stdout, re.MULTILINE).group(1)
        for out in (first, second)
    ]
    assert codes[0] != codes[1]
    assert nonces[0] != nonces[1]
    assert "承诺码（现在就发到群里）" in first.stdout
    assert "自己保管" in first.stdout


def full_input(rooms=None, **overrides):
    data = four_roommates()
    if rooms is not None:
        order = [data["rooms"].index(room) for room in rooms]
        data["rooms"] = list(rooms)
        data["bids"] = {name: [row[k] for k in order] for name, row in data["bids"].items()}
    data.update(overrides)
    return data


def verify(data, digest=ORGANIZER_DIGEST, nonce=NONCE, person="阿明"):
    args = ["--verify-commit", digest, "--nonce", nonce, "--input", "-"]
    if person is not None:
        args += ["--person", person]
    return run_script(*args, stdin=dumps(data))


def test_the_revealed_row_matches_the_code():
    done = verify(full_input())
    assert done.returncode == 0
    assert done.stdout == "核对通过：阿明 的报价和盐与承诺码一致。\n"


def test_the_order_of_rooms_and_the_spelling_of_numbers_do_not_matter():
    data = full_input(rooms=["小书房", "北次卧", "南次卧", "主卧带卫"])
    data["bids"]["阿明"] = ["1200.00", 1600, "2200", 3000.0]
    assert verify(data).returncode == 0
    assert verify(data, digest=ORGANIZER_DIGEST.upper()).returncode == 0


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["bids"]["阿明"].__setitem__(1, 2201),
        lambda d: d.update(total_rent=8001),
        lambda d: d.update(rooms=["主卧带卫", "南次卧", "北次卧", "阁楼"]),
    ],
    ids=["a bid changed", "the total changed", "a room renamed"],
)
def test_a_changed_row_does_not_match_and_exits_1(change):
    data = full_input()
    change(data)
    if "阁楼" in data["rooms"]:
        data["bids"]["阿明"] = data["bids"]["阿明"]
    done = verify(data)
    assert done.returncode == 1
    assert "核对失败" in done.stdout


def test_the_wrong_nonce_or_the_wrong_person_does_not_match():
    assert verify(full_input(), nonce="f" * 32).returncode == 1
    assert verify(full_input(), person="小红").returncode == 1


def test_other_peoples_bids_do_not_affect_the_commitment():
    data = full_input()
    data["bids"]["小红"] = [8000, 0, 0, 0]
    assert verify(data).returncode == 0


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"person": None}, "--person"),
        ({"person": "老王"}, "--person"),
        ({"nonce": "xyz"}, "nonce"),
    ],
)
def test_a_verification_with_bad_arguments_exits_2(kwargs, field):
    done = verify(full_input(), **kwargs)
    assert done.returncode == 2
    assert field in done.stderr


def test_verify_json_reports_the_match():
    done = run_script(
        "--verify-commit", ORGANIZER_DIGEST, "--nonce", NONCE, "--person", "阿明", "--json",
        "--input", "-", stdin=dumps(full_input()),
    )  # fmt: skip
    assert json.loads(done.stdout) == {"match": True, "person": "阿明"}


def test_a_commitment_to_one_of_several_people_needs_a_name():
    done = commit(full_input(), "--nonce", NONCE)
    assert done.returncode == 2
    assert "--person" in done.stderr
    named = commit(full_input(), "--nonce", NONCE, "--person", "阿明", "--json")
    assert json.loads(named.stdout)["digest"] == ORGANIZER_DIGEST


def test_the_digest_needs_the_nonce_to_be_valid_hex_of_the_right_length():
    done = commit(None, "--nonce", "abc")
    assert done.returncode == 2
    assert "32 lowercase hex" in done.stderr


# --------------------------------------------------------------------------------------
# Private messages and the audit through the command line
# --------------------------------------------------------------------------------------


def test_the_private_messages_come_one_per_person_with_the_organizer_note():
    text = run_script("--input", str(EXAMPLES / "four_roommates.json"), "--format", "dm").stdout
    assert text.startswith("（给组织者：下面每一段只私发给对应的人，不要贴到群里。）")
    blocks = re.split(r"^--- 发给 (.+) ---$", text, flags=re.MULTILINE)
    names = blocks[1::2]
    assert names == ["阿明", "小红", "大刘", "Coco"]
    for name, body in zip(names, blocks[2::2]):
        assert f"{name}，这是只给你的分房租结果" in body
        assert "你的核对表" in body


def test_the_audit_appears_in_every_format():
    path = str(EXAMPLES / "audit_equal_split.json")
    md = run_script("--input", path, "--audit").stdout
    dm = run_script("--input", path, "--audit", "--format", "dm").stdout
    group = run_script("--input", path, "--audit", "--format", "group").stdout
    assert "多掏 1,050.00" in md
    assert "你现在每月多掏 1,050.00" in dm
    assert "阿明 住小书房：现在每月 2,000.00，按规则该付 950.00（多掏 1,050.00）" in group
    assert "1,800.00" not in group  # how much someone envies is private
    plain = run_script("--input", path).stdout
    assert "没有加 --audit" in plain
    assert "现在的分法体检" not in plain
