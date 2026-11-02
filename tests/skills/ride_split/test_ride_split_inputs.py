"""Bad input: exit code 2, and the message names the field that is wrong."""

from __future__ import annotations

import copy
import json

import fsq_core as fc
import pytest
import ride_split as rs
from ride_support import RIDERS, run_json, run_script, run_script_bytes

METER = {
    "mode": "meter",
    "riders": RIDERS,
    "meter_at_dropoff": [14, 26, 41, 63],
}
ESTIMATES = {
    "mode": "estimates",
    "riders": RIDERS,
    "solo_estimate": [15, 27, 40, 66],
    "actual_total": 63,
}
PRICES = [
    {"riders": ["A"], "cost": 10},
    {"riders": ["B"], "cost": 12},
    {"riders": ["A", "B"], "cost": 16},
]
GENERAL_TABLE = {"mode": "general", "riders": ["A", "B"], "subset_costs": PRICES}
GENERAL_MATRIX = {
    "mode": "general",
    "riders": ["A", "B"],
    "distance_matrix": [[0, 3, 5], [3, 0, 4], [5, 4, 0]],
    "tariff": {"base": 10, "per_unit": 2},
}


def changed(base: dict, **fields) -> dict:
    """A copy of base with some fields replaced; a value of None removes the field."""
    data = copy.deepcopy(base)
    for key, value in fields.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    return data


BAD_INPUTS = [
    # --- meter mode
    (
        "decreasing reading",
        changed(METER, meter_at_dropoff=[14, 26, 20, 63]),
        "meter_at_dropoff[2]",
    ),
    ("negative reading", changed(METER, meter_at_dropoff=[14, 26, -1, 63]), "meter_at_dropoff[2]"),
    (
        "negative first reading",
        changed(METER, meter_at_dropoff=[-14, 26, 41, 63]),
        "meter_at_dropoff[0]",
    ),
    ("all readings zero", changed(METER, meter_at_dropoff=[0, 0, 0, 0]), "meter_at_dropoff"),
    (
        "three decimals",
        changed(METER, meter_at_dropoff=[14, 26, 41, 63.005]),
        "meter_at_dropoff[3]",
    ),
    (
        "reading is text",
        changed(METER, meter_at_dropoff=[14, "abc", 41, 63]),
        "meter_at_dropoff[1]",
    ),
    (
        "reading is boolean",
        changed(METER, meter_at_dropoff=[14, True, 41, 63]),
        "meter_at_dropoff[1]",
    ),
    ("one reading too few", changed(METER, meter_at_dropoff=[14, 26, 41]), "meter_at_dropoff"),
    ("riders missing", changed(METER, riders=RIDERS[:3]), "riders"),
    ("riders field absent", changed(METER, riders=None), "riders"),
    ("readings field absent", changed(METER, meter_at_dropoff=None), "meter_at_dropoff"),
    ("one rider only", changed(METER, riders=["A"], meter_at_dropoff=[10]), "riders"),
    ("duplicate rider", changed(METER, riders=["A", "B", "A", "C"]), "riders[2]"),
    ("blank rider", changed(METER, riders=["A", " ", "C", "D"]), "riders[1]"),
    (
        "thirteen riders",
        changed(METER, riders=[f"r{i}" for i in range(13)], meter_at_dropoff=list(range(1, 14))),
        "riders",
    ),
    ("unknown mode", changed(METER, mode="taxi"), "mode"),
    ("mode absent", changed(METER, mode=None), "mode"),
    ("field of another mode", changed(METER, solo_estimate=[1, 2, 3, 4]), "solo_estimate"),
    ("misspelled field", changed(METER, meter_at_dropof=[1, 2, 3, 4]), "meter_at_dropof"),
    ("payer is not a rider", changed(METER, paid_by="Zed"), "paid_by"),
    ("empty ride id", changed(METER, ride_id=" "), "ride_id"),
    ("unknown rule", changed(METER, rules={"method": "nucleolus"}), "rules.method"),
    ("unknown rule field", changed(METER, rules={"shape": 1}), "rules.shape"),
    # --- estimates mode
    ("negative estimate", changed(ESTIMATES, solo_estimate=[15, -27, 40, 66]), "solo_estimate[1]"),
    ("negative total", changed(ESTIMATES, actual_total=-63), "actual_total"),
    ("zero total", changed(ESTIMATES, actual_total=0), "actual_total"),
    ("total absent", changed(ESTIMATES, actual_total=None), "actual_total"),
    ("all estimates zero", changed(ESTIMATES, solo_estimate=[0, 0, 0, 0]), "solo_estimate"),
    ("estimates missing a rider", changed(ESTIMATES, solo_estimate=[15, 27, 40]), "solo_estimate"),
    ("estimates too many", changed(ESTIMATES, solo_estimate=[15, 27, 40, 66, 70]), "riders"),
    # --- general mode
    ("neither prices nor distances", changed(GENERAL_TABLE, subset_costs=None), "subset_costs"),
    ("both prices and distances", changed(GENERAL_TABLE, distance_matrix=[[0]]), "subset_costs"),
    (
        "negative group price",
        changed(GENERAL_TABLE, subset_costs=[{"riders": ["A"], "cost": -1}, PRICES[1], PRICES[2]]),
        "subset_costs[0].cost",
    ),
    ("group price missing", changed(GENERAL_TABLE, subset_costs=PRICES[:2]), "subset_costs"),
    (
        "group priced twice",
        changed(GENERAL_TABLE, subset_costs=PRICES + [PRICES[0]]),
        "subset_costs[3]",
    ),
    (
        "unknown rider in a group",
        changed(GENERAL_TABLE, subset_costs=[{"riders": ["Z"], "cost": 5}] + PRICES[1:]),
        "subset_costs[0].riders[0]",
    ),
    (
        "rider twice in a group",
        changed(GENERAL_TABLE, subset_costs=PRICES[:2] + [{"riders": ["A", "A"], "cost": 5}]),
        "subset_costs[2].riders[1]",
    ),
    (
        "group entry without cost",
        changed(GENERAL_TABLE, subset_costs=PRICES[:2] + [{"riders": ["A", "B"]}]),
        "subset_costs[2].cost",
    ),
    ("seven riders", changed(GENERAL_TABLE, riders=[f"r{i}" for i in range(7)]), "riders"),
    ("tariff without distances", changed(GENERAL_TABLE, tariff={"per_unit": 1}), "tariff"),
    ("matrix without tariff", changed(GENERAL_MATRIX, tariff=None), "tariff"),
    ("tariff without per_unit", changed(GENERAL_MATRIX, tariff={"base": 5}), "tariff.per_unit"),
    ("negative per_unit", changed(GENERAL_MATRIX, tariff={"per_unit": -1}), "tariff.per_unit"),
    (
        "matrix not square",
        changed(GENERAL_MATRIX, distance_matrix=[[0, 3, 5], [3, 0, 4]]),
        "distance_matrix",
    ),
    (
        "matrix row too short",
        changed(GENERAL_MATRIX, distance_matrix=[[0, 3, 5], [3, 0], [5, 4, 0]]),
        "distance_matrix[1]",
    ),
    (
        "negative distance",
        changed(GENERAL_MATRIX, distance_matrix=[[0, 3, 5], [3, 0, -4], [5, 4, 0]]),
        "distance_matrix[1][2]",
    ),
    (
        "diagonal not zero",
        changed(GENERAL_MATRIX, distance_matrix=[[0, 3, 5], [3, 1, 4], [5, 4, 0]]),
        "distance_matrix[1][1]",
    ),
    ("total is zero", changed(GENERAL_MATRIX, tariff={"per_unit": 0}), "distance_matrix"),
    ("actual total negative", changed(GENERAL_MATRIX, actual_total=-1), "actual_total"),
]


