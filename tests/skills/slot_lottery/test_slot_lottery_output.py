"""Output: every format renders, private messages stay private, and --verify round-trips."""

from __future__ import annotations

import copy
import json
import re

import fsq_core as fc
import pytest
import slot_lottery as sl
from lottery_support import (
    EXAMPLES,
    GOLDEN_ORDER,
    GOLDEN_SEED,
    PEOPLE6,
    PEOPLE8,
    RSD_ALLOCATION,
    RSD_ORDER,
    RSD_PREFS,
    SOURCE,
    WEEKS,
    da_data,
    load_example,
    lottery_data,
    ps_data,
    reveal_data,
    rsd_data,
    run_json,
    run_script,
)

ENVELOPE_KEYS = ["certificate", "inputs_echo", "not_modeled", "reproduce", "result"]
FORMATS = ["md", "dm", "group", "json"]


def all_inputs():
    """(label, data) for every example and a few shapes that reach the other branches."""
    cases = [(path.name, load_example(path.name)) for path in sorted(EXAMPLES.glob("*.json"))]
    people = ["甲", "乙", "丙", "丁", "戊"]
    cases += [
        ("everybody drawn", lottery_data(PEOPLE8, 8)),
        ("more slots than people", lottery_data(PEOPLE8, 20)),
        ("one slot", lottery_data(PEOPLE8, 1)),
        ("forfeit", reveal_data(people, revealing=people[:4], non_reveal="forfeit")),
        ("assigned", reveal_data(people, revealing=people[:4], non_reveal="assigned")),
        ("failed reveal", reveal_data(people, tampered=["丙"], non_reveal="assigned")),
        (
            "rsd with a person without a ranking",
            rsd_data(
                PEOPLE6,
                [*WEEKS, "元旦"],
                {k: v for k, v in RSD_PREFS.items() if k != "小红"},
                no_ranking="assigned",
            ),
        ),
        (
            "rsd with an empty ranking",
            rsd_data(PEOPLE6, WEEKS, dict(RSD_PREFS, 小红=[])),
        ),
        (
            "rsd with a person out",
            rsd_data(
                PEOPLE6,
                WEEKS,
                {k: v for k, v in RSD_PREFS.items() if k != "老王"},
                no_ranking="forfeit",
            ),
        ),
        (
            "ps with seats and a person who lists nothing",
            ps_data(PEOPLE6, [*WEEKS, "元旦"], dict(RSD_PREFS, 小红=[]), capacities={"五一": 2}),
        ),
        (
            "ps with a person out",
            ps_data(PEOPLE6, WEEKS, {k: v for k, v in RSD_PREFS.items() if k != "老王"}),
        ),
        (
            "ps with people who take what is left",
            ps_data(
                PEOPLE6,
                [*WEEKS, "元旦"],
                {k: v for k, v in RSD_PREFS.items() if k not in ("小红", "Coco")},
                no_ranking="assigned",
            ),
        ),
        (
            "da with seats and a slot nobody lists",
            da_data(PEOPLE6, [*WEEKS, "元旦"], RSD_PREFS, capacities={"五一": 2, "端午": 3}),
        ),
        (
            "da with a person out and a person who lists nothing",
            da_data(
                PEOPLE6,
                WEEKS,
                {k: v for k, v in dict(RSD_PREFS, 小红=[]).items() if k != "老王"},
                priorities={"五一": [["阿明", "Coco"], ["小红"]]},
            ),
        ),
        (
            "da with people who take what is left",
            da_data(
                PEOPLE6,
                [*WEEKS, "元旦"],
                {k: v for k, v in RSD_PREFS.items() if k not in ("小红", "Coco")},
                no_ranking="assigned",
            ),
        ),
        (
            "rsd commit-reveal with a lapse at the back",
            reveal_data(
                people,
                revealing=people[:4],
                non_reveal="assigned",
                mode="rsd",
                slots=["x", "y", "z"],
                prefs={p: ["x", "y", "z"] for p in people},
            ),
        ),
    ]
    return cases


