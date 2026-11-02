"""Split a shared taxi or carpool fare fairly, exact to the cent.

The fare is shared by the Shapley value. Three ways to describe the ride (input mode):

  meter      riders in drop-off order and the cumulative meter reading when each got off.
             Every stretch of road is paid for by the riders still in the car (the airport
             game of Littlechild and Owen, 1973).
  estimates  each rider's solo fare estimate from the shared start, plus the fare actually
             paid. The estimates are scaled to the paid total, then the airport game is run.
  general    the price of every group riding alone (typed in), or a distance matrix with a
             tariff (every route is enumerated). The Shapley value is computed over all groups.

Every split that is shown, and any split you ask to audit, gets a core check: does some rider
or some group of riders pay more than the same people would pay riding alone? The answer lists
the groups. Money is exact (Fractions, whole cents), and the cents are rounded with the largest
remainder rule of fsq_core.

Input is JSON on standard input (--input -). Output is --format md|dm|group or --json. With
--audit the script compares the split in input["audit"] with the fair one. Exit code 0 means
success, 2 invalid input (the message names the field). Standard library only, Python 3.9+.
"""

from __future__ import annotations

import argparse
import itertools
import math
import re
import sys
import textwrap
from collections.abc import Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

try:
    import fsq_core as fc
except ModuleNotFoundError:  # python -I, -P and PYTHONSAFEPATH leave the script folder off sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import fsq_core as fc

# ---------------------------------------------------------------------------------------
# Limits, defaults and fixed names
# ---------------------------------------------------------------------------------------

MAX_RIDERS_CLOSED_FORM = 12  # meter and estimates: the core check visits all 2**n groups
MAX_RIDERS_GENERAL = 6  # general: every group's price and route is enumerated
DEFAULT_RIDE_ID = "ride-1"  # breaks exact ties when a leftover cent is handed out
MAX_SHOWN = 6  # violating groups listed per split in md output (json lists all)
MAX_COALITION_TABLE = 4  # md lists every group's price up to this many riders (15 prices)
MAX_DISTANCE = 10**9

MODES = ("meter", "estimates", "general")
COMMON_FIELDS = ("mode", "riders", "ride_id", "rules", "paid_by", "audit")
MODE_FIELDS = {
    "meter": ("meter_at_dropoff",),
    "estimates": ("solo_estimate", "actual_total"),
    "general": ("subset_costs", "distance_matrix", "tariff", "actual_total"),
}
TARIFF_FIELDS = ("base", "per_unit", "minimum")
RULE_METHODS = ("shapley",)
AUDIT_SHORTCUTS = ("equal", "proportional")

DEMO_JSON = (
    '{"mode": "meter", "ride_id": "ride-1", "riders": ["小周", "阿杰", "Mia", "老陈"], '
    '"meter_at_dropoff": [14, 26, 41, 63], "audit": {"current": "equal"}}'
)

# ---------------------------------------------------------------------------------------
# Texts (zh is the default, en is the same content)
# ---------------------------------------------------------------------------------------

