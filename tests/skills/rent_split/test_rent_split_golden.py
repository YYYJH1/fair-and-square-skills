"""Golden numbers of the rent-split skill: the worked examples that the documentation quotes.

Every number below was worked out by hand or by an independent script before the skill existed,
so these tests fail if the skill drifts from the numbers it advertises.
"""

from __future__ import annotations

from fractions import Fraction

import pytest
from rent_split_support import (
    FOUR_BIDS,
    FOUR_PEOPLE,
    FOUR_ROOMS,
    STORAGE_BIDS,
    STORAGE_ROOMS,
    four_roommates,
    load_script,
    make_input,
    storage_room,
)

rs = load_script()
fc = rs.fc


def run(data, audit=False):
    return rs.analyse(data, want_audit=audit)


def rents_by_person(result):
    assignment = result.result["assignment"]
    rent = result.result["rent_cents"]
    return {name: int(rent[room]) for name, room in assignment.items()}


def text_of(amount):
    """An amount in units as the script prints it, for example 3,017.23."""
    return fc.fmt_cents(int(amount * 100))


def audit_input(assignment, rents=2000):
    data = four_roommates()
    data["audit"] = {
        "assignment": dict(assignment),
        "rent": {name: rents for name in FOUR_PEOPLE},
    }
    return data


# --------------------------------------------------------------------------------------
# Four roommates: 950 / 2250 / 3150 / 1650, surpluses 250 / 250 / 250 / 350
# --------------------------------------------------------------------------------------


class TestFourRoommates:
    def test_assignment_and_rents(self):
        result = run(four_roommates()).result
        assert result["assignment"] == {
            "阿明": "小书房",
            "小红": "南次卧",
            "大刘": "主卧带卫",
            "Coco": "北次卧",
        }
        assert {room: int(cents) for room, cents in result["rent_cents"].items()} == {
            "主卧带卫": 315000,
            "南次卧": 225000,
            "北次卧": 165000,
            "小书房": 95000,
        }

    def test_surpluses(self):
        surplus = run(four_roommates()).result["surplus_cents"]
        assert {name: int(value) for name, value in surplus.items()} == {
            "阿明": 25000,
            "小红": 25000,
            "大刘": 25000,
            "Coco": 35000,
        }

    def test_the_rule_applied_and_no_envy(self):
        result = run(four_roommates()).result
        assert result["rule_applied"] == "non_negative"
        assert result["has_negative_rent"] is False
        assert int(result["max_envy_cents"]) == 0
        assert result["shifted"] == {}
        assert result["tie_break"] == {"was_tie": False, "method": "not_needed", "seed_hex": None}

    def test_the_four_certificate_lines_of_the_worked_example(self):
        lines = run(four_roommates()).certificate["one_liner"]
        assert lines == {
            "阿明": "按你报的价，小书房比你心里价位便宜 250.00，换哪间都不会更划算。",
            "小红": (
                "按你报的价，南次卧比你心里价位便宜 250.00，换哪间都不会更划算；"
                "小书房对你来说一样划算（也便宜 250.00），打平不算吃亏。"
            ),
            "大刘": "按你报的价，主卧带卫比你心里价位便宜 250.00，换哪间都不会更划算。",
            "Coco": (
                "按你报的价，北次卧比你心里价位便宜 350.00，换哪间都不会更划算；"
                "小书房对你来说一样划算（也便宜 350.00），打平不算吃亏。"
            ),
        }

    def test_ties_are_listed_per_person(self):
        ties = run(four_roommates()).certificate["ties"]
        assert ties == {"阿明": [], "小红": ["小书房"], "大刘": [], "Coco": ["小书房"]}

    def test_the_envy_table_uses_the_rounded_cents(self):
        table = run(four_roommates()).certificate["envy_table"]
        cents = {
            name: {room: int(value) for room, value in row.items()} for name, row in table.items()
        }
        assert cents["阿明"] == {
            "主卧带卫": -15000,
            "南次卧": -5000,
            "北次卧": -5000,
            "小书房": 25000,
        }
        assert cents["小红"] == {
            "主卧带卫": -55000,
            "南次卧": 25000,
            "北次卧": 5000,
            "小书房": 25000,
        }
        assert cents["大刘"] == {
            "主卧带卫": 25000,
            "南次卧": -25000,
            "北次卧": -15000,
            "小书房": 15000,
        }
        assert cents["Coco"] == {
            "主卧带卫": -75000,
            "南次卧": 5000,
            "北次卧": 35000,
            "小书房": 35000,
        }

    def test_nobody_pays_more_than_their_own_bid(self):
        within = run(four_roommates()).certificate["rent_within_own_bid"]
        assert within == dict.fromkeys(FOUR_PEOPLE, True)

    def test_the_hook_averaging_makes_everybody_want_the_master_bedroom(self):
        # If everyone paid 2000, each person would pick the master bedroom with ensuite.
        for name in FOUR_PEOPLE:
            gains = [bid - 2000 for bid in FOUR_BIDS[name]]
            assert gains.index(max(gains)) == 0

    def test_the_markdown_tables(self):
        text = fc.render_md(run(four_roommates()))
        assert "| 阿明 | 小书房 | 950.00 | 1,200.00 | 250.00 |" in text
        assert "| 小红 | 南次卧 | 2,250.00 | 2,500.00 | 250.00 |" in text
        assert "| 大刘 | 主卧带卫 | 3,150.00 | 3,400.00 | 250.00 |" in text
        assert "| Coco | 北次卧 | 1,650.00 | 2,000.00 | 350.00 |" in text
        assert "| 合计 |  | 8,000.00 |  |  |" in text
        assert "| 小红 | -550.00 | 250.00* | 50.00 | 250.00 |" in text


