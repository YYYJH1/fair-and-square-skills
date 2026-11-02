"""Recorded examples: the piano, the roommates, the weights, and the stored outputs.

The numbers below were worked out by hand. The stored outputs are the exact text the script prints,
so a change of wording shows up here as a failure and has to be made on purpose.
"""

from __future__ import annotations

import json
import os

import pytest
from stuff_split_support import EXAMPLES, GOLDEN, run_script

# (arguments, name of the stored output)
STORED = [
    (["--demo"], "demo_md_zh.txt"),
    (["--demo", "--lang", "en"], "demo_md_en.txt"),
    (["--demo", "--format", "dm"], "demo_dm_zh.txt"),
    (["--demo", "--format", "dm", "--lang", "en"], "demo_dm_en.txt"),
    (["--demo", "--format", "group"], "demo_group_zh.txt"),
    (["--demo", "--format", "group", "--lang", "en"], "demo_group_en.txt"),
    (["--demo", "--json"], "demo_json.txt"),
    (["--demo", "--json", "--lang", "en"], "demo_json_en.txt"),
    (["--input", str(EXAMPLES / "piano_knaster.json")], "piano_knaster_md_zh.txt"),
    (
        ["--input", str(EXAMPLES / "piano_knaster.json"), "--format", "dm"],
        "piano_knaster_dm_zh.txt",
    ),
    (
        ["--input", str(EXAMPLES / "piano_envy_free.json"), "--lang", "en"],
        "piano_envy_free_md_en.txt",
    ),
    (
        ["--input", str(EXAMPLES / "weighted_knaster.json"), "--format", "group", "--lang", "en"],
        "weighted_knaster_group_en.txt",
    ),
    (["--input", str(EXAMPLES / "moving_out_14_items.json")], "moving_out_md_zh.txt"),
    (
        ["--input", str(EXAMPLES / "moving_out_14_items.json"), "--format", "dm", "--lang", "en"],
        "moving_out_dm_en.txt",
    ),
]


@pytest.mark.parametrize(("flags", "name"), STORED, ids=[name for _, name in STORED])
def test_the_output_is_byte_stable_and_matches_the_stored_copy(flags, name):
    first = run_script(*flags)
    second = run_script(*flags)
    assert first.returncode == 0, first.stderr
    assert first.stdout == second.stdout
    if os.environ.get("FSQ_UPDATE_GOLDEN") == "1":
        (GOLDEN / name).write_text(first.stdout, encoding="utf-8", newline="\n")
    assert first.stdout == (GOLDEN / name).read_text(encoding="utf-8"), (
        f"{name} differs from the stored copy. If the change is intended, rerun with "
        "FSQ_UPDATE_GOLDEN=1 and review the diff."
    )


def cash_of(path_name):
    done = run_script("--input", str(EXAMPLES / path_name), "--json")
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)["result"]["cash_cents"]


def test_the_piano_under_knaster_reproduces_the_recorded_cash():
    assert cash_of("piano_knaster.json") == {"甲": "101.11", "乙": "-498.89", "丙": "397.78"}
    text = run_script("--input", str(EXAMPLES / "piano_knaster.json")).stdout
    assert "| 甲 | （没有东西） | 0.00 | +101.11 | 101.11 |" in text
    assert "| 乙 | 钢琴 | 900.00 | -498.89 | 401.11 |" in text
    assert "| 丙 | （没有东西） | 0.00 | +397.78 | 397.78 |" in text
    assert (
        "所以你羡慕丙"
        in run_script("--input", str(EXAMPLES / "piano_knaster.json"), "--format", "dm").stdout
    )


def test_the_piano_under_envy_free_gives_everybody_300():
    assert cash_of("piano_envy_free.json") == {"甲": "300.00", "乙": "-600.00", "丙": "300.00"}
    text = run_script("--input", str(EXAMPLES / "piano_envy_free.json")).stdout
    assert "| 乙 | 钢琴 | 900.00 | -600.00 | 300.00 |" in text
    assert "每个人最后得到的（东西加现金）都是 300.00" in text
    assert "取整到分后，没有人羡慕任何人（最大羡慕 0.00）" in text


def test_the_piano_comparison_in_the_demo_reproduces_both_columns():
    text = run_script("--demo").stdout
    assert "| 甲 | 没拿到 | +101.11 | 101.11 | +300.00 | 300.00 |" in text
    assert "| 乙 | 拿到 | -498.89 | 401.11 | -600.00 | 300.00 |" in text
    assert "| 丙 | 没拿到 | +397.78 | 397.78 | +300.00 | 300.00 |" in text
    assert "甲按自己的估值，看丙那一份（东西加现金）值 397.78，比自己的 101.11 多 296.67" in text
    english = run_script("--demo", "--lang", "en").stdout
    assert "| 乙 | gets it | -498.89 | 401.11 | -600.00 | 300.00 |" in english


def test_the_roommates_reproduce_the_recorded_allocation():
    text = run_script("--demo").stdout
    assert "| 阿明 | 冰箱、电视 | 45.00 | 100.00 |" in text
    assert "| 小红 | 洗衣机、书架 | 40.00 | 100.00 |" in text
    assert "| 大刘 | 沙发、微波炉 | 40.00 | 100.00 |" in text
    assert "| 小红 | 阿明 | 40.00 | 45.00 | 冰箱 (25.00) | 20.00 | 去掉后不羡慕 |" in text
    assert "| 大刘 | 阿明 | 40.00 | 45.00 | 冰箱 (35.00) | 10.00 | 去掉后不羡慕 |" in text
    assert "逐一核对了全部 729 种分法" in text and "乘积 72000" in text


def test_the_weighted_example_reproduces_the_hand_computed_numbers():
    assert cash_of("weighted_knaster.json") == {"大姐": "5.00", "二哥": "-7.50", "小妹": "2.50"}
    doc = json.loads(
        run_script("--input", str(EXAMPLES / "weighted_knaster.json"), "--json").stdout
    )
    recompute = doc["certificate"]["recompute"]
    assert recompute["shares"] == {"大姐": "1/2", "二哥": "1/4", "小妹": "1/4"}
    assert recompute["total_value_cents"] == {"大姐": "670.00", "二哥": "630.00", "小妹": "390.00"}
    assert recompute["fair_share_exact"] == {"大姐": "335.00", "二哥": "157.50", "小妹": "97.50"}
    assert recompute["surplus_exact"] == "140.00" and recompute["total_best_cents"] == "730.00"
    assert recompute["worth_exact"] == {"大姐": "405.00", "二哥": "192.50", "小妹": "132.50"}
    assert doc["result"]["tie_break"]["method"] == "random_source"


def test_the_fourteen_item_example_takes_turns_and_the_order_is_by_name():
    doc = json.loads(
        run_script("--input", str(EXAMPLES / "moving_out_14_items.json"), "--json").stdout
    )
    assert doc["result"]["tie_break"]["order"] == ["Mia", "小周", "阿杰"]
    picks = doc["certificate"]["recompute"]["picks"]
    assert picks[:3] == [["Mia", "椅子"], ["小周", "显示器"], ["阿杰", "小冰箱"]]
    assert len(picks) == 14