CASES = all_inputs()
IDS = [case[0] for case in CASES]


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
        for bad in ("None", "Fraction(", "Traceback", "{pos}", "{names}", "{k}"):
            assert bad not in out, bad
    for name in data["people"]:
        assert name in out, f"{name} is missing from the {fmt} output"


@pytest.mark.parametrize(("label", "data"), CASES, ids=IDS)
def test_text_output_is_the_same_on_every_run(label, data):
    for flags in ([], ["--json"]):
        assert run_json(data, *flags).stdout == run_json(data, *flags).stdout


def test_both_languages_have_the_same_texts():
    assert set(sl.TEXT["zh"]) == set(sl.TEXT["en"])
    for key, zh in sl.TEXT["zh"].items():
        en = sl.TEXT["en"][key]
        assert type(zh) is type(en), key
        if isinstance(zh, list):
            assert len(zh) == len(en), key
        if isinstance(zh, str):
            placeholders = set(re.findall(r"\{[a-z]+\}", zh))
            assert placeholders == set(re.findall(r"\{[a-z]+\}", en)), key


def test_json_envelope_of_the_recorded_example():
    parsed = json.loads(run_script("--demo", "--json").stdout)
    assert sorted(parsed) == ENVELOPE_KEYS
    result = parsed["result"]
    assert result["order"] == GOLDEN_ORDER
    assert result["draws"][0]["participants"] == sorted(PEOPLE8)
    assert result["draws"][0]["seed_hex"] == GOLDEN_SEED
    assert result["removed"] == [] and result["placed_by_rule"] == [] and result["lapses"] == {}
    assert parsed["inputs_echo"]["participants"] == sorted(PEOPLE8)
    assert parsed["inputs_echo"]["randomness"] == "public_source"
    assert parsed["inputs_echo"]["random_source"] == SOURCE
    assert parsed["certificate"]["recompute"]["seeds"] == {"main": GOLDEN_SEED}
    assert parsed["certificate"]["recompute"]["algorithm"] == fc.SEED_SPEC
    assert parsed["not_modeled"]
    assert parsed["reproduce"].startswith("python3 scripts/slot_lottery.py")


def test_json_envelope_of_the_pick_in_turn_example():
    parsed = json.loads(run_json(rsd_data(PEOPLE6, WEEKS, RSD_PREFS), "--json").stdout)
    result = parsed["result"]
    assert result["order"] == RSD_ORDER
    assert result["allocation"] == dict(sorted(RSD_ALLOCATION.items()))
    assert result["waiting"] == ["老王", "小红"]
    assert result["unassigned_slots"] == []
    assert [t["person"] for t in result["turns"]] == RSD_ORDER
    assert result["turns"][2] == {
        "position": 3,
        "person": "Yuki",
        "slot": "端午",
        "rank": 2,
        "passed_over": ["春节前一周"],
    }
    assert result["turns"][4]["slot"] is None
    assert parsed["inputs_echo"]["prefs"]["阿明"] == RSD_PREFS["阿明"]


# ---------------------------------------------------------------------------------------
# Private messages and the group card
# ---------------------------------------------------------------------------------------


class TestPrivateMessages:
    def messages(self, data, lang="zh"):
        return fc.render_dm_messages(sl.solve(data, lang))

    @pytest.mark.parametrize("lang", ["zh", "en"])
    def test_a_lottery_message_is_one_line_with_the_result_and_the_position(self, lang):
        for person, text in self.messages(lottery_data(PEOPLE8, 3), lang).items():
            assert "\n" not in text
            position = GOLDEN_ORDER.index(person) + 1
            assert str(position) in text
            drawn = position <= 3
            if lang == "zh":
                assert ("你抽中了" in text) == drawn and ("你没有抽中" in text) == (not drawn)
            else:
                assert text.startswith("You are drawn") == drawn

    def test_every_person_gets_a_message_even_when_they_are_out(self):
        people = ["甲", "乙", "丙", "丁", "戊"]
        data = reveal_data(people, revealing=people[:4], non_reveal="forfeit")
        messages = self.messages(data)
        assert sorted(messages) == sorted(people)
        assert "退出这次抽签" in messages["戊"]

    @pytest.mark.parametrize(("label", "data"), CASES, ids=IDS)
    def test_no_message_names_another_person(self, label, data):
        for person, text in self.messages(data).items():
            for other in data["people"]:
                if other != person and len(other) > 1:
                    assert other not in text, f"{person}'s message names {other}"

    def test_a_pick_in_turn_message_repeats_only_the_persons_own_ranking(self):
        messages = self.messages(rsd_data(PEOPLE6, WEEKS, RSD_PREFS))
        for person, text in messages.items():
            own = " > ".join(RSD_PREFS[person])
            assert own in text
            for ranking in RSD_PREFS.values():
                if ranking != RSD_PREFS[person]:
                    assert " > ".join(ranking) not in text

    def test_the_result_lines_say_what_the_person_got(self):
        messages = self.messages(rsd_data(PEOPLE6, WEEKS, RSD_PREFS))
        assert "你挑到了「春节前一周」（你的第 1 志愿）" in messages["阿明"]
        assert "你挑到了「端午」（你的第 2 志愿）" in messages["Yuki"]
        assert "候补第 1 位" in messages["老王"] and "候补第 2 位" in messages["小红"]