# --------------------------------------------------------------------------------------
# The storage room: the same bids under allow and under spliddit or forbid
# --------------------------------------------------------------------------------------


class TestStorageRoom:
    def test_allow_pays_the_person_in_the_storage_room(self):
        result = run(storage_room("allow"))
        assert rents_by_person(result) == {"甲": 353333, "乙": 353333, "丙": -106666}
        assert result.result["rule_applied"] == "negative_allowed"
        assert result.result["has_negative_rent"] is True
        surplus = result.result["surplus_cents"]
        assert [int(surplus[name]) for name in ("甲", "乙", "丙")] == [126667, 126667, 126666]
        assert int(result.result["max_envy_cents"]) == 0

    @pytest.mark.parametrize("rule", ["spliddit", "forbid"])
    def test_spliddit_and_forbid_agree_when_a_split_without_negative_rent_exists(self, rule):
        result = run(storage_room(rule))
        assert rents_by_person(result) == {"甲": 300000, "乙": 300000, "丙": 0}
        assert result.result["rule_applied"] == "non_negative"
        surplus = result.result["surplus_cents"]
        assert [int(surplus[name]) for name in ("甲", "乙", "丙")] == [180000, 180000, 20000]
        assert int(result.result["max_envy_cents"]) == 0

    def test_naive_rounding_would_leave_one_cent_of_envy(self):
        # The exact rents are 10600/3, 10600/3 and -3200/3 (in units). Largest-remainder rounding
        # gives the spare cent to a big room; the envy-minimising rounding gives it to the closet.
        outcome = rs.compute(rs.read_problem(storage_room("allow")))
        assert outcome.rents == [353333, 353333, -106666]
        assert outcome.exact_rents == [
            Fraction(1060000, 3),
            Fraction(1060000, 3),
            Fraction(-320000, 3),
        ]

    def test_the_comparison_table_of_the_demo(self):
        text = fc.render_md(rs.storage_comparison())
        assert (
            "| 甲 | 大主卧，付 3,533.33，赚 1,266.67 | 大主卧，付 3,000.00，赚 1,800.00 |" in text
        )
        assert (
            "| 丙 | 储物间改的小间，付 -1,066.66，赚 1,266.66 | 储物间改的小间，付 0.00，赚 200.00 |"
            in text
        )


# --------------------------------------------------------------------------------------
# The audit of an existing split
# --------------------------------------------------------------------------------------


