"""Golden values: the recorded example with its 96 plans and 40 circles, the three-person case
that has no draw, a twelve-person draw by random proposals, the examples and a byte-stable demo."""

from __future__ import annotations

import hashlib
import json
import os
from typing import ClassVar

import fsq_core as fc
import gift_exchange as ge
import pytest
from gift_reference import (
    blocked_indexes,
    both_ways,
    enumeration_draw,
    legal_plans,
    rejection_draw,
    spec_seed,
)
from gift_support import (
    BLOCKED6,
    EXAMPLES,
    FORBIDDEN6,
    GOLDEN_COUNT,
    GOLDEN_DIR,
    GOLDEN_NUMBER,
    GOLDEN_PLAN,
    GOLDEN_RING_COUNT,
    GOLDEN_SEED,
    PEOPLE6,
    RING_CIRCLE,
    RING_NUMBER,
    RING_SEED,
    SOURCE,
    THREE,
    THREE_FORBIDDEN,
    TWELVE_ATTEMPTS,
    TWELVE_PLAN,
    TWELVE_SEED,
    directions,
    exchange_data,
    load_example,
    run_json,
    run_script,
    six_people,
)


def outcome(data):
    return ge.compute(ge.parse_problem(data))


class TestRecordedExample:
    """Six people, two couples, and Lao Wang gave to Yuki last year."""

    def test_there_are_96_legal_plans_and_40_of_them_are_single_circles(self):
        problem = ge.parse_problem(six_people())
        assert len(ge.list_plans(problem.allowed, ring=False)) == GOLDEN_COUNT
        assert len(ge.list_plans(problem.allowed, ring=True)) == GOLDEN_RING_COUNT

    def test_a_search_over_all_720_permutations_finds_the_same_plans(self):
        problem = ge.parse_problem(six_people())
        blocked = blocked_indexes(PEOPLE6, BLOCKED6)
        assert ge.list_plans(problem.allowed, ring=False) == legal_plans(6, blocked, False)
        assert ge.list_plans(problem.allowed, ring=True) == legal_plans(6, blocked, True)

    def test_seed_plan_number_and_plan_match_the_recorded_values(self):
        out = outcome(six_people())
        assert out.draw.seed_hex == GOLDEN_SEED
        assert out.draw.count == GOLDEN_COUNT
        assert out.draw.number == GOLDEN_NUMBER
        assert out.draw.method == "enumeration" and out.draw.attempts is None
        assert out.receiver_of == GOLDEN_PLAN
        assert out.circle is None

    def test_the_command_line_prints_the_same_values(self):
        done = run_json(six_people(), "--json")
        assert done.returncode == 0, done.stderr
        parsed = json.loads(done.stdout)
        result = parsed["result"]
        assert result["seed_hex"] == GOLDEN_SEED
        assert result["plan_count"] == GOLDEN_COUNT and result["plan_number"] == GOLDEN_NUMBER
        assert result["assignments"] == GOLDEN_PLAN
        assert result["rule"] == "gift_exchange_any_enum_v1"
        assert result["method"] == "enumeration"
        assert parsed["certificate"]["recompute"]["plan_number"] == GOLDEN_NUMBER

    def test_the_independent_reference_agrees(self):
        assert spec_seed("gift_exchange_any_enum_v1", PEOPLE6, 6, SOURCE).hex() == GOLDEN_SEED
        plan, number, count = enumeration_draw(PEOPLE6, BLOCKED6, False, SOURCE)
        assert (number, count) == (GOLDEN_NUMBER, GOLDEN_COUNT)
        names = sorted(PEOPLE6)
        assert {names[i]: names[j] for i, j in enumerate(plan)} == GOLDEN_PLAN

    def test_the_printed_preimage_hashes_to_the_seed(self):
        out = outcome(six_people())
        preimage = out.draw.preimage
        assert hashlib.sha256(preimage.encode("utf-8")).hexdigest() == GOLDEN_SEED
        assert json.loads(preimage) == {
            "n_slots": 6,
            "participants": sorted(PEOPLE6),
            "rule": "gift_exchange_any_enum_v1",
            "source": SOURCE,
        }

    def test_the_shared_core_makes_the_same_seed(self):
        seed = fc.make_seed("gift_exchange_any_enum_v1", PEOPLE6, 6, SOURCE)
        assert seed.hex() == GOLDEN_SEED

    def test_the_demo_is_the_recorded_example(self):
        demo = json.loads(ge.DEMO_JSON)
        expected = six_people()
        expected["rules"] = demo["rules"]
        assert demo == expected

    def test_every_listed_gift_is_allowed(self):
        out = outcome(six_people())
        blocked = set(BLOCKED6)
        for giver, receiver in out.receiver_of.items():
            assert giver != receiver and (giver, receiver) not in blocked