class TestGroupCard:
    def card(self, data, lang="zh"):
        return fc.render_group(sl.solve(data, lang))

    def test_it_holds_the_order_and_everything_needed_to_recompute_it(self):
        text = self.card(lottery_data(PEOPLE8, 3))
        assert SOURCE in text
        assert GOLDEN_SEED in text
        assert "uniform_lottery_v1" in text
        assert "1 Yuki、2 小周、3 大刘、4 Coco、5 小红、6 阿明、7 Mia、8 老王" in text
        assert "抽中（前 3 位）：Yuki、小周、大刘" in text
        assert "候补（按顺序递补，不重抽）：Coco、小红、阿明、Mia、老王" in text

    def test_it_holds_the_source_description_and_the_deadline(self):
        data = lottery_data(PEOPLE8, 3)
        text = self.card(data)
        assert data["rules"]["source_description"] in text
        assert data["rules"]["deadline"] in text

    def test_it_does_not_hold_any_ranking(self):
        text = self.card(rsd_data(PEOPLE6, WEEKS, RSD_PREFS))
        assert "志愿顺序" not in text and " > " not in text
        for ranking in RSD_PREFS.values():
            assert " > ".join(ranking) not in text
        assert "1 阿明 挑到「春节前一周」" in text
        assert "5 老王 候补 1" in text

    def test_the_preimage_in_the_card_hashes_to_the_seed_in_the_card(self):
        import hashlib
        import re

        text = self.card(lottery_data(PEOPLE8, 3))
        preimage = re.search(r"种子原像.*?：(\{.*\})", text).group(1)
        assert hashlib.sha256(preimage.encode("utf-8")).hexdigest() == GOLDEN_SEED

    def test_it_never_claims_that_cheating_is_impossible(self):
        for lang in ("zh", "en"):
            for data in (lottery_data(PEOPLE8, 3), load_example("commit_reveal.json")):
                result = sl.solve(data, lang)
                text = fc.render_md(result, lang) + fc.render_group(result)
                for phrase in (
                    "无法作弊",
                    "不可能作弊",
                    "谁也做不了手脚",
                    "cannot cheat",
                    "tamper-proof",
                ):
                    assert phrase not in text


# ---------------------------------------------------------------------------------------
# --verify
# ---------------------------------------------------------------------------------------


def claimed_from(data, with_seed=True, with_allocation=False):
    """The `claimed` block a result card would carry, from a real run."""
    result = json.loads(run_json(data, "--json").stdout)["result"]
    claimed = {"order": result["order"]}
    if with_seed:
        claimed["seed"] = result["seed_hex"]
    if with_allocation:
        claimed["allocation"] = result["allocation"]
    return claimed


