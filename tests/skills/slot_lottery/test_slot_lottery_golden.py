"""Golden values: the recorded seed, order and winners, the examples, and a byte-stable demo."""

from __future__ import annotations

import hashlib
import json
import os
from typing import ClassVar

import fsq_core as fc
import pytest
import slot_lottery as sl
from lottery_reference import reference_order, spec_seed
from lottery_support import (
    EXAMPLES,
    GOLDEN_DIR,
    GOLDEN_ORDER,
    GOLDEN_SEED,
    GOLDEN_SEED_PREFIX,
    GOLDEN_WAITING,
    GOLDEN_WINNERS,
    PEOPLE6,
    PEOPLE8,
    RSD_ALLOCATION,
    RSD_ORDER,
    RSD_PREFS,
    RSD_SEED,
    SOURCE,
    WEEKS,
    load_example,
    lottery_data,
    rsd_data,
    run_json,
    run_script,
)


def outcome(data):
    return sl.compute(sl.parse_problem(data))


class TestRecordedLottery:
    """Eight people, three tickets, one fictional published source."""

    def test_seed_order_winners_and_waiting_list_match_the_recorded_values(self):
        out = outcome(lottery_data(PEOPLE8, 3))
        assert out.draws[0].seed_hex.startswith(GOLDEN_SEED_PREFIX)
        assert out.draws[0].seed_hex == GOLDEN_SEED
        assert out.order == GOLDEN_ORDER
        assert out.winners == GOLDEN_WINNERS
        assert out.waiting == GOLDEN_WAITING

    def test_the_command_line_prints_the_same_values(self):
        done = run_json(lottery_data(PEOPLE8, 3), "--json")
        assert done.returncode == 0, done.stderr
        result = json.loads(done.stdout)["result"]
        assert result["seed_hex"] == GOLDEN_SEED
        assert result["order"] == GOLDEN_ORDER
        assert result["winners"] == GOLDEN_WINNERS
        assert result["waiting"] == GOLDEN_WAITING
        assert result["rule"] == "uniform_lottery_v1"
        assert result["positions"]["Yuki"] == 1 and result["positions"]["老王"] == 8

    def test_the_independent_reference_agrees(self):
        assert spec_seed("uniform_lottery_v1", PEOPLE8, 3, SOURCE).hex() == GOLDEN_SEED
        assert reference_order("uniform_lottery_v1", PEOPLE8, 3, SOURCE) == GOLDEN_ORDER

    def test_the_shared_core_gives_the_same_order(self):
        assert fc.draw_order("uniform_lottery_v1", PEOPLE8, 3, SOURCE) == GOLDEN_ORDER

    def test_changing_the_slot_count_changes_the_seed(self):
        other = outcome(lottery_data(PEOPLE8, 4))
        assert other.draws[0].seed_hex != GOLDEN_SEED

    def test_the_printed_preimage_hashes_to_the_seed(self):
        out = outcome(lottery_data(PEOPLE8, 3))
        preimage = out.draws[0].preimage
        assert hashlib.sha256(preimage.encode("utf-8")).hexdigest() == GOLDEN_SEED
        assert json.loads(preimage) == {
            "n_slots": 3,
            "participants": sorted(PEOPLE8),
            "rule": "uniform_lottery_v1",
            "source": SOURCE,
        }


class TestRecordedSerialDictatorship:
    """Six people, four holiday weeks: the queue and who picked what."""

    def test_queue_seed_and_allocation(self):
        out = outcome(rsd_data(PEOPLE6, WEEKS, RSD_PREFS))
        assert out.draws[0].seed_hex == RSD_SEED
        assert out.order == RSD_ORDER
        assert out.allocation == RSD_ALLOCATION
        assert out.waiting == ["老王", "小红"]
        assert out.free_slots == []

    def test_each_pick_is_explained_by_the_slots_taken_before(self):
        out = outcome(rsd_data(PEOPLE6, WEEKS, RSD_PREFS))
        picks = {t.person: (t.slot, t.rank, t.passed) for t in out.turns}
        assert picks["阿明"] == ("春节前一周", 1, [])
        assert picks["Yuki"] == ("端午", 2, ["春节前一周"])
        assert picks["Coco"] == ("五一", 4, ["春节前一周", "国庆后一周", "端午"])
        assert picks["老王"] == (None, None, ["五一", "春节前一周", "国庆后一周", "端午"])

    def test_the_independent_reference_agrees(self):
        assert reference_order("rsd_v1", PEOPLE6, 4, SOURCE) == RSD_ORDER