TEXT = {
    "zh": {
        "sep": "、",
        "title_meter": "拼车分摊：计价器读数",
        "title_estimates": "拼车分摊：App 预估价",
        "title_general": "拼车分摊：一般模式",
        "title_audit": "拼车分摊审计：现在的分法公平吗",
        "m_shapley": "按路段平摊（Shapley）",
        "m_shapley_general": "Shapley 值",
        "m_equal": "平均分",
        "m_proportional": "按单独打车价比例",
        "m_current": "现在的分法",
        "cap_segments": "每一段路谁来付",
        "hdr_segments": ["段", "到谁下车为止", "本段车费", "还在车上的人", "人数"],
        "hdr_segments_est": [
            "段",
            "到谁下车为止",
            "本段预估差额（App 数字）",
            "还在车上的人",
            "人数",
        ],
        "cap_shares": "每人付多少",
        "hdr_shares": ["人", "单独打车", "这次付", "省下", "省下比例"],
        "hdr_shares_est": ["人", "单独打车（按实付折算）", "这次付", "省下", "省下比例"],
        "row_total": "合计",
        "cap_compare": "和其他分法比较",
        "hdr_compare": ["人"],
        "row_core": "核心检查",
        "cell_in_core": "在核心里",
        "cell_violated": "{count} 个组合违反",
        "cap_violations": "付得比自己单独打车还多的组合",
        "hdr_violations": ["分法", "组合", "合付", "自己打车", "多付"],
        "more_violations": "（{method}另有 {count} 个组合没有列出，完整列表见 --json。）",
        "cap_coalitions": "每种乘车组合单独打一辆车的价",
        "hdr_coalitions": ["组合", "单独打车的价"],
        "cap_audit": "谁在吃亏",
        "hdr_audit": ["人", "现在付", "按规则该付", "差额（现在减应付）", "单独打车", "结论"],
        "cap_transfers": "谁转给谁",
        "hdr_transfers": ["付款人", "收款人", "金额"],
        "verdict_over": "多掏 {amount}",
        "verdict_under": "少掏 {amount}",
        "verdict_same": "刚好",
        "verdict_over_alone": "，比单独打车还多 {amount}",
        "note_meter": (
            "计价器读数：每一段路的车费，由当时还在车上的人平摊，这就是 Shapley 值"
            "（机场博弈，Littlechild 与 Owen 1973）。第一个读数里含起步价。"
        ),
        "note_estimates": (
            "App 预估价：每个人在打车 App 里查从同一个出发地单独打车到自己下车点的预估价。"
            "脚本先把预估价按 实付总价 ÷ 最大预估价 = {factor} 折算，再按每一段路由还在车上的人"
            "平摊。折算假设大家顺路；绕路时，折算会把绕路成本按比例摊给所有人。"
        ),
        "note_general": (
            "一般模式：先算出每一种乘车组合单独打一辆车的价。每个人的份额，是他加入每一种"
            "上车顺序时让总车费多出来的部分的平均值（Shapley 值）。"
        ),
        "note_scaled": "实付总价 {actual} 与模型总价 {model} 不同，所有组合价已按 {factor} 折算。",
        "note_alone": "{name}付得最多：最后那段 {cost} 元只有{name}一个人坐。",
        "note_alone_est": "{name}付得最多：最后那段（App 预估差额 {cost}）只有{name}一个人坐。",
        "note_core": (
            "核心检查：任何一个人，或者几个人合起来，付的钱都不应超过他们自己单独打一辆车"
            "的价。超过了，这些人就会觉得不如自己打车。"
        ),
        "note_core_pass": "{method}：核对了全部 {count} 个组合，没有哪个人或小组付得比自己单独打车还多。",
        "note_core_fail": "{method}：{count} 个组合付得比自己单独打车还多，明细见上表。",
        "note_prop_in_core": "按比例分在这里也在核心里。它和{method}的分歧是规则选择，要事先定。",
        "note_prop_undefined": "按单独打车价比例没有定义：没有人单独打车的价大于 0。",
        "note_general_limits": "一般模式的结果不一定在核心里，核心也可能是空的。",
        "note_core_empty": (
            "核心是空的：不管怎么分，总有人或小组付得比自己单独打车还多。"
            "合坐本身比分开打车贵，或者各人要去的方向冲突。"
        ),
        "note_core_open": (
            "核心不是空的：存在不让任何人或小组吃亏的分法，但那是另一条规则，脚本不计算。"
            "要用的话请大家先商量好规则。"
        ),
        "note_route": "所有人一起坐的最省走法：起点{arrow}{route}，路程 {distance}。",
        "note_rounding": "取整：零头按最大余数分到分，恰好并列时由 ride_id「{ride_id}」决定。",
        "note_audit": "审计只做比较，不替大家决定改不改。",
        "note_audit_ignored": "输入里有 audit 块，但这次没有加 --audit，所以没有使用。",
        "note_paid": "{payer} 先垫付了全部车费。",
        "nm_tolls": "过路费、小费、附加费、等待时间：请先算进总价，脚本不单独分。",
        "nm_public": "没有防策略保证：读数和预估价由乘客自己报。",
        "nm_route": "路线只考虑从起点依次到各人的下车点，不含绕路接人、折返和路况。",
        "nm_scale": "折算假设大家顺路；绕路时折算会把绕路成本按比例摊给所有人。",
        "part": "第 {index} 段 {cost} 元，{people} 人同坐",
        "part_one": "第 {index} 段 {cost} 元，只有 1 人在车上",
        "part_est": "第 {index} 段 {cost}（{people} 人同坐）",
        "part_est_one": "第 {index} 段 {cost}（只有 1 人在车上）",
        "dm_pay": "这次拼车你付 {share}。",
        "dm_null": "你下车时没有产生任何车费，所以不用付。",
        "dm_parts": "路程分成几段，每段车费由还在车上的人平摊：{parts}。",
        "dm_parts_est": (
            "按 App 预估，你单独打车要 {estimate}，按实付总价折算后是 {solo}。每段由还在车上"
            "的人平摊（App 数字）：{parts}；再乘折算比例 {factor}。"
        ),
        "dm_alone": "最后那段 {cost} 元只有你一个人坐，所以你多付。",
        "dm_alone_est": "最后那段（App 预估差额 {cost}）只有你一个人坐，所以你多付。",
        "dm_general": "你的份额，是你加入每一种上车顺序时，让总车费多出来的部分的平均值。",
        "dm_save": "单独打车要 {solo}，你省了 {saved}（{pct}%）。",
        "dm_save_zero": "单独打车也要 {solo}，拼车对你没有省也没有多付。",
        "dm_loss": "单独打车只要 {solo}，这次你多付了 {extra}，比单独打车还贵。",
        "dm_transfer": "请转给 {payer} {amount}。",
        "dm_payer": "你先垫付了全部车费 {total}，其他人会把各自的份额转给你。",
        "dm_audit": "现在你付 {current}，按规则该付 {fair}，{verdict}。",
        "dm_audit_alone": "你单独打车只要 {solo}，现在的分法让你付得比单独打车还多 {extra}。",
        "dm_audit_groups": "有 {count} 个含你的小组，合起来付得比自己单独打车还多。",
        "g_intro": "{count} 人拼车，共 {total}，每人付：",
        "g_line": "{name} {amount}",
        "g_method": "分法：每一段路的车费，由当时还在车上的人平摊。",
        "g_method_general": "分法：Shapley 值，每个人付他加入每一种上车顺序时让总车费多出来的部分的平均值。",
        "g_core_pass": "核对：没有哪个人或小组付得比自己单独打车还多。",
        "g_core_fail": "提醒：有 {count} 个组合合起来付得比自己单独打车还多，明细在组织者的表格里。",
        "g_transfer": "转账：{src} 转给 {dst} {amount}",
        "g_audit_intro": "总额 {total}。现在的分法对比{method}：",
        "g_audit_line": "{name} 现在付 {current}，该付 {fair}，{verdict}",
        "g_audit_pass": "现在的分法里没有人或小组付得比自己单独打车还多。",
        "g_audit_fail": "现在的分法有 {count} 个组合，合起来付得比自己单独打车还多。",
        "arrow": " → ",
    },
    "en": {
        "sep": ", ",
        "title_meter": "Ride split: meter readings",
        "title_estimates": "Ride split: app estimates",
        "title_general": "Ride split: general mode",
        "title_audit": "Ride split audit: is the current split fair?",
        "m_shapley": "Stretch by stretch (Shapley)",
        "m_shapley_inline": "stretch by stretch (Shapley)",
        "m_shapley_general": "Shapley value",
        "m_equal": "Equal split",
        "m_proportional": "Proportional to solo fare",
        "m_current": "Current split",
        "cap_segments": "Who pays for each stretch",
        "hdr_segments": [
            "Stretch",
            "Until this rider gets off",
            "Cost",
            "Still in the car",
            "People",
        ],
        "hdr_segments_est": [
            "Stretch",
            "Until this rider gets off",
            "Estimate for the stretch (app figures)",
            "Still in the car",
            "People",
        ],
        "cap_shares": "What each rider pays",
        "hdr_shares": ["Rider", "Riding alone", "Pays", "Saves", "Saves %"],
        "hdr_shares_est": ["Rider", "Riding alone (scaled)", "Pays", "Saves", "Saves %"],
        "row_total": "Total",
        "cap_compare": "Compared with other splits",
        "hdr_compare": ["Rider"],
        "row_core": "Core check",
        "cell_in_core": "in the core",
        "cell_violated": "{count} groups pay more than alone",
        "cell_violated_one": "1 group pays more than alone",
        "cap_violations": "Groups that pay more than riding alone",
        "hdr_violations": ["Split", "Group", "Pay together", "Alone", "Extra"],
        "more_violations": "({method}: {count} more groups not listed; see --json for the full list.)",
        "cap_coalitions": "Price of each group riding alone",
        "hdr_coalitions": ["Group", "Price alone"],
        "cap_audit": "Who is losing",
        "hdr_audit": [
            "Rider",
            "Pays now",
            "Fair share",
            "Difference (now minus fair)",
            "Alone",
            "Verdict",
        ],
        "cap_transfers": "Who sends what to whom",
        "hdr_transfers": ["From", "To", "Amount"],
        "verdict_over": "{amount} too much",
        "verdict_under": "{amount} too little",
        "verdict_same": "exactly right",
        "verdict_over_alone": " (and {amount} more than riding alone)",
        "note_meter": (
            "Meter readings: each stretch of road is paid for by the riders still in the car. "
            "This is the Shapley value (the airport game of Littlechild and Owen, 1973). "
            "The first reading includes the starting fare."
        ),
        "note_estimates": (
            "App estimates: each rider looked up the fare of riding alone from the shared start "
            "to their own stop. The script scales the estimates by paid total / largest estimate "
            "= {factor}, then each stretch is shared by the riders still in the car. Scaling "
            "assumes everyone is on the same road; with a detour it spreads the detour cost over "
            "everybody in proportion."
        ),
        "note_general": (
            "General mode: the price of every group riding alone is known. A rider's share is "
            "the average extra fare they cause when they join in every possible order (the "
            "Shapley value)."
        ),
        "note_scaled": "The paid total {actual} differs from the modelled total {model}, so all group prices were scaled by {factor}.",
        "note_alone": "{name} pays the most: nobody else is in the car for the last stretch of {cost}.",
        "note_alone_est": "{name} pays the most: nobody else is in the car for the last stretch (app estimate {cost}).",
        "note_core": (
            "Core check: no rider, and no group of riders, should pay more than the same "
            "people would pay for a ride of their own. Where that happens, those riders would "
            "be better off leaving the shared ride."
        ),
        "note_core_pass": "{method}: all {count} groups checked, none pays more than riding alone.",
        "note_core_fail": "{method}: {count} groups pay more than riding alone, see the table above.",
        "note_core_fail_one": "{method}: 1 group pays more than riding alone, see the table above.",
        "note_prop_in_core": "The proportional split is in the core here too. How it differs from the {method} split is a choice of rule and must be agreed in advance.",
        "note_prop_undefined": "The proportional split is undefined: nobody has a solo fare above zero.",
        "note_general_limits": "In general mode the result need not lie in the core, and the core can be empty.",
        "note_core_empty": (
            "The core is empty: however the fare is split, some rider or group pays more than "
            "riding alone. Sharing costs more than separate rides, or the riders go in "
            "conflicting directions."
        ),
        "note_core_open": (
            "The core is not empty: some split keeps every group at or below its solo price, "
            "but such a split follows a different rule, which the script does not compute. "
            "Agree on that rule first."
        ),
        "note_route": "Cheapest way to take everybody: start{arrow}{route}, distance {distance}.",
        "note_rounding": 'Rounding: leftover cents go to the largest remainders; exact ties are decided by the ride_id "{ride_id}".',
        "note_audit": "The audit only compares. The group decides whether to change.",
        "note_audit_ignored": "The input has an audit block, but --audit was not given, so it was not used.",
        "note_paid": "{payer} paid the whole fare up front.",
        "nm_tolls": "Tolls, tips, surcharges and waiting time: add them to the total first, the script does not split them separately.",
        "nm_public": "Not strategy-proof: readings and estimates are reported by the riders themselves.",
        "nm_route": "Routes only go from the start to each rider's stop in turn: no pick-up detours, no return trips, no traffic.",
        "nm_scale": "Scaling assumes everyone is on the same road; with a detour it spreads the detour cost over everybody in proportion.",
        "part": "stretch {index} costs {cost}, {people} in the car",
        "part_est": "stretch {index} {cost} ({people} in the car)",
        "dm_pay": "You pay {share} for this ride.",
        "dm_null": "Your ride added nothing to the fare, so you pay nothing.",
        "dm_parts": "The trip is cut into stretches and the people still in the car share each one: {parts}.",
        "dm_parts_est": (
            "The app estimate for riding alone to your stop is {estimate}, which is {solo} once "
            "scaled to the paid total. The people still in the car share each stretch (app "
            "figures): {parts}; then multiply by the scale {factor}."
        ),
        "dm_alone": "Nobody else is in the car for the last stretch of {cost}, so you pay for it.",
        "dm_alone_est": "Nobody else is in the car for the last stretch (app estimate {cost}), so you pay for it.",
        "dm_general": "Your share is the average extra fare you cause when you join in every possible order.",
        "dm_save": "Riding alone would cost {solo}, so you save {saved} ({pct}%).",
        "dm_save_zero": "Riding alone would also cost {solo}, so sharing saves you nothing and costs you nothing extra.",
        "dm_loss": "Riding alone would cost only {solo}, so you pay {extra} more than that.",
        "dm_transfer": "Please send {amount} to {payer}.",
        "dm_payer": "You paid the whole fare of {total} up front. The others will send you their shares.",
        "dm_audit": "You pay {current} now and the fair share is {fair}: {verdict}.",
        "dm_audit_alone": "Riding alone would cost only {solo}, so the current split makes you pay {extra} more than that.",
        "dm_audit_groups": "{count} groups that include you pay more together than riding alone.",
        "dm_audit_groups_one": "1 group that includes you pays more together than riding alone.",
        "g_intro": "{count} riders, {total} in total, each pays:",
        "g_line": "{name} {amount}",
        "g_method": "Method: each stretch of road is paid for by the riders still in the car.",
        "g_method_general": "Method: Shapley value, the average extra fare each rider causes when joining in every possible order.",
        "g_core_pass": "Check: no rider or group pays more than riding alone.",
        "g_core_fail": "Warning: {count} groups pay more together than riding alone, details are in the organizer's table.",
        "g_core_fail_one": "Warning: 1 group pays more together than riding alone, details are in the organizer's table.",
        "g_transfer": "Transfer: {src} sends {dst} {amount}",
        "g_audit_intro": "Total {total}. Current split against the {method} split:",
        "g_audit_line": "{name} pays {current} now, fair share {fair}: {verdict}",
        "g_audit_pass": "In the current split no rider or group pays more than riding alone.",
        "g_audit_fail": "In the current split {count} groups pay more together than riding alone.",
        "g_audit_fail_one": "In the current split 1 group pays more together than riding alone.",
        "arrow": " -> ",
    },
}