class TestAudit:
    def test_equal_split_audit_a(self):
        data = audit_input(
            {"阿明": "小书房", "小红": "南次卧", "大刘": "主卧带卫", "Coco": "北次卧"}
        )
        audit = run(data, audit=True).result["audit"]
        assert audit["assignment_is_optimal"] is True
        assert int(audit["bids_total_now_cents"]) == int(audit["bids_total_best_cents"]) == 910000
        deltas = {name: int(entry["delta_cents"]) for name, entry in audit["per_person"].items()}
        assert deltas == {"阿明": 105000, "小红": -25000, "大刘": -115000, "Coco": 35000}
        envy = {name: int(entry["envy_cents"]) for name, entry in audit["per_person"].items()}
        assert envy == {"阿明": 180000, "小红": 10000, "大刘": 0, "Coco": 40000}
        assert audit["per_person"]["阿明"]["envied_rooms"] == ["主卧带卫"]
        assert audit["per_person"]["大刘"]["envied_rooms"] == []

    def test_audit_a_lines_of_the_worked_example(self):
        data = audit_input(
            {"阿明": "小书房", "小红": "南次卧", "大刘": "主卧带卫", "Coco": "北次卧"}
        )
        text = fc.render_md(run(data, audit=True))
        assert (
            "- 阿明 住小书房：按自己的报价羡慕主卧带卫 1,800.00；"
            "按规则该付 950.00，现在每月多掏 1,050.00"
        ) in text
        assert (
            "- 小红 住南次卧：按自己的报价羡慕主卧带卫 100.00；"
            "按规则该付 2,250.00，现在每月少掏 250.00"
        ) in text
        assert (
            "- 大刘 住主卧带卫：按自己的报价不羡慕任何人；"
            "按规则该付 3,150.00，现在每月少掏 1,150.00"
        ) in text
        assert (
            "- Coco 住北次卧：按自己的报价羡慕主卧带卫 400.00；"
            "按规则该付 1,650.00，现在每月多掏 350.00"
        ) in text

    def test_audit_b_assignment_by_arrival_order(self):
        arrival = {"阿明": "主卧带卫", "小红": "南次卧", "大刘": "北次卧", "Coco": "小书房"}
        result = run(audit_input(arrival), audit=True)
        audit = result.result["audit"]
        assert audit["assignment_is_optimal"] is False
        assert int(audit["bids_total_now_cents"]) == 830000
        assert int(audit["bids_total_best_cents"]) == 910000
        text = fc.render_md(result)
        assert "报价之和是 8,300.00" in text
        assert "低于最优住法的 9,100.00" in text
        assert "都做不到人人不羡慕" in text
        suggested = {name: entry["rule_room"] for name, entry in audit["per_person"].items()}
        assert suggested == result.result["assignment"]
        assert audit["per_person"]["阿明"]["delta_cents"] is None

    def test_audit_needs_the_block(self):
        with pytest.raises(fc.InputError) as caught:
            run(four_roommates(), audit=True)
        assert caught.value.field == "audit"

    def test_audit_block_without_the_flag_is_ignored_with_a_note(self):
        data = audit_input(
            {"阿明": "小书房", "小红": "南次卧", "大刘": "主卧带卫", "Coco": "北次卧"}
        )
        result = run(data)
        assert "audit" not in result.result
        assert "没有加 --audit" in fc.render_md(result)

    def test_a_current_assignment_that_is_a_tie_variant_counts_as_optimal(self):
        # Two people are indifferent between two rooms at the rule's rents, so the rooms can be
        # swapped without any loss. The audit must not call that split wrong.
        data = make_input(
            600,
            ["a", "b", "c"],
            {"x": [200, 200, 200], "y": [200, 200, 200], "z": [200, 200, 200]},
            "allow",
            audit={
                "assignment": {"x": "c", "y": "b", "z": "a"},
                "rent": {"x": 200, "y": 200, "z": 200},
            },
        )
        audit = run(data, audit=True).result["audit"]
        assert audit["assignment_is_optimal"] is True
        assert all(int(entry["delta_cents"]) == 0 for entry in audit["per_person"].values())


# --------------------------------------------------------------------------------------
# Hygiene: shift, never scale; the organizer who sees the other bids first
# --------------------------------------------------------------------------------------


H1 = {"甲": [3800, 1400, 2000], "乙": [2900, 3000, 100], "丙": [2600, 2800, 600]}


