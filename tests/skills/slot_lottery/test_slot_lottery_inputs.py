"""Bad input: exit code 2, and the message names the field that is wrong."""

from __future__ import annotations

import copy
import json

import fsq_core as fc
import pytest
import slot_lottery as sl
from lottery_support import (
    PEOPLE6,
    PEOPLE8,
    RSD_PREFS,
    WEEKS,
    da_data,
    lottery_data,
    ps_data,
    reveal_data,
    rsd_data,
    run_json,
    run_script,
    run_script_bytes,
)

LOTTERY = lottery_data(PEOPLE8, 3)
RSD = rsd_data(PEOPLE6, WEEKS, RSD_PREFS)


def changed(base: dict, **fields) -> dict:
    """A copy of base with some fields replaced; a value of None removes the field."""
    data = copy.deepcopy(base)
    for key, value in fields.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    return data


def rules(base: dict, **fields) -> dict:
    """A copy of base whose rules block has some fields replaced (None removes one)."""
    data = copy.deepcopy(base)
    for key, value in fields.items():
        if value is None:
            data["rules"].pop(key, None)
        else:
            data["rules"][key] = value
    return data


def prefs(base: dict, **fields) -> dict:
    data = copy.deepcopy(base)
    for key, value in fields.items():
        if value is None:
            data["prefs"].pop(key, None)
        else:
            data["prefs"][key] = value
    return data


BAD_INPUTS = [
    # --- the top level
    ("mode missing", changed(LOTTERY, mode=None), "mode"),
    ("mode unknown", changed(LOTTERY, mode="raffle"), "mode"),
    ("unknown top-level field", changed(LOTTERY, slot_name=["x"]), "slot_name"),
    # --- people
    ("people missing", changed(LOTTERY, people=None), "people"),
    ("people not a list", changed(LOTTERY, people="阿明"), "people"),
    ("one person", changed(LOTTERY, people=["阿明"]), "people"),
    ("duplicate person", changed(LOTTERY, people=["a", "b", "a"]), "people[2]"),
    ("blank person", changed(LOTTERY, people=["a", " "]), "people[1]"),
    ("person with a leading space", changed(LOTTERY, people=[" a", "b"]), "people[0]"),
    ("person is a number", changed(LOTTERY, people=["a", "b", 3]), "people[2]"),
    ("unpaired surrogate in a name", changed(LOTTERY, people=["a\ud800", "b"]), "people[0]"),
    # --- n_slots and slot_names
    ("n_slots missing", changed(LOTTERY, n_slots=None), "n_slots"),
    ("n_slots zero", changed(LOTTERY, n_slots=0), "n_slots"),
    ("n_slots negative", changed(LOTTERY, n_slots=-1), "n_slots"),
    ("n_slots fractional", changed(LOTTERY, n_slots=2.5), "n_slots"),
    ("n_slots is text", changed(LOTTERY, n_slots="3"), "n_slots"),
    ("n_slots is boolean", changed(LOTTERY, n_slots=True), "n_slots"),
    ("slot_names in lottery mode", changed(LOTTERY, slot_names=["x"]), "slot_names"),
    ("prefs in lottery mode", changed(LOTTERY, prefs={}), "prefs"),
    ("n_slots in rsd mode", changed(RSD, n_slots=4), "n_slots"),
    ("slot_names missing", changed(RSD, slot_names=None), "slot_names"),
    ("duplicate slot name", changed(RSD, slot_names=["x", "y", "x"]), "slot_names[2]"),
    ("empty slot name", changed(RSD, slot_names=[""]), "slot_names[0]"),
    # --- the randomness
    ("random source missing", changed(LOTTERY, random_source=None), "random_source"),
    ("random source blank", changed(LOTTERY, random_source="   "), "random_source"),
    ("random source is a number", changed(LOTTERY, random_source=20261108), "random_source"),
    (
        "random source too long",
        changed(LOTTERY, random_source="x" * (fc.MAX_SOURCE_CHARS + 1)),
        "random_source",
    ),
    (
        "random source with a surrogate",
        changed(LOTTERY, random_source="draw \ud800"),
        "random_source",
    ),
    # --- rules
    ("rules missing", changed(LOTTERY, rules=None), "rules"),
    ("rules not an object", changed(LOTTERY, rules=["forfeit"]), "rules"),
    ("deadline missing", rules(LOTTERY, deadline=None), "rules.deadline"),
    ("deadline blank", rules(LOTTERY, deadline="  "), "rules.deadline"),
    ("deadline over two lines", rules(LOTTERY, deadline="a\nb"), "rules.deadline"),
    ("deadline too long", rules(LOTTERY, deadline="d" * 301), "rules.deadline"),
    (
        "source description missing",
        rules(LOTTERY, source_description=None),
        "rules.source_description",
    ),
    (
        "source description with a surrogate",
        rules(LOTTERY, source_description="x\ud800"),
        "rules.source_description",
    ),
    ("unknown rule", rules(LOTTERY, tie_break="name"), "rules.tie_break"),
    ("no_ranking in lottery mode", rules(LOTTERY, no_ranking="forfeit"), "rules.no_ranking"),
    ("no_ranking missing in rsd mode", rules(RSD, no_ranking=None), "rules.no_ranking"),
    ("no_ranking unknown", rules(RSD, no_ranking="ignore"), "rules.no_ranking"),
    # --- rankings
    ("prefs missing", changed(RSD, prefs=None), "prefs"),
    ("prefs empty", changed(RSD, prefs={}), "prefs"),
    ("prefs not an object", changed(RSD, prefs=[["x"]]), "prefs"),
    ("ranking of a stranger", prefs(RSD, 陌生人=["五一"]), "prefs.陌生人"),
    ("ranking not a list", prefs(RSD, 阿明="五一"), "prefs.阿明"),
    ("ranking names an unknown slot", prefs(RSD, 阿明=["五一", "中秋"]), "prefs.阿明[1]"),
    ("ranking lists a slot twice", prefs(RSD, 阿明=["五一", "五一"]), "prefs.阿明[1]"),
    ("ranking longer than the slots", prefs(RSD, 阿明=[*WEEKS, "五一"]), "prefs.阿明"),
    ("ranking entry is a number", prefs(RSD, 阿明=[1]), "prefs.阿明[0]"),
    # --- verification fields
    ("claimed without --verify", changed(LOTTERY, claimed={"order": ["a"]}), "claimed"),
]