# ---------------------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------------------


@dataclass
class Segment:
    """One stretch of road: its cost (in the unit of the input) and who is still in the car."""

    index: int  # 1-based, only stretches with a positive cost are kept
    until: int  # the rider whose stop ends this stretch
    cost: Fraction
    sharers: list


@dataclass
class Violation:
    """A group that pays more together than the same people would pay riding alone."""

    members: tuple
    paid: int  # cents
    alone: int  # cents

    @property
    def excess(self) -> int:
        return self.paid - self.alone


@dataclass
class Ride:
    """A validated ride. Amounts are exact; cents are whole numbers of cents."""

    mode: str
    riders: list
    ride_id: str
    total: int  # cents actually paid
    given: list = field(default_factory=list)  # meter readings or estimates (Fractions)
    solo: list = field(default_factory=list)  # airport modes: exact solo prices, paid scale
    scale: Fraction = Fraction(1)
    table: list = field(default_factory=list)  # general: price of every group in cents
    model_total: int = 0  # general: total before scaling to the paid total
    distances: list = field(default_factory=list)
    tariff: dict = field(default_factory=dict)
    route: list = field(default_factory=list)  # cheapest order for everybody (rider indexes)
    route_length: Fraction = Fraction(0)
    paid_by: int = -1
    audit: object = None  # None, a list of cents, or a shortcut name
    audit_ignored: bool = False

    @property
    def n(self) -> int:
        return len(self.riders)


@dataclass
class Split:
    """One way of dividing the fare, in cents per rider (input order), with its core check."""

    cents: list
    violations: list


@dataclass
class Game:
    """The cost game behind a ride."""

    alone: list  # cents of every group riding alone, indexed by bit mask (0 = empty = 0)
    exact: list  # exact Shapley value per rider, in currency units
    segments: list  # airport modes only


@dataclass
class Outcome:
    """Everything computed for a ride."""

    game: Game
    shapley: Split
    alternatives: dict  # "equal" and "proportional" -> Split (proportional may be missing)
    current: object = None  # Split of the audited split, or None
    core_empty: object = None  # general mode: True/False once Shapley left the core, else None


# ---------------------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------------------


def round_cents(amount: Fraction) -> int:
    """Whole cents nearest to an amount in currency units (halves go up)."""
    return fc.round_half_up(Fraction(amount) * 100)


def money(cents: int) -> str:
    """Display form of cents: 1,050.00."""
    return fc.fmt_cents(cents)


def signed(cents: int) -> str:
    """Display form with an explicit plus sign for gains: +12.25, -21.25, 0.00."""
    return ("+" if cents > 0 else "") + money(cents)


def percent(saved: int, solo: int):
    """Whole percent of the solo fare that is saved (halves go up), or None for a zero fare."""
    if solo <= 0:
        return None
    return (200 * saved + solo) // (2 * solo)


def decimal(value: Fraction, places: int = 4) -> str:
    """A number as plain decimal text with up to `places` decimals and no trailing zeros."""
    value = Fraction(value)
    scaled = math.floor(abs(value) * 10**places + Fraction(1, 2))
    whole, part = divmod(scaled, 10**places)
    text = str(whole)
    if part:
        text += "." + str(part).rjust(places, "0").rstrip("0")
    return ("-" if value < 0 and scaled else "") + text


def ratio_text(value: Fraction) -> str:
    """A scale factor as 21/22 (about 0.9545), or 1."""
    value = Fraction(value)
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator} (≈{decimal(value)})"


def say(lang: str, key: str, **fields) -> str:
    """Fill the text template of this key (see fsq_core.fill_text for the Latin-name spacing)."""
    return fc.fill_text(lang, TEXT[lang][key], **fields)


def counted(lang: str, key: str, count: int, **fields) -> str:
    """Text with a count in it, using a separate singular form where the language has one."""
    if count == 1 and key + "_one" in TEXT[lang]:
        key += "_one"
    return say(lang, key, count=count, **fields)


def shapley_label(ride, lang: str, inline: bool = False) -> str:
    """Name of the fair split: stretch by stretch in a line, the plain Shapley value otherwise.

    inline asks for the form to use in the middle of a sentence. In English that form starts with
    a small letter.
    """
    key = "m_shapley_general" if ride.mode == "general" else "m_shapley"
    if inline and key + "_inline" in TEXT[lang]:
        key += "_inline"
    return TEXT[lang][key]


def names(riders, members, lang: str) -> str:
    return TEXT[lang]["sep"].join(riders[i] for i in members)


def bits(mask: int, n: int) -> list:
    return [i for i in range(n) if mask >> i & 1]


# ---------------------------------------------------------------------------------------
# Mathematics: Shapley value, core check, emptiness of the core
# ---------------------------------------------------------------------------------------


def airport_order(solo) -> list:
    """Riders from the cheapest solo ride to the dearest (ties keep the input order)."""
    return sorted(range(len(solo)), key=lambda i: (solo[i], i))


def airport_shapley(solo) -> list:
    """Exact Shapley value of the airport game with stand-alone prices `solo`.

    The fare of a group is the dearest solo price among its members. With the prices sorted
    c(1) <= ... <= c(n), rider k pays the sum over j <= k of (c(j) - c(j-1)) / (n - j + 1):
    every stretch of road is shared equally by the riders still in the car.
    """
    n = len(solo)
    share = [Fraction(0)] * n
    running = Fraction(0)
    previous = Fraction(0)
    for position, rider in enumerate(airport_order(solo)):
        running += (Fraction(solo[rider]) - previous) / (n - position)
        previous = Fraction(solo[rider])
        share[rider] = running
    return share


def shapley_by_orders(n: int, price) -> list:
    """The same value by averaging over all n! orders (slow, used to cross-check)."""
    total = [Fraction(0)] * n
    count = 0
    for order in itertools.permutations(range(n)):
        mask = 0
        for rider in order:
            total[rider] += price[mask | 1 << rider] - price[mask]
            mask |= 1 << rider
        count += 1
    return [value / count for value in total]


def core_violations(n: int, alone, paid) -> list:
    """Every group that pays more together than it would pay riding alone.

    `alone[mask]` is the price in cents of the group `mask` riding alone, `paid[i]` what rider
    i pays in cents. Groups come back smallest first. When the shares add up to the fare, as
    they always do here, the group of all riders cannot be among them.
    """
    sums = [0] * (1 << n)
    found = []
    for mask in range(1, 1 << n):
        low = mask & -mask
        sums[mask] = sums[mask ^ low] + paid[low.bit_length() - 1]
        if sums[mask] > alone[mask]:
            found.append(Violation(tuple(bits(mask, n)), sums[mask], alone[mask]))
    found.sort(key=lambda item: (len(item.members), item.members))
    return found