class TestRecordedCircle:
    """The same people in one single circle: 40 plans, number 10 drawn."""

    def test_seed_number_and_circle_match_the_recorded_values(self):
        out = outcome(six_people("ring"))
        assert out.draw.seed_hex == RING_SEED
        assert out.draw.rule == "gift_exchange_ring_enum_v1"
        assert (out.draw.number, out.draw.count) == (RING_NUMBER, GOLDEN_RING_COUNT)
        assert out.circle == RING_CIRCLE

    def test_the_independent_reference_agrees(self):
        plan, number, count = enumeration_draw(PEOPLE6, BLOCKED6, True, SOURCE)
        assert (number, count) == (RING_NUMBER, GOLDEN_RING_COUNT)
        names = sorted(PEOPLE6)
        chain, person = [names[0]], plan[0]
        while person != 0:
            chain.append(names[person])
            person = plan[person]
        assert chain == RING_CIRCLE

    def test_the_way_of_giving_changes_the_seed(self):
        assert RING_SEED != GOLDEN_SEED

    def test_the_example_file_gives_the_recorded_values(self):
        out = outcome(load_example("six_circle.json"))
        assert out.draw.seed_hex == RING_SEED and out.circle == RING_CIRCLE


class TestThreePeopleWithACouple:
    """Hall's condition fails: Jia and Yi can only give to Bing, one person for two."""

    def test_there_is_no_legal_draw_and_the_reason_is_the_couple(self):
        with pytest.raises(ge.NoLegalPlan) as caught:
            ge.check_problem(
                ge.parse_problem({"people": THREE, "forbidden": THREE_FORBIDDEN}, check=True)
            )
        assert caught.value.kind == "hall"
        assert caught.value.group == ["甲", "乙"]
        assert caught.value.others == ["丙"]

    def test_the_message_has_both_languages_and_the_recorded_sentence(self):
        done = run_json(exchange_data(THREE, THREE_FORBIDDEN))
        assert done.returncode == 3 and done.stdout == ""
        assert "甲、乙这 2 个人能送的只有丙（1 人）" in done.stderr
        assert "甲, 乙 (2 people) can only give to 丙 (1 person)" in done.stderr

    def test_the_brute_force_search_agrees_there_is_nothing_to_draw(self):
        blocked = blocked_indexes(THREE, both_ways([("甲", "乙")]))
        assert legal_plans(3, blocked, False) == []

    def test_without_the_couple_there_are_two_plans(self):
        problem = ge.parse_problem({"people": THREE}, check=True)
        assert len(ge.list_plans(problem.allowed, ring=False)) == 2


class TestTwelvePeopleAreDrawnByProposals:
    def test_seed_attempt_and_plan_match_the_recorded_values(self):
        out = outcome(load_example("office_twelve.json"))
        assert out.draw.method == "rejection" and out.draw.rule == "gift_exchange_any_reject_v1"
        assert out.draw.seed_hex == TWELVE_SEED
        assert out.draw.attempts == TWELVE_ATTEMPTS
        assert out.draw.count is None and out.draw.number is None
        assert out.receiver_of == TWELVE_PLAN

    def test_the_independent_reference_agrees(self):
        data = load_example("office_twelve.json")
        blocked = [(a, b) for a, b in directions(data["forbidden"])]
        plan, attempts = rejection_draw(data["people"], blocked, False, data["random_source"])
        assert attempts == TWELVE_ATTEMPTS
        names = sorted(data["people"])
        assert {names[i]: names[j] for i, j in enumerate(plan)} == TWELVE_PLAN