@pytest.mark.parametrize(("label", "data", "field"), BAD_INPUTS, ids=[b[0] for b in BAD_INPUTS])
def test_bad_input_is_refused_with_the_field_named(label, data, field):
    with pytest.raises(fc.InputError) as caught:
        sl.parse_problem(data)
    assert field in caught.value.field, (
        f"{label}: expected {field!r}, got {caught.value.field!r}: {caught.value.message}"
    )


@pytest.mark.parametrize(("label", "data", "field"), BAD_INPUTS, ids=[b[0] for b in BAD_INPUTS])
def test_command_line_exits_with_code_2_and_names_the_field(label, data, field):
    done = run_script("--input", "-", stdin=json.dumps(data))
    assert done.returncode == 2, f"{label}: exit {done.returncode}\n{done.stderr}"
    assert done.stdout == ""
    assert field in done.stderr, done.stderr
    assert "Traceback" not in done.stderr


PS = ps_data(PEOPLE6, WEEKS, RSD_PREFS, capacities={"五一": 2})
DA = da_data(
    PEOPLE6,
    WEEKS,
    RSD_PREFS,
    capacities={"五一": 2},
    priorities={"五一": [["阿明"], ["小红", "大刘"]]},
)


def reveal_with_method(method: str) -> dict:
    people = ["甲", "乙", "丙"]
    slots = ["x", "y"]
    data = reveal_data(
        people, mode="rsd", slots=slots, prefs={p: slots for p in people}, non_reveal="forfeit"
    )
    data["rules"]["method"] = method
    return data