def packing_lp_value(n: int, gain) -> Fraction:
    """max sum of gain[S] * x[S] with, for every rider, the x of the groups holding him <= 1.

    Exact simplex on Fractions with Bland's rule (it cannot cycle). The origin is feasible, so
    no first phase is needed, and every x[S] <= 1, so the maximum exists. `gain[mask]` is an
    int for every non-empty group.
    """
    groups = (1 << n) - 1
    width = groups + n
    rows = []
    for rider in range(n):
        row = [Fraction(0)] * (width + 1)
        for mask in range(1, groups + 1):
            if mask >> rider & 1:
                row[mask - 1] = Fraction(1)
        row[groups + rider] = Fraction(1)
        row[width] = Fraction(1)
        rows.append(row)
    basis = [groups + rider for rider in range(n)]
    objective = [Fraction(-gain[mask]) for mask in range(1, groups + 1)]
    objective += [Fraction(0)] * (n + 1)
    while True:
        entering = next((j for j in range(width) if objective[j] < 0), None)
        if entering is None:
            return objective[width]
        best = None
        for r in range(n):
            if rows[r][entering] > 0:
                key = (rows[r][width] / rows[r][entering], basis[r])
                if best is None or key < best[0]:
                    best = (key, r)
        pivot_row = best[1]
        pivot = rows[pivot_row][entering]
        rows[pivot_row] = [value / pivot for value in rows[pivot_row]]
        for r in range(n):
            if r != pivot_row and rows[r][entering] != 0:
                factor = rows[r][entering]
                rows[r] = [a - factor * b for a, b in zip(rows[r], rows[pivot_row])]
        factor = objective[entering]
        objective = [a - factor * b for a, b in zip(objective, rows[pivot_row])]
        basis[pivot_row] = entering


def core_is_empty(n: int, alone) -> bool:
    """True when no split of the grand coalition's price keeps every group at or below its own.

    With y[i] = solo(i) - x[i] the question becomes: can the total savings d(N) be handed out
    so that every group S gets at least d(S) = sum of its solo prices - price(S)? That covering
    problem has the same optimum as the packing problem solved by packing_lp_value (LP duality);
    the core is non-empty exactly when that optimum equals d(N) (Bondareva and Shapley).
    """
    full = (1 << n) - 1
    solo = [alone[1 << i] for i in range(n)]
    gain = {}
    for mask in range(1, full + 1):
        gain[mask] = sum(solo[i] for i in bits(mask, n)) - alone[mask]
    return packing_lp_value(n, gain) > gain[full]


def route_table(distances, n: int):
    """Shortest open route from the start through the stops of every group, by exhaustive search.

    distances[0] is the start and distances[i + 1] the stop of rider i. Returns (length, order)
    lists indexed by bit mask; `order` holds rider indexes. Ties keep the first order found.
    """
    length = [Fraction(0)] * (1 << n)
    order = [()] * (1 << n)
    for mask in range(1, 1 << n):
        members = bits(mask, n)
        best = None
        for perm in itertools.permutations(members):
            total = distances[0][perm[0] + 1]
            for a, b in zip(perm, perm[1:]):
                total += distances[a + 1][b + 1]
            if best is None or total < best[0]:
                best = (total, perm)
        length[mask], order[mask] = best
    return length, order


# ---------------------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------------------


def need(data: dict, key: str, hint: str = "is required"):
    if key not in data:
        raise fc.InputError(key, hint)
    return data[key]


def number(value, field_name: str) -> Fraction:
    """A non-negative number that is not an amount of money (distance, price per unit)."""
    if isinstance(value, bool):
        raise fc.InputError(field_name, "must be a number")
    if isinstance(value, int):
        result = Fraction(value)
    elif isinstance(value, Fraction):
        result = value
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise fc.InputError(field_name, "NaN and infinity are not numbers")
        result = Fraction(repr(value))
    elif isinstance(value, str) and re.fullmatch(r"\s*[+-]?[0-9]+(?:\.[0-9]+)?\s*", value):
        result = Fraction(value.strip())
    else:
        raise fc.InputError(field_name, "must be a number")
    if result < 0:
        raise fc.InputError(field_name, "must not be negative")
    if result > MAX_DISTANCE:
        raise fc.InputError(field_name, "is too large")
    return result


def one_per_rider(raw, riders: list, field_name: str, other: str) -> None:
    """Both lists must have one entry per rider; the message names both fields."""
    if len(raw) < len(riders):
        raise fc.InputError(
            field_name,
            f"has {len(raw)} value(s) but riders lists {len(riders)}: give one {other} per rider",
        )
    if len(raw) > len(riders):
        raise fc.InputError(
            "riders",
            f"lists {len(riders)} rider(s) but {field_name} has {len(raw)} values: "
            "add the missing rider(s)",
        )


def parse_meter(data: dict, riders: list, ride: Ride) -> None:
    raw = fc.require_list(need(data, "meter_at_dropoff"), "meter_at_dropoff", 1)
    one_per_rider(raw, riders, "meter_at_dropoff", "reading")
    readings = [fc.money(value, f"meter_at_dropoff[{i}]") for i, value in enumerate(raw)]
    for i in range(1, len(readings)):
        if readings[i] < readings[i - 1]:
            raise fc.InputError(
                f"meter_at_dropoff[{i}]",
                f"is {fc.fmt_cents(fc.to_cents(readings[i]))}, lower than the reading before it "
                f"({fc.fmt_cents(fc.to_cents(readings[i - 1]))}): readings are cumulative and "
                "list the riders in drop-off order",
            )
    if readings[-1] <= 0:
        raise fc.InputError("meter_at_dropoff", "the last reading must be greater than zero")
    ride.given = readings
    ride.solo = list(readings)
    ride.total = fc.to_cents(readings[-1])


def parse_estimates(data: dict, riders: list, ride: Ride) -> None:
    raw = fc.require_list(need(data, "solo_estimate"), "solo_estimate", 1)
    one_per_rider(raw, riders, "solo_estimate", "estimate")
    estimates = [fc.money(value, f"solo_estimate[{i}]") for i, value in enumerate(raw)]
    biggest = max(estimates)
    if biggest <= 0:
        raise fc.InputError("solo_estimate", "at least one estimate must be greater than zero")
    actual = fc.money(need(data, "actual_total"), "actual_total", allow_zero=False)
    ride.given = estimates
    ride.scale = actual / biggest
    ride.solo = [value * ride.scale for value in estimates]
    ride.total = fc.to_cents(actual)


def parse_tariff(data: dict) -> dict:
    tariff = fc.require_object(need(data, "tariff", "is required with distance_matrix"), "tariff")
    fc.check_fields(tariff, TARIFF_FIELDS, "tariff")
    if "per_unit" not in tariff:
        raise fc.InputError("tariff.per_unit", "is required: the price per unit of distance")
    return {
        "base": fc.money(tariff.get("base", 0), "tariff.base"),
        "per_unit": number(tariff["per_unit"], "tariff.per_unit"),
        "minimum": fc.money(tariff.get("minimum", 0), "tariff.minimum"),
    }


def parse_distances(raw, n: int) -> list:
    size = n + 1
    rows = fc.require_list(raw, "distance_matrix")
    if len(rows) != size:
        raise fc.InputError(
            "distance_matrix",
            f"must have {size} rows: the starting point first, then one stop per rider",
        )
    matrix = []
    for a, row in enumerate(rows):
        row = fc.require_list(row, f"distance_matrix[{a}]")
        if len(row) != size:
            raise fc.InputError(f"distance_matrix[{a}]", f"must have {size} numbers")
        parsed = [number(value, f"distance_matrix[{a}][{b}]") for b, value in enumerate(row)]
        if parsed[a] != 0:
            raise fc.InputError(f"distance_matrix[{a}][{a}]", "must be 0 (a stop to itself)")
        matrix.append(parsed)
    return matrix


def group_mask(members, index: dict, field_name: str) -> int:
    """Bit mask of a group given by rider names; unknown or repeated names name their field."""
    mask = 0
    for j, name in enumerate(members):
        if not isinstance(name, str) or name not in index:
            raise fc.InputError(f"{field_name}[{j}]", f"{name!r} is not one of the riders")
        if mask >> index[name] & 1:
            raise fc.InputError(f"{field_name}[{j}]", f"{name!r} is listed twice")
        mask |= 1 << index[name]
    return mask