class TestVerify:
    def test_a_round_trip_matches(self):
        data = lottery_data(PEOPLE8, 3)
        done = run_json(dict(data, claimed=claimed_from(data)), "--verify")
        assert done.returncode == 0, done.stdout + done.stderr
        assert "复算核对：一致" in done.stdout and "可以复现" in done.stdout

    def test_the_recorded_order_matches(self):
        data = dict(lottery_data(PEOPLE8, 3), claimed={"order": GOLDEN_ORDER, "seed": GOLDEN_SEED})
        assert run_json(data, "--verify").returncode == 0

    def test_a_swapped_pair_is_found(self):
        data = lottery_data(PEOPLE8, 3)
        claimed = claimed_from(data)
        claimed["order"][0], claimed["order"][1] = claimed["order"][1], claimed["order"][0]
        done = run_json(dict(data, claimed=claimed), "--verify")
        assert done.returncode == 1
        assert "不一致" in done.stdout and "第 1 位" in done.stdout
        assert done.stderr == ""

    def test_a_different_name_is_found(self):
        data = lottery_data(PEOPLE8, 3)
        claimed = claimed_from(data)
        claimed["order"][3] = "路人"
        done = run_json(dict(data, claimed=claimed), "--verify", "--lang", "en")
        assert done.returncode == 1
        assert "the names differ" in done.stdout and "路人" in done.stdout

    def test_a_wrong_seed_alone_is_found(self):
        data = lottery_data(PEOPLE8, 3)
        claimed = claimed_from(data)
        claimed["seed"] = "0" * 64
        done = run_json(dict(data, claimed=claimed), "--verify")
        assert done.returncode == 1 and "种子" in done.stdout

    def test_the_published_source_can_be_typed_in_again(self):
        data = lottery_data(PEOPLE8, 3)
        no_source = {k: v for k, v in data.items() if k != "random_source"}
        done = run_json(dict(no_source, claimed=claimed_from(data)), "--verify", "--source", SOURCE)
        assert done.returncode == 0, done.stdout + done.stderr

    def test_a_card_that_prints_a_different_source_is_caught(self):
        """The order is the true one, but the source text printed on the card would not give
        it, so the card does not verify by itself."""
        data = lottery_data(PEOPLE8, 3)
        card = dict(data, random_source="（虚构示例）another draw", claimed=claimed_from(data))
        done = run_json(card, "--verify", "--source", SOURCE)
        assert done.returncode == 1
        assert "随机源原文" in done.stdout and "和卡片上的不同" in done.stdout
        assert "6 个名字" not in done.stdout and "8 个名字的顺序完全一致" in done.stdout

    def test_a_wrong_source_gives_a_different_order(self):
        data = lottery_data(PEOPLE8, 3)
        done = run_json(
            dict(data, claimed=claimed_from(data)), "--verify", "--source", SOURCE + " "
        )
        assert done.returncode == 1

    def test_pick_in_turn_allocation_is_verified_too(self):
        data = rsd_data(PEOPLE6, WEEKS, RSD_PREFS)
        claimed = claimed_from(data, with_allocation=True)
        assert run_json(dict(data, claimed=claimed), "--verify").returncode == 0
        claimed["allocation"]["Yuki"] = "五一"
        done = run_json(dict(data, claimed=claimed), "--verify")
        assert done.returncode == 1 and "Yuki" in done.stdout and "分配结果" in done.stdout

    def test_a_missing_allocation_entry_is_found(self):
        data = rsd_data(PEOPLE6, WEEKS, RSD_PREFS)
        claimed = claimed_from(data, with_allocation=True)
        claimed["allocation"]["老王"] = "五一"  # 老王 got nothing
        assert run_json(dict(data, claimed=claimed), "--verify").returncode == 1

    @pytest.mark.parametrize("example", ["ps_holiday_weeks.json", "da_parking.json"])
    def test_a_ps_or_da_round_trip_matches_and_a_changed_allocation_does_not(self, example):
        data = load_example(example)
        result = json.loads(run_json(data, "--json").stdout)["result"]
        claimed = {"allocation": result["allocation"], "seed": result["seed_hex"]}
        if "order" in result:
            claimed["order"] = result["order"]
        done = run_json(dict(data, claimed=claimed), "--verify")
        assert done.returncode == 0, done.stdout + done.stderr
        assert "复算核对：一致" in done.stdout
        wrong = dict(claimed, allocation=dict(claimed["allocation"], Coco="某个不存在的时段"))
        done = run_json(dict(data, claimed=wrong), "--verify")
        assert done.returncode == 1 and "Coco" in done.stdout and "分配结果" in done.stdout
        reordered = dict(data, people=list(reversed(data["people"])), claimed=claimed)
        assert run_json(reordered, "--verify").returncode == 0

    def test_a_da_card_with_another_lottery_order_does_not_verify(self):
        data = load_example("da_parking.json")
        result = json.loads(run_json(data, "--json").stdout)["result"]
        order = list(result["order"])
        order[0], order[1] = order[1], order[0]
        claimed = {"allocation": result["allocation"], "order": order}
        done = run_json(dict(data, claimed=claimed), "--verify")
        assert done.returncode == 1 and "第 1 位" in done.stdout

    def test_a_ps_card_is_checked_against_the_source_typed_in_again(self):
        data = load_example("ps_holiday_weeks.json")
        result = json.loads(run_json(data, "--json").stdout)["result"]
        card = {k: v for k, v in data.items() if k != "random_source"}
        card["claimed"] = {"allocation": result["allocation"]}
        done = run_json(card, "--verify", "--source", data["random_source"])
        assert done.returncode == 0, done.stdout + done.stderr
        other = run_json(card, "--verify", "--source", data["random_source"] + " ")
        assert other.returncode in (0, 1)

    def test_the_json_form_of_a_ps_check_has_the_recomputed_allocation(self):
        data = load_example("ps_holiday_weeks.json")
        result = json.loads(run_json(data, "--json").stdout)["result"]
        done = run_json(
            dict(data, claimed={"allocation": result["allocation"]}), "--verify", "--json"
        )
        parsed = json.loads(done.stdout)
        assert parsed["result"]["match"] is True
        assert parsed["result"]["recomputed_allocation"] == result["allocation"]
        assert [c["name"] for c in parsed["result"]["checks"]] == ["allocation"]

    def test_a_commit_reveal_round_verifies_and_a_changed_reveal_does_not(self):
        data = load_example("commit_reveal.json")
        claimed = claimed_from(data)
        assert run_json(dict(data, claimed=claimed), "--verify").returncode == 0
        forged = copy.deepcopy(data)
        forged["commit_reveal"]["reveals"][0]["reveal"] = "0" * 32
        done = run_json(dict(forged, claimed=claimed), "--verify")
        assert done.returncode == 1

    def test_json_form(self):
        data = lottery_data(PEOPLE8, 3)
        done = run_json(dict(data, claimed=claimed_from(data)), "--verify", "--json")
        assert done.returncode == 0
        parsed = json.loads(done.stdout)
        assert sorted(parsed) == ENVELOPE_KEYS
        assert parsed["result"]["match"] is True
        assert [c["name"] for c in parsed["result"]["checks"]] == ["order", "seed"]
        assert parsed["result"]["recomputed_order"] == GOLDEN_ORDER

    def test_group_form_is_a_short_conclusion(self):
        data = lottery_data(PEOPLE8, 3)
        done = run_json(dict(data, claimed=claimed_from(data)), "--verify", "--format", "group")
        assert done.returncode == 0
        assert done.stdout.count("\n") == 2 and "可以复现" in done.stdout

    def test_it_does_not_depend_on_how_people_are_listed(self):
        data = lottery_data(PEOPLE8, 3)
        claimed = claimed_from(data)
        shuffled = dict(data, people=list(reversed(PEOPLE8)), claimed=claimed)
        assert run_json(shuffled, "--verify").returncode == 0


def test_a_vertical_bar_in_the_text_is_flagged_in_the_tables_and_exact_elsewhere():
    data = lottery_data(["a|b", "c", "d"], 1, source="draw | 03 11 19")
    result = sl.solve(data)
    md = fc.render_md(result)
    assert "反斜杠" in md
    exact = json.loads(run_json(data, "--json").stdout)["result"]["draws"][0]["seed_preimage"]
    assert "draw | 03 11 19" in exact and "a|b" in exact
    assert exact in fc.render_group(result)
    plain = sl.solve(lottery_data(PEOPLE8, 3))
    assert "反斜杠" not in fc.render_md(plain)
