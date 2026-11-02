"""Commit-reveal: valid reveals pass, a tampered reveal fails, and a missing or failed reveal is
handled exactly as the rules declared before the draw."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from fractions import Fraction

import fsq_core as fc
import pytest
import slot_lottery as sl
from lottery_reference import reference_order
from lottery_support import PEOPLE8, code_for, lottery_data, reveal_data, run_json, run_script

PEOPLE = ["甲", "乙", "丙", "丁", "戊"]
RULE = "uniform_lottery_v1"


def outcome(data):
    return sl.compute(sl.parse_problem(data))


def statuses(out):
    return {check.person: check.status for check in out.checks}


def source_of(data, who):
    """The text that seeds the draw: the canonical JSON of the verified reveal codes."""
    return fc.canonical_json({p: code_for(p) for p in who})


# ---------------------------------------------------------------------------------------
# Making and checking commitments
# ---------------------------------------------------------------------------------------


class TestCommitments:
    def test_a_commitment_round_trips(self):
        digest, code = sl.make_commitment("甲")
        assert re.fullmatch(r"[0-9a-f]{64}", digest)
        assert re.fullmatch(r"[0-9a-f]{32}", code)
        assert fc.verify_commit(digest, sl.commit_payload("甲"), code)

    def test_the_digest_follows_the_documented_formula(self):
        digest, code = sl.make_commitment("阿明", code_for("阿明"))
        text = f'fsq-commit-v1\n{code_for("阿明")}\n{{"person":"阿明"}}'
        assert digest == hashlib.sha256(text.encode("utf-8")).hexdigest()
        assert code == code_for("阿明")

    def test_the_reveal_code_comes_from_the_system_random_generator(self, monkeypatch):
        monkeypatch.setattr(fc.secrets, "token_hex", lambda n: "ab" * n)
        digest, code = sl.make_commitment("甲")
        assert code == "ab" * 16
        assert fc.verify_commit(digest, sl.commit_payload("甲"), code)

    def test_every_commitment_is_fresh(self):
        made = {sl.make_commitment("甲") for _ in range(30)}
        assert len(made) == 30

    def test_a_commitment_belongs_to_one_person(self):
        digest, code = sl.make_commitment("甲")
        assert not fc.verify_commit(digest, sl.commit_payload("乙"), code)

    def test_a_changed_code_does_not_verify(self):
        digest, code = sl.make_commitment("甲")
        other = code_for("甲", "other")
        assert other != code
        assert not fc.verify_commit(digest, sl.commit_payload("甲"), other)


# ---------------------------------------------------------------------------------------
# Checking the reveals of a round
# ---------------------------------------------------------------------------------------


class TestChecking:
    def test_valid_reveals_pass(self):
        out = outcome(reveal_data(PEOPLE))
        assert set(statuses(out).values()) == {"ok"}
        assert out.removed == [] and out.penalized == []
        assert sorted(out.order) == sorted(PEOPLE)
        assert out.reasons == {p: [] for p in PEOPLE}

    def test_the_source_text_is_the_canonical_join_of_the_sorted_verified_reveals(self):
        out = outcome(reveal_data(PEOPLE))
        expected = json.dumps(
            {p: code_for(p) for p in sorted(PEOPLE)},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        assert out.source_text == expected
        assert out.source_text == source_of(None, PEOPLE)
        assert list(json.loads(out.source_text)) == sorted(PEOPLE)

    def test_the_order_is_the_draw_over_that_source(self):
        out = outcome(reveal_data(PEOPLE, n_slots=2))
        assert out.order == reference_order(RULE, PEOPLE, 2, source_of(None, PEOPLE))

    def test_a_tampered_reveal_fails(self):
        out = outcome(reveal_data(PEOPLE, tampered=["丙"]))
        assert statuses(out)["丙"] == "mismatch"
        assert [c.status for c in out.checks].count("ok") == 4
        assert out.removed == ["丙"]
        assert "丙" not in out.order

    def test_a_reveal_cannot_be_used_by_somebody_else(self):
        data = reveal_data(PEOPLE)
        reveals = {e["name"]: e["reveal"] for e in data["commit_reveal"]["reveals"]}
        for entry in data["commit_reveal"]["reveals"]:
            if entry["name"] == "乙":
                entry["reveal"] = reveals["甲"]  # 乙 posts 甲's code
        out = outcome(data)
        assert statuses(out)["乙"] == "mismatch"

    def test_a_commitment_without_a_reveal(self):
        out = outcome(reveal_data(PEOPLE, revealing=PEOPLE[:4]))
        assert statuses(out)["戊"] == "no_reveal"
        assert out.reasons["戊"] == ["no_reveal"]

    def test_a_reveal_without_a_commitment_does_not_count(self):
        out = outcome(reveal_data(PEOPLE, committing=PEOPLE[:4], revealing=PEOPLE))
        assert statuses(out)["戊"] == "no_commitment"
        assert "戊" not in json.loads(out.source_text)
        assert out.removed == ["戊"]

    def test_neither_a_commitment_nor_a_reveal(self):
        out = outcome(reveal_data(PEOPLE, committing=PEOPLE[:4], revealing=PEOPLE[:4]))
        assert statuses(out)["戊"] == "no_commitment"

    def test_uppercase_hex_is_accepted_and_gives_the_same_draw(self):
        data = reveal_data(PEOPLE)
        loud = copy.deepcopy(data)
        for key, field in (("commitments", "commitment"), ("reveals", "reveal")):
            for entry in loud["commit_reveal"][key]:
                entry[field] = entry[field].upper()
        assert outcome(loud).order == outcome(data).order
        assert set(statuses(outcome(loud)).values()) == {"ok"}

    def test_the_listing_order_of_commitments_and_reveals_is_irrelevant(self):
        data = reveal_data(PEOPLE, revealing=PEOPLE[:4], tampered=["乙"])
        flipped = copy.deepcopy(data)
        flipped["commit_reveal"]["commitments"].reverse()
        flipped["commit_reveal"]["reveals"].reverse()
        flipped["people"].reverse()
        assert fc.envelope(sl.solve(data)) == fc.envelope(sl.solve(flipped))

    def test_a_changed_reveal_changes_the_seed(self):
        base = outcome(reveal_data(PEOPLE, salt="one"))
        other = outcome(reveal_data(PEOPLE, salt="two"))
        assert base.draws[0].seed_hex != other.draws[0].seed_hex

    def test_the_same_round_gives_the_same_bytes(self):
        data = reveal_data(PEOPLE, revealing=PEOPLE[:4])
        first = run_json(data, "--format", "group")
        second = run_json(data, "--format", "group")
        assert first.returncode == 0, first.stderr
        assert first.stdout == second.stdout


# ---------------------------------------------------------------------------------------
# The declared handling of a missing or failed reveal
# ---------------------------------------------------------------------------------------


class TestForfeit:
    """For good slots: no verified reveal, no place in the draw."""

    def test_the_person_is_out_before_the_draw(self):
        data = reveal_data(PEOPLE, revealing=PEOPLE[:4], non_reveal="forfeit", n_slots=2)
        out = outcome(data)
        assert out.removed == ["戊"]
        assert "戊" not in out.order and "戊" not in out.winners and "戊" not in out.waiting
        assert out.draws[0].members == sorted(PEOPLE[:4])
        assert out.order == reference_order(RULE, PEOPLE[:4], 2, source_of(None, PEOPLE[:4]))

    def test_a_failed_reveal_and_a_missing_one_are_treated_alike(self):
        data = reveal_data(PEOPLE, revealing=PEOPLE[:4], tampered=["丙"], non_reveal="forfeit")
        out = outcome(data)
        assert out.removed == sorted(["丙", "戊"])
        assert sorted(out.order) == sorted(["甲", "乙", "丁"])

    def test_it_is_reported_in_every_format(self):
        data = reveal_data(PEOPLE, revealing=PEOPLE[:4], non_reveal="forfeit")
        assert "退出抽签" in run_json(data).stdout
        assert "戊" in run_json(data, "--format", "group").stdout
        assert "退出这次抽签" in run_json(data, "--format", "dm").stdout
        english = run_json(data, "--format", "dm", "--lang", "en").stdout
        assert "out of this draw" in english
        envelope = json.loads(run_json(data, "--json").stdout)
        assert envelope["result"]["removed"] == ["戊"]
        assert envelope["result"]["lapses"] == {"戊": {"reasons": ["no_reveal"], "tier": "out"}}
        assert envelope["certificate"]["reveal_check"]["戊"]["status"] == "no_reveal"

    def test_it_works_for_pick_in_turn_too(self):
        data = reveal_data(
            PEOPLE,
            revealing=PEOPLE[:4],
            mode="rsd",
            slots=["x", "y"],
            prefs={p: ["x", "y"] for p in PEOPLE},
        )
        out = outcome(data)
        assert out.removed == ["戊"]
        assert sorted(out.order) == sorted(PEOPLE[:4])
        assert len(out.allocation) == 2


class TestAssigned:
    """For chores: no verified reveal, and the chore is yours."""

    def test_the_person_is_placed_first_in_the_lottery(self):
        data = reveal_data(PEOPLE, revealing=PEOPLE[:4], non_reveal="assigned", n_slots=2)
        out = outcome(data)
        assert out.order[0] == "戊"
        assert "戊" in out.winners
        assert out.penalized == ["戊"]
        assert out.removed == []
        rest = reference_order(RULE, PEOPLE[:4], 2, source_of(None, PEOPLE[:4]))
        assert out.order[1:] == rest, "the others are drawn among themselves for what is left"

    def test_with_more_people_without_a_reveal_than_slots_they_are_drawn_among_themselves(self):
        data = reveal_data(PEOPLE, revealing=PEOPLE[:2], non_reveal="assigned", n_slots=2)
        out = outcome(data)
        lapsed = sorted(["丙", "丁", "戊"])
        assert sorted(out.order[:3]) == lapsed
        assert out.order[:3] == reference_order(RULE, lapsed, 2, source_of(None, PEOPLE[:2]))
        assert out.winners == out.order[:2]
        assert out.order[3:] == reference_order(RULE, PEOPLE[:2], 2, source_of(None, PEOPLE[:2]))

    def test_two_separate_draws_are_reported(self):
        data = reveal_data(PEOPLE, revealing=PEOPLE[:4], non_reveal="assigned")
        out = outcome(data)
        assert [d.group for d in out.draws] == ["main", "penalty"]
        assert out.draws[1].members == ["戊"]
        for draw in out.draws:
            assert hashlib.sha256(draw.preimage.encode()).hexdigest() == draw.seed_hex

    def test_it_is_reported_in_every_format(self):
        data = reveal_data(PEOPLE, revealing=PEOPLE[:4], non_reveal="assigned")
        assert "直接排在最前面" in run_json(data).stdout
        assert "直接排在最前面" in run_json(data, "--format", "group").stdout
        assert "直接排在最前面" in run_json(data, "--format", "dm").stdout
        assert "placed first" in run_json(data, "--format", "dm", "--lang", "en").stdout

    def test_in_pick_in_turn_the_person_picks_last(self):
        slots = ["x", "y", "z"]
        data = reveal_data(
            PEOPLE,
            revealing=PEOPLE[:4],
            non_reveal="assigned",
            mode="rsd",
            slots=slots,
            prefs={p: slots for p in PEOPLE},
        )
        out = outcome(data)
        assert out.order[-1] == "戊"
        assert out.penalized == ["戊"]
        assert "戊" not in out.allocation, "the three slots were gone before their turn"
        assert out.waiting[-1] == "戊"


# ---------------------------------------------------------------------------------------
# At least two verified reveals
# ---------------------------------------------------------------------------------------


class TestMinimumReveals:
    def test_one_verified_reveal_is_not_enough(self):
        data = reveal_data(PEOPLE, revealing=["甲"])
        with pytest.raises(fc.NoSolution):
            outcome(data)
        done = run_json(data)
        assert done.returncode == 3, done.stderr
        assert "only 1 of 5 reveals" in done.stderr and done.stdout == ""

    def test_nobody_revealing_is_not_enough_either(self):
        done = run_json(reveal_data(PEOPLE, revealing=[]))
        assert done.returncode == 3

    def test_two_are_enough(self):
        out = outcome(reveal_data(PEOPLE, revealing=["甲", "乙"], n_slots=1))
        assert sorted(out.order) == ["乙", "甲"]
        assert sorted(out.removed) == sorted(["丙", "丁", "戊"])

    def test_nobody_left_to_draw_is_no_solution(self):
        data = reveal_data(
            ["甲", "乙", "丙"],
            revealing=["甲", "乙"],
            mode="rsd",
            slots=["x"],
            prefs={"丙": ["x"]},
        )
        # 甲 and 乙 revealed but sent no ranking, 丙 sent one but did not reveal: all are out
        with pytest.raises(fc.NoSolution):
            outcome(data)
        assert run_json(data).returncode == 3


# ---------------------------------------------------------------------------------------
# The warning and the numbers behind it
# ---------------------------------------------------------------------------------------


class TestTheWarning:
    def test_every_commit_reveal_output_carries_the_warning(self):
        data = reveal_data(PEOPLE)
        for flags, words in (
            ((), ("提醒", "0.375", "0.643")),
            (("--format", "group"), ("提醒", "0.375", "0.643")),
            (("--lang", "en"), ("Warning", "0.375", "0.643")),
            (("--format", "group", "--lang", "en"), ("Warning", "0.375", "0.643")),
        ):
            text = run_json(data, *flags).stdout
            for word in words:
                assert word in text, (flags, word)

    def test_a_public_source_draw_has_no_such_warning(self):
        text = run_json(lottery_data(PEOPLE8, 3)).stdout
        assert "提醒" not in text and "0.643" not in text

    def test_the_numbers_in_the_warning_are_exact_values(self):
        """3 tickets among 8 people. If the last person to reveal can choose between 'reveal'
        (a draw among 8) and 'withhold' (a draw among 7, she is out), her friend wins if
        either draw picks him."""
        either = 1 - (1 - Fraction(3, 8)) * (1 - Fraction(3, 7))
        assert either == Fraction(9, 14)
        assert f"{float(either):.3f}" == "0.643"
        assert f"{3 / 8:.3f}" == "0.375"
        # as a chore: withholding makes her take one of the three, the other two are drawn
        # among 7; her friend is drafted only if both choices draft him
        both = Fraction(3, 8) * Fraction(2, 7)
        assert both == Fraction(3, 28)
        assert f"{float(both):.3f}" == "0.107"

    def test_a_simulation_with_the_real_draw_gives_the_same_numbers(self):
        last, friend = "Mia", "阿明"
        others = [p for p in PEOPLE8 if p != last]
        n = 6000
        alone = good = chore = 0
        for t in range(n):
            codes = {p: f"{t:05d}-{p}" for p in PEOPLE8}
            full = sl.reveal_source(codes)
            part = sl.reveal_source({p: codes[p] for p in others})
            order_full = sl.make_draw("main", PEOPLE8, RULE, 3, full).order
            order_part = sl.make_draw("main", others, RULE, 3, part).order
            win_full = friend in order_full[:3]
            win_part = friend in order_part[:3]
            alone += win_full
            good += win_full or win_part
            chore += win_full and friend in order_part[:2]
        assert abs(alone / n - 0.375) < 0.03
        assert abs(good / n - 9 / 14) < 0.03
        assert abs(chore / n - 3 / 28) < 0.03

    def test_withholding_in_the_pipeline_is_the_draw_among_the_others(self):
        data = reveal_data(PEOPLE8, revealing=[p for p in PEOPLE8 if p != "Mia"], n_slots=3)
        out = outcome(data)
        others = [p for p in PEOPLE8 if p != "Mia"]
        source = fc.canonical_json({p: code_for(p) for p in others})
        assert out.order == reference_order(RULE, others, 3, source)
        assert out.removed == ["Mia"]


# ---------------------------------------------------------------------------------------
# Input checks for the commit_reveal block and its rules
# ---------------------------------------------------------------------------------------


def mutated(**changes):
    """The all-revealed round with some parts replaced: key path -> value (None deletes)."""
    data = reveal_data(PEOPLE)
    for path, value in changes.items():
        target = data
        keys = path.split("/")
        for key in keys[:-1]:
            target = target[int(key)] if isinstance(target, list) else target[key]
        last = keys[-1]
        if isinstance(target, list):
            last = int(last)
        if value is None:
            del target[last]
        else:
            target[last] = value
    return data


BAD_ROUNDS = [
    (
        "unknown name",
        mutated(**{"commit_reveal/commitments/0/name": "陌生人"}),
        "commitments[0].name",
    ),
    (
        "commitment listed twice",
        mutated(**{"commit_reveal/commitments/1/name": "甲"}),
        "commitments[1].name",
    ),
    (
        "commitment not hex",
        mutated(**{"commit_reveal/commitments/0/commitment": "xyz"}),
        "commitment",
    ),
    (
        "commitment too short",
        mutated(**{"commit_reveal/commitments/0/commitment": "ab" * 31}),
        "commitments[0].commitment",
    ),
    (
        "reveal too short",
        mutated(**{"commit_reveal/reveals/2/reveal": "ab" * 15}),
        "reveals[2].reveal",
    ),
    ("reveal not text", mutated(**{"commit_reveal/reveals/2/reveal": 5}), "reveals[2].reveal"),
    ("reveal listed twice", mutated(**{"commit_reveal/reveals/3/name": "甲"}), "reveals[3].name"),
    (
        "extra field in an entry",
        mutated(**{"commit_reveal/reveals/0/extra": "x"}),
        "reveals[0].extra",
    ),
    ("entry without a name", mutated(**{"commit_reveal/reveals/0/name": None}), "reveals[0].name"),
    ("commit_reveal not an object", mutated(commit_reveal=[1]), "commit_reveal"),
    ("no commitments", mutated(**{"commit_reveal/commitments": []}), "commitments"),
    ("reveals missing", mutated(**{"commit_reveal/reveals": None}), "reveals"),
    ("unknown block field", mutated(**{"commit_reveal/extra": 1}), "commit_reveal.extra"),
    ("non_reveal missing", mutated(**{"rules/non_reveal": None}), "rules.non_reveal"),
    ("non_reveal unknown", mutated(**{"rules/non_reveal": "ignore"}), "rules.non_reveal"),
    ("deadline missing", mutated(**{"rules/deadline": None}), "rules.deadline"),
    (
        "both randomness inputs",
        mutated(random_source="the draw numbers"),
        "commit_reveal",
    ),
]


@pytest.mark.parametrize(("label", "data", "field"), BAD_ROUNDS, ids=[b[0] for b in BAD_ROUNDS])
def test_a_bad_round_is_refused_with_the_field_named(label, data, field):
    with pytest.raises(fc.InputError) as caught:
        sl.parse_problem(data)
    assert field in caught.value.field, f"{label}: {caught.value.field}: {caught.value.message}"
    done = run_json(data)
    assert done.returncode == 2 and done.stdout == ""
    assert field in done.stderr and "Traceback" not in done.stderr


def test_non_reveal_without_commit_reveal_is_refused():
    data = lottery_data(PEOPLE8, 3)
    data["rules"]["non_reveal"] = "forfeit"
    done = run_json(data)
    assert done.returncode == 2 and "rules.non_reveal" in done.stderr


# ---------------------------------------------------------------------------------------
# The --commit command
# ---------------------------------------------------------------------------------------


class TestCommitCommand:
    def test_it_prints_a_commitment_and_a_reveal_code_that_verify(self):
        done = run_script("--commit", "--person", "阿明")
        assert done.returncode == 0, done.stderr
        digest = re.search(r"[0-9a-f]{64}", done.stdout).group(0)
        code = re.search(r"(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])", done.stdout).group(0)
        assert fc.verify_commit(digest, {"person": "阿明"}, code)
        assert '{"person":"阿明"}' in done.stdout

    def test_json_form(self):
        done = run_script("--commit", "--person", "Coco", "--json")
        assert done.returncode == 0, done.stderr
        record = json.loads(done.stdout)
        assert sorted(record) == ["commitment", "payload", "person", "reveal"]
        assert fc.verify_commit(record["commitment"], record["payload"], record["reveal"])

    def test_a_second_run_gives_different_codes(self):
        first = json.loads(run_script("--commit", "--person", "甲", "--json").stdout)
        second = json.loads(run_script("--commit", "--person", "甲", "--json").stdout)
        assert first["reveal"] != second["reveal"] and first["commitment"] != second["commitment"]

    def test_english_text_warns_not_to_let_somebody_else_run_it(self):
        done = run_script("--commit", "--person", "Alice", "--lang", "en")
        assert "your own device" in done.stdout and "keep it to yourself" in done.stdout

    def test_it_needs_a_person(self):
        done = run_script("--commit")
        assert done.returncode == 2 and "--person" in done.stderr

    def test_a_name_with_spaces_around_it_is_refused(self):
        done = run_script("--commit", "--person", " 甲")
        assert done.returncode == 2 and "--person" in done.stderr

    def test_a_commitment_made_by_the_command_works_in_a_round(self):
        people = ["甲", "乙", "丙"]
        made = {
            p: json.loads(run_script("--commit", "--person", p, "--json").stdout) for p in people
        }
        data = {
            "mode": "lottery",
            "people": people,
            "n_slots": 1,
            "rules": {"deadline": "d", "non_reveal": "forfeit"},
            "commit_reveal": {
                "commitments": [{"name": p, "commitment": made[p]["commitment"]} for p in people],
                "reveals": [{"name": p, "reveal": made[p]["reveal"]} for p in people],
            },
        }
        out = outcome(data)
        assert set(statuses(out).values()) == {"ok"}
        assert sorted(out.order) == sorted(people)