def subset_entries(raw, index: dict) -> list:
    """(field, mask, cost value) for each priced group, from either accepted layout.

    A list of {"riders": [...], "cost": amount} objects works for any names. An object
    {"A+B": amount} is shorter to type, and splits each key at "+", so it needs names
    without a "+" in them.
    """
    if isinstance(raw, dict):
        found = []
        for key, value in raw.items():
            where = f"subset_costs.{key}"
            members = [part.strip() for part in key.split("+")]
            if "" in members:
                raise fc.InputError(where, "write a group as names joined by +, such as A+B")
            found.append((where, group_mask(members, index, where), value))
        return found
    found = []
    for k, entry in enumerate(fc.require_list(raw, "subset_costs", 1)):
        where = f"subset_costs[{k}]"
        obj = fc.require_object(entry, where)
        fc.check_fields(obj, ("riders", "cost"), where)
        members = fc.require_list(need_in(obj, "riders", where), f"{where}.riders", 1)
        mask = group_mask(members, index, f"{where}.riders")
        found.append((f"{where}.cost", mask, need_in(obj, "cost", where)))
    return found


def parse_subset_costs(raw, riders: list) -> list:
    n = len(riders)
    index = {name: i for i, name in enumerate(riders)}
    table = [None] * (1 << n)
    table[0] = 0
    for where, mask, value in subset_entries(raw, index):
        cost = fc.money(value, where)
        if table[mask] is not None:
            raise fc.InputError(where, "this group already has a price above")
        table[mask] = fc.to_cents(cost)
    missing = [mask for mask in range(1, 1 << n) if table[mask] is None]
    if missing:
        example = "+".join(riders[i] for i in bits(missing[0], n))
        plural = "" if len(missing) == 1 else "s"
        raise fc.InputError(
            "subset_costs",
            f"missing the price of {len(missing)} group{plural}, for example {example}: every "
            f"non-empty group needs one ({(1 << n) - 1} in all for {n} riders)",
        )
    return table


def need_in(obj: dict, key: str, where: str):
    if key not in obj:
        raise fc.InputError(f"{where}.{key}", "is required")
    return obj[key]


def parse_general(data: dict, riders: list, ride: Ride) -> None:
    n = len(riders)
    has_table = "subset_costs" in data
    has_matrix = "distance_matrix" in data
    if has_table == has_matrix:
        raise fc.InputError(
            "subset_costs",
            "give either subset_costs (the price of every group riding alone) or "
            "distance_matrix with tariff, not both and not neither",
        )
    if has_table and "tariff" in data:
        raise fc.InputError("tariff", "is only used together with distance_matrix")
    if has_table:
        table = parse_subset_costs(data["subset_costs"], riders)
    else:
        distances = parse_distances(data["distance_matrix"], n)
        tariff = parse_tariff(data)
        length, order = route_table(distances, n)
        table = [0] * (1 << n)
        for mask in range(1, 1 << n):
            fare = max(tariff["minimum"], tariff["base"] + tariff["per_unit"] * length[mask])
            table[mask] = round_cents(fare)
        full = (1 << n) - 1
        ride.distances = distances
        ride.tariff = tariff
        ride.route = list(order[full])
        ride.route_length = length[full]
    full = (1 << n) - 1
    if table[full] <= 0:
        raise fc.InputError(
            "subset_costs" if has_table else "distance_matrix",
            "the price of all riders together must be greater than zero",
        )
    ride.model_total = table[full]
    if "actual_total" in data:
        actual = fc.to_cents(fc.money(data["actual_total"], "actual_total", allow_zero=False))
        if actual != table[full]:
            ride.scale = Fraction(actual, table[full])
            table = [round_cents(Fraction(value * actual, table[full]) / 100) for value in table]
        ride.total = actual
    else:
        ride.total = table[full]
    ride.table = table


def parse_audit(raw, ride: Ride):
    obj = fc.require_object(raw, "audit")
    fc.check_fields(obj, ("current",), "audit")
    current = need_in(obj, "current", "audit")
    if isinstance(current, str):
        if current not in AUDIT_SHORTCUTS:
            raise fc.InputError(
                "audit.current",
                f"text must be one of {', '.join(AUDIT_SHORTCUTS)}; otherwise give an object "
                "with what each rider pays now",
            )
        return current
    pays = fc.require_object(current, "audit.current")
    unknown = [name for name in pays if name not in ride.riders]
    if unknown:
        raise fc.InputError(f"audit.current.{unknown[0]}", "is not one of the riders")
    missing = [name for name in ride.riders if name not in pays]
    if missing:
        raise fc.InputError(f"audit.current.{missing[0]}", "is missing: give what every rider pays")
    cents = [fc.to_cents(fc.money(pays[name], f"audit.current.{name}")) for name in ride.riders]
    if sum(cents) != ride.total:
        raise fc.InputError(
            "audit.current",
            f"adds up to {money(sum(cents))}, but the fare paid is {money(ride.total)}",
        )
    return cents


def parse_ride(data: dict, audit: bool = False) -> Ride:
    """Validate the input and return a Ride. Any problem raises fc.InputError naming the field."""
    mode = fc.require_choice(need(data, "mode"), "mode", MODES)
    fc.check_fields(data, COMMON_FIELDS + MODE_FIELDS[mode], "")
    limit = MAX_RIDERS_GENERAL if mode == "general" else MAX_RIDERS_CLOSED_FORM
    raw_riders = need(data, "riders")
    if isinstance(raw_riders, list) and len(raw_riders) > limit:
        reason = (
            "every group's price and route is enumerated"
            if mode == "general"
            else "the core check looks at every group of riders"
        )
        raise fc.InputError(
            "riders",
            f"has {len(raw_riders)} names but {mode} mode takes at most {limit} ({reason})",
        )
    riders = fc.require_names(raw_riders, "riders", 2, limit)
    for i, name in enumerate(riders):
        fc.encodable(name, f"riders[{i}]")
    ride_id = fc.require_text(data.get("ride_id", DEFAULT_RIDE_ID), "ride_id")
    fc.encodable(ride_id, "ride_id")
    rules = fc.require_object(data.get("rules", {}), "rules")
    fc.check_fields(rules, ("method",), "rules")
    fc.require_choice(rules.get("method", RULE_METHODS[0]), "rules.method", RULE_METHODS)
    ride = Ride(mode=mode, riders=riders, ride_id=ride_id, total=0)
    if mode == "meter":
        parse_meter(data, riders, ride)
    elif mode == "estimates":
        parse_estimates(data, riders, ride)
    else:
        parse_general(data, riders, ride)
    if "paid_by" in data:
        payer = fc.require_text(data["paid_by"], "paid_by")
        if payer not in riders:
            raise fc.InputError("paid_by", f"{payer!r} is not one of the riders")
        ride.paid_by = riders.index(payer)
    if audit:
        ride.audit = parse_audit(
            need(data, "audit", "is required with --audit: what each rider pays now"), ride
        )
    else:
        ride.audit_ignored = "audit" in data
    return ride


# ---------------------------------------------------------------------------------------
# Computation
# ---------------------------------------------------------------------------------------


def build_game(ride: Ride) -> Game:
    n = ride.n
    if ride.mode != "general":
        solo_cents = [round_cents(value) for value in ride.solo]
        alone = [0] * (1 << n)
        for mask in range(1, 1 << n):
            alone[mask] = max(solo_cents[i] for i in bits(mask, n))
        order = airport_order(ride.solo)
        segments = []
        previous = Fraction(0)
        for position, rider in enumerate(order):
            cost = Fraction(ride.given[rider]) - previous
            previous = Fraction(ride.given[rider])
            if cost > 0:
                segments.append(Segment(len(segments) + 1, rider, cost, order[position:]))
        exact = airport_shapley(ride.solo)
    else:
        alone = list(ride.table)
        segments = []
        exact = [value / 100 for value in fc.shapley_values(n, alone)]
    if sum(exact) != Fraction(ride.total, 100):
        raise AssertionError("the exact shares do not add up to the fare")
    return Game(alone, exact, segments)


def check_split(ride: Ride, game: Game, cents) -> Split:
    return Split(list(cents), core_violations(ride.n, game.alone, cents))


def equal_split(ride: Ride) -> list:
    shares = {name: Fraction(ride.total, 100 * ride.n) for name in ride.riders}
    rounded = fc.round_shares(shares, ride.total, ride.ride_id)
    return [rounded[name] for name in ride.riders]


def proportional_split(ride: Ride, game: Game):
    """Shares in proportion to the solo prices, or None when every solo price is zero."""
    weights = ride.solo if ride.mode != "general" else [game.alone[1 << i] for i in range(ride.n)]
    if all(w <= 0 for w in weights):
        return None
    rounded = fc.apportion(ride.total, dict(zip(ride.riders, weights)), ride.ride_id)
    return [rounded[name] for name in ride.riders]