BAD_METHOD_INPUTS = [
    # --- the method itself
    ("method unknown", rules(RSD, method="borda"), "rules.method"),
    ("method is not text", rules(RSD, method=3), "rules.method"),
    ("method in lottery mode", rules(LOTTERY, method="ps"), "rules.method"),
    ("method rsd in lottery mode", rules(LOTTERY, method="rsd"), "rules.method"),
    ("no_ranking missing with ps", rules(PS, no_ranking=None), "rules.no_ranking"),
    ("no_ranking unknown with da", rules(DA, no_ranking="ignore"), "rules.no_ranking"),
    ("commit_reveal with ps", reveal_with_method("ps"), "commit_reveal"),
    ("commit_reveal with da", reveal_with_method("da"), "commit_reveal"),
    # --- fields that belong to ps and da
    ("capacities in lottery mode", changed(LOTTERY, capacities={}), "capacities"),
    ("priorities in lottery mode", changed(LOTTERY, priorities={}), "priorities"),
    ("capacities with the default method", changed(RSD, capacities={"五一": 2}), "capacities"),
    ("priorities with the default method", changed(RSD, priorities={}), "priorities"),
    (
        "capacities with method rsd written out",
        rules(changed(RSD, capacities={}), method="rsd"),
        "capacities",
    ),
    ("priorities with ps", changed(PS, priorities={"五一": [["阿明"]]}), "priorities"),
    # --- capacities
    ("capacities not an object", changed(PS, capacities=[1, 2]), "capacities"),
    ("capacity of an unknown slot", changed(PS, capacities={"中秋": 2}), "capacities.中秋"),
    ("capacity zero", changed(PS, capacities={"五一": 0}), "capacities.五一"),
    ("capacity negative", changed(PS, capacities={"五一": -1}), "capacities.五一"),
    ("capacity fractional", changed(PS, capacities={"五一": 2.5}), "capacities.五一"),
    ("capacity is text", changed(PS, capacities={"五一": "2"}), "capacities.五一"),
    ("capacity is boolean", changed(PS, capacities={"五一": True}), "capacities.五一"),
    ("capacity too large", changed(DA, capacities={"五一": 2001}), "capacities.五一"),
    # --- priorities
    ("priorities not an object", changed(DA, priorities=[["阿明"]]), "priorities"),
    (
        "priorities of an unknown slot",
        changed(DA, priorities={"中秋": [["阿明"]]}),
        "priorities.中秋",
    ),
    ("priorities without a tier", changed(DA, priorities={"五一": []}), "priorities.五一"),
    ("tiers not a list", changed(DA, priorities={"五一": "阿明"}), "priorities.五一"),
    ("a tier is a name", changed(DA, priorities={"五一": ["阿明"]}), "priorities.五一[0]"),
    ("an empty tier", changed(DA, priorities={"五一": [["阿明"], []]}), "priorities.五一[1]"),
    ("a stranger in a tier", changed(DA, priorities={"五一": [["路人"]]}), "priorities.五一[0][0]"),
    ("a number in a tier", changed(DA, priorities={"五一": [[1]]}), "priorities.五一[0][0]"),
    (
        "a person twice in one tier",
        changed(DA, priorities={"五一": [["阿明", "阿明"]]}),
        "priorities.五一[0][1]",
    ),
    (
        "a person in two tiers",
        changed(DA, priorities={"五一": [["阿明"], ["小红", "阿明"]]}),
        "priorities.五一[1][1]",
    ),
    # --- the claimed block of ps and da
    ("claimed without allocation, ps", changed(PS, claimed={"seed": "0" * 64}), "claimed"),
]


@pytest.mark.parametrize(
    ("label", "data", "field"), BAD_METHOD_INPUTS, ids=[b[0] for b in BAD_METHOD_INPUTS]
)
def test_bad_ps_and_da_input_is_refused_with_the_field_named(label, data, field):
    with pytest.raises(fc.InputError) as caught:
        sl.parse_problem(data)
    assert field in caught.value.field, (
        f"{label}: expected {field!r}, got {caught.value.field!r}: {caught.value.message}"
    )


@pytest.mark.parametrize(
    ("label", "data", "field"), BAD_METHOD_INPUTS, ids=[b[0] for b in BAD_METHOD_INPUTS]
)
def test_command_line_exits_with_code_2_for_bad_ps_and_da_input_and_names_the_field(
    label, data, field
):
    done = run_script("--input", "-", stdin=json.dumps(data))
    assert done.returncode == 2, f"{label}: exit {done.returncode}\n{done.stderr}"
    assert done.stdout == "" and field in done.stderr
    assert "Traceback" not in done.stderr


class TestClaimedBlockOfPsAndDa:
    @pytest.mark.parametrize(
        ("data", "claimed", "field"),
        [
            (PS, {}, "claimed.allocation"),
            (PS, {"allocation": {"阿明": "五一"}, "order": ["阿明"]}, "claimed.order"),
            (PS, {"allocation": []}, "claimed.allocation"),
            (PS, {"allocation": {"阿明": 5}}, "claimed.allocation.阿明"),
            (DA, {"order": ["阿明"]}, "claimed.allocation"),
            (DA, {"order": [], "allocation": {}}, "claimed.order"),
            (DA, {"allocation": {}, "winners": ["阿明"]}, "claimed.winners"),
        ],
    )
    def test_bad_claimed_blocks(self, data, claimed, field):
        done = run_json(dict(data, claimed=claimed), "--verify")
        assert done.returncode == 2, done.stderr
        assert field in done.stderr

    def test_ps_needs_no_order_and_da_may_leave_it_out(self):
        for data in (PS, DA):
            result = json.loads(run_json(data, "--json").stdout)["result"]
            claimed = {"allocation": result["allocation"]}
            done = run_json(dict(data, claimed=claimed), "--verify")
            assert done.returncode == 0, done.stdout + done.stderr