class TestShiftNotScale:
    def test_a_shifted_row_gives_the_rents_of_the_shifted_bids(self):
        result = run(make_input(6000, ["一", "二", "三"], H1))
        assert result.result["assignment"]["甲"] == "三"
        assert [int(result.result["rent_cents"][room]) for room in ("一", "二", "三")] == [
            256667,
            266667,
            76666,
        ]
        shifted = result.result["shifted"]
        assert list(shifted) == ["甲"]
        # 甲 bid 7200 in total for rooms worth 6000, so every bid drops by 1200 / 3 = 400.
        assert shifted["甲"]["exact_shift_per_room"] == "-400.00"
        assert int(shifted["甲"]["bids_sum_cents"]) == 720000

    def test_the_person_checks_the_result_against_the_original_bids(self):
        result = run(make_input(6000, ["一", "二", "三"], H1))
        rents = {room: int(cents) for room, cents in result.result["rent_cents"].items()}
        original = dict(zip(["一", "二", "三"], H1["甲"]))
        own = result.result["assignment"]["甲"]
        envy = max(original[room] * 100 - rents[room] for room in rents) - (
            original[own] * 100 - rents[own]
        )
        assert envy <= 1  # scaling instead of shifting would leave 300.00 of envy here

    def test_scaling_would_have_broken_the_guarantee(self):
        total = Fraction(6000)
        rows = [[Fraction(x) for x in row] for row in H1.values()]
        scaled = [row * 1 for row in rows]
        scaled[0] = [x * total / sum(rows[0]) for x in rows[0]]
        solution = rs.solve_exact(scaled, total, "allow")
        original = rows[0]
        own = solution.room_of[0]
        envy = max(original[k] - solution.rents[k] for k in range(3)) - (
            original[own] - solution.rents[own]
        )
        assert envy == 300

    def test_the_message_to_the_person_says_what_happened(self):
        result = run(make_input(6000, ["一", "二", "三"], H1))
        text = "\n".join(result.person_lines["甲"])
        assert "你报的价加起来是 7,200.00，比总租金 6,000.00 多 1,200.00" in text
        assert "统一减了 400.00" in text
        assert "不是按比例缩放" in text
        assert "\n".join(result.person_lines["乙"]).count("加起来") == 0
        assert "（调整后）" in fc.render_md(result)

    def test_a_bid_sum_that_is_off_by_a_third_of_a_cent_per_room_is_reported_exactly(self):
        bids = dict(STORAGE_BIDS)
        bids["丙"] = [2900, 2900, 201]
        result = run(make_input(6000, STORAGE_ROOMS, bids, "allow"))
        entry = result.result["shifted"]["丙"]
        assert entry["exact_shift_per_room"] == "-1/3"
        assert int(entry["shown_shift_per_room_cents"]) == -33
        assert "精确值是 1/3" in "\n".join(result.person_lines["丙"])
        assert sum(int(c) for c in result.result["rent_cents"].values()) == 600000
        assert int(result.result["max_envy_cents"]) == 0


class TestOrganizerWhoGoesLast:
    """The organizer who sees every other bid first can gain by lying, so the skill asks the
    organizer to go first. This documents that the method itself is not strategy-proof."""

    def test_a_lie_by_one_person_raises_their_true_surplus(self):
        honest = rs.compute(rs.read_problem(four_roommates()))
        lie = {**FOUR_BIDS, "大刘": [2900, 2300, 1750, 1050]}
        lying = rs.compute(rs.read_problem(make_input(8000, FOUR_ROOMS, lie)))
        people = lying.problem.people
        i = people.index("大刘")
        room = lying.room_of[i]
        assert lying.rents[room] == 285000
        true_surplus = FOUR_BIDS["大刘"][room] * 100 - lying.rents[room]
        assert true_surplus == 55000
        assert honest.surplus[honest.problem.people.index("大刘")] == 25000
        # The other three still see no envy when they check against their own true bids.
        for name in ("阿明", "小红", "Coco"):
            j = people.index(name)
            own = lying.room_of[j]
            row = [FOUR_BIDS[name][k] * 100 - lying.rents[k] for k in range(4)]
            assert max(row) == row[own]