@pytest.mark.parametrize(("label", "data", "field"), BAD_INPUTS, ids=[b[0] for b in BAD_INPUTS])
def test_bad_input_is_refused_with_the_field_named(label, data, field):
    with pytest.raises(fc.InputError) as caught:
        rs.parse_ride(data)
    assert field in caught.value.field or field in caught.value.message, (
        f"{label}: expected {field!r}, got field {caught.value.field!r}: {caught.value.message}"
    )


@pytest.mark.parametrize(("label", "data", "field"), BAD_INPUTS, ids=[b[0] for b in BAD_INPUTS])
def test_command_line_exits_with_code_2_and_names_the_field(label, data, field):
    done = run_script("--input", "-", stdin=json.dumps(data))
    assert done.returncode == 2, f"{label}: exit {done.returncode}\n{done.stderr}"
    assert done.stdout == ""
    assert field in done.stderr, done.stderr
    assert "Traceback" not in done.stderr


class TestOtherFailures:
    def test_invalid_json(self):
        done = run_script("--input", "-", stdin="{not json")
        assert done.returncode == 2
        assert "input" in done.stderr

    def test_top_level_must_be_an_object(self):
        done = run_script("--input", "-", stdin="[1, 2]")
        assert done.returncode == 2
        assert "input" in done.stderr

    def test_missing_file(self):
        done = run_script("--input", "/nonexistent/ride.json")
        assert done.returncode == 2
        assert "input" in done.stderr

    def test_standard_input_that_is_not_utf8(self):
        done = run_script_bytes("--input", "-", stdin=b"\xff\xfe{}")
        assert done.returncode == 2
        assert b"input" in done.stderr and b"Traceback" not in done.stderr

    @pytest.mark.parametrize(
        ("data", "field"),
        [
            ({**METER, "riders": ["a\ud800", "b", "c", "d"]}, "riders[0]"),
            ({**METER, "ride_id": "x\ud800"}, "ride_id"),
        ],
    )
    def test_unpaired_surrogates_are_refused(self, data, field):
        done = run_script("--input", "-", stdin=json.dumps(data))
        assert done.returncode == 2
        assert field in done.stderr and "Traceback" not in done.stderr

    def test_nothing_on_standard_input_is_an_error_not_a_hang(self):
        done = run_script("--input", "-", stdin="")
        assert done.returncode == 2

    def test_audit_without_an_audit_block(self):
        done = run_json(METER, "--audit")
        assert done.returncode == 2
        assert "audit" in done.stderr

    @pytest.mark.parametrize(
        ("audit", "field"),
        [
            ({"current": "half"}, "audit.current"),
            ({"current": {"小周": 15.75}}, "audit.current."),
            ({"current": {n: 15 for n in RIDERS}}, "audit.current"),
            ({"current": {**{n: 15.75 for n in RIDERS}, "Zed": 1}}, "audit.current.Zed"),
            ({"current": {**{n: 15.75 for n in RIDERS}, "Mia": -1}}, "audit.current.Mia"),
            ({"current": {**{n: 15.75 for n in RIDERS}, "Mia": 15.755}}, "audit.current.Mia"),
            ({"shape": "equal"}, "audit.shape"),
            ({}, "audit.current"),
        ],
    )
    def test_bad_audit_blocks(self, audit, field):
        done = run_json({**METER, "audit": audit}, "--audit")
        assert done.returncode == 2, done.stderr
        assert field in done.stderr

    def test_the_audit_block_is_ignored_with_a_note_when_the_flag_is_missing(self):
        audit = {"current": "equal"}
        done = run_json({**METER, "audit": audit})
        assert done.returncode == 0
        assert "--audit" in done.stdout

    def test_proportional_audit_needs_a_positive_solo_price(self):
        data = {
            "mode": "general",
            "riders": ["A", "B"],
            "subset_costs": [
                {"riders": ["A"], "cost": 0},
                {"riders": ["B"], "cost": 0},
                {"riders": ["A", "B"], "cost": 10},
            ],
            "audit": {"current": "proportional"},
        }
        done = run_json(data, "--audit")
        assert done.returncode == 2
        assert "audit.current" in done.stderr


