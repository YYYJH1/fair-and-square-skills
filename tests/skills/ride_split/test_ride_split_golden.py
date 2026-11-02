"""Golden numbers: the worked examples, reproduced by the script."""

from __future__ import annotations

import json
import os
from typing import ClassVar

import fsq_core as fc
import pytest
import ride_split as rs
from ride_support import (
    EXAMPLES,
    GOLDEN_DIR,
    RIDERS,
    estimates_data,
    meter_data,
    run_json,
    run_script,
)


def shown(cents):
    """Cents as the two-decimal strings the script prints."""
    return [fc.fmt_cents(value) for value in cents]


def compute(data: dict, audit: bool = False):
    ride = rs.parse_ride(data, audit)
    return ride, rs.compute(ride)


def violation_rows(split, riders):
    return [
        (
            [riders[i] for i in item.members],
            fc.fmt_cents(item.paid),
            fc.fmt_cents(item.alone),
        )
        for item in split.violations
    ]


METER = meter_data([1400, 2600, 4100, 6300], RIDERS, ride_id="ride-1")
ESTIMATES = estimates_data([1500, 2700, 4000, 6600], 6300, RIDERS, ride_id="ride-1")


class TestMeterExample:
    """Meter readings 14, 26, 41, 63 (the airport example)."""

    def test_shapley_shares(self):
        _, out = compute(METER)
        assert shown(out.shapley.cents) == ["3.50", "7.50", "15.00", "37.00"]
        assert out.shapley.violations == []

    def test_each_stretch_is_shared_by_those_still_in_the_car(self):
        _, out = compute(METER)
        stretches = [
            (fc.to_cents(seg.cost), [RIDERS[i] for i in seg.sharers]) for seg in out.game.segments
        ]
        assert stretches == [
            (1400, RIDERS),
            (1200, RIDERS[1:]),
            (1500, RIDERS[2:]),
            (2200, RIDERS[3:]),
        ]

    def test_equal_split_breaks_the_core_in_three_groups(self):
        _, out = compute(METER)
        equal = out.alternatives["equal"]
        assert shown(equal.cents) == ["15.75"] * 4
        assert violation_rows(equal, RIDERS) == [
            (["小周"], "15.75", "14.00"),
            (["小周", "阿杰"], "31.50", "26.00"),
            (["小周", "阿杰", "Mia"], "47.25", "41.00"),
        ]

    def test_the_first_rider_pays_more_than_a_solo_ride_under_equal_split(self):
        _, out = compute(METER)
        assert out.alternatives["equal"].cents[0] == 1575
        assert out.game.alone[1] == 1400

    def test_proportional_split_is_in_the_core(self):
        _, out = compute(METER)
        proportional = out.alternatives["proportional"]
        assert shown(proportional.cents) == ["6.13", "11.37", "17.94", "27.56"]
        assert proportional.violations == []

    def test_savings_against_riding_alone(self):
        _, out = compute(METER)
        stats = rs.solo_savings(out.game, out.shapley)
        assert [fc.fmt_cents(saved) for _, saved, _ in stats] == [
            "10.50",
            "18.50",
            "26.00",
            "26.00",
        ]
        assert [pct for _, _, pct in stats] == [75, 71, 63, 41]

    def test_the_last_rider_is_told_why_they_pay_more(self):
        result = rs.solve(METER, lang="zh")
        assert "最后那段 22.00 元只有你一个人坐，所以你多付。" in result.person_lines["老陈"]
        assert not any("只有你一个人坐" in line for line in result.person_lines["小周"])


class TestEstimatesExample:
    """App estimates 15, 27, 40, 66 and 63 actually paid."""

    def test_scaled_shapley_shares(self):
        _, out = compute(ESTIMATES)
        assert shown(out.shapley.cents) == ["3.58", "7.40", "13.60", "38.42"]
        assert sum(out.shapley.cents) == 6300
        assert out.shapley.violations == []

    def test_scale_factor_is_the_paid_total_over_the_largest_estimate(self):
        ride, _ = compute(ESTIMATES)
        assert (ride.scale.numerator, ride.scale.denominator) == (21, 22)

    def test_equal_split_breaks_the_core_in_three_groups(self):
        _, out = compute(ESTIMATES)
        equal = out.alternatives["equal"]
        assert violation_rows(equal, RIDERS) == [
            (["小周"], "15.75", "14.32"),
            (["小周", "阿杰"], "31.50", "25.77"),
            (["小周", "阿杰", "Mia"], "47.25", "38.18"),
        ]

    def test_solo_prices_are_the_scaled_estimates(self):
        _, out = compute(ESTIMATES)
        assert shown([out.game.alone[1 << i] for i in range(4)]) == [
            "14.32",
            "25.77",
            "38.18",
            "63.00",
        ]