class TestExamplesFolder:
    def test_the_six_person_example_is_the_demo_input(self):
        assert load_example("six_with_couples.json") == json.loads(ge.DEMO_JSON)

    def test_the_six_person_example_lists_the_recorded_exclusions(self):
        assert load_example("six_with_couples.json")["forbidden"] == FORBIDDEN6

    @pytest.mark.parametrize(
        "name", ["six_with_couples.json", "six_circle.json", "office_twelve.json"]
    )
    def test_each_example_runs_from_the_command_line(self, name):
        done = run_script("--input", str(EXAMPLES / name))
        assert done.returncode == 0, done.stderr
        assert done.stdout.startswith("# ")

    @pytest.mark.parametrize(
        "name", ["six_with_couples.json", "six_circle.json", "office_twelve.json"]
    )
    def test_each_example_passes_the_check_without_its_source(self, name):
        data = load_example(name)
        del data["random_source"], data["rules"]
        done = run_json(data, "--check")
        assert done.returncode == 0, done.stderr
        assert done.stdout.startswith("# ")

    def test_there_are_exactly_these_examples(self):
        assert sorted(path.name for path in EXAMPLES.glob("*.json")) == [
            "office_twelve.json",
            "six_circle.json",
            "six_with_couples.json",
        ]

    def test_the_examples_are_marked_as_made_up(self):
        for path in EXAMPLES.glob("*.json"):
            assert "虚构示例" in path.read_text(encoding="utf-8"), path.name


def check_stored(name: str, text: str) -> None:
    stored = GOLDEN_DIR / name
    if os.environ.get("FSQ_UPDATE_GOLDEN") == "1":
        GOLDEN_DIR.mkdir(exist_ok=True)
        stored.write_text(text, encoding="utf-8", newline="\n")
    assert text == stored.read_text(encoding="utf-8"), (
        f"{name} differs from the stored copy. If the change is intended, rerun with "
        "FSQ_UPDATE_GOLDEN=1 and review the diff."
    )


class TestDemoIsByteStable:
    """The demo prints the same bytes on every run and matches the stored copies."""

    CASES: ClassVar[dict] = {
        "demo_md_zh.txt": ["--demo"],
        "demo_md_en.txt": ["--demo", "--lang", "en"],
        "demo_dm_zh.txt": ["--demo", "--format", "dm"],
        "demo_dm_en.txt": ["--demo", "--format", "dm", "--lang", "en"],
        "demo_group_zh.txt": ["--demo", "--format", "group"],
        "demo_group_en.txt": ["--demo", "--format", "group", "--lang", "en"],
        "demo_json.txt": ["--demo", "--json"],
        "demo_check_zh.txt": ["--demo", "--check"],
        "demo_check_json.txt": ["--demo", "--check", "--json"],
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
        check_stored(name, done.stdout)

    def test_demo_json_carries_the_recorded_values(self):
        parsed = json.loads(run_script("--demo", "--json").stdout)
        assert parsed["result"]["seed_hex"] == GOLDEN_SEED
        assert parsed["reproduce"] == "python3 scripts/gift_exchange.py --demo --json"

    def test_demo_from_json_input_gives_the_same_result(self):
        by_input = run_json(json.loads(ge.DEMO_JSON), "--json")
        by_demo = run_script("--demo", "--json")
        assert json.loads(by_input.stdout)["result"] == json.loads(by_demo.stdout)["result"]


class TestStoredCopiesOfOtherExamples:
    """The circle and the twelve-person examples have stored copies too."""

    CASES: ClassVar[dict] = {
        "circle_md_zh.txt": ("six_circle.json", []),
        "circle_dm_zh.txt": ("six_circle.json", ["--format", "dm"]),
        "circle_group_en.txt": ("six_circle.json", ["--format", "group", "--lang", "en"]),
        "twelve_md_zh.txt": ("office_twelve.json", []),
        "twelve_group_zh.txt": ("office_twelve.json", ["--format", "group"]),
        "twelve_check_en.txt": ("office_twelve.json", ["--check", "--lang", "en"]),
    }

    @pytest.mark.parametrize("name", sorted(CASES))
    def test_output_matches_the_stored_copy(self, name):
        example, flags = self.CASES[name]
        done = run_script("--input", str(EXAMPLES / example), *flags)
        assert done.returncode == 0, done.stderr
        check_stored(name, done.stdout)