def compute(ride: Ride) -> Outcome:
    game = build_game(ride)
    rounded = fc.round_shares(dict(zip(ride.riders, game.exact)), ride.total, ride.ride_id)
    shapley = check_split(ride, game, [rounded[name] for name in ride.riders])
    alternatives = {"equal": check_split(ride, game, equal_split(ride))}
    proportional = proportional_split(ride, game)
    if proportional is not None:
        alternatives["proportional"] = check_split(ride, game, proportional)
    current = None
    if ride.audit is not None:
        if ride.audit == "equal":
            cents = alternatives["equal"].cents
        elif ride.audit == "proportional":
            if proportional is None:
                raise fc.InputError("audit.current", "proportional is undefined for this ride")
            cents = proportional
        else:
            cents = ride.audit
        current = check_split(ride, game, cents)
    core_empty = None
    if ride.mode == "general" and shapley.violations:
        core_empty = core_is_empty(ride.n, game.alone)
    return Outcome(game, shapley, alternatives, current, core_empty)


# ---------------------------------------------------------------------------------------
# Result: tables, notes, messages, JSON
# ---------------------------------------------------------------------------------------


def violation_json(ride: Ride, found: list) -> list:
    return [
        {
            "riders": [ride.riders[i] for i in item.members],
            "paid": fc.Cents(item.paid),
            "alone": fc.Cents(item.alone),
            "excess": fc.Cents(item.excess),
        }
        for item in found
    ]


def split_json(ride: Ride, split: Split) -> dict:
    return {
        "share_cents": {name: fc.Cents(c) for name, c in zip(ride.riders, split.cents)},
        "in_core": not split.violations,
        "violation_count": len(split.violations),
        "violations": violation_json(ride, split.violations),
    }


def solo_savings(game: Game, split: Split) -> list:
    """(solo cents, saved cents, percent or None) per rider."""
    out = []
    for i, paid in enumerate(split.cents):
        solo = game.alone[1 << i]
        out.append((solo, solo - paid, percent(solo - paid, solo)))
    return out


def segment_text(ride: Ride, segment: Segment, lang: str) -> tuple:
    return (
        str(segment.index),
        ride.riders[segment.until],
        money(fc.to_cents(segment.cost)),
        names(ride.riders, segment.sharers, lang),
        str(len(segment.sharers)),
    )


def parts_for(ride: Ride, game: Game, rider: int, lang: str) -> str:
    """The stretches a rider sits through, as 'stretch 1 costs 14.00, 4 in the car; ...'."""
    key = "part_est" if ride.mode == "estimates" else "part"
    pieces = []
    for segment in game.segments:
        if rider in segment.sharers:
            pieces.append(
                counted(
                    lang,
                    key,
                    len(segment.sharers),
                    index=segment.index,
                    cost=money(fc.to_cents(segment.cost)),
                    people=len(segment.sharers),
                )
            )
    return ("；" if lang == "zh" else "; ").join(pieces)


def alone_rider(game: Game):
    """The rider who has the last stretch to themselves, with its cost, or None."""
    if game.segments and len(game.segments[-1].sharers) == 1:
        last = game.segments[-1]
        return last.sharers[0], last.cost
    return None


def saving_line(lang: str, solo: int, saved: int, pct) -> str:
    if saved > 0:
        return say(
            lang, "dm_save", solo=money(solo), saved=money(saved), pct="-" if pct is None else pct
        )
    if saved == 0:
        return say(lang, "dm_save_zero", solo=money(solo))
    return say(lang, "dm_loss", solo=money(solo), extra=money(-saved))


def rider_lines(ride: Ride, out: Outcome, rider: int, lang: str) -> list:
    """Private message lines for one rider, written in that rider's own numbers."""
    text = TEXT[lang]
    game = out.game
    share = out.shapley.cents[rider]
    solo, saved, pct = solo_savings(game, out.shapley)[rider]
    lines = [say(lang, "dm_pay", share=money(share))]
    if ride.mode == "general":
        lines.append(text["dm_general"])
    elif solo == 0:
        lines.append(text["dm_null"])
    elif ride.mode == "estimates":
        lines.append(
            say(
                lang,
                "dm_parts_est",
                estimate=money(fc.to_cents(ride.given[rider])),
                solo=money(solo),
                parts=parts_for(ride, game, rider, lang),
                factor=ratio_text(ride.scale),
            )
        )
    else:
        lines.append(say(lang, "dm_parts", parts=parts_for(ride, game, rider, lang)))
    alone = alone_rider(game)
    if ride.mode != "general" and alone is not None and alone[0] == rider:
        key = "dm_alone_est" if ride.mode == "estimates" else "dm_alone"
        lines.append(say(lang, key, cost=money(fc.to_cents(alone[1]))))
    if solo > 0:
        lines.append(saving_line(lang, solo, saved, pct))
    if ride.paid_by >= 0:
        if rider == ride.paid_by:
            lines.append(say(lang, "dm_payer", total=money(ride.total)))
        elif share > 0:
            lines.append(
                say(lang, "dm_transfer", payer=ride.riders[ride.paid_by], amount=money(share))
            )
    return lines


def verdict_base(lang: str, difference: int) -> str:
    """'pays 12.25 too much' / 'pays 21.25 too little' / 'exactly right'."""
    text = TEXT[lang]
    if difference > 0:
        return say(lang, "verdict_over", amount=money(difference))
    if difference < 0:
        return say(lang, "verdict_under", amount=money(-difference))
    return text["verdict_same"]


def verdict_text(lang: str, difference: int, current: int, solo: int) -> str:
    """The verdict, plus a clause when the rider pays more than riding alone would cost."""
    said = verdict_base(lang, difference)
    if current > solo:
        said += say(lang, "verdict_over_alone", amount=money(current - solo))
    return said


def audit_lines(ride: Ride, out: Outcome, rider: int, lang: str) -> list:
    current = out.current.cents[rider]
    fair = out.shapley.cents[rider]
    solo = out.game.alone[1 << rider]
    lines = [
        say(
            lang,
            "dm_audit",
            current=money(current),
            fair=money(fair),
            verdict=verdict_base(lang, current - fair),
        )
    ]
    if current > solo:
        lines.append(say(lang, "dm_audit_alone", solo=money(solo), extra=money(current - solo)))
    count = sum(1 for item in out.current.violations if rider in item.members)
    if count:
        lines.append(counted(lang, "dm_audit_groups", count))
    return lines


def violation_rows(ride: Ride, label: str, split: Split, lang: str) -> list:
    return [
        [
            label,
            names(ride.riders, item.members, lang),
            money(item.paid),
            money(item.alone),
            money(item.excess),
        ]
        for item in split.violations[:MAX_SHOWN]
    ]


def compare_table(ride: Ride, out: Outcome, lang: str) -> fc.Table:
    text = TEXT[lang]
    columns = [("m_shapley_general" if ride.mode == "general" else "m_shapley", out.shapley)]
    columns.append(("m_equal", out.alternatives["equal"]))
    if "proportional" in out.alternatives:
        columns.append(("m_proportional", out.alternatives["proportional"]))
    header = text["hdr_compare"] + [text[key] for key, _ in columns]
    rows = [
        [name] + [money(split.cents[i]) for _, split in columns]
        for i, name in enumerate(ride.riders)
    ]
    rows.append([text["row_total"]] + [money(sum(split.cents)) for _, split in columns])
    rows.append(
        [text["row_core"]]
        + [
            counted(lang, "cell_violated", len(split.violations))
            if split.violations
            else text["cell_in_core"]
            for _, split in columns
        ]
    )
    return fc.Table(header, rows, text["cap_compare"])


def violations_table(ride: Ride, splits, lang: str):
    """(table, notes) for the groups that pay more than riding alone, or (None, [])."""
    text = TEXT[lang]
    rows, notes = [], []
    for label, split in splits:
        if not split.violations:
            continue
        rows += violation_rows(ride, label, split, lang)
        hidden = len(split.violations) - MAX_SHOWN
        if hidden > 0:
            notes.append(say(lang, "more_violations", method=label, count=hidden))
    if not rows:
        return None, notes
    return fc.Table(text["hdr_violations"], rows, text["cap_violations"]), notes


def segments_table(ride: Ride, game: Game, lang: str):
    if not game.segments:
        return None
    text = TEXT[lang]
    header = text["hdr_segments_est"] if ride.mode == "estimates" else text["hdr_segments"]
    return fc.Table(
        header, [list(segment_text(ride, seg, lang)) for seg in game.segments], text["cap_segments"]
    )


def shares_table(ride: Ride, out: Outcome, lang: str) -> fc.Table:
    text = TEXT[lang]
    rows = []
    stats = solo_savings(out.game, out.shapley)
    for i, name in enumerate(ride.riders):
        solo, saved, pct = stats[i]
        rows.append(
            [
                name,
                money(solo),
                money(out.shapley.cents[i]),
                money(saved),
                "-" if pct is None else f"{pct}%",
            ]
        )
    rows.append([text["row_total"], "", money(sum(out.shapley.cents)), "", ""])
    header = text["hdr_shares_est"] if ride.mode == "estimates" else text["hdr_shares"]
    return fc.Table(header, rows, text["cap_shares"])