class TestExamplesFolder:
    """Every example file runs, and the numbers in the skill's text come out."""

    @staticmethod
    def load(name: str) -> dict:
        return fc.parse_input((EXAMPLES / name).read_text(encoding="utf-8"))

    def test_meter_example_equals_the_demo_data(self):
        by_file = rs.solve(self.load("meter_four_riders.json"))
        by_demo = rs.solve(fc.parse_input(rs.DEMO_JSON))
        assert fc.envelope(by_file)["result"] == fc.envelope(by_demo)["result"]

    def test_estimates_example_with_a_payer(self):
        result = rs.solve(self.load("app_estimates.json"))
        shares = fc.envelope(result)["result"]["share_cents"]
        assert shares == {"小周": "3.58", "阿杰": "7.40", "Mia": "13.60", "老陈": "38.42"}
        transfers = fc.envelope(result)["result"]["transfers"]
        assert transfers == [
            {"from": "小周", "to": "老陈", "amount": "3.58"},
            {"from": "阿杰", "to": "老陈", "amount": "7.40"},
            {"from": "Mia", "to": "老陈", "amount": "13.60"},
        ]

    def test_detour_example(self):
        data = self.load("general_detour.json")
        ride, out = compute(data)
        assert shown(out.shapley.cents) == ["5.00", "23.75", "21.25"]
        assert out.shapley.violations == []
        assert [fc.fmt_cents(out.game.alone[1 << i]) for i in range(3)] == [
            "15.00",
            "40.00",
            "37.50",
        ]
        assert ride.total == 5000
        assert [ride.riders[i] for i in ride.route] == ["小周", "Mia", "阿杰"]
        equal = out.alternatives["equal"]
        assert violation_rows(equal, ride.riders) == [(["小周"], "16.67", "15.00")]

    def test_audit_example(self):
        data = self.load("audit_equal.json")
        _, out = compute(data, audit=True)
        assert shown(out.current.cents) == ["15.75"] * 4
        assert len(out.current.violations) == 3
        assert [out.current.cents[i] - out.shapley.cents[i] for i in range(4)] == [
            1225,
            825,
            75,
            -2125,
        ]

    @pytest.mark.parametrize(
        "name",
        ["meter_four_riders.json", "app_estimates.json", "general_detour.json", "audit_equal.json"],
    )
    def test_each_example_runs_from_the_command_line(self, name):
        flags = ["--audit"] if name == "audit_equal.json" else []
        done = run_script("--input", str(EXAMPLES / name), *flags)
        assert done.returncode == 0, done.stderr
        assert done.stdout.startswith("# ")


class TestDemoIsByteStable:
    """The demo prints the same bytes on every run and matches the stored copies."""

    CASES: ClassVar[dict] = {
        "demo_md_zh.txt": ["--demo"],
        "demo_dm_zh.txt": ["--demo", "--format", "dm"],
        "demo_group_zh.txt": ["--demo", "--format", "group"],
        "demo_json.txt": ["--demo", "--json"],
        "demo_md_en.txt": ["--demo", "--lang", "en"],
        "demo_audit_md_zh.txt": ["--demo", "--audit"],
    }

    @pytest.mark.parametrize("name", sorted(CASES))
    def test_two_runs_are_identical(self, name):
        first = run_script(*self.CASES[name])
        second = run_script(*self.CASES[name])
        assert first.returncode == 0, first.stderr
        assert first.stdout == second.stdout

    @pytest.mark.parametrize("name", sorted(CASES))
    def test_output_matches_the_stored_copy(self, name):
        done = run_script(*self.CASES[name])
        assert done.returncode == 0, done.stderr
        stored = GOLDEN_DIR / name
        if os.environ.get("FSQ_UPDATE_GOLDEN") == "1":
            GOLDEN_DIR.mkdir(exist_ok=True)
            stored.write_text(done.stdout, encoding="utf-8", newline="\n")
        assert done.stdout == stored.read_text(encoding="utf-8"), (
            f"{name} differs from the stored copy. If the change is intended, rerun with "
            "FSQ_UPDATE_GOLDEN=1 and review the diff."
        )

    def test_demo_json_carries_the_worked_example_numbers(self):
        done = run_script("--demo", "--json")
        result = json.loads(done.stdout)["result"]
        assert result["share_cents"] == {
            "小周": "3.50",
            "阿杰": "7.50",
            "Mia": "15.00",
            "老陈": "37.00",
        }
        assert result["alternatives"]["equal"]["violation_count"] == 3
        assert result["alternatives"]["proportional"]["share_cents"] == {
            "小周": "6.13",
            "阿杰": "11.37",
            "Mia": "17.94",
            "老陈": "27.56",
        }

    def test_demo_from_json_input_gives_the_same_result(self):
        by_input = run_json(METER, "--json")
        by_demo = run_script("--demo", "--json")
        assert json.loads(by_input.stdout)["result"] == json.loads(by_demo.stdout)["result"]
