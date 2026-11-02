"""Draw a gift exchange (Secret Santa) that anyone can recompute.

Everybody gives one gift and receives one gift, nobody draws themselves, and some pairs must not
be matched (couples, last year's pairs). The input lists the people, the directions that are not
allowed (pair for both ways, giver with receiver for one way) and the public random source.

First the script checks that a legal draw exists. A legal plan is a perfect matching of the
bipartite graph of allowed gifts, so Hall's theorem gives the reason when there is none: a group
of people who may give to fewer people than they are. Two ways of giving:

  any   any derangement: nobody draws themselves or a person who is not allowed. Two people may
        give to each other.
  ring  one single circle: everybody gives to the next person in a circle through all of them.

Up to ENUMERATE_MAX people the script lists every legal plan in a fixed order and draws one number
below the count, so every legal plan has the same chance. With more people it proposes random
plans from the same stream and keeps the first legal one (rejection sampling), up to MAX_ATTEMPTS
proposals. Seed and stream follow fsq_core.SEED_SPEC: SHA-256 only, never the random module, so
the same input prints the same bytes on every Python version.

--check only asks whether a legal draw exists and needs no random source.

Input is JSON on standard input (--input -) or in a file (--input FILE). Output is --format
md|dm|group or --json, in Chinese or English (--lang). Exit code 0 means success, 1 a failed
self-test, 2 invalid input (the message names the field), 3 that no legal draw exists or was found.
Standard library only, Python 3.9+.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import fsq_core as fc
except ModuleNotFoundError:  # python -I, -P and PYTHONSAFEPATH leave the script folder off sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import fsq_core as fc

# ---------------------------------------------------------------------------------------
# Limits, fixed names and the demo
# ---------------------------------------------------------------------------------------

MODES = ("any", "ring")
DEFAULT_MODE = "any"
METHODS = ("enumeration", "rejection")
ENUMERATE_MAX = 9  # up to this many people every legal plan is listed (9! is 362880)
MAX_ATTEMPTS = 20000  # rejection sampling gives up after this many proposals
MAX_PEOPLE = 100
MAX_FORBIDDEN = 5000
RULE_NAMES = {
    ("any", "enumeration"): "gift_exchange_any_enum_v1",
    ("any", "rejection"): "gift_exchange_any_reject_v1",
    ("ring", "enumeration"): "gift_exchange_ring_enum_v1",
    ("ring", "rejection"): "gift_exchange_ring_reject_v1",
}
TOP_FIELDS = ("mode", "people", "forbidden", "random_source", "rules")
FORBIDDEN_FIELDS = ("pair", "giver", "receiver")
RULE_FIELDS = ("source_description", "deadline")
SEED_ORDER_SENTENCE = " The order is Fisher-Yates"

# The fictional six-person example: two couples, and Lao Wang gave to Yuki last year. It has 96
# legal plans, 40 of them single circles.
DEMO_JSON = """{
  "mode": "any",
  "people": ["阿明", "小红", "大刘", "Coco", "老王", "Yuki"],
  "forbidden": [
    {"pair": ["阿明", "小红"]},
    {"pair": ["大刘", "Coco"]},
    {"giver": "老王", "receiver": "Yuki"}
  ],
  "random_source": "（虚构示例）2026-11-08 某公开开奖号码 03 11 19 24 33 + 02 07",
  "rules": {
    "source_description": "虚构示例：2026 年 11 月 8 日某公开开奖，按官网显示的格式原样抄写",
    "deadline": "2026-11-07 20:00 报名截止，名单和不能互送的规则随后锁定"
  }
}"""

# ---------------------------------------------------------------------------------------
# Texts (zh is the default, en says the same)
# ---------------------------------------------------------------------------------------

TEXT = {
    "zh": {
        "sep": "、",
        "none": "无",
        "mode_any": "任意错排",
        "mode_ring": "一圈传下去",
        "title": "交换礼物抽签结果：{people} 人（{mode}）",
        "title_check": "交换礼物规则检查：{people} 人（{mode}）",
        "cap_pairs": "谁送给谁（完整表，只给组织者）",
        "hdr_pairs": ["送礼人", "收礼人"],
        "n_organizer": (
            "给组织者：上表写着每个人送给谁。只把各人自己的那一条私信发给本人，"
            "不要把上表或它的截图发到群里。运行这个脚本的人（包括这次会话）会看到全表。"
        ),
        "n_ring": "一圈的顺序：{chain}。",
        "cap_source": "抽法与复算材料（礼物交换完之后再公布）",
        "hdr_facts": ["项目", "内容"],
        "f_description": "随机源说明",
        "f_deadline": "截止时间",
        "f_source": "随机源原文（逐字）",
        "f_mode": "方式",
        "f_method": "选法",
        "f_rule": "规则名",
        "f_n": "人数（写进种子的 n_slots）",
        "f_count": "人数",
        "f_people": "名单（按码位排序，写进种子）",
        "f_forbidden": "不能送的方向（谁不能送给谁）",
        "f_total": "合法方案总数",
        "f_number": "抽到的方案序号",
        "f_attempts": "第几次随机试排合法",
        "f_preimage": "种子原像（对这段文字取 SHA-256）",
        "f_seed": "种子（SHA-256，十六进制）",
        "method_enumeration": "列出全部合法方案，按序号抽一个",
        "method_rejection": "随机试排，第一个合法的就是结果",
        "number_value": "第 {k} 种（共 {total} 种）",
        "attempts_value": "第 {t} 次（最多试 {max} 次）",
        "shape_any": "",
        "shape_ring": "，并且所有人连成一个圈（从任何人出发，走 {n} 步才回到自己）",
        "prop_any": "编号 i 的人送给编号 s(i) 的人。",
        "prop_ring": "s 的第 k 位送给第 k+1 位，最后一位送给第一位，所有人连成一个圈。",
        "n_algo_enumeration": (
            "复算方法：① 种子 = 「种子原像」的 SHA-256（UTF-8）。② 第 c 次取数（c 从 0 起）"
            "= SHA-256（种子 + c 的 8 字节大端）的前 8 字节，按大端读成整数 x。要取 0 到 n−1 "
            "之间的整数时，x 小于 2^64 − (2^64 mod n) 就取 x 除以 n 的余数，否则 c 加 1 重取。"
            "③ 名单按码位排序，编号 0 到 {last}。一个方案给每位送礼人 i 定一位收礼人 r(i)，"
            "r 是一一对应的，r(i) 不等于 i，也不在「不能送的方向」里{shape}。"
            "④ 把全部合法方案按 r(0)、r(1)、r(2)、…… 从小到大排好，用第 ② 步取一个 0 到 N−1 "
            "之间的整数 k（N 是合法方案总数），第 k+1 种就是结果。整个过程不用 random 模块。"
        ),
        "n_algo_rejection": (
            "复算方法：① 种子 = 「种子原像」的 SHA-256（UTF-8）。② 第 c 次取数（c 从 0 起）"
            "= SHA-256（种子 + c 的 8 字节大端）的前 8 字节，按大端读成整数 x。要取 0 到 n−1 "
            "之间的整数时，x 小于 2^64 − (2^64 mod n) 就取 x 除以 n 的余数，否则 c 加 1 重取。"
            "③ 名单按码位排序，编号 0 到 {last}。第 t 次试排（t 从 1 起）：接着用同一串取数，"
            "对编号 0 到 {last} 做洗牌（i 从 {last} 降到 1，每步取一个 0 到 i 之间的整数 j，"
            "交换第 i 位和第 j 位），得到排列 s。{proposal}"
            "如果没有人送给自己，也没有用到「不能送的方向」，这次试排就合法，立刻停下，"
            "它就是结果，否则做下一次试排。最多试 {max} 次，超过就报错。整个过程不用 random 模块。"
        ),
        "n_pipe": (
            "表格里的竖线 | 前面被加了一个反斜杠。复算时请用 --json 里的种子原像，"
            "不要从表格里复制。"
        ),
        "n_verify": (
            "核对：用同样的输入再运行一次这个脚本，输出逐字节相同。礼物交换完之后公布上面的材料，"
            "任何人都可以自己重新算一遍。"
        ),
        "nm_source": (
            "随机源是否真的事先约定、事后无法更改、临场无人能预测：脚本核对不了。"
            "这三条只要有一条不成立，就有人能影响结果。"
        ),
        "nm_frozen": (
            "名单、方式和不能互送的规则是否在随机源公布前就已冻结：由群里的记录证明，"
            "脚本只按输入计算。"
        ),
        "nm_view": (
            "谁看得到结果：运行脚本的人看到全表，抽法又是公开的，所以有名单、不能互送的规则"
            "和随机源原文的人，自己跑一遍也能算出全表。这些材料要等礼物交换完再公布。"
        ),
        "nm_swap": (
            "任意错排允许两个人互送（甲送给乙，乙也送给甲）。不想出现这种情况，"
            "就选「一圈传下去」，或者把这两个人登记为不能互送。"
        ),
        "dm_gift": "你要送礼物给：{receiver}。",
        "dm_ring": "这次是「一圈传下去」：所有人连成一个圈，每个人只送给圈里的下一个人。",
        "dm_keep": "到交换礼物那天再揭晓，在那之前请不要告诉别人。",
        "dm_rule": "按事先定的规则，你不会抽到自己，也不会抽到事先登记为不能互送的人。",
        "g_names": "名单：{names}",
        "g_sent": "每个人已经收到一条私信，写着自己要送给谁。这张卡片不含任何人送给谁。",
        "g_mode": "方式：{mode}",
        "g_forbidden": "不能互送的规则：共 {k} 条（每条是一个方向，谁不能送给谁）。",
        "g_total": "合法方案共 {total} 种。如果随机源事先无法被预测，每一种被抽中的机会相同。",
        "g_reject": (
            "人数超过 {limit}，不逐个枚举：随机试排，第一个合法的就是结果。"
            "如果随机源事先无法被预测，每一种合法方案被抽中的机会相同。"
        ),
        "g_description": "随机源说明：{text}",
        "g_deadline": "截止时间：{text}",
        "g_open": (
            "抽法公开、可复算：随机源是事先约定的公开文本，从文本到结果只用 SHA-256 和整数运算，"
            "不用 random 模块。随机源原文、种子原像、不能互送的规则和抽到的方案序号，"
            "等礼物交换完再公布，任何人都可以重新算一遍。现在不公布，是因为有了这些材料，"
            "会跑脚本的人能直接算出每个人送给谁。"
        ),
        "cap_check": "检查结果",
        "c_conclusion": "结论",
        "c_ok": "有合法方案",
        "c_open": "没有发现无解的迹象，但一圈是否真的存在，要等抽签时才知道",
        "n_check_scope": (
            "这一步只检查规则有没有解，不抽签，不需要随机源，可以在随机源公布之前做。"
            "结果只取决于名单、方式和不能互送的规则。"
        ),
        "n_check_many_any": (
            "人数超过 {limit}，不逐个枚举。有合法方案已经确认。抽签时随机试排，最多试 {max} 次，"
            "方案很少时可能试不到，那时脚本会报错，而不是给出一个不均匀的结果。"
        ),
        "n_check_many_ring": (
            "人数超过 {limit}，不逐个枚举。每个人都有人可送，所有人也彼此连得上，所以没有发现无解的迹象。"
            "但一圈是否真的存在，要等抽签时随机试排才知道，最多试 {max} 次。"
        ),
        "err_hall": (
            "没有合法的抽法：{group}这 {k} 个人能送的只有{others}（{m} 人），人数不够分，"
            "必有人没有对象可送。请改一改不能互送的规则，或者增加人数。"
        ),
        "err_hall_none": (
            "没有合法的抽法：{group}这 {k} 个人一个能送的人都没有。请改一改不能互送的规则，"
            "或者增加人数。"
        ),
        "err_closed": (
            "没有合法的一圈：{group}这 {k} 个人能送的人都在他们自己中间，一个圈走不出这个小组，"
            "没法把全部 {n} 个人连成一圈。可以改用任意错排，或者改一改不能互送的规则。"
        ),
        "err_exhausted": (
            "没有合法的一圈：{n} 个人所有 {total} 种一圈传下去的排法都查过了，"
            "每一种都用到了不能送的方向。可以改用任意错排，或者改一改不能互送的规则。"
        ),
        "err_limit": (
            "随机试了 {attempts} 次，没有找到合法的抽法。这 {n} 个人在现有规则下合法方案很少，"
            "但这不能证明一定没有。请放宽不能互送的规则，或者把人分成两组。"
        ),
    },
    "en": {
        "sep": ", ",
        "none": "none",
        "mode_any": "any derangement",
        "mode_ring": "one circle",
        "title": "Gift exchange draw: {people} people ({mode})",
        "title_check": "Gift exchange rules check: {people} people ({mode})",
        "cap_pairs": "Who gives to whom (the full table, for the organizer only)",
        "hdr_pairs": ["Giver", "Receiver"],
        "n_organizer": (
            "For the organizer: the table above says who gives to whom. Send each person only "
            "their own private message, and do not post the table or a screenshot of it in the "
            "group. Whoever runs this script (this session included) sees the whole table."
        ),
        "n_ring": "Order of the circle: {chain}.",
        "cap_source": "How it was drawn and what is needed to recompute (publish after the exchange)",
        "hdr_facts": ["Item", "Value"],
        "f_description": "Where the source comes from",
        "f_deadline": "Deadline",
        "f_source": "Source text (verbatim)",
        "f_mode": "Way of giving",
        "f_method": "How the plan is chosen",
        "f_rule": "Rule name",
        "f_n": "Number of people (the n_slots of the seed)",
        "f_count": "Number of people",
        "f_people": "Names (sorted by code point, part of the seed)",
        "f_forbidden": "Directions that are not allowed (who may not give to whom)",
        "f_total": "Number of legal plans",
        "f_number": "Number of the plan drawn",
        "f_attempts": "Random proposal that was legal",
        "f_preimage": "Seed preimage (take the SHA-256 of this text)",
        "f_seed": "Seed (SHA-256, hex)",
        "method_enumeration": "list every legal plan and draw one by its number",
        "method_rejection": "propose random plans, the first legal one is the result",
        "number_value": "number {k} of {total}",
        "attempts_value": "try {t} (at most {max})",
        "shape_any": "",
        "shape_ring": ", and everybody is in one circle (starting from anybody it takes {n} steps to get back)",
        "prop_any": "The person numbered i gives to the person numbered s(i).",
        "prop_ring": (
            "The person at place k of s gives to the person at place k+1, the last gives to the "
            "first, and everybody is in one circle."
        ),
        "n_algo_enumeration": (
            "Recompute: (1) The seed is the SHA-256 of the seed preimage (UTF-8). (2) Draw "
            "number c (c counts from 0) is the first 8 bytes, read big-endian, of SHA-256 of the "
            "seed followed by c as 8 big-endian bytes. A uniform integer in [0, n) takes x mod n "
            "if x < 2^64 - (2^64 mod n), otherwise the next draw is used. (3) Sort the names by "
            "code point and number them 0 to {last}. A plan gives every giver i one receiver "
            "r(i). r is one-to-one, r(i) is not i, and (i, r(i)) is not a direction that is not "
            "allowed{shape}. (4) Sort all legal plans by r(0), r(1), r(2), ... in increasing "
            "order. Take a uniform integer k in [0, N) with step (2), where N is the number of "
            "legal plans. Plan number k+1 is the result. The random module is not used."
        ),
        "n_algo_rejection": (
            "Recompute: (1) The seed is the SHA-256 of the seed preimage (UTF-8). (2) Draw "
            "number c (c counts from 0) is the first 8 bytes, read big-endian, of SHA-256 of the "
            "seed followed by c as 8 big-endian bytes. A uniform integer in [0, n) takes x mod n "
            "if x < 2^64 - (2^64 mod n), otherwise the next draw is used. (3) Sort the names by "
            "code point and number them 0 to {last}. Proposal t (t counts from 1) goes on with "
            "the same stream: Fisher-Yates over the numbers 0 to {last} (i from {last} down to "
            "1, swap place i with a uniform integer in [0, i]) gives a permutation s. "
            "{proposal} If nobody gives to themselves and no direction that is not allowed is "
            "used, the proposal is legal, the search stops, and it is the result. Otherwise "
            "the next proposal is made. After {max} proposals the script reports an error. The "
            "random module is not used."
        ),
        "n_pipe": (
            "A backslash was put in front of each vertical bar | in the tables. To recompute, "
            "use the seed preimage in the --json output, not a copy from a table."
        ),
        "n_verify": (
            "Check it: run this script again on the same input and the output is identical byte "
            "for byte. After the exchange, publish the material above and anybody can recompute "
            "it."
        ),
        "nm_source": (
            "Whether the random source was really fixed in advance, cannot be changed afterwards "
            "and could not be predicted: the script cannot check this. If any of the three fails, "
            "the result can be steered."
        ),
        "nm_frozen": (
            "Whether the names, the way of giving and the exclusions were frozen before the "
            "source was published: the group's records show it, the script only computes from "
            "the input."
        ),
        "nm_view": (
            "Who can see the result: whoever runs the script sees the whole table, and because "
            "the draw is public, anybody who has the names, the exclusions and the source text "
            "can run it and get the whole table too. Publish this material only after the "
            "exchange."
        ),
        "nm_swap": (
            "Any derangement allows two people to give to each other (A to B and B to A). To "
            "avoid that, choose one circle, or list the two as a pair that may not be matched."
        ),
        "dm_gift": "You give a gift to: {receiver}.",
        "dm_ring": (
            'This is the "one circle" way: everybody is in a single circle and gives only to '
            "the next person in it."
        ),
        "dm_keep": "Do not tell anyone before the exchange.",
        "dm_rule": (
            "By the agreed rules you cannot draw yourself or anyone registered as not allowed "
            "for you."
        ),
        "g_names": "Names: {names}",
        "g_sent": (
            "Everybody has received a private message saying who they give to. This card does "
            "not say who gives to whom."
        ),
        "g_mode": "Way of giving: {mode}",
        "g_forbidden": (
            "Exclusions: {k} in all (each is one direction, who may not give to whom)."
        ),
        "g_total": (
            "There are {total} legal plans. If the random source could not be predicted in "
            "advance, each of them is equally likely to be drawn."
        ),
        "g_reject": (
            "With more than {limit} people the plans are not listed: random plans are proposed "
            "and the first legal one is the result. If the random source could not be predicted "
            "in advance, each legal plan is equally likely to be drawn."
        ),
        "g_description": "Where the source comes from: {text}",
        "g_deadline": "Deadline: {text}",
        "g_open": (
            "The way of drawing is public and can be recomputed: the random source is a public "
            "text agreed in advance, and from that text to the result the script uses only "
            "SHA-256 and integer arithmetic, never the random module. The source text, the "
            "seed preimage, the exclusions and the number of the plan drawn will be published "
            "after the exchange, and anybody can recompute the draw from them. They are not "
            "published now because with them anybody who runs the script can work out who gives "
            "to whom."
        ),
        "cap_check": "Result of the check",
        "c_conclusion": "Conclusion",
        "c_ok": "a legal plan exists",
        "c_open": "no sign that none exists, but whether a circle really exists is only known at the draw",
        "n_check_scope": (
            "This step only asks whether the rules have a solution. It draws nothing and needs "
            "no random source, so it can be done before the source is published. The answer "
            "depends only on the names, the way of giving and the exclusions."
        ),
        "n_check_many_any": (
            "With more than {limit} people the plans are not listed. A legal plan is known to "
            "exist. The draw proposes random plans, at most {max} of them. If legal plans are "
            "very rare it may find none, and then the script reports an error instead of giving "
            "an uneven result."
        ),
        "n_check_many_ring": (
            "With more than {limit} people the plans are not listed. Everybody has someone to "
            "give to and everybody can be reached from everybody, so there is no sign that no "
            "circle exists. Whether one really exists is only known when the draw proposes "
            "random plans, at most {max} of them."
        ),
        "err_hall": (
            "No legal draw exists. {group} ({gcount}) can only give to {others} ({ocount}), so "
            "somebody would have nobody to give to. Change the exclusions or add people."
        ),
        "err_hall_none": (
            "No legal draw exists. {group} ({gcount}) cannot give to anybody under the "
            "exclusions. Change the exclusions or add people."
        ),
        "err_closed": (
            "No single circle exists. {group} ({gcount}) may only give to each other, so a "
            "circle cannot leave this group and reach everybody else. Use the way any, change "
            "the exclusions or add people."
        ),
        "err_exhausted": (
            "No single circle exists. All {total} circles through the {n} people were checked "
            "and each one uses a direction that is not allowed. Use the way any, change the "
            "exclusions or add people."
        ),
        "err_limit": (
            "No legal plan was found in {attempts} random tries. The rules leave very few legal "
            "plans for {n} people, but this does not prove that none exists. Loosen the "
            "exclusions or split the group in two."
        ),
    },
}


def say(lang: str, key: str, **values: Any) -> str:
    """The text of one key, filled in. Chinese text puts a space between a Latin name and the
    Chinese characters next to it (see fsq_core.fill_text)."""
    return fc.fill_text(lang, TEXT[lang][key], **values)


def joined(lang: str, items: Sequence[str]) -> str:
    """Names joined with the separator of the language, or the word for none."""
    text = TEXT[lang]
    return text["sep"].join(items) if items else text["none"]


def count_text(lang: str, count: int) -> str:
    """'1 person', '3 people' in English and '3 人' in Chinese."""
    if lang == "zh":
        return f"{count} 人"
    return f"{count} person" if count == 1 else f"{count} people"


# ---------------------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------------------


@dataclass
class Problem:
    """A validated input. People are numbered by their place in the code point order."""

    mode: str
    names: list  # all the people, sorted by code point
    blocked: frozenset  # (giver, receiver) pairs of numbers that are not allowed
    source: str | None  # the public text; None for --check without one
    description: str
    deadline: str
    listed: list  # the people in the order the input listed them (only error messages use it)

    @property
    def n(self) -> int:
        return len(self.names)

    @property
    def allowed(self) -> list:
        """allowed[i] is the sorted list of the numbers person i may give to."""
        return allowed_lists(self.n, self.blocked)


def allowed_lists(n: int, blocked: frozenset) -> list:
    return [[j for j in range(n) if j != i and (i, j) not in blocked] for i in range(n)]


def known_person(value: Any, where: str, index: dict) -> int:
    name = fc.require_text(value, where)
    if name not in index:
        raise fc.InputError(where, f"{name!r} is not a person listed in people")
    return index[name]


def parse_forbidden(value: Any, index: dict) -> frozenset:
    """forbidden: pair (both ways) or giver with receiver (one way) -> set of directions."""
    entries = fc.require_list(value, "forbidden", 0, MAX_FORBIDDEN)
    blocked: set = set()
    for position, entry in enumerate(entries):
        where = f"forbidden[{position}]"
        obj = fc.require_object(entry, where)
        fc.check_fields(obj, FORBIDDEN_FIELDS, where)
        if "pair" in obj:
            if "giver" in obj or "receiver" in obj:
                raise fc.InputError(where, "give either pair, or giver with receiver, not both")
            pair = fc.require_list(obj["pair"], f"{where}.pair", 2, 2)
            first = known_person(pair[0], f"{where}.pair[0]", index)
            second = known_person(pair[1], f"{where}.pair[1]", index)
            if first == second:
                raise fc.InputError(f"{where}.pair", "needs two different people")
            blocked |= {(first, second), (second, first)}
        elif "giver" in obj and "receiver" in obj:
            giver = known_person(obj["giver"], f"{where}.giver", index)
            receiver = known_person(obj["receiver"], f"{where}.receiver", index)
            if giver == receiver:
                raise fc.InputError(where, "giver and receiver must be different people")
            blocked.add((giver, receiver))
        else:
            raise fc.InputError(where, "needs pair, or both giver and receiver")
    return frozenset(blocked)


def parse_problem(data: Any, *, check: bool = False) -> Problem:
    """Validate an input object. check=True is for --check: the random source and the rules are
    optional, because the question whether a legal draw exists does not depend on them."""
    data = fc.require_object(data, "input")
    fc.check_fields(data, TOP_FIELDS, "")
    people = fc.require_encodable_names(data.get("people"), "people", 2, MAX_PEOPLE)
    mode = DEFAULT_MODE
    if "mode" in data:
        mode = fc.require_choice(data["mode"], "mode", MODES)
    names = sorted(people)
    index = {name: number for number, name in enumerate(names)}
    blocked = parse_forbidden(data.get("forbidden", []), index)

    source: str | None = None
    if "random_source" in data:
        source = fc.require_source_text(data["random_source"], "random_source")
    elif not check:
        raise fc.InputError(
            "random_source",
            "is required: the public text the draw is seeded from, copied exactly",
        )
    description = ""
    deadline = ""
    if "rules" in data or not check:
        rules = fc.require_object(data.get("rules"), "rules")
        fc.check_fields(rules, RULE_FIELDS, "rules")
        if "deadline" in rules or not check:
            deadline = fc.one_line(rules.get("deadline"), "rules.deadline")
        if "source_description" in rules or not check:
            description = fc.one_line(rules.get("source_description"), "rules.source_description")
    return Problem(mode, names, blocked, source, description, deadline, list(people))


# ---------------------------------------------------------------------------------------
# Is there a legal plan? Hall's theorem for the matching, closed groups for the circle
# ---------------------------------------------------------------------------------------


def neighbours(allowed: Sequence[Sequence[int]], group: Sequence[int]) -> list:
    """The people that somebody in the group may give to, sorted."""
    return sorted({receiver for giver in group for receiver in allowed[giver]})


def hall_violator(allowed: Sequence[Sequence[int]]) -> tuple | None:
    """None when every person can be given exactly one receiver, otherwise a group of givers
    that may give to fewer people than the group has (Hall 1935), as (givers, receivers).

    A legal plan of the way any is a perfect matching of givers and receivers. The method is the
    augmenting path method. When it fails for a giver, the givers it reached through alternating
    paths have exactly one receiver fewer than members. That group is then cut down until
    no member can be dropped, so the group that is reported is as small as this order of
    dropping allows, and the numbers are sorted, so the same input gives the same group.
    """
    n = len(allowed)
    owner = [-1] * n  # owner[r] is the giver now matched to receiver r

    def augment(giver: int, seen: list) -> bool:
        for receiver in allowed[giver]:
            if not seen[receiver]:
                seen[receiver] = True
                if owner[receiver] < 0 or augment(owner[receiver], seen):
                    owner[receiver] = giver
                    return True
        return False

    for giver in range(n):
        seen = [False] * n
        if not augment(giver, seen):
            group = sorted({giver} | {owner[r] for r in range(n) if seen[r]})
            shrunk = True
            while shrunk:
                shrunk = False
                for member in list(group):
                    rest = [other for other in group if other != member]
                    if rest and len(neighbours(allowed, rest)) < len(rest):
                        group, shrunk = rest, True
                        break
            return group, neighbours(allowed, group)
    return None


def reachable(edges: Sequence[Sequence[int]], start: int) -> set:
    """The people reachable from start along the edges, start included."""
    found = {start}
    queue = [start]
    while queue:
        for nxt in edges[queue.pop()]:
            if nxt not in found:
                found.add(nxt)
                queue.append(nxt)
    return found


def closed_group(allowed: Sequence[Sequence[int]]) -> list | None:
    """None when everybody can reach everybody along allowed gifts, otherwise a group of people
    who can give only to each other (never the whole set). A single circle through everybody
    needs the first case, because a circle that never leaves a closed group cannot reach the
    others."""
    n = len(allowed)
    forward = reachable(allowed, 0)
    if len(forward) < n:
        return sorted(forward)
    reverse: list = [[] for _ in range(n)]
    for giver, row in enumerate(allowed):
        for receiver in row:
            reverse[receiver].append(giver)
    back = reachable(reverse, 0)
    if len(back) < n:
        return sorted(set(range(n)) - back)
    return None


class NoLegalPlan(fc.NoSolution):
    """No legal draw exists or none could be found. kind says why: hall (too few receivers),
    closed (a group that cannot be left), exhausted (every circle checked) or limit (the random
    search gave up). group and others hold the names that the message mentions."""

    def __init__(self, kind: str, message: str, group: Sequence[str] = (), others: Sequence = ()):
        super().__init__(message)
        self.kind = kind
        self.group = list(group)
        self.others = list(others)


def no_plan(
    kind: str, problem: Problem, group: Sequence = (), others: Sequence = ()
) -> NoLegalPlan:
    """The error for a rule set without a legal draw, in English and then in Chinese."""
    names = sorted((problem.names[i] for i in group), key=problem.listed.index)
    receivers = sorted((problem.names[i] for i in others), key=problem.listed.index)
    texts = []
    for lang in ("en", "zh"):
        key = "err_hall_none" if kind == "hall" and not receivers else f"err_{kind}"
        texts.append(
            say(
                lang,
                key,
                group=joined(lang, names),
                gcount=count_text(lang, len(names)),
                k=len(names),
                others=joined(lang, receivers),
                ocount=count_text(lang, len(receivers)),
                m=len(receivers),
                n=problem.n,
                total=math.factorial(problem.n - 1) if kind == "exhausted" else 0,
                attempts=MAX_ATTEMPTS,
            )
        )
    return NoLegalPlan(kind, " ".join(texts), names, receivers)


def check_rules(problem: Problem) -> None:
    """Raise NoLegalPlan when the rules leave no legal plan that can be shown to exist or to be
    missing without enumerating: too few receivers (Hall), or for the circle a group that
    cannot be left."""
    allowed = problem.allowed
    violation = hall_violator(allowed)
    if violation is not None:
        raise no_plan("hall", problem, *violation)
    if problem.mode == "ring":
        closed = closed_group(allowed)
        if closed is not None:
            raise no_plan("closed", problem, closed)


# ---------------------------------------------------------------------------------------
# The plans
# ---------------------------------------------------------------------------------------


def is_single_circle(plan: Sequence[int]) -> bool:
    """True when following the gifts from person 0 visits everybody before coming back."""
    steps, person = 1, plan[0]
    while person != 0:
        person = plan[person]
        steps += 1
    return steps == len(plan)


def list_plans(allowed: Sequence[Sequence[int]], ring: bool) -> list:
    """Every legal plan as a tuple r with r[i] the receiver of giver i, in increasing order.

    The way any lists the permutations without fixed points and without forbidden gifts. The
    way ring lists those that are one single circle. Meant for up to ENUMERATE_MAX people.
    """
    n = len(allowed)
    plans: list = []
    if not ring:
        used = [False] * n
        row = [0] * n

        def place(giver: int) -> None:
            if giver == n:
                plans.append(tuple(row))
                return
            for receiver in allowed[giver]:
                if not used[receiver]:
                    used[receiver] = True
                    row[giver] = receiver
                    place(giver + 1)
                    used[receiver] = False

        place(0)
        return plans
    visited = [False] * n
    visited[0] = True
    path = [0]

    def extend() -> None:
        last = path[-1]
        if len(path) == n:
            if 0 in allowed[last]:
                plan = [0] * n
                for here, there in zip(path, path[1:] + [0]):
                    plan[here] = there
                plans.append(tuple(plan))
            return
        for receiver in allowed[last]:
            if not visited[receiver]:
                visited[receiver] = True
                path.append(receiver)
                extend()
                path.pop()
                visited[receiver] = False

    extend()
    plans.sort()
    return plans


def is_legal(allowed_sets: Sequence[frozenset], plan: Sequence[int], ring: bool) -> bool:
    """Whether a proposal (a permutation) is a legal plan. For the circle the proposal lists
    the people in circle order, and plan[k] gives to plan[k+1]."""
    n = len(plan)
    if ring:
        return all(plan[(k + 1) % n] in allowed_sets[plan[k]] for k in range(n))
    return all(plan[i] in allowed_sets[i] for i in range(n))


def plan_from_proposal(proposal: Sequence[int], ring: bool) -> tuple:
    """The plan (receiver of each giver) that a legal proposal stands for."""
    n = len(proposal)
    if not ring:
        return tuple(proposal)
    plan = [0] * n
    for k in range(n):
        plan[proposal[k]] = proposal[(k + 1) % n]
    return tuple(plan)


@dataclass
class Draw:
    """The plan that was drawn, with what anyone needs to recompute it."""

    plan: tuple  # plan[i] is the number of the receiver of giver i
    method: str  # enumeration | rejection
    rule: str
    preimage: str
    seed_hex: str
    count: int | None  # enumeration: the number of legal plans
    number: int | None  # enumeration: which of them was drawn, counted from 1
    attempts: int | None  # rejection: the proposal that was legal, counted from 1


def draw_plan(problem: Problem) -> Draw:
    """Draw one legal plan. check_rules has already run, so the matching exists."""
    assert problem.source is not None
    ring = problem.mode == "ring"
    method = "enumeration" if problem.n <= ENUMERATE_MAX else "rejection"
    rule = RULE_NAMES[(problem.mode, method)]
    seed = fc.make_seed(rule, problem.names, problem.n, problem.source)
    preimage = fc.seed_preimage(rule, problem.names, problem.n, problem.source)
    stream = fc.SeedStream(seed)
    allowed = problem.allowed
    if method == "enumeration":
        plans = list_plans(allowed, ring)
        if not plans:
            if not ring:
                raise AssertionError("a perfect matching exists but no legal plan was listed")
            raise no_plan("exhausted", problem)
        index = stream.below(len(plans))
        return Draw(plans[index], method, rule, preimage, seed.hex(), len(plans), index + 1, None)
    allowed_sets = [frozenset(row) for row in allowed]
    numbers = list(range(problem.n))
    for attempt in range(1, MAX_ATTEMPTS + 1):
        proposal = fc.shuffle(numbers, stream)
        if is_legal(allowed_sets, proposal, ring):
            plan = plan_from_proposal(proposal, ring)
            return Draw(plan, method, rule, preimage, seed.hex(), None, None, attempt)
    raise no_plan("limit", problem)


@dataclass
class Outcome:
    problem: Problem
    draw: Draw
    receiver_of: dict  # giver name -> receiver name, in the order of the names
    circle: list | None  # the way ring: the names in circle order, starting with the first name


def compute(problem: Problem) -> Outcome:
    """Check that a legal draw exists, then draw one."""
    check_rules(problem)
    draw = draw_plan(problem)
    names = problem.names
    receiver_of = {names[giver]: names[draw.plan[giver]] for giver in range(problem.n)}
    circle = None
    if problem.mode == "ring":
        circle, person = [names[0]], draw.plan[0]
        while person != 0:
            circle.append(names[person])
            person = draw.plan[person]
    return Outcome(problem, draw, receiver_of, circle)


@dataclass
class Check:
    """What --check found: the rules have a legal plan (or, for a big circle, no sign of none)."""

    problem: Problem
    count: int | None  # the number of legal plans when they are listed
    open_question: bool  # a circle for more than ENUMERATE_MAX people is not known to exist


def check_problem(problem: Problem) -> Check:
    """Does a legal draw exist? Raises NoLegalPlan when not."""
    check_rules(problem)
    if problem.n <= ENUMERATE_MAX:
        count = len(list_plans(problem.allowed, problem.mode == "ring"))
        if count == 0:
            raise no_plan("exhausted", problem)
        return Check(problem, count, False)
    return Check(problem, None, problem.mode == "ring")


# ---------------------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------------------


def mode_text(problem: Problem, lang: str) -> str:
    return TEXT[lang]["mode_" + problem.mode]


def blocked_names(problem: Problem) -> list:
    """The directions that are not allowed, as (giver, receiver) names, sorted."""
    return sorted((problem.names[a], problem.names[b]) for a, b in problem.blocked)


def blocked_text(problem: Problem, lang: str) -> str:
    pairs = [f"{giver}→{receiver}" for giver, receiver in blocked_names(problem)]
    return ", ".join(pairs) if pairs else TEXT[lang]["none"]


def seed_steps() -> str:
    """The part of fsq_core.SEED_SPEC that explains the seed and the counter stream."""
    head, found, _ = fc.SEED_SPEC.partition(SEED_ORDER_SENTENCE)
    return head if found else fc.SEED_SPEC


PLAN_STEPS = {
    "enumeration": (
        " Number the names 0 to n-1 in that order. A plan gives every giver i one receiver r(i). "
        "r is one-to-one, r(i) is not i and (i, r(i)) is not an excluded direction. In the way "
        "ring, following the gifts from person 0 also visits everybody before coming back. List "
        "all legal plans in increasing order of (r(0), r(1), ...). The first uniform integer k "
        "in [0, N) of the stream, N being the number of legal plans, picks plan number k+1."
    ),
    "rejection": (
        " Number the names 0 to n-1 in that order. Proposal t (t = 1, 2, ...) is the next "
        "Fisher-Yates shuffle s of 0 to n-1 on the same stream. In the way any, giver i gives to "
        "s(i). In the way ring, the person at place k of s gives to the person at place k+1 and "
        "the last gives to the first. The first proposal in which nobody gives to themselves and "
        "no excluded direction is used is the result. After {max} proposals the script reports "
        "an error."
    ),
}


def algorithm_certificate(method: str) -> str:
    """The recipe for the JSON certificate, in English: the stream and then the choice."""
    if method == "enumeration":
        return seed_steps() + PLAN_STEPS[method]
    return fc.SEED_SPEC + PLAN_STEPS[method].format(max=MAX_ATTEMPTS)


def algorithm_text(outcome: Outcome, lang: str) -> str:
    draw = outcome.draw
    problem = outcome.problem
    last = problem.n - 1
    if draw.method == "enumeration":
        shape = say(lang, "shape_" + problem.mode, n=problem.n)
        return say(lang, "n_algo_enumeration", last=last, shape=shape)
    proposal = say(lang, "prop_" + problem.mode)
    return say(lang, "n_algo_rejection", last=last, proposal=proposal, max=MAX_ATTEMPTS)


def pair_table(outcome: Outcome, lang: str) -> fc.Table:
    text = TEXT[lang]
    rows = [[giver, receiver] for giver, receiver in outcome.receiver_of.items()]
    return fc.Table(text["hdr_pairs"], rows, text["cap_pairs"])


def facts_table(outcome: Outcome, lang: str) -> fc.Table:
    """The way of drawing and everything needed to recompute it."""
    text = TEXT[lang]
    problem = outcome.problem
    draw = outcome.draw
    rows = []
    if problem.description:
        rows.append([text["f_description"], problem.description])
    if problem.deadline:
        rows.append([text["f_deadline"], problem.deadline])
    rows += [
        [text["f_source"], problem.source],
        [text["f_mode"], mode_text(problem, lang)],
        [text["f_method"], text["method_" + draw.method]],
        [text["f_rule"], draw.rule],
        [text["f_n"], str(problem.n)],
        [text["f_people"], ", ".join(problem.names)],
        [text["f_forbidden"], blocked_text(problem, lang)],
    ]
    if draw.method == "enumeration":
        rows.append([text["f_total"], str(draw.count)])
        rows.append([text["f_number"], say(lang, "number_value", k=draw.number, total=draw.count)])
    else:
        rows.append(
            [text["f_attempts"], say(lang, "attempts_value", t=draw.attempts, max=MAX_ATTEMPTS)]
        )
    rows += [
        [text["f_preimage"], draw.preimage],
        [text["f_seed"], draw.seed_hex],
    ]
    return fc.Table(text["hdr_facts"], rows, text["cap_source"])


def notes(outcome: Outcome, lang: str) -> list:
    """The paragraphs under the tables of the md output."""
    items = [say(lang, "n_organizer")]
    if outcome.circle is not None:
        chain = " → ".join(outcome.circle + outcome.circle[:1])
        items.append(say(lang, "n_ring", chain=chain))
    if any("|" in value for value in (outcome.draw.preimage, *outcome.problem.names)):
        items.append(say(lang, "n_pipe"))
    items.append(algorithm_text(outcome, lang))
    items.append(say(lang, "n_verify"))
    return items


def not_modeled(problem: Problem, lang: str) -> list:
    items = [say(lang, "nm_source"), say(lang, "nm_frozen"), say(lang, "nm_view")]
    if problem.mode == "any" and problem.n >= 4:
        items.append(say(lang, "nm_swap"))
    return items


def person_lines(outcome: Outcome, lang: str) -> dict:
    """The private message of every person: only who they give to."""
    lines: dict = {}
    for giver, receiver in outcome.receiver_of.items():
        rows = [say(lang, "dm_gift", receiver=receiver)]
        if outcome.problem.mode == "ring":
            rows.append(say(lang, "dm_ring"))
        rows += [say(lang, "dm_keep"), say(lang, "dm_rule")]
        lines[giver] = rows
    return lines


def group_lines(outcome: Outcome, lang: str) -> list:
    """The card for the group chat: who takes part and how the draw works, not who gives to whom,
    and nothing that would let a reader compute that."""
    problem = outcome.problem
    lines = [
        say(lang, "g_names", names=joined(lang, problem.names)),
        say(lang, "g_sent"),
        say(lang, "g_mode", mode=mode_text(problem, lang)),
    ]
    if problem.blocked:
        lines.append(say(lang, "g_forbidden", k=len(problem.blocked)))
    if outcome.draw.method == "enumeration":
        lines.append(say(lang, "g_total", total=outcome.draw.count))
    else:
        lines.append(say(lang, "g_reject", limit=ENUMERATE_MAX))
    if problem.description:
        lines.append(say(lang, "g_description", text=problem.description))
    if problem.deadline:
        lines.append(say(lang, "g_deadline", text=problem.deadline))
    lines.append(say(lang, "g_open"))
    return lines


def inputs_echo(problem: Problem) -> dict:
    echo: dict = {
        "mode": problem.mode,
        "participants": list(problem.names),
        "forbidden": [{"giver": a, "receiver": b} for a, b in blocked_names(problem)],
        "randomness": "public_source",
    }
    if problem.source is not None:
        echo["random_source"] = problem.source
    if problem.deadline:
        echo["deadline"] = problem.deadline
    if problem.description:
        echo["source_description"] = problem.description
    return echo


def result_json(outcome: Outcome) -> dict:
    draw = outcome.draw
    return {
        "rule": draw.rule,
        "method": draw.method,
        "assignments": dict(outcome.receiver_of),
        "circle": list(outcome.circle) if outcome.circle is not None else None,
        "plan_count": draw.count,
        "plan_number": draw.number,
        "attempts": draw.attempts,
        "seed_hex": draw.seed_hex,
        "seed_preimage": draw.preimage,
        "source_text": outcome.problem.source,
    }


def build_result(outcome: Outcome, lang: str = "zh", reproduce: str = "") -> fc.Result:
    """Turn an outcome into the shared Result (md, dm, group and json all come from it)."""
    if lang not in TEXT:
        raise ValueError(f"lang must be one of {', '.join(TEXT)}")
    problem = outcome.problem
    draw = outcome.draw
    lines = person_lines(outcome, lang)
    certificate = {
        "one_liner": {person: rows[0] for person, rows in lines.items()},
        "recompute": {
            "source_text": problem.source,
            "rule": draw.rule,
            "method": draw.method,
            "seed_preimage": draw.preimage,
            "seed_hex": draw.seed_hex,
            "plan_count": draw.count,
            "plan_number": draw.number,
            "attempts": draw.attempts,
            "max_attempts": MAX_ATTEMPTS if draw.method == "rejection" else None,
            "algorithm": algorithm_certificate(draw.method),
        },
    }
    title = say(lang, "title", people=problem.n, mode=mode_text(problem, lang))
    return fc.Result(
        title=title,
        inputs_echo=inputs_echo(problem),
        result=result_json(outcome),
        certificate=certificate,
        not_modeled=not_modeled(problem, lang),
        reproduce=reproduce,
        tables=[pair_table(outcome, lang), facts_table(outcome, lang)],
        notes=notes(outcome, lang),
        person_lines=lines,
        group_lines=group_lines(outcome, lang),
    )


def solve(data: Any, lang: str = "zh", reproduce: str = "") -> fc.Result:
    """Validate, draw and build the Result for one input object."""
    return build_result(compute(parse_problem(data)), lang, reproduce)


def check_result(data: Any, lang: str = "zh", reproduce: str = "") -> fc.Result:
    """--check: does a legal draw exist? The Result has a title, a table and notes only."""
    if lang not in TEXT:
        raise ValueError(f"lang must be one of {', '.join(TEXT)}")
    found = check_problem(parse_problem(data, check=True))
    problem = found.problem
    text = TEXT[lang]
    rows = [
        [text["f_mode"], mode_text(problem, lang)],
        [text["f_count"], str(problem.n)],
        [text["f_people"], ", ".join(problem.names)],
        [text["f_forbidden"], blocked_text(problem, lang)],
        [text["c_conclusion"], text["c_open" if found.open_question else "c_ok"]],
    ]
    if found.count is not None:
        rows.append([text["f_total"], str(found.count)])
    items = [say(lang, "n_check_scope")]
    if found.count is None:
        key = "n_check_many_ring" if problem.mode == "ring" else "n_check_many_any"
        items.append(say(lang, key, limit=ENUMERATE_MAX, max=MAX_ATTEMPTS))
    method = "enumeration" if problem.n <= ENUMERATE_MAX else "rejection"
    return fc.Result(
        title=say(lang, "title_check", people=problem.n, mode=mode_text(problem, lang)),
        inputs_echo=inputs_echo(problem),
        result={
            "legal_plan_exists": None if found.open_question else True,
            "method": method,
            "plan_count": found.count,
        },
        certificate={},
        not_modeled=[],
        reproduce=reproduce,
        tables=[fc.Table(text["hdr_facts"], rows, text["cap_check"])],
        notes=items,
    )


# ---------------------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------------------


def reproduce_command(args: argparse.Namespace) -> str:
    parts = ["python3", "scripts/gift_exchange.py"]
    parts += ["--demo"] if args.demo else ["--input", "-"]
    if args.check:
        parts.append("--check")
    parts += ["--json"] if args.json else ["--format", args.format]
    if args.lang != "zh":
        parts += ["--lang", args.lang]
    return " ".join(parts)


# Recorded for the fictional example: seed prefix 1a00559810149576dff6f98c, plan number 13 of 96.
GOLDEN_SEED_PREFIX = "1a00559810149576dff6f98c"
GOLDEN_NUMBER = 13
GOLDEN_PLAN = {
    "Coco": "Yuki",
    "Yuki": "小红",
    "大刘": "阿明",
    "小红": "老王",
    "老王": "Coco",
    "阿明": "大刘",
}


def selftest_checks() -> list:
    """Checks for --selftest: the recorded example and the rules of the script."""

    def demo_data() -> dict:
        return fc.parse_input(DEMO_JSON)

    def counts_of_the_recorded_example() -> None:
        problem = parse_problem(demo_data())
        fc.expect(len(list_plans(problem.allowed, False)) == 96, "96 legal plans")
        fc.expect(len(list_plans(problem.allowed, True)) == 40, "40 legal circles")

    def golden_draw() -> None:
        out = compute(parse_problem(demo_data()))
        fc.expect(out.draw.seed_hex.startswith(GOLDEN_SEED_PREFIX), "golden seed")
        fc.expect(out.draw.count == 96, "plan count")
        fc.expect(out.draw.number == GOLDEN_NUMBER, f"plan number {out.draw.number}")
        fc.expect(out.receiver_of == GOLDEN_PLAN, f"plan {out.receiver_of}")

    def preimage_is_what_is_hashed() -> None:
        out = compute(parse_problem(demo_data()))
        digest = hashlib.sha256(out.draw.preimage.encode("utf-8")).hexdigest()
        fc.expect(digest == out.draw.seed_hex, "the printed preimage must hash to the seed")

    def nobody_draws_themselves_or_a_forbidden_person() -> None:
        out = compute(parse_problem(demo_data()))
        blocked = set(blocked_names(out.problem))
        for giver, receiver in out.receiver_of.items():
            fc.expect(giver != receiver, "nobody draws themselves")
            fc.expect((giver, receiver) not in blocked, f"{giver} gives to {receiver}")
        fc.expect(sorted(out.receiver_of.values()) == sorted(out.problem.names), "one gift each")

    def a_circle_is_one_circle() -> None:
        data = demo_data()
        data["mode"] = "ring"
        out = compute(parse_problem(data))
        fc.expect(out.circle is not None and len(out.circle) == 6, "all six in one circle")
        fc.expect(is_single_circle(out.draw.plan), "a single circle")

    def a_couple_among_three_has_no_draw() -> None:
        data = {"people": ["甲", "乙", "丙"], "forbidden": [{"pair": ["甲", "乙"]}]}
        try:
            check_problem(parse_problem(data, check=True))
        except NoLegalPlan as err:
            fc.expect(err.kind == "hall", err.kind)
            fc.expect(err.group == ["甲", "乙"], str(err.group))
            fc.expect(err.others == ["丙"], str(err.others))
            return
        raise AssertionError("three people with a couple among them have no legal draw")

    def listing_order_is_irrelevant() -> None:
        data = demo_data()
        data["people"] = list(reversed(data["people"]))
        data["forbidden"] = list(reversed(data["forbidden"]))
        fc.expect(compute(parse_problem(data)).receiver_of == GOLDEN_PLAN, "listing order")

    def many_people_are_drawn_by_rejection() -> None:
        people = [f"p{k:02d}" for k in range(12)]
        data = {
            "people": people,
            "forbidden": [{"pair": [people[0], people[1]]}],
            "random_source": "selftest",
            "rules": {"source_description": "selftest", "deadline": "selftest"},
        }
        out = compute(parse_problem(data))
        fc.expect(out.draw.method == "rejection" and (out.draw.attempts or 0) >= 1, "rejection")
        fc.expect(all(a != b for a, b in out.receiver_of.items()), "a derangement")

    def no_randomness_is_refused() -> None:
        data = demo_data()
        del data["random_source"]
        try:
            parse_problem(data)
        except fc.InputError as err:
            fc.expect(err.field == "random_source", err.field)
        else:
            raise AssertionError("a draw without a random source was accepted")

    return [
        ("96 legal plans and 40 circles", counts_of_the_recorded_example),
        ("golden draw", golden_draw),
        ("seed preimage hashes to the seed", preimage_is_what_is_hashed),
        (
            "nobody draws themselves or a forbidden person",
            nobody_draws_themselves_or_a_forbidden_person,
        ),
        ("a circle is one circle", a_circle_is_one_circle),
        ("three people with a couple have no draw", a_couple_among_three_has_no_draw),
        ("listing order is irrelevant", listing_order_is_irrelevant),
        ("more than nine people are drawn by rejection", many_people_are_drawn_by_rejection),
        ("no randomness is refused", no_randomness_is_refused),
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gift_exchange.py",
        description=(
            "Draw a gift exchange (Secret Santa) that anyone can recompute. Reads one JSON "
            "object (people, forbidden, mode, random_source, rules) from standard input or "
            "--input FILE. First it checks that a legal draw exists and says why when none "
            "does, then it draws one of all legal plans with the same chance for each, from "
            "the public source text through SHA-256, never from the random module."
        ),
        epilog=(
            "mode any (default): any derangement, nobody gives to themselves or to a person who "
            "is not allowed. mode ring: everybody in one single circle. forbidden: a list of "
            '{"pair": [A, B]} (neither gives to the other) and {"giver": A, "receiver": B} '
            "(A may not give to B). With --check the random source and the rules are not needed. "
        )
        + fc.exit_codes_epilog(three="no legal draw exists or none was found"),
    )
    fc.standard_args(parser)
    fc.add_lang_option(parser, "JSON keys and names do not change")
    parser.add_argument(
        "--check",
        action="store_true",
        help="only check that a legal draw exists, and say why when none does. No random source "
        "is needed. Exit 0 when a legal draw exists (or, for a circle of more than 9 people, "
        "cannot be ruled out), 3 when none does. Works with --format md and --json",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    fc.exclusive_modes(args, "--demo", "--selftest")
    fc.exclusive_modes(args, "--check", "--selftest")
    if args.selftest:
        return fc.run_selftest(selftest_checks())
    if args.check and not args.json and args.format != "md":
        raise fc.InputError("--format", f"{args.format} is not available with --check")
    data = fc.read_object(args, DEMO_JSON)
    reproduce = reproduce_command(args)
    if args.check:
        fc.emit(check_result(data, args.lang, reproduce), args, lang=args.lang)
        return 0
    fc.emit(solve(data, args.lang, reproduce), args, lang=args.lang)
    return 0


if __name__ == "__main__":
    fc.run_cli(main)