class TestExamplesFolder:
    def test_the_tickets_example_is_the_demo_input(self):
        assert load_example("tickets_8_for_3.json") == json.loads(sl.DEMO_JSON)

    def test_the_tickets_example_gives_the_recorded_values(self):
        out = outcome(load_example("tickets_8_for_3.json"))
        assert out.order == GOLDEN_ORDER and out.winners == GOLDEN_WINNERS

    def test_the_shifts_example_gives_the_recorded_values(self):
        out = outcome(load_example("shifts_rsd.json"))
        assert out.order == RSD_ORDER
        assert out.allocation == RSD_ALLOCATION

    def test_the_commit_reveal_example_is_a_complete_valid_round(self):
        data = load_example("commit_reveal.json")
        out = outcome(data)
        assert [c.status for c in out.checks] == ["ok"] * 6
        assert out.removed == []
        assert sorted(out.order) == sorted(data["people"])
        assert len(out.winners) == 2

    def test_the_commit_reveal_example_commitments_were_made_by_the_script(self):
        data = load_example("commit_reveal.json")
        commitments = {e["name"]: e["commitment"] for e in data["commit_reveal"]["commitments"]}
        reveals = {e["name"]: e["reveal"] for e in data["commit_reveal"]["reveals"]}
        assert set(commitments) == set(reveals) == set(data["people"])
        for person, code in reveals.items():
            digest, _ = sl.make_commitment(person, code)
            assert digest == commitments[person]

    @pytest.mark.parametrize(
        "name",
        [
            "tickets_8_for_3.json",
            "shifts_rsd.json",
            "commit_reveal.json",
            "ps_holiday_weeks.json",
            "da_parking.json",
        ],
    )
    def test_each_example_runs_from_the_command_line(self, name):
        done = run_script("--input", str(EXAMPLES / name))
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
        "demo_group_en.txt": ["--demo", "--format", "group", "--lang", "en"],
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

    def test_demo_json_carries_the_recorded_values(self):
        parsed = json.loads(run_script("--demo", "--json").stdout)
        assert parsed["result"]["order"] == GOLDEN_ORDER
        assert parsed["result"]["seed_hex"] == GOLDEN_SEED
        assert parsed["reproduce"] == "python3 scripts/slot_lottery.py --demo --json"

    def test_demo_from_json_input_gives_the_same_result(self):
        by_input = run_json(json.loads(sl.DEMO_JSON), "--json")
        by_demo = run_script("--demo", "--json")
        assert json.loads(by_input.stdout)["result"] == json.loads(by_demo.stdout)["result"]


class TestStoredCopiesOfOtherExamples:
    """The shifts, commit-reveal, ps and da examples have stored copies too."""

    CASES: ClassVar[dict] = {
        "shifts_md_zh.txt": ("shifts_rsd.json", []),
        "shifts_dm_zh.txt": ("shifts_rsd.json", ["--format", "dm"]),
        "shifts_group_zh.txt": ("shifts_rsd.json", ["--format", "group"]),
        "commit_reveal_md_zh.txt": ("commit_reveal.json", []),
        "commit_reveal_group_en.txt": ("commit_reveal.json", ["--format", "group", "--lang", "en"]),
        "ps_holiday_md_zh.txt": ("ps_holiday_weeks.json", []),
        "ps_holiday_dm_zh.txt": ("ps_holiday_weeks.json", ["--format", "dm"]),
        "ps_holiday_group_zh.txt": ("ps_holiday_weeks.json", ["--format", "group"]),
        "ps_holiday_group_en.txt": ("ps_holiday_weeks.json", ["--format", "group", "--lang", "en"]),
        "ps_holiday_json.txt": ("ps_holiday_weeks.json", ["--json"]),
        "da_parking_md_zh.txt": ("da_parking.json", []),
        "da_parking_dm_zh.txt": ("da_parking.json", ["--format", "dm"]),
        "da_parking_group_zh.txt": ("da_parking.json", ["--format", "group"]),
        "da_parking_group_en.txt": ("da_parking.json", ["--format", "group", "--lang", "en"]),
        "da_parking_json.txt": ("da_parking.json", ["--json"]),
    }

    @pytest.mark.parametrize("name", sorted(CASES))
    def test_output_matches_the_stored_copy(self, name):
        example, flags = self.CASES[name]
        done = run_script("--input", str(EXAMPLES / example), *flags)
        assert done.returncode == 0, done.stderr
        stored = GOLDEN_DIR / name
        if os.environ.get("FSQ_UPDATE_GOLDEN") == "1":
            GOLDEN_DIR.mkdir(exist_ok=True)
            stored.write_text(done.stdout, encoding="utf-8", newline="\n")
        assert done.stdout == stored.read_text(encoding="utf-8"), (
            f"{name} differs from the stored copy. If the change is intended, rerun with "
            "FSQ_UPDATE_GOLDEN=1 and review the diff."
        )


class TestTheDefaultMethodIsUnchanged:
    """Naming the default method, rsd, in the rules changes nothing, and the new fields are
    refused by the two old setups, so their inputs and outputs are the ones recorded above."""

    @pytest.mark.parametrize(
        "flags", [[], ["--format", "dm"], ["--format", "group"], ["--json"], ["--lang", "en"]]
    )
    def test_naming_rsd_in_the_rules_prints_the_same_bytes_as_leaving_it_out(self, flags):
        plain = load_example("shifts_rsd.json")
        named = json.loads(json.dumps(plain))
        named["rules"]["method"] = "rsd"
        by_plain = run_json(plain, *flags)
        by_name = run_json(named, *flags)
        assert by_plain.returncode == by_name.returncode == 0, by_name.stderr
        assert by_plain.stdout == by_name.stdout != ""

    def test_the_old_examples_have_no_method_and_print_no_method(self):
        for name in ("tickets_8_for_3.json", "shifts_rsd.json", "commit_reveal.json"):
            data = load_example(name)
            assert "method" not in data.get("rules", {})
            parsed = json.loads(run_json(data, "--json").stdout)
            assert "method" not in parsed["inputs_echo"]
            assert parsed["result"]["rule"] in ("uniform_lottery_v1", "rsd_v1")