def coalition_table(ride: Ride, game: Game, lang: str):
    if ride.mode != "general" or ride.n > MAX_COALITION_TABLE:
        return None
    text = TEXT[lang]
    rows = [
        [names(ride.riders, bits(mask, ride.n), lang), money(game.alone[mask])]
        for mask in range(1, 1 << ride.n)
    ]
    return fc.Table(text["hdr_coalitions"], rows, text["cap_coalitions"])


def transfers(ride: Ride, out: Outcome) -> list:
    if ride.paid_by < 0:
        return []
    return [
        (ride.riders[i], ride.riders[ride.paid_by], out.shapley.cents[i])
        for i in range(ride.n)
        if i != ride.paid_by and out.shapley.cents[i] > 0
    ]


def mode_note(ride: Ride, lang: str) -> list:
    text = TEXT[lang]
    if ride.mode == "meter":
        return [text["note_meter"]]
    if ride.mode == "estimates":
        return [say(lang, "note_estimates", factor=ratio_text(ride.scale))]
    notes = [text["note_general"]]
    if ride.scale != 1:
        notes.append(
            say(
                lang,
                "note_scaled",
                actual=money(ride.total),
                model=money(ride.model_total),
                factor=ratio_text(ride.scale),
            )
        )
    if ride.route:
        notes.append(
            say(
                lang,
                "note_route",
                arrow=text["arrow"],
                route=text["arrow"].join(ride.riders[i] for i in ride.route),
                distance=decimal(ride.route_length),
            )
        )
    return notes


def core_notes(ride: Ride, out: Outcome, lang: str) -> list:
    text = TEXT[lang]
    notes = [text["note_core"]]
    method = shapley_label(ride, lang)
    count = (1 << ride.n) - 1
    if out.shapley.violations:
        notes.append(counted(lang, "note_core_fail", len(out.shapley.violations), method=method))
    else:
        notes.append(say(lang, "note_core_pass", count=count, method=method))
    prop = out.alternatives.get("proportional")
    if prop is None:
        notes.append(text["note_prop_undefined"])
    elif not prop.violations and prop.cents != out.shapley.cents:
        notes.append(say(lang, "note_prop_in_core", method=shapley_label(ride, lang, inline=True)))
    if ride.mode == "general":
        notes.append(text["note_general_limits"])
        if out.core_empty is True:
            notes.append(text["note_core_empty"])
        elif out.core_empty is False:
            notes.append(text["note_core_open"])
    return notes


def not_modeled(ride: Ride, lang: str) -> list:
    text = TEXT[lang]
    items = [text["nm_tolls"], text["nm_public"]]
    if ride.mode == "general" and ride.route:
        items.append(text["nm_route"])
    if ride.mode == "estimates":
        items.append(text["nm_scale"])
    return items


def inputs_echo(ride: Ride, game: Game) -> dict:
    echo = {
        "mode": ride.mode,
        "riders": list(ride.riders),
        "ride_id": ride.ride_id,
        "total": fc.Cents(ride.total),
        "rules": {"method": RULE_METHODS[0]},
    }
    if ride.mode == "meter":
        echo["meter_at_dropoff"] = [fc.Cents(fc.to_cents(v)) for v in ride.given]
    elif ride.mode == "estimates":
        echo["solo_estimate"] = [fc.Cents(fc.to_cents(v)) for v in ride.given]
        echo["actual_total"] = fc.Cents(ride.total)
        echo["scale"] = ratio_text(ride.scale)
    else:
        echo["subset_costs"] = [
            {
                "riders": [ride.riders[i] for i in bits(mask, ride.n)],
                "cost": fc.Cents(game.alone[mask]),
            }
            for mask in range(1, 1 << ride.n)
        ]
        if ride.distances:
            echo["distance_matrix"] = [[decimal(d) for d in row] for row in ride.distances]
            echo["tariff"] = {
                "base": fc.Cents(fc.to_cents(ride.tariff["base"])),
                "per_unit": decimal(ride.tariff["per_unit"]),
                "minimum": fc.Cents(fc.to_cents(ride.tariff["minimum"])),
            }
        if ride.scale != 1:
            echo["scale"] = ratio_text(ride.scale)
    if ride.paid_by >= 0:
        echo["paid_by"] = ride.riders[ride.paid_by]
    return echo


def build_result(
    ride: Ride, out: Outcome, audit: bool = False, lang: str = "zh", reproduce: str = ""
) -> fc.Result:
    """Turn a computed ride into the shared Result (md, dm, group and json come from it)."""
    if lang not in TEXT:
        raise ValueError(f"lang must be one of {', '.join(TEXT)}")
    text = TEXT[lang]
    game = out.game
    shapley = out.shapley
    stats = solo_savings(game, shapley)
    result = {
        "method": RULE_METHODS[0],
        "share_cents": {name: fc.Cents(c) for name, c in zip(ride.riders, shapley.cents)},
        "solo_cents": {name: fc.Cents(s[0]) for name, s in zip(ride.riders, stats)},
        "saved_cents": {name: fc.Cents(s[1]) for name, s in zip(ride.riders, stats)},
        "saved_percent": {name: s[2] for name, s in zip(ride.riders, stats)},
        "segments": [
            {
                "index": seg.index,
                "until": ride.riders[seg.until],
                "cost": fc.Cents(fc.to_cents(seg.cost)),
                "shared_by": [ride.riders[i] for i in seg.sharers],
            }
            for seg in game.segments
        ],
        "in_core": not shapley.violations,
        "violation_count": len(shapley.violations),
        "violations": violation_json(ride, shapley.violations),
        "alternatives": {key: split_json(ride, split) for key, split in out.alternatives.items()},
    }
    if ride.mode == "general":
        result["core_is_empty"] = out.core_empty
        if ride.route:
            result["route"] = [ride.riders[i] for i in ride.route]
            result["route_length"] = decimal(ride.route_length)
    pay_list = transfers(ride, out)
    if ride.paid_by >= 0:
        result["transfers"] = [
            {"from": src, "to": dst, "amount": fc.Cents(amount)} for src, dst, amount in pay_list
        ]
    key = "title_audit" if audit else f"title_{ride.mode}"
    title = text[key]
    if audit:
        tables, notes, person_lines, group_lines = audit_report(ride, out, result, lang)
    else:
        tables, notes, person_lines, group_lines = normal_report(ride, out, pay_list, lang)
        if ride.audit_ignored:
            notes.append(text["note_audit_ignored"])
    notes.append(say(lang, "note_rounding", ride_id=ride.ride_id))
    certificate = {
        "one_liner": {name: " ".join(lines) for name, lines in person_lines.items()},
    }
    return fc.Result(
        title=title,
        inputs_echo=inputs_echo(ride, game),
        result=result,
        certificate=certificate,
        not_modeled=not_modeled(ride, lang),
        reproduce=reproduce,
        tables=tables,
        notes=notes,
        person_lines=person_lines,
        group_lines=group_lines,
    )


def normal_report(ride: Ride, out: Outcome, pay_list: list, lang: str):
    text = TEXT[lang]
    game = out.game
    tables = []
    seg_table = segments_table(ride, game, lang)
    if seg_table is not None:
        tables.append(seg_table)
    coal = coalition_table(ride, game, lang)
    if coal is not None:
        tables.append(coal)
    tables.append(shares_table(ride, out, lang))
    if ride.paid_by >= 0 and pay_list:
        tables.append(
            fc.Table(
                text["hdr_transfers"],
                [[src, dst, money(amount)] for src, dst, amount in pay_list],
                text["cap_transfers"],
            )
        )
    tables.append(compare_table(ride, out, lang))
    labelled = [(shapley_label(ride, lang), out.shapley)]
    labelled.append((text["m_equal"], out.alternatives["equal"]))
    if "proportional" in out.alternatives:
        labelled.append((text["m_proportional"], out.alternatives["proportional"]))
    viol_table, viol_notes = violations_table(ride, labelled, lang)
    if viol_table is not None:
        tables.append(viol_table)
    notes = mode_note(ride, lang)
    alone = alone_rider(game)
    if ride.mode != "general" and alone is not None:
        key = "note_alone_est" if ride.mode == "estimates" else "note_alone"
        notes.append(say(lang, key, name=ride.riders[alone[0]], cost=money(fc.to_cents(alone[1]))))
    notes += core_notes(ride, out, lang) + viol_notes
    if ride.paid_by >= 0:
        notes.append(say(lang, "note_paid", payer=ride.riders[ride.paid_by]))
    person_lines = {name: rider_lines(ride, out, i, lang) for i, name in enumerate(ride.riders)}
    group_lines = [say(lang, "g_intro", count=ride.n, total=money(ride.total))]
    group_lines += [
        say(lang, "g_line", name=name, amount=money(c))
        for name, c in zip(ride.riders, out.shapley.cents)
    ]
    group_lines.append(text["g_method_general"] if ride.mode == "general" else text["g_method"])
    if out.shapley.violations:
        group_lines.append(counted(lang, "g_core_fail", len(out.shapley.violations)))
    else:
        group_lines.append(text["g_core_pass"])
    group_lines += [
        say(lang, "g_transfer", src=src, dst=dst, amount=money(amount))
        for src, dst, amount in pay_list
    ]
    return tables, notes, person_lines, group_lines