class TestAcceptedInput:
    """Edge cases that must work."""

    def test_amounts_may_be_numbers_or_decimal_strings(self):
        numbers = {**METER, "meter_at_dropoff": [14.5, 26, 41.25, 63]}
        strings = {**METER, "meter_at_dropoff": ["14.50", "26", "41.25", "63.00"]}
        one = run_json(numbers, "--json")
        two = run_json(strings, "--json")
        assert one.returncode == 0 and two.returncode == 0, one.stderr + two.stderr
        assert json.loads(one.stdout)["result"] == json.loads(two.stdout)["result"]

    def test_json_decimals_are_read_exactly(self):
        # 0.29 as a binary float times 100 is 28.999999999999996
        data = {**METER, "meter_at_dropoff": [0.29, 0.58, 0.87, 1.16]}
        done = run_json(data, "--json")
        assert done.returncode == 0, done.stderr
        echo = json.loads(done.stdout)["inputs_echo"]
        assert echo["meter_at_dropoff"] == ["0.29", "0.58", "0.87", "1.16"]

    def test_equal_readings_mean_the_same_drop_off_place(self):
        ride = rs.parse_ride({**METER, "meter_at_dropoff": [20, 20, 30, 30]})
        out = rs.compute(ride)
        assert (
            out.shapley.cents[0] == out.shapley.cents[1]
            or abs(out.shapley.cents[0] - out.shapley.cents[1]) == 1
        )
        assert [len(seg.sharers) for seg in out.game.segments] == [4, 2]
        assert out.shapley.violations == []

    def test_twelve_riders_in_meter_mode(self):
        data = {
            "mode": "meter",
            "riders": [f"r{i}" for i in range(12)],
            "meter_at_dropoff": [10 * (i + 1) for i in range(12)],
        }
        done = run_json(data, "--json")
        assert done.returncode == 0, done.stderr
        result = json.loads(done.stdout)["result"]
        assert result["in_core"] is True
        assert sum(int(v.replace(".", "")) for v in result["share_cents"].values()) == 12000

    def test_six_riders_in_general_mode(self):
        n = 6
        prices = [0] + [100 + 7 * bin(mask).count("1") for mask in range(1, 1 << n)]
        entries = [
            {"riders": [f"r{i}" for i in range(n) if mask >> i & 1], "cost": prices[mask]}
            for mask in range(1, 1 << n)
        ]
        data = {"mode": "general", "riders": [f"r{i}" for i in range(n)], "subset_costs": entries}
        done = run_json(data, "--json")
        assert done.returncode == 0, done.stderr

    def test_a_rider_with_a_zero_solo_price_is_told_they_pay_nothing(self):
        data = {**ESTIMATES, "solo_estimate": [0, 27, 40, 66]}
        done = run_json(data, "--format", "dm")
        assert done.returncode == 0, done.stderr
        block = done.stdout.split("--- 发给 阿杰 ---")[0].split("--- 发给 小周 ---")[1]
        assert block.strip().splitlines() == [
            "这次拼车你付 0.00。",
            "你下车时没有产生任何车费，所以不用付。",
        ]

    def test_the_default_ride_id_is_the_one_of_the_worked_example(self):
        assert rs.DEFAULT_RIDE_ID == "ride-1"
        assert rs.parse_ride(METER).ride_id == "ride-1"