class TestOtherFailures:
    def test_invalid_json(self):
        done = run_script("--input", "-", stdin="{not json")
        assert done.returncode == 2 and "input" in done.stderr

    def test_the_top_level_must_be_an_object(self):
        done = run_script("--input", "-", stdin="[1, 2]")
        assert done.returncode == 2 and "input" in done.stderr

    def test_a_missing_file(self):
        done = run_script("--input", "/nonexistent/draw.json")
        assert done.returncode == 2 and "input" in done.stderr

    def test_standard_input_that_is_not_utf8(self):
        done = run_script_bytes("--input", "-", stdin=b"\xff\xfe{}")
        assert done.returncode == 2
        assert b"input" in done.stderr and b"Traceback" not in done.stderr

    def test_nothing_on_standard_input_is_an_error_not_a_hang(self):
        assert run_script("--input", "-", stdin="").returncode == 2

    def test_a_repeated_key_is_refused(self):
        text = '{"mode": "lottery", "mode": "rsd"}'
        done = run_script("--input", "-", stdin=text)
        assert done.returncode == 2 and "duplicate key" in done.stderr

    def test_nan_is_refused(self):
        done = run_script("--input", "-", stdin='{"n_slots": NaN}')
        assert done.returncode == 2 and "NaN" in done.stderr

    def test_more_people_than_the_limit(self):
        people = [f"p{i}" for i in range(sl.MAX_PEOPLE + 1)]
        done = run_json(lottery_data(people, 3))
        assert done.returncode == 2 and "people" in done.stderr

    def test_the_largest_allowed_draw_still_runs(self):
        people = [f"p{i}" for i in range(sl.MAX_PEOPLE)]
        done = run_json(lottery_data(people, 100), "--format", "group")
        assert done.returncode == 0, done.stderr

    def test_whole_number_slot_counts_written_as_decimals_are_fine(self):
        done = run_script(
            "--input",
            "-",
            "--json",
            stdin=json.dumps(LOTTERY).replace('"n_slots": 3', '"n_slots": 3.0'),
        )
        assert done.returncode == 0, done.stderr
        assert json.loads(done.stdout)["inputs_echo"]["n_slots"] == 3


class TestOptions:
    def test_help_lists_every_option_and_the_exit_codes(self):
        text = " ".join(run_script("--help").stdout.split())
        for option in ("--input", "--format", "--json", "--demo", "--selftest", "--lang"):
            assert option in text
        for option in ("--verify", "--source", "--commit", "--person"):
            assert option in text
        assert "Exit code 0 means success" in text

    @pytest.mark.parametrize(
        "flags",
        [
            ["--commit", "--demo"],
            ["--commit", "--selftest"],
            ["--demo", "--verify"],
            ["--selftest", "--verify"],
        ],
    )
    def test_at_most_one_mode(self, flags):
        done = run_script(*flags, "--person", "x")
        assert done.returncode == 2 and "at most one" in done.stderr

    def test_person_belongs_to_commit(self):
        done = run_script("--demo", "--person", "阿明")
        assert done.returncode == 2 and "--person" in done.stderr

    def test_source_belongs_to_verify(self):
        done = run_script("--demo", "--source", "x")
        assert done.returncode == 2 and "--source" in done.stderr

    def test_verify_needs_a_claimed_result(self):
        done = run_json(LOTTERY, "--verify")
        assert done.returncode == 2 and "claimed" in done.stderr

    def test_dm_is_not_available_with_verify(self):
        data = changed(LOTTERY, claimed={"order": ["a", "b"]})
        done = run_json(data, "--verify", "--format", "dm")
        assert done.returncode == 2 and "--format" in done.stderr

    def test_selftest_passes(self):
        done = run_script("--selftest")
        assert done.returncode == 0, done.stdout + done.stderr
        assert "0 failed" in done.stdout
        assert "golden lottery" in done.stdout


class TestClaimedBlock:
    @pytest.mark.parametrize(
        ("claimed", "field"),
        [
            ({}, "claimed.order"),
            ({"order": []}, "claimed.order"),
            ({"order": "Yuki"}, "claimed.order"),
            ({"order": [1, 2]}, "claimed.order[0]"),
            ({"order": ["a"], "seed": "abc"}, "claimed.seed"),
            ({"order": ["a"], "seed": 5}, "claimed.seed"),
            ({"order": ["a"], "allocation": []}, "claimed.allocation"),
            ({"order": ["a"], "allocation": {"阿明": 5}}, "claimed.allocation.阿明"),
            ({"order": ["a"], "winners": ["a"]}, "claimed.winners"),
            ({"order": ["a"], "allocation": {"阿明": "x"}}, "claimed.allocation"),  # lottery mode
        ],
    )
    def test_bad_claimed_blocks(self, claimed, field):
        done = run_json(changed(LOTTERY, claimed=claimed), "--verify")
        assert done.returncode == 2, done.stderr
        assert field in done.stderr

    def test_notes_are_optional_when_verifying(self):
        data = {
            "mode": "lottery",
            "people": PEOPLE8,
            "n_slots": 3,
            "random_source": lottery_data(PEOPLE8, 3)["random_source"],
            "claimed": {"order": ["Yuki", "小周", "大刘", "Coco", "小红", "阿明", "Mia", "老王"]},
        }
        done = run_json(data, "--verify")
        assert done.returncode == 0, done.stderr