# --------------------------------------------------------------------------------------
# Private messages and the group summary
# --------------------------------------------------------------------------------------


DISTINCT = {
    "甲": [Fraction("3017.23"), Fraction("2211.07"), Fraction("1771.70")],
    "乙": [Fraction("1903.41"), Fraction("3511.19"), Fraction("1585.40")],
    "丙": [Fraction("2301.37"), Fraction("2419.13"), Fraction("2279.50")],
}


class TestPrivacy:
    def result(self):
        return run(make_input(Fraction(7000), ["东", "西", "南"], DISTINCT))

    def test_the_group_summary_holds_no_bid(self):
        group = fc.render_group(self.result())
        for row in DISTINCT.values():
            for bid in row:
                assert text_of(bid) not in group

    def test_a_private_message_holds_only_the_receivers_bids(self):
        result = self.result()
        for name, row in DISTINCT.items():
            message = "\n".join(result.person_lines[name])
            others = [
                text_of(bid)
                for other, other_row in DISTINCT.items()
                if other != name
                for bid in other_row
            ]
            assert not any(text in message for text in others)
            assert all(text_of(bid) in message for bid in row)

    def test_the_private_messages_are_ordered_like_the_input(self):
        assert list(self.result().person_lines) == list(DISTINCT)

    def test_the_group_summary_has_the_rents_and_the_rooms(self):
        text = fc.render_group(run(four_roommates()))
        assert "阿明 住 小书房，每月付 950.00" in text
        assert "合计 8,000.00，等于总租金 8,000.00。" in text
        assert "私信" in text

    def test_negative_rent_reads_as_money_received(self):
        text = fc.render_group(run(storage_room("allow")))
        assert "丙 住 储物间改的小间，每月倒收 1,066.66" in text
        dm = "\n".join(run(storage_room("allow")).person_lines["丙"])
        assert "每月倒收 1,066.66" in dm
        assert "200.00 - (-1,066.66) = 1,266.66" in dm


# --------------------------------------------------------------------------------------
# Single cents: the cases where the rounded numbers need a caveat
# --------------------------------------------------------------------------------------


ENVY = {
    "p0": ["0.13", "0.12", "0.05"],
    "p1": ["0.10", "0.09", "0.11"],
    "p2": ["0.12", "0.00", "0.18"],
}
EXCESS = {
    "p0": ["0.00", "0.03", "0.00"],
    "p1": ["0.00", "0.01", "0.02"],
    "p2": ["0.00", "0.03", "0.02"],
}


class TestRoundingEdges:
    def test_one_cent_of_rounded_envy_is_reported_as_rounding(self):
        result = run(make_input("0.30", ["r0", "r1", "r2"], ENVY, "allow"))
        assert int(result.result["max_envy_cents"]) == 1
        assert result.certificate["one_liner"]["p0"] == (
            "按你报的价，r0 比你心里价位便宜 0.04。取整到分后，r1 比这间多划算 0.01，"
            "这是取整造成的误差（精确值下换哪间都不会更划算）。"
        )
        assert "最大羡慕是 0.01" in fc.render_md(result)
        assert "取整到分后最多差 0.01" in fc.render_group(result)

    def test_a_rent_one_cent_above_the_shifted_bid_is_reported(self):
        result = run(make_input("0.03", ["r0", "r1", "r2"], EXCESS, "allow"))
        assert result.certificate["rent_within_own_bid"] == {"p0": True, "p1": True, "p2": False}
        message = "\n".join(result.person_lines["p2"])
        assert (
            "你付的比你自己给这间房的报价多 0.01，这是取整到分造成的（精确值下不超过报价）。"
            in message
        )
        assert "精确值是 1/150" in message

    def test_the_line_for_a_person_who_gains_nothing_says_the_rent_equals_the_bid(self):
        flat = {name: [Fraction(100)] * 3 for name in ("x", "y", "z")}
        result = run(make_input(300, ["a", "b", "c"], flat, "allow"))
        line = result.certificate["one_liner"]["x"]
        assert line.startswith("按你报的价，a 的房租正好等于你心里的价位，换哪间都不会更划算")
        assert "b、c 对你来说一样划算（也正好等于你的报价）" in line
