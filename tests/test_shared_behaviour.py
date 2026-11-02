"""Behaviour that all eight skill scripts share, checked on every script the same way.

An invalid input is reported in one wording whichever skill reads it: invalid UTF-8 on standard
input, a field that the skill does not know, and a name with an unpaired surrogate. Chinese text
puts a space between a Latin name and the Chinese words around it, and every script offers
``--lang en``. Every script also takes ``--delete-input``: it reads the ``--input`` file, deletes
it, and gives the same output as when the same text arrives on standard input. The scripts run as
programs, as the contract tests run them.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "plugin" / "skills"
SCRIPTS = {
    "rent-split": "rent_split.py",
    "bill-split": "bill_split.py",
    "ride-split": "ride_split.py",
    "slot-lottery": "slot_lottery.py",
    "group-vote": "group_vote.py",
    "chore-split": "chore_split.py",
    "gift-exchange": "gift_exchange.py",
    "stuff-split": "stuff_split.py",
}
CJK_RUN = re.compile(r"[㐀-鿿]+")
TOUCHING = re.compile(r"[A-Za-z0-9][㐀-鿿]|[㐀-鿿][A-Za-z0-9]")
UNKNOWN_FIELD = re.compile(
    r'error: invalid input, field "(?P<field>.+)": '
    r"is not a known field; allowed: (?P<allowed>[a-z_]+(?:, [a-z_]+)*)\n"
)
SURROGATE_MESSAGE = "contains an invalid character (unpaired surrogate)"


def run(skill: str, *args: str, stdin: bytes = b"") -> subprocess.CompletedProcess[bytes]:
    """Run a skill script like the contract tests do: no site-packages, no bytecode files."""
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    script = SKILLS / skill / "scripts" / SCRIPTS[skill]
    return subprocess.run(
        [sys.executable, "-B", "-S", str(script), *args],
        input=stdin,
        env=env,
        capture_output=True,
        timeout=120,
        check=False,
    )


def examples(skill: str) -> list[Path]:
    return sorted((SKILLS / skill / "examples").glob("*.json"))


def load(skill: str, name: str) -> Any:
    return json.loads((SKILLS / skill / "examples" / name).read_text(encoding="utf-8"))


def feed(skill: str, data: Any, *args: str) -> subprocess.CompletedProcess[bytes]:
    return run(skill, "--input", "-", *args, stdin=json.dumps(data).encode("utf-8"))


# --------------------------------------------------------------------------------------
# Standard input that is not UTF-8
# --------------------------------------------------------------------------------------

NOT_UTF8 = [
    ("rent-split", ()),
    ("rent-split", ("--commit",)),
    ("rent-split", ("--verify-commit", "00", "--nonce", "0" * 32)),
    ("bill-split", ()),
    ("ride-split", ()),
    ("slot-lottery", ()),
    ("slot-lottery", ("--verify",)),
    ("group-vote", ()),
    ("chore-split", ()),
    ("gift-exchange", ()),
    ("stuff-split", ()),
]


@pytest.mark.parametrize(
    ("skill", "extra"),
    NOT_UTF8,
    ids=[f"{skill} {' '.join(extra)}".strip() for skill, extra in NOT_UTF8],
)
def test_standard_input_that_is_not_utf8_is_an_input_error(skill, extra):
    done = run(skill, "--input", "-", *extra, stdin=b'{"name": "\xff\xfe"}')
    assert done.returncode == 2
    assert done.stdout == b""
    assert done.stderr == b'error: invalid input, field "input": is not valid UTF-8\n'


# --------------------------------------------------------------------------------------
# A field that the skill does not know
# --------------------------------------------------------------------------------------

# (skill, example, path of an object in the example). The object gets a field "zzz".
UNKNOWN_FIELD_PLACES = [
    ("rent-split", "audit_equal_split.json", ""),
    ("rent-split", "audit_equal_split.json", "rules"),
    ("rent-split", "audit_equal_split.json", "audit"),
    ("bill-split", "audit_aa.json", ""),
    ("bill-split", "audit_aa.json", "audit"),
    ("bill-split", "audit_aa.json", "rules"),
    ("bill-split", "audit_aa.json", "expenses[0]"),
    ("bill-split", "audit_aa.json", "expenses[0].items[0]"),
    ("bill-split", "audit_aa.json", "expenses[0].fees[0]"),
    ("bill-split", "group_order_coupon.json", ""),
    ("bill-split", "group_order_coupon.json", "items[0]"),
    ("bill-split", "group_order_coupon.json", "coupons[0]"),
    ("bill-split", "group_order_takeout.json", "fees[0]"),
    ("ride-split", "meter_four_riders.json", ""),
    ("ride-split", "meter_four_riders.json", "rules"),
    ("ride-split", "general_detour.json", "tariff"),
    ("slot-lottery", "commit_reveal.json", ""),
    ("slot-lottery", "commit_reveal.json", "rules"),
    ("slot-lottery", "commit_reveal.json", "commit_reveal"),
    ("group-vote", "team_outing_27.json", ""),
    ("group-vote", "team_outing_27.json", "rules"),
    ("group-vote", "team_outing_27.json", "rules.tie_break"),
    ("group-vote", "team_outing_27.json", "ballots[0]"),
    ("chore-split", "cannot_cook.json", ""),
    ("chore-split", "cannot_cook.json", "rules"),
    ("chore-split", "cannot_cook.json", "chores[0]"),
    ("gift-exchange", "six_with_couples.json", ""),
    ("gift-exchange", "six_with_couples.json", "rules"),
    ("gift-exchange", "six_with_couples.json", "forbidden[0]"),
    ("gift-exchange", "six_with_couples.json", "forbidden[2]"),
    ("stuff-split", "three_roommates.json", ""),
    ("stuff-split", "three_roommates.json", "rules"),
    ("stuff-split", "weighted_knaster.json", "rules"),
]


def object_at(data: Any, path: str) -> dict[str, Any]:
    """The object at a path such as rules.tie_break or expenses[0].items[1], created if missing."""
    node = data
    for step in filter(None, re.split(r"\.|(?=\[)", path)):
        if step.startswith("["):
            node = node[int(step[1:-1])]
        else:
            node = node.setdefault(step, {})
    return node


@pytest.mark.parametrize(
    ("skill", "example", "path"),
    UNKNOWN_FIELD_PLACES,
    ids=[
        f"{skill} {example} {path or 'top level'}" for skill, example, path in UNKNOWN_FIELD_PLACES
    ],
)
def test_an_unknown_field_is_refused_in_one_wording(skill, example, path):
    data = load(skill, example)
    node = object_at(data, path)
    present = set(node)
    node["zzz"] = 1
    done = feed(skill, data)
    assert done.returncode == 2, done.stderr
    assert done.stdout == b""
    found = UNKNOWN_FIELD.fullmatch(done.stderr.decode("utf-8"))
    assert found, done.stderr
    assert found["field"] == (f"{path}.zzz" if path else "zzz")
    allowed = found["allowed"].split(", ")
    assert "zzz" not in allowed
    assert present <= set(allowed), present - set(allowed)


# --------------------------------------------------------------------------------------
# A name that cannot be written as UTF-8
# --------------------------------------------------------------------------------------


def lone(name: str) -> str:
    return name + "\ud800"


def rename_key(mapping: dict[str, Any], old: str, new: str) -> dict[str, Any]:
    return {(new if key == old else key): value for key, value in mapping.items()}


def edit_room(data):
    data["rooms"][1] = lone(data["rooms"][1])


def edit_person(data):
    data["bids"] = rename_key(data["bids"], "Coco", lone("Coco"))


def edit_rider(data):
    data["riders"][0] = lone(data["riders"][0])


def edit_ride_id(data):
    data["ride_id"] = lone("ride-1")


def edit_first_person(data):
    data["people"][0] = lone(data["people"][0])


def edit_option(data):
    data["options"][0] = lone(data["options"][0])


def edit_expense_id(data):
    data["expenses"][0]["id"] = lone(data["expenses"][0]["id"])


def edit_expense_what(data):
    data["expenses"][0]["what"] = lone(data["expenses"][0]["what"])


def edit_item_name(data):
    item = data["expenses"][0]["items"][0]
    item["name"] = lone(item["name"])


def edit_fee_name(data):
    fee = data["expenses"][0]["fees"][0]
    fee["name"] = lone(fee["name"])


def edit_discount_name(data):
    expense = data["expenses"][0]
    expense["discounts"] = [{"name": lone("优惠"), "amount": 10, "split": "equal"}]
    expense["paid_by"] = {"阿明": 670}  # the bill stays consistent, so only the name is wrong


def edit_order_id(data):
    data["id"] = lone(data["id"])


def edit_buyer(data):
    data["items"][0]["who"] = lone(data["items"][0]["who"])


def edit_dish_name(data):
    data["items"][0]["name"] = lone(data["items"][0]["name"])


def edit_order_fee_name(data):
    data["fees"][0]["name"] = lone(data["fees"][0]["name"])


def edit_coupon_name(data):
    data["coupons"][0]["name"] = lone(data["coupons"][0]["name"])


def edit_payer(data):
    data["paid_by"] = lone(data["paid_by"])


def edit_payer_key(data):
    data["paid_by"] = {lone("阿明"): 49}  # the order of the takeout example comes to 49.00


def edit_stuff_item(data):
    data["items"][0] = lone(data["items"][0])


def edit_note(data):
    data["note"] = lone("备注")


def edit_random_source(data):
    data["rules"]["random_source"] = lone("某一期")


SURROGATES = [
    ("rent-split", "audit_equal_split.json", edit_room, "rooms[1]"),
    ("rent-split", "audit_equal_split.json", edit_person, r"bids.Coco\ud800"),
    ("bill-split", "audit_aa.json", edit_first_person, "people[0]"),
    ("bill-split", "audit_aa.json", edit_expense_id, "expenses[0].id"),
    ("bill-split", "audit_aa.json", edit_expense_what, "expenses[0].what"),
    ("bill-split", "audit_aa.json", edit_item_name, "expenses[0].items[0].name"),
    ("bill-split", "audit_aa.json", edit_fee_name, "expenses[0].fees[0].name"),
    ("bill-split", "audit_aa.json", edit_discount_name, "expenses[0].discounts[0].name"),
    ("bill-split", "group_order_takeout.json", edit_order_id, "id"),
    ("bill-split", "group_order_takeout.json", edit_buyer, "items[0].who"),
    ("bill-split", "group_order_takeout.json", edit_dish_name, "items[0].name"),
    ("bill-split", "group_order_takeout.json", edit_order_fee_name, "fees[0].name"),
    ("bill-split", "group_order_takeout.json", edit_coupon_name, "coupons[0].name"),
    ("bill-split", "group_order_coupon.json", edit_payer, "paid_by"),
    ("bill-split", "group_order_takeout.json", edit_payer_key, r"paid_by.阿明\ud800"),
    ("ride-split", "meter_four_riders.json", edit_rider, "riders[0]"),
    ("ride-split", "meter_four_riders.json", edit_ride_id, "ride_id"),
    ("slot-lottery", "tickets_8_for_3.json", edit_first_person, "people[0]"),
    ("group-vote", "team_outing_27.json", edit_option, "options[0]"),
    ("chore-split", "three_roommates.json", edit_first_person, "people[0]"),
    ("gift-exchange", "six_with_couples.json", edit_first_person, "people[0]"),
    ("stuff-split", "three_roommates.json", edit_first_person, "people[0]"),
    ("stuff-split", "three_roommates.json", edit_stuff_item, "items[0]"),
    ("stuff-split", "three_roommates.json", edit_note, "note"),
    ("stuff-split", "three_roommates.json", edit_random_source, "rules.random_source"),
]


@pytest.mark.parametrize(
    ("skill", "example", "edit", "field"),
    SURROGATES,
    ids=[f"{skill} {field}" for skill, _, _, field in SURROGATES],
)
def test_a_name_with_an_unpaired_surrogate_is_refused_in_one_wording(skill, example, edit, field):
    data = load(skill, example)
    edit(data)
    done = feed(skill, data)
    assert done.returncode == 2, done.stderr
    assert done.stdout == b""
    assert done.stderr.decode("utf-8") == (
        f'error: invalid input, field "{field}": {SURROGATE_MESSAGE}\n'
    )


# --------------------------------------------------------------------------------------
# Latin names inside Chinese text
# --------------------------------------------------------------------------------------

LATIN_RUNS = [(skill, path) for skill in SCRIPTS for path in examples(skill)]


def latinize(text: str) -> str:
    """The example with every run of Chinese characters turned into a Latin token (Qa, Qb, ...)."""
    tokens: dict[str, str] = {}

    def token(match: re.Match[str]) -> str:
        run_ = match.group(0)
        if run_ not in tokens:
            index = len(tokens)
            tokens[run_] = "Q" + chr(97 + index % 26) + (str(index // 26) if index >= 26 else "")
        return tokens[run_]

    return CJK_RUN.sub(token, text)


def flag_sets(skill: str, text: str) -> list[list[str]]:
    """The flags to try on an example besides the plain run.

    --audit exists in some scripts only, and a script refuses a flag it does not have with exit
    code 2, so that run is skipped. A vote also explains a result with every rule (--all-rules)
    and counts again without one option (--remove), alone and together. Those two print
    sentences that the plain run does not.
    """
    sets: list[list[str]] = [[], ["--audit"]]
    if skill == "group-vote":
        sets.append(["--all-rules"])
        for name in json.loads(text)["options"]:
            sets += [["--remove", name], ["--all-rules", "--remove", name]]
    return sets


@pytest.mark.parametrize(
    ("skill", "path"), LATIN_RUNS, ids=[f"{skill} {path.name}" for skill, path in LATIN_RUNS]
)
def test_latin_names_never_touch_a_chinese_character(skill, path):
    text = latinize(path.read_text(encoding="utf-8"))
    shown = 0
    for extra in flag_sets(skill, text):
        for fmt in ("md", "dm", "group"):
            done = run(skill, "--input", "-", "--format", fmt, *extra, stdin=text.encode("utf-8"))
            if done.returncode != 0:
                continue  # a format that this input cannot be shown in, for example dm without voters
            shown += 1
            output = done.stdout.decode("utf-8")
            found = TOUCHING.search(output)
            assert found is None, (
                fmt,
                extra,
                output[max(found.start() - 20, 0) : found.end() + 20],
            )
    assert shown >= 2


# --------------------------------------------------------------------------------------
# English output
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("skill", sorted(SCRIPTS))
def test_every_script_offers_english(skill):
    help_text = run(skill, "--help").stdout.decode("utf-8")
    assert re.search(r"(?<![\w-])--lang(?![\w-])", help_text)
    zh = run(skill, "--demo")
    en = run(skill, "--demo", "--lang", "en")
    assert zh.returncode == en.returncode == 0
    assert en.stdout != zh.stdout
    assert zh.stdout == run(skill, "--demo", "--lang", "zh").stdout


# --------------------------------------------------------------------------------------
# --delete-input
# --------------------------------------------------------------------------------------

# One valid input for each script. Rent-split and slot-lottery also run their other modes below.
DELETE_INPUT_EXAMPLES = {
    "rent-split": "four_roommates.json",
    "bill-split": "dinner_680.json",
    "ride-split": "meter_four_riders.json",
    "slot-lottery": "tickets_8_for_3.json",
    "group-vote": "team_outing_27.json",
    "chore-split": "three_roommates.json",
    "gift-exchange": "six_with_couples.json",
    "stuff-split": "three_roommates.json",
}
NO_STDIN_MESSAGE = (
    b'error: invalid input, field "--delete-input": '
    b"needs --input FILE (standard input leaves no file to delete)\n"
)
RENT_NONCE = "00112233445566778899aabbccddeeff"
LOTTERY_ORDER = ["Yuki", "小周", "大刘", "Coco", "小红", "阿明", "Mia", "老王"]


def write_input(folder: Path, data: Any, name: str = "input.json") -> tuple[Path, bytes]:
    """Write data as UTF-8 JSON into folder and return the path with the bytes written."""
    raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
    path = folder / name
    path.write_bytes(raw)
    return path, raw


@pytest.mark.parametrize("skill", sorted(SCRIPTS))
@pytest.mark.parametrize("output", [["--format", "md"], ["--format", "group"], ["--json"]])
def test_a_script_reads_the_file_deletes_it_and_prints_what_standard_input_gives(
    skill, output, tmp_path
):
    data = load(skill, DELETE_INPUT_EXAMPLES[skill])
    path, raw = write_input(tmp_path, data)
    by_file = run(skill, "--input", str(path), "--delete-input", *output)
    by_stdin = run(skill, "--input", "-", *output, stdin=raw)
    assert by_file.returncode == by_stdin.returncode == 0, by_file.stderr
    assert by_file.stdout == by_stdin.stdout != b""
    assert by_file.stderr == by_stdin.stderr == b""
    assert not path.exists()


@pytest.mark.parametrize("skill", sorted(SCRIPTS))
def test_an_input_the_script_rejects_is_deleted_too(skill, tmp_path):
    data = load(skill, DELETE_INPUT_EXAMPLES[skill])
    data["zzz"] = 1
    path, raw = write_input(tmp_path, data)
    by_file = run(skill, "--input", str(path), "--delete-input")
    by_stdin = run(skill, "--input", "-", stdin=raw)
    assert by_file.returncode == by_stdin.returncode == 2
    assert by_file.stdout == b"" and by_file.stderr == by_stdin.stderr
    assert UNKNOWN_FIELD.fullmatch(by_file.stderr.decode("utf-8"))
    assert not path.exists()


@pytest.mark.parametrize("skill", sorted(SCRIPTS))
def test_text_that_is_not_json_is_deleted_too(skill, tmp_path):
    path = tmp_path / "input.json"
    path.write_text("{not json", encoding="utf-8")
    done = run(skill, "--input", str(path), "--delete-input")
    assert done.returncode == 2 and done.stdout == b""
    assert done.stderr.decode("utf-8").startswith('error: invalid input, field "input": not valid')
    assert not path.exists()


@pytest.mark.parametrize("skill", sorted(SCRIPTS))
def test_the_file_is_single_use(skill, tmp_path):
    path, _ = write_input(tmp_path, load(skill, DELETE_INPUT_EXAMPLES[skill]))
    assert run(skill, "--input", str(path), "--delete-input").returncode == 0
    again = run(skill, "--input", str(path), "--delete-input")
    assert again.returncode == 2 and again.stdout == b""
    assert again.stderr.decode("utf-8").startswith(
        'error: invalid input, field "input": cannot read'
    )
    assert not path.exists()


@pytest.mark.parametrize("skill", sorted(SCRIPTS))
def test_standard_input_with_the_option_is_refused_before_it_is_read(skill):
    raw = json.dumps(load(skill, DELETE_INPUT_EXAMPLES[skill]), ensure_ascii=False).encode("utf-8")
    for extra in ((), ("--input", "-")):
        done = run(skill, *extra, "--delete-input", stdin=raw)
        assert (done.returncode, done.stdout, done.stderr) == (2, b"", NO_STDIN_MESSAGE)


@pytest.mark.parametrize("skill", sorted(SCRIPTS))
def test_a_missing_file_is_an_error_and_the_other_files_stay(skill, tmp_path):
    other, raw = write_input(tmp_path, load(skill, DELETE_INPUT_EXAMPLES[skill]), "other.json")
    done = run(skill, "--input", str(tmp_path / "nope.json"), "--delete-input")
    assert done.returncode == 2 and done.stdout == b""
    assert done.stderr.decode("utf-8").startswith(
        'error: invalid input, field "input": cannot read'
    )
    assert [item.name for item in tmp_path.iterdir()] == ["other.json"]
    assert other.read_bytes() == raw


@pytest.mark.parametrize("skill", sorted(SCRIPTS))
def test_the_demo_reads_no_file_so_it_deletes_none(skill, tmp_path):
    path, raw = write_input(tmp_path, load(skill, DELETE_INPUT_EXAMPLES[skill]))
    done = run(skill, "--demo", "--input", str(path), "--delete-input")
    assert done.returncode == 0
    assert done.stdout == run(skill, "--demo").stdout
    assert path.read_bytes() == raw


def test_rent_split_commit_and_verify_read_the_file_the_same_way(tmp_path):
    row = {
        "total_rent": 8000,
        "rooms": ["主卧带卫", "南次卧", "北次卧", "小书房"],
        "bids": {"阿明": [3000, 2200, 1600, 1200]},
    }
    path, raw = write_input(tmp_path, row)
    commit = ("--commit", "--nonce", RENT_NONCE)
    by_file = run("rent-split", "--input", str(path), "--delete-input", *commit)
    by_stdin = run("rent-split", "--input", "-", *commit, stdin=raw)
    assert by_file.returncode == by_stdin.returncode == 0, by_file.stderr
    assert by_file.stdout == by_stdin.stdout and RENT_NONCE.encode() in by_file.stdout
    assert not path.exists()
    digest = re.search(rb"[0-9a-f]{64}", by_file.stdout)
    assert digest is not None
    path, raw = write_input(tmp_path, row)
    check = ("--verify-commit", digest.group(0).decode(), "--nonce", RENT_NONCE)
    verified = run("rent-split", "--input", str(path), "--delete-input", *check)
    assert verified.returncode == 0, verified.stdout
    assert not path.exists()


def test_slot_lottery_verify_reads_the_file_the_same_way(tmp_path):
    data = load("slot-lottery", "tickets_8_for_3.json")
    data["claimed"] = {"order": LOTTERY_ORDER}
    path, raw = write_input(tmp_path, data)
    by_file = run("slot-lottery", "--verify", "--input", str(path), "--delete-input")
    by_stdin = run("slot-lottery", "--verify", "--input", "-", stdin=raw)
    assert by_file.returncode == by_stdin.returncode == 0, by_file.stdout
    assert by_file.stdout == by_stdin.stdout
    assert not path.exists()