def audit_report(ride: Ride, out: Outcome, result: dict, lang: str):
    text = TEXT[lang]
    game = out.game
    current = out.current
    fair = out.shapley.cents
    rows = []
    differences = []
    for i, name in enumerate(ride.riders):
        solo = game.alone[1 << i]
        diff = current.cents[i] - fair[i]
        differences.append(diff)
        rows.append(
            [
                name,
                money(current.cents[i]),
                money(fair[i]),
                signed(diff),
                money(solo),
                verdict_text(lang, diff, current.cents[i], solo),
            ]
        )
    result["audit"] = {
        "current_cents": {name: fc.Cents(c) for name, c in zip(ride.riders, current.cents)},
        "difference_cents": {name: fc.Cents(d) for name, d in zip(ride.riders, differences)},
        "in_core": not current.violations,
        "violation_count": len(current.violations),
        "violations": violation_json(ride, current.violations),
    }
    tables = [fc.Table(text["hdr_audit"], rows, text["cap_audit"])]
    viol_table, viol_notes = violations_table(ride, [(text["m_current"], current)], lang)
    if viol_table is not None:
        tables.append(viol_table)
    seg_table = segments_table(ride, game, lang)
    if seg_table is not None:
        tables.append(seg_table)
    notes = mode_note(ride, lang) + [text["note_core"]] + viol_notes
    if ride.mode == "general" and out.shapley.violations:
        notes.append(text["note_general_limits"])
        if out.core_empty is True:
            notes.append(text["note_core_empty"])
        elif out.core_empty is False:
            notes.append(text["note_core_open"])
    notes.append(text["note_audit"])
    person_lines = {name: audit_lines(ride, out, i, lang) for i, name in enumerate(ride.riders)}
    group_lines = [
        say(
            lang,
            "g_audit_intro",
            total=money(ride.total),
            method=shapley_label(ride, lang, inline=True),
        )
    ]
    for i, name in enumerate(ride.riders):
        group_lines.append(
            say(
                lang,
                "g_audit_line",
                name=name,
                current=money(current.cents[i]),
                fair=money(fair[i]),
                verdict=verdict_text(lang, differences[i], current.cents[i], game.alone[1 << i]),
            )
        )
    if current.violations:
        group_lines.append(counted(lang, "g_audit_fail", len(current.violations)))
    else:
        group_lines.append(text["g_audit_pass"])
    return tables, notes, person_lines, group_lines


def solve(data: dict, audit: bool = False, lang: str = "zh", reproduce: str = "") -> fc.Result:
    """Validate, compute and build the Result for one input object."""
    ride = parse_ride(data, audit)
    return build_result(ride, compute(ride), audit, lang, reproduce)


# ---------------------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------------------


def selftest_checks() -> list:
    """Checks for --selftest: the worked examples and a few cross-checks, all fast."""

    def run(data: dict) -> Outcome:
        return compute(parse_ride(data))

    meter = {
        "mode": "meter",
        "ride_id": "ride-1",
        "riders": ["小周", "阿杰", "Mia", "老陈"],
        "meter_at_dropoff": [14, 26, 41, 63],
    }

    def check_meter_numbers() -> None:
        out = run(meter)
        fc.expect(out.shapley.cents == [350, 750, 1500, 3700], f"shapley {out.shapley.cents}")
        fc.expect(out.alternatives["equal"].cents == [1575] * 4, "equal split")
        fc.expect(
            out.alternatives["proportional"].cents == [613, 1137, 1794, 2756],
            f"proportional {out.alternatives['proportional'].cents}",
        )
        fc.expect(not out.shapley.violations, "Shapley must be in the core")
        fc.expect(len(out.alternatives["equal"].violations) == 3, "equal split breaks 3 groups")
        fc.expect(not out.alternatives["proportional"].violations, "proportional is in the core")
        saved = [s[1] for s in solo_savings(out.game, out.shapley)]
        fc.expect(saved == [1050, 1850, 2600, 2600], f"savings {saved}")

    def check_estimates_numbers() -> None:
        data = dict(meter, mode="estimates", solo_estimate=[15, 27, 40, 66], actual_total=63)
        del data["meter_at_dropoff"]
        out = run(data)
        fc.expect(out.shapley.cents == [358, 740, 1360, 3842], f"estimates {out.shapley.cents}")
        fc.expect(len(out.alternatives["equal"].violations) == 3, "equal split breaks 3 groups")

    def check_closed_form() -> None:
        solo = [Fraction(v) for v in (5, 5, 12, 20, 20, 31)]
        n = len(solo)
        table = [Fraction(0)] + [max(solo[i] for i in bits(mask, n)) for mask in range(1, 1 << n)]
        fc.expect(airport_shapley(solo) == fc.shapley_values(n, table), "closed form vs subsets")
        small = table[: 1 << 4]
        fc.expect(
            shapley_by_orders(4, small) == fc.shapley_values(4, small),
            "orders vs subsets",
        )

    def check_core_emptiness() -> None:
        # three riders in three directions: sharing costs 5, separate cars only 3
        alone = [0, 1, 1, 3, 1, 3, 3, 5]
        fc.expect(core_is_empty(3, alone), "the star game has an empty core")
        fc.expect(not core_is_empty(3, [0, 4, 4, 6, 4, 6, 6, 9]), "a convex game has a core")

    def check_rejections() -> None:
        for bad, field_name in (
            (dict(meter, meter_at_dropoff=[14, 26, 20, 63]), "meter_at_dropoff[2]"),
            (dict(meter, meter_at_dropoff=[14, 26, -1, 63]), "meter_at_dropoff[2]"),
            (dict(meter, riders=["小周", "阿杰", "Mia"]), "riders"),
        ):
            try:
                parse_ride(bad)
            except fc.InputError as err:
                fc.expect(field_name in err.field or field_name in err.message, err.field)
            else:
                raise AssertionError(f"{field_name} was accepted")

    return [
        ("meter example", check_meter_numbers),
        ("estimates example", check_estimates_numbers),
        ("closed form equals subsets and orders", check_closed_form),
        ("empty core detected", check_core_emptiness),
        ("bad input names its field", check_rejections),
    ]


# ---------------------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=textwrap.fill(
            "Split a shared taxi or carpool fare fairly (Shapley value, exact to the cent) and "
            "check whether any rider or group pays more than riding alone.",
            width=78,
        ),
        epilog=(
            "Input is a JSON object with a mode:\n"
            "  meter      riders (in drop-off order), meter_at_dropoff (cumulative readings)\n"
            "  estimates  riders, solo_estimate (app estimate per rider), actual_total\n"
            "  general    riders, and subset_costs (price of every group) or distance_matrix\n"
            "             with tariff; optional actual_total\n"
            "Optional in every mode: paid_by, ride_id, audit (with --audit).\n"
            "Limits: meter and estimates take 2 to 12 riders, general takes 2 to 6.\n\n"
        )
        + fc.exit_codes_epilog(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    fc.standard_args(parser)
    parser.add_argument(
        "--audit",
        action="store_true",
        help="compare the split in the input's audit.current (an object with what each rider "
        "pays now, or the text equal or proportional) with the fair split, and list the groups "
        "that pay more than riding alone",
    )
    fc.add_lang_option(parser, "amounts and JSON keys do not change")
    return parser


def reproduce_command(args: argparse.Namespace) -> str:
    parts = ["python3", "scripts/ride_split.py"]
    parts += ["--demo"] if args.demo else ["--input", "-"]
    parts += ["--json"] if args.json else ["--format", args.format]
    if args.audit:
        parts.append("--audit")
    if args.lang != "zh":
        parts += ["--lang", args.lang]
    return " ".join(parts)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    fc.exclusive_modes(args, "--demo", "--selftest")
    if args.selftest:
        return fc.run_selftest(selftest_checks())
    data = fc.read_object(args, DEMO_JSON)
    if args.demo and not args.audit:
        data.pop("audit", None)
    result = solve(data, args.audit, args.lang, reproduce_command(args))
    fc.emit(result, args, lang=args.lang)
    return 0


if __name__ == "__main__":
    fc.run_cli(main)
