"""Share out household chores: take turns (plan A), or fixed bundles with compensation (plan B).

Plan A, round_robin (the default). Everyone ranks the chores of one week, from the one they mind
least to the one they mind most. The people then take turns in a fixed order. Whoever is up
takes the remaining chore they mind least, until every chore is taken (round-robin picking).
The order of the first week comes from a public random source named in advance, through SHA-256
and never the random module. After that the start moves one place each week, so everybody
starts first in turn.

A chore that repeats during the week is several units: dishes three times a week is three
units, and each unit is picked on its own. A chore a person cannot do is left out of that
person's ranking and they never pick it. If that leaves a person with nothing they can pick,
they are skipped for the rest of the week.

Guarantee. Without chores that somebody cannot do, every week is envy-free up to one chore
(EF1) for every way of putting non-negative numbers on how much each person minds each chore,
as long as the numbers agree with that person's ranking: after setting aside one of their own
chores, nobody prefers another person's chores to their own. With chores that somebody cannot
do the guarantee can fail, so the script checks every pair of people and reports it. The
method is not strategy-proof, and it needs rankings only. Liked tasks are refused (exit 2).

Input is one JSON object on standard input (--input -)::

    {"people": ["Ann", "Bob", "Cy"],
     "chores": ["dishes", {"name": "trash", "units": 2}, "mopping"],
     "rankings": {"Ann": ["trash", "dishes", "mopping"], "Bob": [...], "Cy": [...]},
     "cannot": {"Bob": ["mopping"]},
     "weeks": 4,
     "rules": {"random_source": "public text", "rotate": "shift"}}

Plan B, bundle_pay (chosen with "plan": "bundle_pay" in rules). Every person states what each
chore they can do costs them per unit, in money or points (never negative), and how many chore
units they take at most (their cap). The chores go to the people so that the total cost is as
small as possible within the caps and the cannot lists (Hungarian method on one slot per unit
of cap). Money then moves between the people, adding up to zero, so that nobody would swap
their share and its payment for another person's share and payment, and the worst-off person
is as well off as possible among such payments. That step is the maximin step of rent-split
with a total rent of zero. Everything is exact fractions, rounded to whole cents at the end::

    {"people": ["Ann", "Bob", "Cy"],
     "chores": ["dishes", {"name": "trash", "units": 2}, "mopping"],
     "costs": {"Ann": {"dishes": 30, "trash": 5, "mopping": 20}, "Bob": {...}, "Cy": {...}},
     "caps": {"Ann": 2, "Bob": 2, "Cy": 2},
     "cannot": {"Bob": ["mopping"]},
     "rules": {"plan": "bundle_pay", "random_source": "optional public text for ties"}}

Output is --format md|dm|group or --json, in Chinese or English (--lang). Exit code 0 means
success, 1 a failed self-test, 2 invalid input (the message names the field), 3 that the
agreed rules have no solution: some chore is on every person's cannot list or, in plan B, the
caps and the cannot lists leave no way to share out all the chores. Standard library only,
Python 3.9 or later. Nothing is written to disk.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from fractions import Fraction
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

RULE_NAME = "chore_pick_order_v1"
ROTATIONS = ("shift", "none")
MAX_PEOPLE = 12
MAX_CHORES = 40
MAX_UNITS = 21  # units of one chore in one week
MAX_TOTAL_UNITS = 120
MAX_WEEKS = 12
PLAN_ROUND_ROBIN = "round_robin"  # plan A, the default
PLAN_BUNDLE = "bundle_pay"  # plan B: fixed bundles with compensation
PLANS = (PLAN_ROUND_ROBIN, PLAN_BUNDLE)
TOP_FIELDS = ("people", "chores", "rankings", "cannot", "likes", "weeks", "rules")
RULE_FIELDS = ("plan", "random_source", "source_description", "rotate")
CHORE_FIELDS = ("name", "units")
# Plan B. The top-level fields of each plan that the other plan does not use are refused by name.
BUNDLE_TOP_FIELDS = ("people", "chores", "costs", "caps", "cannot", "rules")
BUNDLE_RULE_FIELDS = ("plan", "random_source", "source_description")
ROUND_ROBIN_ONLY = ("rankings", "likes", "weeks")
BUNDLE_ONLY = ("costs", "caps")
BUNDLE_RULE_NAME = "chore_bundle_tiebreak_v1"  # names the seed of the tie order in plan B

STATUS_FREE = "envy_free"  # no envy at all, for every cost that fits the ranking
STATUS_EF1 = "ef1"  # no envy once one chore is set aside
STATUS_FAILS = "fails"
STATUS_EXEMPT = "exempt"  # the other person holds a chore this person cannot do
VIA_ROUNDS = "rounds"
VIA_DOMINANCE = "dominance"

# The recorded example: three roommates, six chores, one week. The fictional source was chosen so
# that the pick order is 阿明, 小红, 大刘. The rankings are the ones implied by the scores 倒垃圾
# 1, 做饭 2, 拖地 4, 擦窗 5, 洗碗 6, 刷厕所 9 (阿明), 2 3 4 5 8 9 (小红) and 2 3 5 6 7 8 (大刘).
DEMO_JSON = """{
  "people": ["阿明", "小红", "大刘"],
  "chores": ["洗碗", "倒垃圾", "拖地", "刷厕所", "做饭", "擦窗"],
  "rankings": {
    "阿明": ["倒垃圾", "做饭", "拖地", "擦窗", "洗碗", "刷厕所"],
    "小红": ["倒垃圾", "洗碗", "擦窗", "拖地", "刷厕所", "做饭"],
    "大刘": ["拖地", "倒垃圾", "做饭", "刷厕所", "洗碗", "擦窗"]
  },
  "weeks": 1,
  "rules": {
    "random_source": "（虚构示例）2026-11-08 某公开开奖号码 03 11 19 24 33 + 02 07",
    "source_description": "虚构示例：2026 年 11 月 8 日某公开开奖，按官网显示的格式原样抄写",
    "rotate": "shift"
  }
}"""

# ---------------------------------------------------------------------------------------
# Texts (zh is the default, en says the same)
# ---------------------------------------------------------------------------------------

TEXT = {
    "zh": {
        "sep": "、",
        "none": "无",
        "quote": "「{}」",
        "poss": "{}的",
        "you": "你",
        "your": "你的",
        "end": "。",
        "times": " ×{k}",
        "title": "分家务结果：{people} 人分 {chores}，轮流挑，共 {weeks}",
        "q_chores_1": "{n} 件家务",
        "q_chores_n": "{n} 件家务",
        "q_weeks_1": "{n} 周",
        "q_weeks_n": "{n} 周",
        "q_weeks_checked_1": "{n} 周",
        "q_weeks_checked_n": "{n} 周",
        "cap_schedule": "每周排班",
        "hdr_schedule": ["周", "挑选顺序"],
        "nothing": "（没有分到）",
        "cap_picks": "挑选过程",
        "hdr_picks": ["周", "轮", "谁挑了什么（按挑选顺序）"],
        "pick_arrow": " → ",
        "pick_item": "{person} {chore}",
        "skipped_from": "（{names}从这一轮起没有自己能做的家务可挑，跳过）",
        "cap_cert": "第 {week} 周逐轮核对（每个人对每个人，用的是本人的排序）",
        "hdr_cert": ["谁", "对谁", "次序", "逐轮比较", "结论"],
        "before": "先于对方挑",
        "after": "后于对方挑",
        "cmp_same": "第 {r} 轮 {c}({k}) ≤ 对方同一轮 {c2}({k2})",
        "cmp_next": "第 {r} 轮 {c}({k}) ≤ 对方第 {r2} 轮 {c2}({k2})",
        "cmp_sep": "；",
        "cmp_none": "（没有可比的）",
        "cant": "做不了",
        "res_free": "不羡慕",
        "res_ef1": "去掉最后挑的{c}后不羡慕",
        "res_free_dom": "按排序整体比较：不羡慕",
        "res_ef1_dom": "按排序整体比较：去掉最重的一件后不羡慕",
        "res_fails": "EF1 不成立（说明见下）",
        "res_exempt": "对方手里有做不了的{chores}，不会羡慕",
        "n_legend": (
            "括号里的数是这件家务在本人排序里的位次（1 是最不讨厌的），≤ 表示不比对方挑的那件"
            "更讨厌。先于对方挑的人和对方同一轮比，后于对方挑的人和对方下一轮比，因为对方在"
            "这一轮里已经先挑走了一件。"
        ),
        "n_more_weeks": (
            "第 {first} 到第 {last} 周的核对格式相同，完整明细在 --json 的 certificate.pairs 里。"
        ),
        "n_more_week": "第 {first} 周的核对格式相同，完整明细在 --json 的 certificate.pairs 里。",
        "n_ef1_ok": (
            "EF1 状态（去掉一件家务后，没有人羡慕别人）：成立。脚本逐周逐对核对了所有人"
            "（共 {weeks}），逐轮比较共 {n} 项，全部成立。"
        ),
        "n_ef1_bad": (
            "EF1 状态（去掉一件家务后，没有人羡慕别人）：不成立。脚本不改分法，只如实报告"
            "下面这些人对人："
        ),
        "n_ef1_line": "第 {week} 周，{person} 对 {other}：{reason}。",
        "n_rotate_shift": (
            "轮换：第 1 周的挑选顺序由随机源定，之后每周先手往后轮一位，{people} 周为一轮，"
            "每个人当一次先手。"
        ),
        "n_rotate_none": "轮换：每周都用第 1 周的挑选顺序，不轮换，先手一直是同一个人。",
        "n_algo": (
            "复算第 1 周的挑选顺序：① 种子 = 「种子原像」的 SHA-256（UTF-8）。② 第 c 次取数"
            "（c 从 0 起）= SHA-256（种子 + c 的 8 字节大端）的前 8 字节，按大端读成整数 x。"
            "要取 0 到 n−1 之间的整数时，x 小于 2^64 − (2^64 mod n) 就取 x 除以 n 的余数，否则 c "
            "加 1 重取。③ 名单按码位排序，i 从 n−1 降到 1，每步取一个 0 到 i 之间的整数 j，"
            "交换第 i 位和第 j 位，最后得到的就是第 1 周的挑选顺序。整个过程不用 random 模块。"
        ),
        "n_pipe": (
            "表格里的竖线 | 前面被加了一个反斜杠。复算时请用 --json 里的种子原像，"
            "或者群里卡片上的原文，不要从表格里复制。"
        ),
        "n_one_liners": "每人一句话（只发给本人，不要贴到群里）：",
        "n_one_liner": "- {person}：{text}",
        "cap_source": "随机源与复算",
        "hdr_facts": ["项目", "内容"],
        "f_description": "随机源说明",
        "f_source": "随机源原文（逐字）",
        "f_rule": "规则名",
        "f_units": "每周家务总件数（写进种子，即种子里的 n_slots）",
        "f_people": "名单（按码位排序，写进种子）",
        "f_preimage": "种子原像（对这段文字取 SHA-256）",
        "f_seed": "种子（SHA-256，十六进制）",
        "f_order": "第 1 周挑选顺序",
        "nm_source": (
            "随机源是否真的事先约定、事后无法更改、临场无人能预测：脚本核对不了。"
            "它只决定第 1 周谁先挑。"
        ),
        "nm_ranking": (
            "排序是否被如实录入：每个人在自己的私信里核对。排序之外的程度，比如谁觉得洗碗比拖地"
            "难受十倍，脚本看不到。"
        ),
        "nm_strategy": (
            "防策略：轮流挑不防策略。知道别人排序的人，有时能靠谎报排序让自己分到更轻的家务。"
        ),
        "nm_weeks": "几周之间：每周各自保证 EF1，不保证几周加起来也一样。",
        "nm_likes": "有人喜欢做的任务：不支持。有人喜欢的任务用 likes 声明，会被拒绝。",
        "nm_money": (
            "花钱请人做家务：这个方案不涉及钱。要在室友之间用钱补偿，请把 rules.plan 设为 "
            "bundle_pay。请外人做家务（比如保洁）的费用不计算，分摊用 bill-split。"
        ),
        "nm_cannot": "做不了的家务：有 cannot 时 EF1 不一定成立，脚本逐对检查并报告，见上面的 EF1 状态。",
        "dm_head": "{person}，这是只给你的分家务结果，别人看不到你的排序。",
        "dm_week": "第 {week} 周（挑选顺序：{order}，你是第 {pos} 个挑）：{picks}。",
        "dm_week_none": "第 {week} 周（挑选顺序：{order}，你是第 {pos} 个挑）：这一周你没有分到家务。",
        "dm_round": "第 {r} 轮 {c}",
        "dm_round_sep": "，",
        "dm_ok": (
            "你每一轮挑的那件（{rounds}），在你的排序里都不比别人紧接着挑的那件更讨厌：对方挑得"
            "比你晚，就和对方同一轮比，对方挑得比你早，就和对方下一轮比。最多只有一件家务例外，"
            "去掉它，你就不羡慕任何人。"
        ),
        "dm_ok_none": "你没有分到家务，所以不会羡慕任何人。",
        "dm_fail_some": (
            "你挑的（{rounds}）。对{names}，EF1 不成立，原因在下面。对其他人，每一轮你挑的那件，"
            "在你的排序里都不比对方紧接着挑的那件更讨厌，最多只有一件家务例外：去掉它，你就"
            "不羡慕他们。"
        ),
        "dm_fail_all": "你挑的（{rounds}）。对其他每个人，EF1 都不成立，原因在下面。",
        "dm_week_rounds": "第 {week} 周：{rounds}",
        "dm_week_sep": "；",
        "dm_no_picks": "没有分到",
        "dm_ranking": (
            "你交的排序（最不讨厌的在前）：{ranking}。如果和你发给组织者的不一样，请马上告诉大家。"
        ),
        "rank_sep": " > ",
        "dm_cannot": "你说做不了：{chores}。它们不在你的排序里，也不会分给你。",
        "pc_head_first": "第 {week} 周，对{other}（你每轮先挑）：",
        "pc_head_second": "第 {week} 周，对{other}（{other}每轮先挑）：",
        "pc_same": "第 {r} 轮你挑的{c}（{k}）不比{other}同一轮挑的{c2}（{k2}）更讨厌",
        "pc_next": (
            "第 {r} 轮你挑的{c}（{k}）不比{other}下一轮（第 {r2} 轮）挑的{c2}（{k2}）更讨厌"
        ),
        "pc_k_own": "你的第 {k} 位",
        "pc_k_other": "第 {k} 位",
        "pc_k_cant": "你做不了",
        "pc_sep": "；",
        "pc_free": "你不羡慕{other}",
        "pc_free_empty": "你这一周没有分到家务，不羡慕{other}",
        "pc_ef1_last": "去掉你最后挑的{c}，你就不羡慕{other}",
        "pc_free_dom": (
            "把你和{other}手里的家务都按你的排序从重到轻排好，你的每一件都不比{other}对应位置的"
            "那件更讨厌，所以你不羡慕{other}"
        ),
        "pc_ef1_dom": (
            "把你和{other}手里的家务都按你的排序从重到轻排好，去掉你最重的一件之后，你的每一件"
            "都不比{other}对应位置的那件更讨厌，所以你不羡慕{other}"
        ),
        "pc_exempt": "{other}手里有你做不了的{chores}，你不会羡慕{other}",
        "pc_fail": "EF1 不成立：{witness}",
        "w_count": (
            "把所有家务都算作一样重，去掉{who}手里最重的一件后，{who}手里还有 {a}，"
            "{other}手里只有 {b}"
        ),
        "w_heavy": (
            "把{who}排序里的{x}和排在它后面的家务都算作重活，去掉{who}手里最重的一件后，"
            "{who}手里还有 {a}，{other}手里只有 {b}"
        ),
        "w_ran_out": "（{other}从第 {r} 轮起没有自己能做的家务可挑）",
        "count_1": "{n} 件",
        "count_n": "{n} 件",
        "heavy_1": "{n} 件重活",
        "heavy_n": "{n} 件重活",
        "g_rule_shift": (
            "规则（事先定好，结果出来后不再改）：每周轮流挑，轮到谁，谁就从剩下的家务里挑自己"
            "最不讨厌的一件，挑完为止。第 1 周的挑选顺序由公开随机源定，之后每周先手往后轮一位。"
        ),
        "g_rule_none": (
            "规则（事先定好，结果出来后不再改）：每周轮流挑，轮到谁，谁就从剩下的家务里挑自己"
            "最不讨厌的一件，挑完为止。挑选顺序由公开随机源定，每周不变。"
        ),
        "g_description": "随机源说明：{text}",
        "g_source": "随机源原文：{text}",
        "g_preimage": "种子原像（对这段文字取 SHA-256 就是种子）：{text}",
        "g_seed": "种子（SHA-256）：{seed}",
        "g_start": "第 1 周挑选顺序：{order}。",
        "g_week": "第 {week} 周（挑选顺序：{order}）",
        "g_round": "第 {r} 轮：{picks}",
        "g_pick": "{person} {chore}",
        "g_pick_sep": "，",
        "g_gets_head": "分到的家务：",
        "g_gets": "{person}：{chores}",
        "g_gets_none": "{person}：（没有分到）",
        "g_guarantee": (
            "保证（EF1）：每个人拿自己的排序来对。每一轮自己挑的那件，都不比别人紧接着挑的那件"
            "更讨厌，最多只有一件家务例外，去掉它就不羡慕任何人。每个人会收到一条只含自己排序的"
            "私信，可以自己核对。"
        ),
        "g_guarantee_partial": (
            "保证（EF1）：下面列出的人对人除外，其余都成立。每个人拿自己的排序来对。每一轮自己"
            "挑的那件，都不比别人紧接着挑的那件更讨厌，最多只有一件家务例外，去掉它就不羡慕"
            "那些人。每个人会收到一条只含自己排序的私信，可以自己核对。"
        ),
        "g_ef1_bad": "EF1 不成立的情况（脚本不改分法，如实报告）：",
        "g_ef1_line": "第 {week} 周，{person} 对 {other}：{person}手里 {a}，{other}手里 {b}{ran}",
        "g_limits": (
            "不保证：轮流挑不防策略，排序也不反映轻重程度，所以只保证 EF1，不保证每个人的总负担"
            "一样重。每一周各自保证，不保证几周加起来也一样。"
        ),
        "g_recompute": (
            "复算：随机源原文、名单、每周家务总件数和规则名都在上面，按种子原像取 SHA-256，再用"
            "计数器洗牌，就得到第 1 周的顺序，之后每周的顺序按轮换规则推出。洗牌的写法见 "
            "github.com/YYYJH1/fair-and-square-skills 里 docs/THEORY.md 的 Public randomness 一节。"
        ),
    },
    "en": {
        "sep": ", ",
        "none": "none",
        "quote": '"{}"',
        "poss": "{}'s",
        "you": "you",
        "your": "your",
        "end": ".",
        "times": " x{k}",
        "title": "Chore split: {people} people, {chores}, taking turns, {weeks}",
        "q_chores_1": "{n} chore",
        "q_chores_n": "{n} chores",
        "q_weeks_1": "{n} week",
        "q_weeks_n": "{n} weeks",
        "q_weeks_checked_1": "the single week",
        "q_weeks_checked_n": "all {n} weeks",
        "cap_schedule": "Weekly schedule",
        "hdr_schedule": ["Week", "Pick order"],
        "nothing": "(none)",
        "cap_picks": "Who picked what",
        "hdr_picks": ["Week", "Round", "Picks (in pick order)"],
        "pick_arrow": " -> ",
        "pick_item": "{person} {chore}",
        "skipped_from": " ({names} had no chore left that they can do, so skipped from this round on)",
        "cap_cert": (
            "Round-by-round check for week {week} (everyone against everyone, "
            "using their own ranking)"
        ),
        "hdr_cert": ["Who", "Against", "Order", "Round by round", "Result"],
        "before": "picks before them",
        "after": "picks after them",
        "cmp_same": "round {r} {c}({k}) <= their same round {c2}({k2})",
        "cmp_next": "round {r} {c}({k}) <= their round {r2} {c2}({k2})",
        "cmp_sep": "; ",
        "cmp_none": "(nothing to compare)",
        "cant": "cannot do",
        "res_free": "no envy",
        "res_ef1": "no envy once the last pick {c} is set aside",
        "res_free_dom": "comparing the whole bundles: no envy",
        "res_ef1_dom": "comparing the whole bundles: no envy once the heaviest chore is set aside",
        "res_fails": "EF1 fails (see below)",
        "res_exempt": "they hold {chores}, which this person cannot do, so no envy",
        "n_legend": (
            "The number in brackets is the place of the chore in that person's own ranking (1 is "
            "the least disliked). <= means no worse than the other person's pick. A person who "
            "picks before the other is compared with the same round, a person who picks after "
            "the other with the next round, because the other has already taken a chore in the "
            "current one."
        ),
        "n_more_weeks": (
            "Weeks {first} to {last} are checked in the same way. The full list is in "
            "certificate.pairs of the --json output."
        ),
        "n_more_week": (
            "Week {first} is checked in the same way. The full list is in certificate.pairs "
            "of the --json output."
        ),
        "n_ef1_ok": (
            "EF1 status (nobody envies anybody once one chore is set aside): holds. The script "
            "checked every pair of people in {weeks}. All {n} round-by-round comparisons "
            "hold."
        ),
        "n_ef1_bad": (
            "EF1 status (nobody envies anybody once one chore is set aside): fails. The script "
            "does not change the split. It reports these pairs as they are:"
        ),
        "n_ef1_line": "Week {week}, {person} against {other}: {reason}.",
        "n_rotate_shift": (
            "Rotation: the pick order of week 1 comes from the source, then the start moves one "
            "place each week. After {people} weeks everybody has started once."
        ),
        "n_rotate_none": (
            "Rotation: every week uses the pick order of week 1. The same person always starts."
        ),
        "n_algo": (
            "How to recompute the pick order of week 1: (1) seed = SHA-256 of the seed preimage "
            "(UTF-8). (2) Draw number c (counting from 0) = the first 8 bytes, big-endian, of "
            "SHA-256(seed + c as 8 big-endian bytes), read as an integer x. For an integer in "
            "0..n-1, take x mod n if x < 2^64 - (2^64 mod n), otherwise add 1 to c and draw "
            "again. (3) Sort the names by code point, go i from n-1 down to 1, draw an integer j "
            "in 0..i and swap positions i and j. The result is the pick order of week 1. The "
            "random module is never used."
        ),
        "n_pipe": (
            "A backslash was added before each | in the tables. To recompute, use the seed "
            "preimage in the --json output or the text on the group card, not a copy from a "
            "table."
        ),
        "n_one_liners": "One line per person (send it to that person only, not to the group):",
        "n_one_liner": "- {person}: {text}",
        "cap_source": "Random source and how to recompute",
        "hdr_facts": ["Item", "Value"],
        "f_description": "Where the source comes from",
        "f_source": "Source text (verbatim)",
        "f_rule": "Rule name",
        "f_units": "Chore units per week (part of the seed, the n_slots of the seed)",
        "f_people": "Names (sorted by code point, part of the seed)",
        "f_preimage": "Seed preimage (take the SHA-256 of this text)",
        "f_seed": "Seed (SHA-256, hex)",
        "f_order": "Pick order of week 1",
        "nm_source": (
            "Whether the source was really fixed in advance, cannot be changed afterwards and "
            "could not be predicted: the script cannot check this. It only decides who picks "
            "first in week 1."
        ),
        "nm_ranking": (
            "Whether the rankings were entered faithfully: each person checks theirs in their own "
            "message. How much a chore is disliked beyond the order, for example if somebody "
            "finds dishes ten times worse than mopping, is not seen by the script."
        ),
        "nm_strategy": (
            "Strategy-proofness: round-robin picking is not strategy-proof. A person who knows "
            "the other rankings can sometimes get a lighter set by ranking untruthfully."
        ),
        "nm_weeks": (
            "Across weeks: every week is guaranteed to be EF1 on its own. Nothing is promised "
            "about the weeks added together."
        ),
        "nm_likes": (
            "Tasks that somebody likes: not supported. A liked task declared in likes is refused."
        ),
        "nm_money": (
            "Paying somebody to take a chore: this plan moves no money. To compensate housemates "
            "with money, set rules.plan to bundle_pay. What an outside cleaner costs is not "
            "calculated. Use bill-split to share that."
        ),
        "nm_cannot": (
            "Chores somebody cannot do: with cannot, EF1 may fail. The script checks every pair "
            "and reports it, see the EF1 status above."
        ),
        "dm_head": "{person}, this is your own chore result. Nobody else sees your ranking.",
        "dm_week": "Week {week} (pick order: {order}; you pick number {pos}): {picks}.",
        "dm_week_none": (
            "Week {week} (pick order: {order}; you pick number {pos}): you get no chores this week."
        ),
        "dm_round": "round {r} {c}",
        "dm_round_sep": ", ",
        "dm_ok": (
            "In every round, the chore you picked ({rounds}) is no worse in your ranking than the "
            "one each other person picked right after you: the same round if they pick after you, "
            "their next round if they pick before you. At most one chore is an exception: set it "
            "aside and you envy nobody."
        ),
        "dm_ok_none": "You get no chores, so you cannot envy anybody.",
        "dm_fail_some": (
            "Your picks: {rounds}. EF1 fails against {names}, the reason is below. Against "
            "everybody else, the chore you picked in every round is no worse in your ranking "
            "than the one they picked right after you, with at most one chore as an exception: "
            "set it aside and you do not envy them."
        ),
        "dm_fail_all": "Your picks: {rounds}. EF1 fails against everybody else, the reason is below.",
        "dm_week_rounds": "week {week}: {rounds}",
        "dm_week_sep": "; ",
        "dm_no_picks": "no chores",
        "dm_ranking": (
            "The ranking you gave (least disliked first): {ranking}. If it differs from what you "
            "sent the organizer, tell everybody now."
        ),
        "rank_sep": " > ",
        "dm_cannot": (
            "You said you cannot do: {chores}. They are not in your ranking and will not be "
            "given to you."
        ),
        "pc_head_first": "Week {week}, against {other} (you pick before {other} each round): ",
        "pc_head_second": "Week {week}, against {other} ({other} picks before you each round): ",
        "pc_same": (
            "in round {r} your pick {c} ({k}) is no worse than {other}'s pick in the same "
            "round, {c2} ({k2})"
        ),
        "pc_next": (
            "in round {r} your pick {c} ({k}) is no worse than {other}'s pick in the next "
            "round (round {r2}), {c2} ({k2})"
        ),
        "pc_k_own": "your no. {k}",
        "pc_k_other": "no. {k}",
        "pc_k_cant": "you cannot do it",
        "pc_sep": "; ",
        "pc_free": "so you do not envy {other}",
        "pc_free_empty": "you get no chores this week, so you do not envy {other}",
        "pc_ef1_last": "set aside your last pick {c} and you do not envy {other}",
        "pc_free_dom": (
            "line up your chores and {other}'s from heaviest to lightest in your ranking: each "
            "of yours is no worse than the one in the same place of {other}'s, so you do not "
            "envy {other}"
        ),
        "pc_ef1_dom": (
            "line up your chores and {other}'s from heaviest to lightest in your ranking and set "
            "aside your heaviest: each of yours left is no worse than the one in the same place "
            "of {other}'s, so you do not envy {other}"
        ),
        "pc_exempt": "{other} holds {chores}, which you cannot do, so you cannot envy {other}",
        "pc_fail": "EF1 fails: {witness}",
        "w_count": (
            "counting every chore the same, after {whose} heaviest chore is set aside, {whose} "
            "bundle still has {a} and {theirs} has {b}"
        ),
        "w_heavy": (
            "treating {x} and every chore ranked after it in {whose} ranking as heavy, after "
            "{whose} heaviest chore is set aside, {whose} bundle still has {a} and {theirs} "
            "has {b}"
        ),
        "w_ran_out": " ({other} had no chore left that they can do from round {r} on)",
        "count_1": "{n} chore",
        "count_n": "{n} chores",
        "heavy_1": "{n} heavy chore",
        "heavy_n": "{n} heavy chores",
        "g_rule_shift": (
            "Rules (fixed in advance, not changed after the result): every week we take turns. "
            "Whoever is up takes the remaining chore they mind least, until none is left. The "
            "pick order of week 1 comes from the public random source, then the start moves one "
            "place each week."
        ),
        "g_rule_none": (
            "Rules (fixed in advance, not changed after the result): every week we take turns. "
            "Whoever is up takes the remaining chore they mind least, until none is left. The "
            "pick order comes from the public random source and stays the same every week."
        ),
        "g_description": "Where the source comes from: {text}",
        "g_source": "Source text: {text}",
        "g_preimage": "Seed preimage (the SHA-256 of this text is the seed): {text}",
        "g_seed": "Seed (SHA-256): {seed}",
        "g_start": "Pick order of week 1: {order}.",
        "g_week": "Week {week} (pick order: {order})",
        "g_round": "Round {r}: {picks}",
        "g_pick": "{person} {chore}",
        "g_pick_sep": ", ",
        "g_gets_head": "Who gets what:",
        "g_gets": "{person}: {chores}",
        "g_gets_none": "{person}: (none)",
        "g_guarantee": (
            "Guarantee (EF1): check it with your own ranking. In every round the chore you "
            "picked is no worse than the one each other person picked right after you, with at "
            "most one chore as an exception: set it aside and you envy nobody. Everybody gets a "
            "private message with their own ranking so they can check."
        ),
        "g_guarantee_partial": (
            "Guarantee (EF1): it holds except for the pairs listed below. Check it with your "
            "own ranking. In every round the chore you picked is no worse than the one each "
            "other person picked right after you, with at most one chore as an exception: set "
            "it aside and you do not envy those people. Everybody gets a private message with "
            "their own ranking so they can check."
        ),
        "g_ef1_bad": "Where EF1 fails (the script does not change the split):",
        "g_ef1_line": "Week {week}, {person} against {other}: {person} holds {a}, {other} holds {b}{ran}",
        "g_limits": (
            "Not guaranteed: round-robin picking is not strategy-proof and rankings do not show "
            "how much a chore is disliked, so only EF1 is promised, not equal total burden. Each "
            "week is guaranteed on its own, not the weeks added together."
        ),
        "g_recompute": (
            "Recompute: the source text, the names, the chore units per week and the rule name are "
            "above. Take the SHA-256 of the seed preimage and shuffle with the counter to get the "
            "order of week 1. Later weeks follow from the rotation rule. The shuffle is "
            "specified under Public randomness in docs/THEORY.md of github.com/YYYJH1/fair-and-square-skills."
        ),
    },
}


def joined(lang: str, items: Sequence[str]) -> str:
    """Names joined with the separator of the language, or the word for none."""
    text = TEXT[lang]
    return text["sep"].join(items) if items else text["none"]


def quoted(lang: str, chore: str) -> str:
    """A chore name in the quotation marks of the language."""
    return TEXT[lang]["quote"].format(chore)


def chore_list(lang: str, chores: Sequence[str]) -> str:
    """Chores in pick order; a chore picked several times appears once with its count."""
    text = TEXT[lang]
    counts: dict = {}
    for chore in chores:
        counts[chore] = counts.get(chore, 0) + 1
    parts = [chore + (text["times"].format(k=k) if k > 1 else "") for chore, k in counts.items()]
    return text["sep"].join(parts)


def say(lang: str, key: str, **values: Any) -> str:
    """Fill the text template of this key (see fsq_core.fill_text for the Latin-name spacing)."""
    return fc.fill_text(lang, TEXT[lang][key], **values)


# ---------------------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------------------


@dataclass
class Problem:
    """A validated input."""

    people: list  # as listed
    chores: list  # [(name, units)] as listed
    rankings: dict  # person -> the chores they can do, least disliked first
    cannot: dict  # person -> the chores they cannot do, sorted by code point
    weeks: int
    rotate: str
    source: str
    description: str

    @property
    def total_units(self) -> int:
        return sum(units for _, units in self.chores)

    @property
    def chore_names(self) -> list:
        return [name for name, _ in self.chores]

    def rank(self, person: str) -> dict:
        """Place of each chore in the person's own ranking, counted from 1."""
        return {chore: index for index, chore in enumerate(self.rankings[person], 1)}


def parse_chores(value: Any) -> list:
    """chores: names, or objects with a name and the number of units in the week."""
    items = fc.require_list(value, "chores", 1, MAX_CHORES)
    parsed = []
    for index, item in enumerate(items):
        where = f"chores[{index}]"
        if isinstance(item, dict):
            fc.check_fields(item, CHORE_FIELDS, where)
            name = item.get("name")
            units = fc.require_int(item.get("units", 1), f"{where}.units", 1, MAX_UNITS)
        elif isinstance(item, str):
            name, units = item, 1
        else:
            raise fc.InputError(where, "must be a chore name or an object with name and units")
        parsed.append((name, units))
    names = fc.require_encodable_names([name for name, _ in parsed], "chores", 1, MAX_CHORES)
    if sum(units for _, units in parsed) > MAX_TOTAL_UNITS:
        raise fc.InputError("chores", f"have more than {MAX_TOTAL_UNITS} units in total")
    return list(zip(names, [units for _, units in parsed]))


def parse_person_chores(value: Any, field_name: str, people: list, chores: list) -> dict:
    """cannot / likes: person -> the distinct chores listed, sorted by code point."""
    obj = fc.require_object(value, field_name)
    known = set(chores)
    found: dict = {}
    for person, listed in obj.items():
        if person not in people:
            raise fc.InputError(f"{field_name}.{person}", "is not a person listed in people")
        items = fc.require_list(listed, f"{field_name}.{person}")
        seen: set = set()
        for index, chore in enumerate(items):
            where = f"{field_name}.{person}[{index}]"
            if not isinstance(chore, str) or chore not in known:
                raise fc.InputError(where, f"{chore!r} is not a chore listed in chores")
            if chore in seen:
                raise fc.InputError(where, f"duplicate chore {chore!r}")
            seen.add(chore)
        found[person] = sorted(seen)
    return found


def parse_ranking(person: str, value: Any, chores: list, blocked: Sequence[str]) -> list:
    """One ranking: every chore the person can do, each exactly once."""
    where = f"rankings.{person}"
    items = fc.require_list(value, where)
    known = set(chores)
    seen: set = set()
    for index, chore in enumerate(items):
        spot = f"{where}[{index}]"
        if not isinstance(chore, str) or chore not in known:
            raise fc.InputError(spot, f"{chore!r} is not a chore listed in chores")
        if chore in blocked:
            raise fc.InputError(
                spot, f"{chore!r} is in cannot for {person}: leave it out of the ranking"
            )
        if chore in seen:
            raise fc.InputError(spot, f"duplicate chore {chore!r}: list each chore only once")
        seen.add(chore)
    missing = [chore for chore in chores if chore not in blocked and chore not in seen]
    if missing:
        raise fc.InputError(
            where,
            "is not a ranking of all the chores this person can do, each exactly once: missing "
            + ", ".join(repr(chore) for chore in missing),
        )
    return list(items)


def chosen_plan(data: dict) -> str:
    """The plan named in rules.plan, or round_robin when the input does not name one.

    A rules block that is missing or not an object is left to the checks of the plan itself.
    """
    rules = data.get("rules")
    if isinstance(rules, dict) and "plan" in rules:
        return fc.require_choice(rules["plan"], "rules.plan", PLANS)
    return PLAN_ROUND_ROBIN


def parse_problem(data: Any) -> Any:
    """Validate an input object. Every message names the field.

    Returns a Problem for plan round_robin and a BundleProblem for plan bundle_pay.
    """
    data = fc.require_object(data, "input")
    if chosen_plan(data) == PLAN_BUNDLE:
        return parse_bundle_problem(data)
    for name in BUNDLE_ONLY:
        if name in data:
            raise fc.InputError(
                name,
                f"is used by plan {PLAN_BUNDLE} only. This input uses plan {PLAN_ROUND_ROBIN}, "
                f"which takes rankings: set rules.plan to {PLAN_BUNDLE} or take {name} out",
            )
    fc.check_fields(data, TOP_FIELDS, "")
    people = fc.require_encodable_names(data.get("people"), "people", 2, MAX_PEOPLE)
    chores = parse_chores(data.get("chores"))
    names = [name for name, _ in chores]
    cannot = parse_person_chores(data.get("cannot", {}), "cannot", people, names)
    likes = parse_person_chores(data.get("likes", {}), "likes", people, names)
    for person in people:
        if likes.get(person):
            raise fc.InputError(
                f"likes.{person}",
                f"{likes[person][0]!r} is a task {person} likes doing. chore-split handles only "
                "chores, where every cost is zero or more, so it cannot include a liked task. "
                "Take it out of chores and agree separately who does it",
            )
    if "rankings" not in data:
        raise fc.InputError(
            "rankings",
            "is required: for every person, the chores they can do, least disliked first",
        )
    obj = fc.require_object(data["rankings"], "rankings")
    for person in obj:
        if person not in people:
            raise fc.InputError(f"rankings.{person}", "is not a person listed in people")
    rankings: dict = {}
    for person in people:
        if person not in obj:
            raise fc.InputError(
                f"rankings.{person}",
                "is missing: every person needs a ranking of the chores they can do",
            )
        rankings[person] = parse_ranking(person, obj[person], names, cannot.get(person, []))
    weeks = fc.require_int(data.get("weeks", 1), "weeks", 1, MAX_WEEKS)
    if "rules" not in data:
        raise fc.InputError(
            "rules",
            "is required: it holds random_source, the public text that fixes the pick order",
        )
    rules = fc.require_object(data["rules"], "rules")
    fc.check_fields(rules, RULE_FIELDS, "rules")
    if "random_source" not in rules:
        raise fc.InputError(
            "rules.random_source",
            "is required: the public text the pick order of week 1 is drawn from, copied exactly",
        )
    source = fc.require_source_text(rules["random_source"], "rules.random_source")
    description = ""
    if "source_description" in rules:
        description = fc.one_line(rules["source_description"], "rules.source_description")
    rotate = fc.require_choice(rules.get("rotate", "shift"), "rules.rotate", ROTATIONS)
    return Problem(
        people=people,
        chores=chores,
        rankings=rankings,
        cannot={person: cannot.get(person, []) for person in people},
        weeks=weeks,
        rotate=rotate,
        source=source,
        description=description,
    )


# ---------------------------------------------------------------------------------------
# Picking
# ---------------------------------------------------------------------------------------


@dataclass
class Pick:
    """One pick: the seq-th of the week, made in round `round` by `person`."""

    seq: int
    round: int
    person: str
    chore: str


@dataclass
class Week:
    number: int
    order: list  # the pick order of this week
    picks: list  # [Pick] in time order
    bundles: dict  # person -> chores in pick order (a chore with several units repeats)
    ran_out: dict  # person -> the round in which they found nothing they can do
    rounds: int


@dataclass
class Comparison:
    """A person's pick against the pick the other person makes right after it."""

    own: Pick
    other: Pick
    own_rank: int
    other_rank: Any  # None when the other chore is one this person cannot do
    holds: bool


@dataclass
class PairCheck:
    """What one person can say about one other person in one week."""

    week: int
    person: str
    other: str
    person_first: bool  # the person picks before the other in every round
    status: str
    via: str
    comparisons: list
    unmatched: list  # picks of the person after the other's last pick
    exempt: list  # chores of the other that this person cannot do
    witness: Any  # for STATUS_FAILS
    other_out_round: Any


@dataclass
class Plan:
    problem: Problem
    seed_hex: str
    preimage: str
    base_order: list
    weeks: list
    checks: list
    failures: list = field(default_factory=list)
    n_comparisons: int = 0
    n_comparisons_failed: int = 0

    @property
    def ef1_holds(self) -> bool:
        return not self.failures


def draw_start(problem: Problem) -> tuple:
    """(order, seed hex, seed preimage) of week 1, from the public source through SHA-256."""
    drawn = fc.seeded_order(RULE_NAME, problem.people, problem.total_units, problem.source)
    return drawn.order, drawn.seed_hex, drawn.preimage


def week_order(base: Sequence[str], number: int, rotate: str) -> list:
    """The pick order of a week: the start moves one place each week unless rotate is none."""
    shift = (number - 1) % len(base) if rotate == "shift" else 0
    return list(base[shift:]) + list(base[:shift])


def run_week(problem: Problem, number: int, order: Sequence[str]) -> Week:
    """Round-robin picking: in order, each person takes the remaining chore they mind least."""
    remaining = {name: units for name, units in problem.chores}
    left = sum(remaining.values())
    picks: list = []
    ran_out: dict = {}
    round_no = 0
    while left:
        round_no += 1
        before = len(picks)
        for person in order:
            if person in ran_out:
                continue
            chore = next((c for c in problem.rankings[person] if remaining[c]), None)
            if chore is None:
                ran_out[person] = round_no
                continue
            remaining[chore] -= 1
            left -= 1
            picks.append(Pick(len(picks) + 1, round_no, person, chore))
            if not left:
                break
        if len(picks) == before:
            raise RuntimeError("a round without a pick: chores are left that nobody can do")
    bundles: dict = {person: [] for person in order}
    for pick in picks:
        bundles[pick.person].append(pick.chore)
    return Week(number, list(order), picks, bundles, ran_out, round_no)


# ---------------------------------------------------------------------------------------
# Envy up to one chore
# ---------------------------------------------------------------------------------------


def counts_of(chores: Sequence[str]) -> dict:
    counts: dict = {}
    for chore in chores:
        counts[chore] = counts.get(chore, 0) + 1
    return counts


def dominated(mine: Sequence[int], theirs: Sequence[int]) -> bool:
    """Both lists hold places in the ranking, heaviest first. True when the bundle `mine` is
    no heavier than `theirs` for every cost that fits the ranking: it has no more chores, and
    its t-th heaviest chore is no worse than the t-th heaviest chore of `theirs`."""
    return len(mine) <= len(theirs) and all(a <= b for a, b in zip(mine, theirs))


def compare_bundles(own: dict, other: dict, ranking: Sequence[str]) -> tuple:
    """Compare a person's bundle with another bundle, for every non-negative additive cost that
    fits the person's ranking (least disliked first, only the chores they can do).

    own and other map chore -> units. Returns (status, witness, exempt):
      exempt   the other bundle holds a chore the person cannot do: nothing to envy;
      envy_free   the person's bundle costs no more than the other bundle for every such cost;
      ef1      the same once the heaviest chore the person holds (the one ranked latest) is set
               aside;
      fails    even then it costs more for some cost, and witness says for which.
    A cost fits the ranking when it is not negative and does not fall along the ranking. Such
    costs are sums of 0/1 step costs (a chore costs 1 from some place on), so comparing the two
    bundles place by place, heaviest first, decides the question exactly.
    """
    place = {chore: index for index, chore in enumerate(ranking, 1)}
    exempt = [chore for chore, units in other.items() if units and chore not in place]
    if exempt:
        return STATUS_EXEMPT, None, exempt
    mine = sorted((place[c] for c, units in own.items() for _ in range(units)), reverse=True)
    theirs = sorted((place[c] for c, units in other.items() for _ in range(units)), reverse=True)
    if dominated(mine, theirs):
        return STATUS_FREE, None, []
    rest = mine[1:]
    if dominated(rest, theirs):
        return STATUS_EF1, None, []
    for k in range(1, len(ranking) + 1):
        own_heavy = sum(1 for p in rest if p >= k)
        other_heavy = sum(1 for p in theirs if p >= k)
        if own_heavy > other_heavy:
            witness = {
                "threshold": k,
                "chore": ranking[k - 1],
                "own_heavy": own_heavy,
                "other_heavy": other_heavy,
            }
            return STATUS_FAILS, witness, []
    raise AssertionError("a failed dominance check always has a failing threshold")


def timing_comparisons(week: Week, person: str, other: str, place: dict) -> tuple:
    """Each pick of the person against the other person's next pick after it.

    The other's chore was still there when the person picked. If the person can do it, they
    ranked it no better than the chore they took, which is what a comparison records. Returns
    (comparisons, unmatched): the unmatched picks come after the last pick of the other person.
    """
    mine = [pick for pick in week.picks if pick.person == person]
    theirs = [pick for pick in week.picks if pick.person == other]
    comparisons = []
    unmatched = []
    for pick in mine:
        follow = next((q for q in theirs if q.seq > pick.seq), None)
        if follow is None:
            unmatched.append(pick)
            continue
        own_rank = place[pick.chore]
        other_rank = place.get(follow.chore)
        holds = other_rank is None or own_rank <= other_rank
        comparisons.append(Comparison(pick, follow, own_rank, other_rank, holds))
    return comparisons, unmatched


def check_pair(problem: Problem, week: Week, person: str, other: str) -> PairCheck:
    place = problem.rank(person)
    comparisons, unmatched = timing_comparisons(week, person, other, place)
    status, witness, exempt = compare_bundles(
        counts_of(week.bundles[person]),
        counts_of(week.bundles[other]),
        problem.rankings[person],
    )
    # "rounds": the comparisons above prove the status (nothing left over for envy-free, exactly
    # the last pick left over for EF1). "dominance": only the place-by-place check proves it.
    via = ""
    if status == STATUS_FREE:
        via = VIA_ROUNDS if not unmatched else VIA_DOMINANCE
    elif status == STATUS_EF1:
        via = VIA_ROUNDS if len(unmatched) == 1 else VIA_DOMINANCE
    return PairCheck(
        week=week.number,
        person=person,
        other=other,
        person_first=week.order.index(person) < week.order.index(other),
        status=status,
        via=via,
        comparisons=comparisons,
        unmatched=unmatched,
        exempt=exempt,
        witness=witness,
        other_out_round=week.ran_out.get(other),
    )


def compute(problem: Any) -> Any:
    """Draw the order of week 1, run every week and check every pair of people.

    A BundleProblem (plan bundle_pay) goes to compute_bundle, and the result is a BundlePlan.
    """
    if isinstance(problem, BundleProblem):
        return compute_bundle(problem)
    for name in problem.chore_names:
        if all(name in problem.cannot[person] for person in problem.people):
            raise fc.NoSolution(
                f"nobody can do the chore {name!r}: every person lists it in cannot. Under the "
                "agreed rules there is nothing to run. Find somebody who can do it or take it "
                "out of chores, and run again"
            )
    base, seed_hex, preimage = draw_start(problem)
    weeks = [
        run_week(problem, number, week_order(base, number, problem.rotate))
        for number in range(1, problem.weeks + 1)
    ]
    checks = [
        check_pair(problem, week, person, other)
        for week in weeks
        for person in week.order
        for other in week.order
        if other != person
    ]
    plan = Plan(problem, seed_hex, preimage, base, weeks, checks)
    plan.failures = [check for check in checks if check.status == STATUS_FAILS]
    plan.n_comparisons = sum(len(check.comparisons) for check in checks)
    plan.n_comparisons_failed = sum(
        1 for check in checks for comparison in check.comparisons if not comparison.holds
    )
    if plan.n_comparisons_failed:
        raise RuntimeError("a round-by-round comparison failed: this is a bug, not an input error")
    return plan


# ---------------------------------------------------------------------------------------
# Texts of the result
# ---------------------------------------------------------------------------------------


def quantity(lang: str, kind: str, n: int) -> str:
    """A number with its noun, in the singular or plural of the language."""
    return TEXT[lang][f"{kind}_{1 if n == 1 else 'n'}"].format(n=n)


def count_text(lang: str, n: int, heavy: bool = False) -> str:
    return quantity(lang, "heavy" if heavy else "count", n)


def witness_text(check: PairCheck, lang: str, second_person: bool) -> str:
    """Why EF1 fails for a pair, spoken to the person or about them."""
    text = TEXT[lang]
    w = check.witness
    who = text["you"] if second_person else check.person
    whose = text["your"] if second_person else text["poss"].format(check.person)
    heavy = w["threshold"] > 1
    out = say(
        lang,
        "w_heavy" if heavy else "w_count",
        who=who,
        whose=whose,
        theirs=text["poss"].format(check.other),
        other=check.other,
        x=quoted(lang, w["chore"]),
        a=count_text(lang, w["own_heavy"], heavy),
        b=count_text(lang, w["other_heavy"], heavy),
    )
    if check.other_out_round is not None:
        out += say(lang, "w_ran_out", other=check.other, r=check.other_out_round)
    return out


def comparison_cell(comparison: Comparison, lang: str) -> str:
    """One comparison for the organizer's table."""
    text = TEXT[lang]
    key = "cmp_same" if comparison.other.round == comparison.own.round else "cmp_next"
    other_rank = text["cant"] if comparison.other_rank is None else str(comparison.other_rank)
    return text[key].format(
        r=comparison.own.round,
        r2=comparison.other.round,
        c=comparison.own.chore,
        k=comparison.own_rank,
        c2=comparison.other.chore,
        k2=other_rank,
    )


def result_cell(check: PairCheck, lang: str) -> str:
    """The conclusion of one pair for the organizer's table."""
    text = TEXT[lang]
    if check.status == STATUS_EXEMPT:
        return text["res_exempt"].format(
            chores=joined(lang, [quoted(lang, c) for c in check.exempt])
        )
    if check.status == STATUS_FAILS:
        return text["res_fails"]
    if check.status == STATUS_FREE:
        return text["res_free" if check.via == VIA_ROUNDS else "res_free_dom"]
    if check.via == VIA_ROUNDS:
        return text["res_ef1"].format(c=quoted(lang, check.unmatched[-1].chore))
    return text["res_ef1_dom"]


def pair_clause(check: PairCheck, lang: str) -> str:
    """What the person can check against the other person, in the second person."""
    text = TEXT[lang]
    other = check.other
    head = say(
        lang,
        "pc_head_first" if check.person_first else "pc_head_second",
        week=check.week,
        other=other,
    )
    if check.status == STATUS_EXEMPT:
        chores = joined(lang, [quoted(lang, c) for c in check.exempt])
        parts = [say(lang, "pc_exempt", other=other, chores=chores)]
    else:
        parts = []
        for comparison in check.comparisons:
            key = "pc_same" if comparison.other.round == comparison.own.round else "pc_next"
            if comparison.other_rank is None:
                other_place = text["pc_k_cant"]
            else:
                other_place = text["pc_k_other"].format(k=comparison.other_rank)
            parts.append(
                say(
                    lang,
                    key,
                    r=comparison.own.round,
                    r2=comparison.other.round,
                    c=quoted(lang, comparison.own.chore),
                    k=text["pc_k_own"].format(k=comparison.own_rank),
                    c2=quoted(lang, comparison.other.chore),
                    k2=other_place,
                    other=other,
                )
            )
        if check.status == STATUS_FAILS:
            parts.append(say(lang, "pc_fail", witness=witness_text(check, lang, True)))
        elif check.status == STATUS_FREE:
            if check.via == VIA_DOMINANCE:
                parts.append(say(lang, "pc_free_dom", other=other))
            else:
                key = "pc_free" if check.comparisons else "pc_free_empty"
                parts.append(say(lang, key, other=other))
        elif check.via == VIA_ROUNDS:
            last = quoted(lang, check.unmatched[-1].chore)
            parts.append(say(lang, "pc_ef1_last", c=last, other=other))
        else:
            parts.append(say(lang, "pc_ef1_dom", other=other))
    return head + text["pc_sep"].join(parts) + text["end"]


def failing_others(plan: Plan, person: str) -> list:
    """The people against whom EF1 fails for this person, in the order of week 1."""
    names = {check.other for check in plan.failures if check.person == person}
    return [name for name in plan.base_order if name in names]


def rounds_summary(plan: Plan, person: str, lang: str) -> str:
    """The rounds in which the person picked, and what they picked, for every week."""
    text = TEXT[lang]
    parts = []
    for week in plan.weeks:
        mine = [pick for pick in week.picks if pick.person == person]
        listed = text["dm_round_sep"].join(
            text["dm_round"].format(r=pick.round, c=pick.chore) for pick in mine
        )
        listed = listed or text["dm_no_picks"]
        if len(plan.weeks) > 1:
            listed = text["dm_week_rounds"].format(week=week.number, rounds=listed)
        parts.append(listed)
    return text["dm_week_sep"].join(parts)


def one_liner(plan: Plan, person: str, lang: str) -> str:
    """The one-sentence certificate of a person, with the rounds they picked in."""
    text = TEXT[lang]
    if not any(pick.person == person for week in plan.weeks for pick in week.picks):
        return text["dm_ok_none"]
    rounds = rounds_summary(plan, person, lang)
    failing = failing_others(plan, person)
    if not failing:
        return text["dm_ok"].format(rounds=rounds)
    if len(failing) == len(plan.base_order) - 1:
        return text["dm_fail_all"].format(rounds=rounds)
    return say(lang, "dm_fail_some", names=joined(lang, failing), rounds=rounds)


def week_line(week: Week, person: str, lang: str) -> str:
    text = TEXT[lang]
    position = week.order.index(person) + 1
    order = joined(lang, week.order)
    mine = [pick for pick in week.picks if pick.person == person]
    if not mine:
        return text["dm_week_none"].format(week=week.number, order=order, pos=position)
    picks = text["dm_round_sep"].join(
        text["dm_round"].format(r=pick.round, c=pick.chore) for pick in mine
    )
    return text["dm_week"].format(week=week.number, order=order, pos=position, picks=picks)


def person_lines(plan: Plan, lang: str) -> dict:
    """The private message of every person: their own picks and their own numbers only."""
    text = TEXT[lang]
    problem = plan.problem
    lines: dict = {}
    for person in plan.base_order:
        rows = [text["dm_head"].format(person=person)]
        rows += [week_line(week, person, lang) for week in plan.weeks]
        rows.append(one_liner(plan, person, lang))
        rows += [pair_clause(check, lang) for check in plan.checks if check.person == person]
        ranking = text["rank_sep"].join(problem.rankings[person]) or text["none"]
        rows.append(text["dm_ranking"].format(ranking=ranking))
        if problem.cannot[person]:
            chores = joined(lang, problem.cannot[person])
            rows.append(text["dm_cannot"].format(chores=chores))
        lines[person] = rows
    return lines


def failure_reason(check: PairCheck, lang: str) -> str:
    return witness_text(check, lang, False)


def schedule_table(plan: Plan, lang: str) -> fc.Table:
    text = TEXT[lang]
    rows = []
    for week in plan.weeks:
        cells = [str(week.number), joined(lang, week.order)]
        for person in plan.base_order:
            chores = week.bundles[person]
            cells.append(chore_list(lang, chores) if chores else text["nothing"])
        rows.append(cells)
    return fc.Table(text["hdr_schedule"] + list(plan.base_order), rows, text["cap_schedule"])


def picks_table(plan: Plan, lang: str) -> fc.Table:
    text = TEXT[lang]
    rows = []
    for week in plan.weeks:
        for round_no in range(1, week.rounds + 1):
            picks = [pick for pick in week.picks if pick.round == round_no]
            cell = text["pick_arrow"].join(
                text["pick_item"].format(person=pick.person, chore=pick.chore) for pick in picks
            )
            skipped = [name for name in week.order if week.ran_out.get(name) == round_no]
            if skipped:
                cell += say(lang, "skipped_from", names=joined(lang, skipped))
            rows.append([str(week.number), str(round_no), cell])
    return fc.Table(text["hdr_picks"], rows, text["cap_picks"])


def cert_table(plan: Plan, lang: str) -> fc.Table:
    """Round-by-round check of every pair, for the first week."""
    text = TEXT[lang]
    rows = []
    for check in plan.checks:
        if check.week != 1:
            continue
        cells = text["cmp_sep"].join(comparison_cell(c, lang) for c in check.comparisons)
        rows.append(
            [
                check.person,
                check.other,
                text["before" if check.person_first else "after"],
                cells or text["cmp_none"],
                result_cell(check, lang),
            ]
        )
    return fc.Table(text["hdr_cert"], rows, text["cap_cert"].format(week=1))


def source_table(plan: Plan, lang: str) -> fc.Table:
    text = TEXT[lang]
    problem = plan.problem
    rows = []
    if problem.description:
        rows.append([text["f_description"], problem.description])
    rows += [
        [text["f_source"], problem.source],
        [text["f_rule"], RULE_NAME],
        [text["f_units"], str(problem.total_units)],
        [text["f_people"], ", ".join(sorted(problem.people))],
        [text["f_preimage"], plan.preimage],
        [text["f_seed"], plan.seed_hex],
        [text["f_order"], joined(lang, plan.base_order)],
    ]
    return fc.Table(text["hdr_facts"], rows, text["cap_source"])


def summary_notes(plan: Plan, lang: str) -> list:
    """Paragraphs under the tables: how to read them, the EF1 status, rotation, recomputing."""
    text = TEXT[lang]
    problem = plan.problem
    notes = [text["n_legend"]]
    if problem.weeks == 2:
        notes.append(text["n_more_week"].format(first=2))
    elif problem.weeks > 2:
        notes.append(text["n_more_weeks"].format(first=2, last=problem.weeks))
    if plan.ef1_holds:
        notes.append(
            text["n_ef1_ok"].format(
                weeks=quantity(lang, "q_weeks_checked", problem.weeks), n=plan.n_comparisons
            )
        )
    else:
        lines = [text["n_ef1_bad"]]
        for check in plan.failures:
            lines.append(
                say(
                    lang,
                    "n_ef1_line",
                    week=check.week,
                    person=check.person,
                    other=check.other,
                    reason=failure_reason(check, lang),
                )
            )
        notes.append("\n".join(lines))
    if problem.rotate == "shift":
        notes.append(text["n_rotate_shift"].format(people=len(problem.people)))
    else:
        notes.append(text["n_rotate_none"])
    if "|" in plan.preimage:
        notes.append(text["n_pipe"])
    notes.append(text["n_algo"])
    lines = [text["n_one_liners"]]
    lines += [
        text["n_one_liner"].format(person=person, text=one_liner(plan, person, lang))
        for person in plan.base_order
    ]
    notes.append("\n".join(lines))
    return notes


def not_modeled(plan: Plan, lang: str) -> list:
    text = TEXT[lang]
    items = [text["nm_source"], text["nm_ranking"], text["nm_strategy"], text["nm_weeks"]]
    if any(plan.problem.cannot.values()):
        items.append(text["nm_cannot"])
    items += [text["nm_likes"], text["nm_money"]]
    return items


def group_lines(plan: Plan, lang: str) -> list:
    """The card for the group chat: the schedule, the picks, the source. No ranking."""
    text = TEXT[lang]
    problem = plan.problem
    lines = [text["g_rule_shift" if problem.rotate == "shift" else "g_rule_none"]]
    if problem.description:
        lines.append(text["g_description"].format(text=problem.description))
    lines.append(text["g_source"].format(text=problem.source))
    lines.append(text["g_preimage"].format(text=plan.preimage))
    lines.append(text["g_seed"].format(seed=plan.seed_hex))
    lines.append(text["g_start"].format(order=joined(lang, plan.base_order)))
    for week in plan.weeks:
        lines.append(text["g_week"].format(week=week.number, order=joined(lang, week.order)))
        for round_no in range(1, week.rounds + 1):
            picks = text["g_pick_sep"].join(
                text["g_pick"].format(person=p.person, chore=p.chore)
                for p in week.picks
                if p.round == round_no
            )
            lines.append(text["g_round"].format(r=round_no, picks=picks))
        lines.append(text["g_gets_head"])
        for person in plan.base_order:
            chores = week.bundles[person]
            key = "g_gets" if chores else "g_gets_none"
            lines.append(text[key].format(person=person, chores=chore_list(lang, chores)))
    lines.append(text["g_guarantee" if plan.ef1_holds else "g_guarantee_partial"])
    if plan.failures:
        lines.append(text["g_ef1_bad"])
        by_number = {week.number: week for week in plan.weeks}
        for check in plan.failures:
            ran = ""
            if check.other_out_round is not None:
                ran = say(lang, "w_ran_out", other=check.other, r=check.other_out_round)
            week = by_number[check.week]
            lines.append(
                say(
                    lang,
                    "g_ef1_line",
                    week=check.week,
                    person=check.person,
                    other=check.other,
                    a=count_text(lang, len(week.bundles[check.person])),
                    b=count_text(lang, len(week.bundles[check.other])),
                    ran=ran,
                )
            )
    lines.append(text["g_limits"])
    lines.append(text["g_recompute"])
    return lines


# ---------------------------------------------------------------------------------------
# The Result
# ---------------------------------------------------------------------------------------


def inputs_echo(plan: Plan) -> dict:
    problem = plan.problem
    echo: dict = {
        "participants": sorted(problem.people),
        "chores": [{"name": name, "units": units} for name, units in problem.chores],
        "total_units": problem.total_units,
        "rankings": {person: list(problem.rankings[person]) for person in sorted(problem.people)},
        "weeks": problem.weeks,
        "rotate": problem.rotate,
        "random_source": problem.source,
    }
    if problem.description:
        echo["source_description"] = problem.description
    cannot = {person: list(c) for person, c in sorted(problem.cannot.items()) if c}
    if cannot:
        echo["cannot"] = cannot
    return echo


def pick_json(pick: Pick) -> dict:
    return {"seq": pick.seq, "round": pick.round, "person": pick.person, "chore": pick.chore}


def week_json(week: Week) -> dict:
    return {
        "week": week.number,
        "order": list(week.order),
        "rounds": week.rounds,
        "picks": [pick_json(pick) for pick in week.picks],
        "bundles": {person: list(week.bundles[person]) for person in week.order},
        "ran_out_in_round": dict(sorted(week.ran_out.items())),
    }


def pair_json(check: PairCheck) -> dict:
    return {
        "week": check.week,
        "person": check.person,
        "other": check.other,
        "person_picks_first": check.person_first,
        "status": check.status,
        "via": check.via,
        "comparisons": [
            {
                "own_round": c.own.round,
                "own_chore": c.own.chore,
                "own_place": c.own_rank,
                "other_round": c.other.round,
                "other_chore": c.other.chore,
                "other_place": c.other_rank,
                "same_round": c.other.round == c.own.round,
                "holds": c.holds,
            }
            for c in check.comparisons
        ],
        "unmatched_picks": [{"round": p.round, "chore": p.chore} for p in check.unmatched],
        "exempt_chores": list(check.exempt),
        "witness": check.witness,
        "other_ran_out_in_round": check.other_out_round,
    }


def result_json(plan: Plan) -> dict:
    problem = plan.problem
    return {
        "rule": RULE_NAME,
        "seed_hex": plan.seed_hex,
        "seed_preimage": plan.preimage,
        "start_order": list(plan.base_order),
        "weeks": [week_json(week) for week in plan.weeks],
        "schedule": {
            person: [list(week.bundles[person]) for week in plan.weeks]
            for person in sorted(problem.people)
        },
        "ef1_holds": plan.ef1_holds,
        "ef1_failures": [
            {"week": c.week, "person": c.person, "other": c.other, "witness": c.witness}
            for c in plan.failures
        ],
        "comparisons_checked": plan.n_comparisons,
        "comparisons_failed": plan.n_comparisons_failed,
    }


def build_result(plan: Any, lang: str = "zh", reproduce: str = "") -> fc.Result:
    """Turn a plan into the shared Result (md, dm, group and json all come from it)."""
    if lang not in TEXT:
        raise ValueError(f"lang must be one of {', '.join(TEXT)}")
    if isinstance(plan, BundlePlan):
        return build_bundle_result(plan, lang, reproduce)
    text = TEXT[lang]
    problem = plan.problem
    title = text["title"].format(
        people=len(problem.people),
        chores=quantity(lang, "q_chores", problem.total_units),
        weeks=quantity(lang, "q_weeks", problem.weeks),
    )
    tables = [
        schedule_table(plan, lang),
        picks_table(plan, lang),
        cert_table(plan, lang),
        source_table(plan, lang),
    ]
    lines = person_lines(plan, lang)
    certificate = {
        "one_liner": {person: one_liner(plan, person, lang) for person in plan.base_order},
        "pairs": [pair_json(check) for check in plan.checks],
        "recompute": {
            "source_text": problem.source,
            "algorithm": fc.SEED_SPEC,
            "seed_hex": plan.seed_hex,
        },
    }
    return fc.Result(
        title=title,
        inputs_echo=inputs_echo(plan),
        result=result_json(plan),
        certificate=certificate,
        not_modeled=not_modeled(plan, lang),
        reproduce=reproduce,
        tables=tables,
        notes=summary_notes(plan, lang),
        person_lines=lines,
        group_lines=group_lines(plan, lang),
    )


def solve(data: Any, lang: str = "zh", reproduce: str = "") -> fc.Result:
    """Validate, run and build the Result for one input object."""
    return build_result(compute(parse_problem(data)), lang, reproduce)


# ---------------------------------------------------------------------------------------
# Plan B, bundle_pay: fixed bundles with compensation. Input
# ---------------------------------------------------------------------------------------

# The recorded example of plan B: the same three roommates, six chores and two chores each. The
# costs are what each person would want per week for doing the chore once, in the group's money.
# Two splits have the smallest total cost, 135. Both leave every person at -45.00 a week.
BUNDLE_DEMO_JSON = """{
  "people": ["阿明", "小红", "大刘"],
  "chores": ["洗碗", "倒垃圾", "拖地", "刷厕所", "做饭", "擦窗"],
  "costs": {
    "阿明": {"洗碗": 30, "倒垃圾": 5, "拖地": 20, "刷厕所": 60, "做饭": 40, "擦窗": 25},
    "小红": {"洗碗": 20, "倒垃圾": 10, "拖地": 25, "刷厕所": 50, "做饭": 70, "擦窗": 20},
    "大刘": {"洗碗": 35, "倒垃圾": 15, "拖地": 10, "刷厕所": 40, "做饭": 30, "擦窗": 45}
  },
  "caps": {"阿明": 2, "小红": 2, "大刘": 2},
  "rules": {
    "plan": "bundle_pay",
    "random_source": "（虚构示例）2026-11-15 某公开开奖号码 05 12 18 26 31 + 03 09",
    "source_description": "虚构示例：2026 年 11 月 15 日某公开开奖，按官网显示的格式原样抄写"
  }
}"""

ROUND_ROBIN_HINTS = {
    "rankings": "every person gives costs instead: what each chore they can do costs them",
    "likes": "a task that somebody likes simply costs them 0 in costs",
    "weeks": "one typical week is settled, and it repeats every week",
    "rules.rotate": "there is no pick order to rotate",
}


@dataclass
class BundleProblem:
    """A validated input of plan bundle_pay. Amounts are integer cents."""

    people: list  # as listed
    chores: list  # [(name, units)] as listed
    costs: dict  # person -> {chore: cost of one unit}, only the chores the person can do
    caps: dict  # person -> the most chore units the person takes in a week
    cannot: dict  # person -> the chores the person cannot do, sorted by code point
    source: Any  # the public random source for ties, or None
    description: str

    @property
    def total_units(self) -> int:
        return sum(units for _, units in self.chores)

    @property
    def chore_names(self) -> list:
        return [name for name, _ in self.chores]

    @property
    def units_of(self) -> dict:
        return dict(self.chores)

    def room(self, person: str) -> int:
        """The most units the person can take, never more than there are units."""
        return min(self.caps[person], self.total_units)


def refuse_round_robin_field(field_name: str) -> None:
    """Plan bundle_pay does not use this field of plan round_robin: say so and name the field."""
    raise fc.InputError(
        field_name,
        f"is used by plan {PLAN_ROUND_ROBIN} only. In plan {PLAN_BUNDLE}, "
        + ROUND_ROBIN_HINTS[field_name],
    )


def parse_costs(data: dict, people: list, chores: list, cannot: dict) -> dict:
    """costs: person -> chore -> cost of one unit in whole cents, for every chore the person can
    do and for no other."""
    if "costs" not in data:
        raise fc.InputError(
            "costs",
            "is required: for every person, what each chore they can do costs them per unit, "
            "an amount of 0 or more",
        )
    obj = fc.require_object(data["costs"], "costs")
    for person in obj:
        if person not in people:
            raise fc.InputError(f"costs.{person}", "is not a person listed in people")
    parsed: dict = {}
    for person in people:
        if person not in obj:
            raise fc.InputError(
                f"costs.{person}",
                "is missing: every person needs the cost of each chore they can do",
            )
        row = fc.require_object(obj[person], f"costs.{person}")
        found: dict = {}
        for chore, amount in row.items():
            where = f"costs.{person}.{chore}"
            if chore not in chores:
                raise fc.InputError(where, "is not a chore listed in chores")
            if chore in cannot.get(person, []):
                raise fc.InputError(where, f"is in cannot for {person}: leave it out of costs")
            found[chore] = fc.to_cents(fc.money(amount, where))
        missing = [c for c in chores if c not in cannot.get(person, []) and c not in found]
        if missing:
            raise fc.InputError(
                f"costs.{person}",
                "is not the cost of all the chores this person can do, each exactly once: "
                "missing " + ", ".join(repr(chore) for chore in missing),
            )
        parsed[person] = found
    return parsed


def parse_caps(data: dict, people: list, total_units: int) -> dict:
    """caps: person -> the most chore units that person takes, a whole number from 0 up."""
    if "caps" not in data:
        raise fc.InputError(
            "caps", "is required: for every person, the most chore units they take in a week"
        )
    obj = fc.require_object(data["caps"], "caps")
    for person in obj:
        if person not in people:
            raise fc.InputError(f"caps.{person}", "is not a person listed in people")
    parsed: dict = {}
    for person in people:
        if person not in obj:
            raise fc.InputError(
                f"caps.{person}", "is missing: every person needs a cap, which may be 0"
            )
        parsed[person] = fc.require_int(obj[person], f"caps.{person}", 0, MAX_TOTAL_UNITS)
    return parsed


def parse_bundle_problem(data: dict) -> BundleProblem:
    """Validate an input of plan bundle_pay. Every message names the field."""
    for name in ROUND_ROBIN_ONLY:
        if name in data:
            refuse_round_robin_field(name)
    fc.check_fields(data, BUNDLE_TOP_FIELDS, "")
    people = fc.require_encodable_names(data.get("people"), "people", 2, MAX_PEOPLE)
    chores = parse_chores(data.get("chores"))
    names = [name for name, _ in chores]
    total = sum(units for _, units in chores)
    cannot = parse_person_chores(data.get("cannot", {}), "cannot", people, names)
    costs = parse_costs(data, people, names, cannot)
    caps = parse_caps(data, people, total)
    rules = fc.require_object(data["rules"], "rules")
    if "rotate" in rules:
        refuse_round_robin_field("rules.rotate")
    fc.check_fields(rules, BUNDLE_RULE_FIELDS, "rules")
    source = None
    description = ""
    if "random_source" in rules:
        source = fc.require_source_text(rules["random_source"], "rules.random_source")
    if "source_description" in rules:
        if source is None:
            raise fc.InputError(
                "rules.source_description", "describes rules.random_source, which is not given"
            )
        description = fc.one_line(rules["source_description"], "rules.source_description")
    return BundleProblem(
        people=people,
        chores=chores,
        costs=costs,
        caps=caps,
        cannot={person: cannot.get(person, []) for person in people},
        source=source,
        description=description,
    )


# ---------------------------------------------------------------------------------------
# Plan B: the cheapest split
# ---------------------------------------------------------------------------------------


def unit_chores(problem: BundleProblem) -> list:
    """The chore of each unit of the week, in the order of the chore names (code point order).

    A chore that repeats appears once per unit."""
    units = problem.units_of
    return [name for name in sorted(units) for _ in range(units[name])]


def nobody_can_do(problem: BundleProblem) -> None:
    """Raise NoSolution when some chore is on every person's cannot list."""
    for name in problem.chore_names:
        if all(name in problem.cannot[person] for person in problem.people):
            raise fc.NoSolution(
                f"nobody can do the chore {name!r}: every person lists it in cannot. Under the "
                "agreed rules there is nothing to run. Find somebody who can do it or take it "
                "out of chores, and run again"
            )


def find_sharing(problem: BundleProblem) -> list:
    """Some way to give every unit to a person who can do it, within the caps.

    Returns the person of each unit, in the order of unit_chores. When there is none, raises
    NoSolution and names a group of chores that the people who can do them cannot take between
    them. The search is augmenting paths (Kuhn), with a capacity for each person."""
    units = unit_chores(problem)
    people = sorted(problem.people)
    can = {p: set(problem.costs[p]) for p in people}
    room = {p: problem.room(p) for p in people}
    held: dict = {p: [] for p in people}
    owner: list = [None] * len(units)

    def place(unit: int, seen_people: set, seen_units: set) -> bool:
        for person in people:
            if units[unit] not in can[person] or room[person] == 0 or person in seen_people:
                continue
            seen_people.add(person)
            if len(held[person]) < room[person]:
                held[person].append(unit)
                owner[unit] = person
                return True
            for other in list(held[person]):
                if other not in seen_units:
                    seen_units.add(other)
                    if place(other, seen_people, seen_units):
                        held[person].remove(other)
                        held[person].append(unit)
                        owner[unit] = person
                        return True
        return False

    for first in range(len(units)):
        seen_people: set = set()
        seen_units = {first}
        if not place(first, seen_people, seen_units):
            stuck = sorted({units[u] for u in seen_units})
            doers = [p for p in people if any(c in can[p] for c in stuck)]
            raise fc.NoSolution(
                "there is no way to share out all the chores: "
                + ", ".join(repr(c) for c in stuck)
                + f" ({sum(problem.units_of[c] for c in stuck)} units in all) can be done only "
                + "by "
                + ", ".join(doers)
                + f", whose caps add up to {sum(room[p] for p in doers)}. Raise a cap, take a "
                "chore out of a cannot list or take a chore out of chores, and run again"
            )
    return owner


def hungarian(cost: Sequence[Sequence[int]]) -> list:
    """Hungarian method: the column chosen for each row in an assignment of smallest total cost.

    cost has integer entries and at least as many columns as rows. Every row gets its own
    column, and some columns stay unused when there are more columns than rows. The method
    keeps potentials for the rows and the columns and grows one alternating path per row, so
    it takes at most rows * rows * columns steps."""
    n, m = len(cost), len(cost[0])
    row_pot = [0] * (n + 1)
    col_pot = [0] * (m + 1)
    owner = [0] * (m + 1)  # owner[c] is the 1-based row matched to column c, 0 if none
    way = [0] * (m + 1)
    for row in range(1, n + 1):
        owner[0] = row
        col0 = 0
        slack: list = [None] * (m + 1)
        seen = [False] * (m + 1)
        while True:
            seen[col0] = True
            row0 = owner[col0]
            delta = None
            col1 = 0
            for col in range(1, m + 1):
                if seen[col]:
                    continue
                reduced = cost[row0 - 1][col - 1] - row_pot[row0] - col_pot[col]
                if slack[col] is None or reduced < slack[col]:
                    slack[col] = reduced
                    way[col] = col0
                if delta is None or slack[col] < delta:
                    delta, col1 = slack[col], col
            for col in range(m + 1):
                if seen[col]:
                    row_pot[owner[col]] += delta
                    col_pot[col] -= delta
                elif slack[col] is not None:
                    slack[col] -= delta
            col0 = col1
            if owner[col0] == 0:
                break
        while col0:
            previous = way[col0]
            owner[col0] = owner[previous]
            col0 = previous
    column_of = [0] * n
    for col in range(1, m + 1):
        if owner[col]:
            column_of[owner[col] - 1] = col - 1
    return column_of


def cheapest_split(problem: BundleProblem, priority: Sequence[str]) -> list:
    """The person of each unit, in the order of unit_chores, in the cheapest split.

    Every person gets one slot for each unit of their cap, and the Hungarian method gives each
    unit a slot. A cell costs the cost of the chore in cents times a big number B plus a small
    tie weight. B is larger than any total of tie weights, so the total cost in cents comes
    first. The tie weight of a unit given to the person at place r of priority is r times a
    power of the number of people, with the first unit the highest power, so among splits of
    the same total cost the one whose owners, read unit by unit, come first in priority wins.
    That split is unique. A cell the person cannot take costs more than any split that avoids
    such cells, and find_sharing has shown that one exists."""
    units = unit_chores(problem)
    m, n = len(units), len(problem.people)
    rank = {person: place for place, person in enumerate(priority)}
    big = n**m
    slots = [person for person in priority for _ in range(problem.room(person))]
    dearest = max((c for row in problem.costs.values() for c in row.values()), default=0)
    forbidden = (m * (dearest + 1) + 1) * big
    matrix = []
    for t, chore in enumerate(units):
        weight = n ** (m - 1 - t)
        matrix.append(
            [
                problem.costs[person][chore] * big + rank[person] * weight
                if chore in problem.costs[person]
                else forbidden
                for person in slots
            ]
        )
    owners = [slots[column] for column in hungarian(matrix)]
    if any(chore not in problem.costs[owner] for chore, owner in zip(units, owners)):
        raise AssertionError("the cheapest split gave a chore to somebody who cannot do it")
    return owners


def has_tied_split(problem: BundleProblem, bundles: dict) -> bool:
    """True when some other split has the same smallest total cost as the one in `bundles`.

    The splits are the integer solutions of a transportation problem: chores supply their
    units, people take them within their caps, and unused room is a chore called idle with a
    cost of 0. Another solution of the same cost exists exactly when the residual graph has a
    cycle of cost 0 that is not just one assignment taken back. Shortest distances from every
    node give potentials. A cycle of cost 0 uses only the arcs whose reduced cost is 0."""
    people = sorted(problem.people)
    chores = sorted(problem.chore_names)
    idle = len(chores)  # the idle "chore" is the last chore node
    first_person = idle + 1
    held = {p: {} for p in people}
    for person in people:
        for chore in bundles[person]:
            held[person][chore] = held[person].get(chore, 0) + 1
    arcs: list = []  # (from, to, cost)
    used: list = []  # (chore node, person node) pairs that carry flow
    for j, person in enumerate(people):
        node = first_person + j
        slack = problem.room(person) - len(bundles[person])
        for i, chore in enumerate(chores):
            if chore in problem.costs[person]:
                arcs.append((i, node, problem.costs[person][chore]))
            if held[person].get(chore, 0) > 0:
                arcs.append((node, i, -problem.costs[person][chore]))
                used.append((i, node))
        if problem.room(person) > 0:
            arcs.append((idle, node, 0))
        if slack > 0:
            arcs.append((node, idle, 0))
            used.append((idle, node))
    nodes = first_person + len(people)
    distance = [0] * nodes
    for sweep in range(nodes + 1):
        changed = False
        for tail, head, cost in arcs:
            if distance[tail] + cost < distance[head]:
                distance[head] = distance[tail] + cost
                changed = True
        if not changed:
            break
        if sweep == nodes:
            raise AssertionError("a split with a cycle of negative cost is not the cheapest one")
    tight: dict = {}
    for tail, head, cost in arcs:
        if distance[tail] + cost == distance[head]:
            tight.setdefault(tail, []).append(head)
    for chore_node, person_node in used:
        # Is there a way back from the chore to the person that is not the arc just left?
        reached = {chore_node}
        frontier = [chore_node]
        while frontier:
            tail = frontier.pop()
            for head in tight.get(tail, []):
                if (tail, head) == (chore_node, person_node) or head in reached:
                    continue
                reached.add(head)
                frontier.append(head)
        if person_node in reached:
            return True
    return False


# ---------------------------------------------------------------------------------------
# Plan B: the compensation. shortest_paths and maximin_utilities are the code of rent-split,
# copied here so that this skill folder stays on its own. A split of chores into bundles is a
# rent division in which the bundles are the rooms, a person's value for a bundle is minus the
# cost of doing it, and the total rent is zero.
# ---------------------------------------------------------------------------------------


def shortest_paths(
    values: Sequence[Sequence[Fraction]], room_of: Sequence[int]
) -> list[list[Fraction]]:
    """All-pairs shortest paths on the envy graph of a welfare-maximising assignment.

    The edge from person i to person k weighs v_k(room of k) - v_i(room of k). A utility
    vector u is envy-free at some rents exactly when u_k - u_i <= dist[i][k] for all i, k.
    """
    n = len(values)
    dist = [
        [
            Fraction(0) if i == k else Fraction(values[k][room_of[k]] - values[i][room_of[k]])
            for k in range(n)
        ]
        for i in range(n)
    ]
    for mid in range(n):
        for i in range(n):
            for k in range(n):
                dist[i][k] = min(dist[i][k], dist[i][mid] + dist[mid][k])
    if any(dist[i][i] < 0 for i in range(n)):
        raise ValueError("the assignment does not maximise the total value")
    return dist


def maximin_utilities(dist: Sequence[Sequence[Fraction]], budget: Fraction) -> list[Fraction]:
    """The unique envy-free utilities that leave the worst-off person as well off as possible.

    budget is the total value of the assignment minus the total rent. Rents may be negative.
    """
    n = len(dist)
    lows = [-min(row) for row in dist]
    level = (Fraction(budget) - sum(lows, Fraction(0))) / n
    return [level + low for low in lows]


@dataclass
class BundlePlan:
    """Everything computed for plan bundle_pay. Amounts without a unit are integer cents."""

    problem: BundleProblem
    people: list  # sorted by name: the order of every output
    priority: list  # the tie order: the sorted names, or the order drawn from the public source
    seed_hex: Any  # None without a public random source
    preimage: Any
    bundles: dict  # person -> chores, in the order of unit_chores
    cost: dict  # person -> cost of the person's own bundle, by the person's own numbers
    cost_of: dict  # person -> holder -> cost of the holder's bundle, None if not takeable
    exact_transfer: dict  # person -> Fraction of cents, money received (negative: paid)
    transfer: dict  # person -> rounded cents, money received (negative: paid)
    net: dict  # person -> transfer minus cost
    shares: dict  # person -> holder -> net if the person took that bundle and its payment
    total_cost: int
    max_envy: int  # the most any person would gain by another bundle, after rounding
    was_tie: bool  # another split has the same smallest total cost


def bundle_priority(problem: BundleProblem) -> tuple:
    """(tie order, seed hex, seed preimage): the sorted names, or the order drawn from the source."""
    if problem.source is None:
        return sorted(problem.people), None, None
    drawn = fc.seeded_order(BUNDLE_RULE_NAME, problem.people, problem.total_units, problem.source)
    return drawn.order, drawn.seed_hex, drawn.preimage


def takeable_cost(problem: BundleProblem, person: str, bundle: Sequence[str]) -> Any:
    """What a bundle of chores costs the person by their own numbers, in cents.

    None when the person cannot take it: it has more units than their cap or a chore they
    cannot do."""
    if len(bundle) > problem.caps[person]:
        return None
    if any(chore not in problem.costs[person] for chore in bundle):
        return None
    return sum(problem.costs[person][chore] for chore in bundle)


def settle_exactly(problem: BundleProblem, bundles: dict) -> tuple:
    """The money for a given split of the chores, exactly.

    Returns (cost_of, values, exact). cost_of[i][k] is what the bundle of k costs i in cents,
    None if i cannot take it. values is the matrix that the rent kernel works on, in cents.
    exact[p] is the money p receives, in cents as a Fraction (negative: p pays). It is the
    unique compensation that adds up to zero, leaves nobody envying a bundle they can take, and
    makes the worst-off person as well off as possible among such payments. This is rent-split
    with a total rent of zero. A bundle that a person cannot take is valued at minus a number
    larger than twice the number of people times the sum of all the other costs. No shortest
    path then uses it, and the constraint it adds is looser than any difference between two
    utilities, so that person simply does not envy it. Raises ValueError when some whole
    bundles can be handed round at a lower total cost, because then no payments stop the envy."""
    people = sorted(problem.people)
    n = len(people)
    cost_of = {i: {k: takeable_cost(problem, i, bundles[k]) for k in people} for i in people}
    total_cost = sum(cost_of[p][p] for p in people)
    finite = sum(c for row in cost_of.values() for c in row.values() if c is not None)
    never = 2 * n * (finite + 1)
    values = [
        [Fraction(-never if cost_of[i][k] is None else -cost_of[i][k]) for k in people]
        for i in people
    ]
    dist = shortest_paths(values, list(range(n)))
    utilities = maximin_utilities(dist, Fraction(-total_cost))
    exact = {people[k]: utilities[k] - values[k][k] for k in range(n)}
    for i in range(n):
        for k in range(n):
            takeable = cost_of[people[i]][people[k]] is not None
            if takeable and utilities[i] < values[i][k] + exact[people[k]]:
                raise AssertionError("the exact compensation leaves envy")
    return cost_of, values, exact


def compute_bundle(problem: BundleProblem) -> BundlePlan:
    """Split the chores at the smallest total cost, then settle the money."""
    nobody_can_do(problem)
    find_sharing(problem)
    priority, seed_hex, preimage = bundle_priority(problem)
    units = unit_chores(problem)
    owners = cheapest_split(problem, priority)
    people = sorted(problem.people)
    n = len(people)
    bundles = {p: [chore for chore, owner in zip(units, owners) if owner == p] for p in people}
    cost_of, values, exact = settle_exactly(problem, bundles)
    own = {p: cost_of[p][p] for p in people}
    total_cost = sum(own.values())
    key = "chore-split|" + fc.canonical_json(
        {
            "people": people,
            "chores": sorted(problem.chore_names),
            "units": problem.total_units,
        }
    )
    prices = {people[k]: -exact[people[k]] / 100 for k in range(n)}
    bids = {people[i]: {people[k]: values[i][k] / 100 for k in range(n)} for i in range(n)}
    by_holder = fc.round_min_envy(prices, 0, bids, {p: p for p in people}, key)
    transfer = {p: -by_holder[p] for p in people}
    net = {p: transfer[p] - own[p] for p in people}
    shares = {
        i: {k: None if cost_of[i][k] is None else transfer[k] - cost_of[i][k] for k in people}
        for i in people
    }
    max_envy = max(
        [shares[i][k] - net[i] for i in people for k in people if shares[i][k] is not None]
    )
    if (
        sum(transfer.values()) != 0
        or max_envy > 1
        or any(abs(Fraction(transfer[p]) - exact[p]) >= 1 for p in people)
    ):
        raise AssertionError("rounding left the total off, or an envy above one cent")
    return BundlePlan(
        problem=problem,
        people=people,
        priority=priority,
        seed_hex=seed_hex,
        preimage=preimage,
        bundles=bundles,
        cost=own,
        cost_of=cost_of,
        exact_transfer=exact,
        transfer=transfer,
        net=net,
        shares=shares,
        total_cost=total_cost,
        max_envy=max_envy,
        was_tie=has_tied_split(problem, bundles),
    )


# ---------------------------------------------------------------------------------------
# Plan B: texts (zh is the default, en says the same)
# ---------------------------------------------------------------------------------------

BUNDLE_TEXT = {
    "zh": {
        "title": "分家务结果（包干加补偿）：{people} 人分 {chores}，每周总代价最小",
        "cap_split": "每周分法和补偿（补偿加起来为 0）",
        "hdr_split": ["人", "分到的家务", "件数 / 上限", "自己填的代价", "补偿", "折算后每周"],
        "total": "合计",
        "cell_pay": "付 {amount}",
        "cell_recv": "收 {amount}",
        "cap_shares": (
            "核对表（换成别人那份时每周的折算，按各人自己填的代价算，带 * 的是本人那份，"
            "数越大越划算）"
        ),
        "hdr_person": "人",
        "share_of": "{holder}那份",
        "cant_take": "接不了",
        "why_cannot": "含你做不了的{chores}",
        "why_cap": "有 {k}，超过你的上限 {cap}",
        "unit_1": "{n} 件",
        "unit_n": "{n} 件",
        "why_sep": "，",
        "or_sep": "、",
        "join": "",
        "end": "。",
        "n_rule": (
            "规则（事先定好，结果出来后不再改）：每人有件数上限，有人做不了的家务不分给他。"
            "在这些限制内选每周总代价最小的分法，再用加起来为 0 的补偿，让每个人按自己填的代价"
            "都不想换成别人那份（连同那份的补偿或付出），并且在这样的补偿里让折算后最差的人"
            "尽量好。"
        ),
        "n_total": (
            "每周总代价（各人按自己填的代价算）：{total}。折算后每周最差的是 {names}：{worst}。"
        ),
        "n_total_all": (
            "每周总代价（各人按自己填的代价算）：{total}。折算后每个人每周都是 {worst}。"
        ),
        "n_pot": (
            "付出的人把钱放进公用的钱罐，收的人从里面拿：付出合计 {paid}，收入合计 {received}，"
            "恰好相等，不需要外人出钱。"
        ),
        "n_envy_zero": (
            "取整到分后，没有人羡慕别人那份（最大羡慕 0.00）。补偿只向下或向上取到分，"
            "加起来恰好是 0.00。"
        ),
        "n_envy_some": (
            "取整到分后，最大羡慕是 {amount}：精确值下没有羡慕，这是取整造成的，最多差 0.01。"
            "补偿只向下或向上取到分，加起来恰好是 0.00。"
        ),
        "n_tie_rule": (
            "平局规则：总代价最小的分法可能不止一种。家务按名称的码位顺序排好，一件一件地分，"
            "每一件给平局顺序里最靠前、并且分给他之后仍能得到一种总代价最小的分法的人。"
        ),
        "n_tie_none": "这次总代价最小的分法只有一种，用不上平局规则。",
        "n_tie_seed": (
            "这次有几种总代价相同的分法，已按规则里的公开随机源排出的顺序打破平局。"
            "种子（SHA-256）：{seed}。算法见 fsq_core 的 SEED_SPEC。"
        ),
        "n_tie_names": (
            "这次有几种总代价相同的分法，没有提供公开随机源，按姓名排序打破平局。"
            "想要不偏向名字靠前的人，下次在规则消息里写一个公开随机源。"
        ),
        "n_seed_unused": "规则里给了公开随机源，但这次总代价最小的分法只有一种，用不上。",
        "n_algo": (
            "复算平局顺序：① 种子 = 「种子原像」的 SHA-256（UTF-8）。② 第 c 次取数"
            "（c 从 0 起）= SHA-256（种子 + c 的 8 字节大端）的前 8 字节，按大端读成整数 x。"
            "要取 0 到 n−1 之间的整数时，x 小于 2^64 − (2^64 mod n) 就取 x 除以 n 的余数，否则 c "
            "加 1 重取。③ 名单按码位排序，i 从 n−1 降到 1，每步取一个 0 到 i 之间的整数 j，"
            "交换第 i 位和第 j 位，最后得到的就是平局顺序。整个过程不用 random 模块。"
        ),
        "n_pipe": (
            "表格里的竖线 | 前面被加了一个反斜杠。复算时请用 --json 里的种子原像，"
            "或者群里卡片上的原文，不要从表格里复制。"
        ),
        "n_one_liners": "每人一句话（只发给本人，不要贴到群里）：",
        "n_one_liner": "- {person}：{text}",
        "cap_source": "平局用的随机源与复算",
        "hdr_facts": ["项目", "内容"],
        "f_description": "随机源说明",
        "f_source": "随机源原文（逐字）",
        "f_rule": "规则名",
        "f_units": "每周家务总件数（写进种子，即种子里的 n_slots）",
        "f_people": "名单（按码位排序，写进种子）",
        "f_preimage": "种子原像（对这段文字取 SHA-256）",
        "f_seed": "种子（SHA-256，十六进制）",
        "f_order": "平局顺序（靠前的优先）",
        "nm_cost": ("代价是否如实：脚本只对大家自己填的数做算术，别人看不到你的数，所以无法核对。"),
        "nm_strategy": (
            "防策略：这个方法不防策略。知道别人填什么的人，有时能靠谎报代价让自己折算后更划算。"
        ),
        "nm_additive": (
            "家务之间的关系：一个人的代价按件相加。一起做更省力或更费力、和做的先后有关的情形"
            "不在模型里。"
        ),
        "nm_money": "钱和代价按 1 比 1 折算，没有预算上限，也不考虑一个人手里有多少钱。",
        "nm_ties": (
            "并列的分法：总代价相同的几种分法里，选哪一种按事先定的顺序，不保证对折算后"
            "最差的人最好。"
        ),
        "nm_best": (
            "最差的人是在总代价最小的这一种分法里尽量好，不是在所有分法里最好。换一种总代价"
            "更高的分法，最差的人有时反而更好。"
        ),
        "nm_weeks": "几周之间：这个方案只算一个典型的周，每周重复，不安排几周之间的轮换。",
        "nm_outside": "请外人做家务（比如保洁）的费用：不计算，分摊用 bill-split。",
        "nm_likes": "有人喜欢做的任务：代价不能是负数，喜欢做的任务填 0。",
        "cert_head": "按你自己填的代价，你这份每周的折算是 {net}",
        "cert_plain": "{head}，换成别人那份（连同那份的补偿或付出）都不会更划算",
        "cert_envied": (
            "{head}。取整到分后，{holders}那份比你的多 {amount}，这是取整造成的误差"
            "（精确值下换哪份都不会更划算）"
        ),
        "cert_ties": "；{holders}那份对你来说一样划算（也是 {net}），打平不算吃亏",
        "cert_skipped": "；{holders}那份你接不了，不参与比较",
        "dm_head": "{person}，这是只给你的分家务结果，别人看不到你的代价。",
        "dm_cap": "你的上限是 {cap}。",
        "dm_bundle": "你每周做：{chores}（共 {k}）。按你自己填的代价，这些一共是 {cost}。",
        "dm_bundle_none": "你每周不用做家务。",
        "dm_pay": "补偿：你每周付出 {amount}。",
        "dm_recv": "补偿：你每周收到 {amount}。",
        "dm_even": "补偿：你既不付也不收。",
        "dm_net": "折算后你每周是 {net}。",
        "dm_table_head": (
            "你的核对表（换成这一份时你每周的折算 = 你的代价取负，再加上那份的补偿，"
            "带 * 的是你自己的那份，数越大越划算）："
        ),
        "dm_table_row": "  {holder}那份（{chores}）：{formula} = {net}{star}",
        "dm_table_cant": "  {holder}那份（{chores}）：你接不了（{reason}）",
        "dm_cannot": "你说做不了：{chores}。它们不在你的代价表里，也不会分给你。",
        "dm_sum": "大家的补偿加起来是 0.00，不需要外人出钱。",
        "g_rule": (
            "规则（事先定好，结果出来后不再改）：每人有件数上限，有人做不了的家务不分给他。"
            "在这些限制内选每周总代价最小的分法，再用加起来为 0 的补偿，让每个人按自己填的代价"
            "都不想换成别人那份。"
        ),
        "g_tie_names": (
            "平局规则：总代价最小的分法不止一种时，家务按名称的码位顺序一件一件地分，每一件给"
            "按姓名排序最靠前、并且分给他之后仍有总代价最小的分法的人。"
        ),
        "g_tie_seed": (
            "平局规则：总代价最小的分法不止一种时，家务按名称的码位顺序一件一件地分，每一件给"
            "下面的平局顺序里最靠前、并且分给他之后仍有总代价最小的分法的人。"
        ),
        "g_description": "随机源说明：{text}",
        "g_source": "随机源原文：{text}",
        "g_preimage": "种子原像（对这段文字取 SHA-256 就是种子）：{text}",
        "g_seed": "种子（SHA-256）：{seed}",
        "g_order": "平局顺序：{order}。",
        "g_split_head": "每周分法：",
        "g_split": "{person}：{chores}（{k}，上限 {cap}）",
        "g_split_none": "{person}：（没有分到，上限 {cap}）",
        "g_comp_head": "补偿（加起来为 0）：",
        "g_comp_pay": "{person}付 {amount}",
        "g_comp_recv": "{person}收 {amount}",
        "g_comp_even": "{person}不付也不收",
        "g_sum": (
            "付出合计 {paid}，收入合计 {received}。付出的人把钱放进公用的钱罐，收的人从里面拿，"
            "不需要外人出钱。"
        ),
        "g_guarantee": (
            "保证：按各人私下填的代价，没有人想换成别人那份（连同那份的补偿或付出，"
            "取整到分后最多差 {amount}）。每个人会收到一条只含自己数字的私信，可以自己核对。"
        ),
        "g_limits": (
            "不保证：不防策略。最差的人只是在总代价最小的这一种分法里尽量好。代价按件相加，"
            "钱和代价按 1 比 1 折算。"
        ),
        "g_recompute": (
            "复算：随机源原文、名单、每周家务总件数和规则名都在上面，按种子原像取 SHA-256，"
            "再用计数器洗牌，就得到平局顺序。洗牌的写法见 github.com/YYYJH1/fair-and-square-skills 里 docs/THEORY.md 的 "
            "Public randomness 一节。"
        ),
    },
    "en": {
        "title": (
            "Chore split (bundles with compensation): {people} people, {chores}, "
            "smallest weekly total cost"
        ),
        "cap_split": "The weekly split and the compensation (the compensation adds up to zero)",
        "hdr_split": ["Person", "Chores", "Count / cap", "Own cost", "Compensation", "Weekly net"],
        "total": "Total",
        "cell_pay": "pays {amount}",
        "cell_recv": "receives {amount}",
        "cap_shares": (
            "Check table (the weekly net if the person took another share, by their own costs; "
            "* marks their own share, higher is better)"
        ),
        "hdr_person": "Person",
        "share_of": "{holder}'s share",
        "cant_take": "cannot take",
        "why_cannot": "it holds {chores}, which you cannot do",
        "why_cap": "it has {k}, over your cap of {cap}",
        "unit_1": "{n} unit",
        "unit_n": "{n} units",
        "why_sep": ", and ",
        "or_sep": " or ",
        "join": " ",
        "end": ".",
        "n_rule": (
            "Rules (fixed in advance, not changed after the result): everybody has a cap on the "
            "number of chores, and nobody is given a chore they cannot do. Within those limits "
            "the script takes the split with the smallest weekly total cost. Then payments "
            "that add up to zero make sure that nobody, by their own costs, would rather have "
            "another person's share (with the payment that goes with it), and among such "
            "payments the worst-off person is as well off as possible."
        ),
        "n_total": (
            "Total weekly cost (each person's own costs): {total}. The worst off after the "
            "compensation is {names}, with {worst} a week."
        ),
        "n_total_all": (
            "Total weekly cost (each person's own costs): {total}. After the compensation "
            "everybody comes to {worst} a week."
        ),
        "n_pot": (
            "The people who pay put the money into a common pot and the people who receive take "
            "theirs from it: {paid} is paid in and {received} is taken out, which is exactly "
            "equal, so nobody outside has to pay."
        ),
        "n_envy_zero": (
            "After rounding to the cent nobody envies another share (largest envy 0.00). The "
            "payments are rounded down or up to a cent and add up to exactly 0.00."
        ),
        "n_envy_some": (
            "After rounding to the cent the largest envy is {amount}. At the exact values there "
            "is no envy, so this comes from rounding and is at most 0.01. The payments are "
            "rounded down or up to a cent and add up to exactly 0.00."
        ),
        "n_tie_rule": (
            "Tie rule: more than one split can have the smallest total cost. The chores are "
            "put in the order of their names (code point order) and given out one unit at a "
            "time. Each goes to the person who comes first in the tie order and for whom a "
            "split with the smallest total cost is still possible."
        ),
        "n_tie_none": "This time only one split has the smallest total cost, so the tie rule is not used.",
        "n_tie_seed": (
            "Several splits have the same smallest total cost this time. The tie was settled by "
            "the order drawn from the public random source in the rules. Seed (SHA-256): "
            "{seed}. The algorithm is SEED_SPEC in fsq_core."
        ),
        "n_tie_names": (
            "Several splits have the same smallest total cost this time and no public random "
            "source was given, so the tie was settled by the order of the names. To avoid "
            "favouring early names, put a public random source in the rules message next time."
        ),
        "n_seed_unused": (
            "The rules name a public random source, but only one split has the smallest total "
            "cost this time, so it is not used."
        ),
        "n_algo": (
            "How to recompute the tie order: (1) seed = SHA-256 of the seed preimage (UTF-8). "
            "(2) Draw number c (counting from 0) = the first 8 bytes, big-endian, of "
            "SHA-256(seed + c as 8 big-endian bytes), read as an integer x. For an integer in "
            "0..n-1, take x mod n if x < 2^64 - (2^64 mod n), otherwise add 1 to c and draw "
            "again. (3) Sort the names by code point, go i from n-1 down to 1, draw an integer j "
            "in 0..i and swap positions i and j. The result is the tie order. The random module "
            "is never used."
        ),
        "n_pipe": (
            "A backslash was added before each | in the tables. To recompute, use the seed "
            "preimage in the --json output or the text on the group card, not a copy from a "
            "table."
        ),
        "n_one_liners": "One line per person (send it to that person only, not to the group):",
        "n_one_liner": "- {person}: {text}",
        "cap_source": "Random source for ties and how to recompute",
        "hdr_facts": ["Item", "Value"],
        "f_description": "Where the source comes from",
        "f_source": "Source text (verbatim)",
        "f_rule": "Rule name",
        "f_units": "Chore units per week (part of the seed, the n_slots of the seed)",
        "f_people": "Names (sorted by code point, part of the seed)",
        "f_preimage": "Seed preimage (take the SHA-256 of this text)",
        "f_seed": "Seed (SHA-256, hex)",
        "f_order": "Tie order (earlier comes first)",
        "nm_cost": (
            "Whether the costs are honest: the script only does arithmetic on the numbers the "
            "people gave, and nobody sees another person's numbers, so it cannot check them."
        ),
        "nm_strategy": (
            "Strategy-proofness: this method is not strategy-proof. A person who knows what the "
            "others entered can sometimes end up better off by misreporting their costs."
        ),
        "nm_additive": (
            "How chores relate: a person's cost is the sum over their chores. Chores that are "
            "easier or harder together, or that depend on the order, are not modeled."
        ),
        "nm_money": (
            "Money and cost trade one for one, there is no budget limit, and how much money a "
            "person already has does not matter."
        ),
        "nm_ties": (
            "Tied splits: when several splits have the same total cost, the order fixed in "
            "advance picks one of them. That one is not guaranteed to be the best for the "
            "worst-off person."
        ),
        "nm_best": (
            "The worst-off person is as well off as possible within the one split of smallest "
            "total cost, not among all splits. A split with a higher total cost sometimes "
            "leaves the worst-off person better off."
        ),
        "nm_weeks": (
            "Across weeks: this plan settles one typical week and repeats it. It does not "
            "rotate anything between weeks."
        ),
        "nm_outside": "What an outside cleaner costs: not calculated. Use bill-split to share that.",
        "nm_likes": (
            "Tasks that somebody likes: costs cannot be negative, so enter 0 for a task that "
            "somebody likes."
        ),
        "cert_head": "By your own costs, your share comes to {net} a week",
        "cert_plain": (
            "{head}, and no other share (with the payment that goes with it) is a better deal "
            "for you"
        ),
        "cert_envied": (
            "{head}. After rounding to the cent, the share of {holders} would be {amount} better "
            "for you than yours. That is a rounding error (at the exact values no other share "
            "is a better deal)"
        ),
        "cert_ties": (
            ". The share of {holders} would be exactly as good a deal for you (also {net}), "
            "and a tie is not a loss"
        ),
        "cert_skipped": ". You cannot take the share of {holders}, so it is not compared",
        "dm_head": "{person}, this is your own chore result. Nobody else sees your costs.",
        "dm_cap": "Your cap is {cap}.",
        "dm_bundle": (
            "Your chores each week: {chores} ({k} in all). By your own costs they come to {cost}."
        ),
        "dm_bundle_none": "You do no chores each week.",
        "dm_pay": "Compensation: you pay {amount} a week.",
        "dm_recv": "Compensation: you receive {amount} a week.",
        "dm_even": "Compensation: you neither pay nor receive.",
        "dm_net": "After the compensation your week comes to {net}.",
        "dm_table_head": (
            "Your check table (your weekly net if you took that share = minus your cost, plus "
            "the payment that goes with it; * marks your own share, higher is better):"
        ),
        "dm_table_row": "  {holder}'s share ({chores}): {formula} = {net}{star}",
        "dm_table_cant": "  {holder}'s share ({chores}): you cannot take it ({reason})",
        "dm_cannot": (
            "You said you cannot do: {chores}. They are not in your costs and will not be "
            "given to you."
        ),
        "dm_sum": "Everybody's payments add up to 0.00, so nobody outside has to pay.",
        "g_rule": (
            "Rules (fixed in advance, not changed after the result): everybody has a cap on the "
            "number of chores, and nobody is given a chore they cannot do. Within those limits "
            "the split with the smallest weekly total cost is taken. Then payments that add up "
            "to zero make sure that nobody, by their own costs, would rather have another "
            "person's share."
        ),
        "g_tie_names": (
            "Tie rule: when more than one split has the smallest total cost, the chores are "
            "given out one unit at a time in the order of their names. Each goes to the person "
            "who comes first in the order of the names and for whom a split with the smallest "
            "total cost is still possible."
        ),
        "g_tie_seed": (
            "Tie rule: when more than one split has the smallest total cost, the chores are "
            "given out one unit at a time in the order of their names. Each goes to the person "
            "who comes first in the tie order below and for whom a split with the smallest "
            "total cost is still possible."
        ),
        "g_description": "Where the source comes from: {text}",
        "g_source": "Source text: {text}",
        "g_preimage": "Seed preimage (the SHA-256 of this text is the seed): {text}",
        "g_seed": "Seed (SHA-256): {seed}",
        "g_order": "Tie order: {order}.",
        "g_split_head": "The weekly split:",
        "g_split": "{person}: {chores} ({k}, cap {cap})",
        "g_split_none": "{person}: (none, cap {cap})",
        "g_comp_head": "Compensation (adds up to zero):",
        "g_comp_pay": "{person} pays {amount}",
        "g_comp_recv": "{person} receives {amount}",
        "g_comp_even": "{person} neither pays nor receives",
        "g_sum": (
            "{paid} is paid in and {received} is taken out. The people who pay put the money "
            "into a common pot and the people who receive take theirs from it, so nobody "
            "outside has to pay."
        ),
        "g_guarantee": (
            "Guarantee: by the costs each person gave in private, nobody would rather have "
            "another person's share (with the payment that goes with it). After rounding to the "
            "cent, the most anybody would gain by swapping is {amount}. Everybody gets a "
            "private message with only their own numbers so they can check."
        ),
        "g_limits": (
            "Not guaranteed: the method is not strategy-proof. The worst-off person is only as "
            "well off as possible within the one split of smallest total cost. A person's cost "
            "is the sum over their chores, and money and cost trade one for one."
        ),
        "g_recompute": (
            "Recompute: the source text, the names, the chore units per week and the rule name "
            "are above. Take the SHA-256 of the seed preimage and shuffle with the counter to "
            "get the tie order. The shuffle is specified under Public randomness in "
            "docs/THEORY.md of github.com/YYYJH1/fair-and-square-skills."
        ),
    },
}


def bsay(lang: str, key: str, **values: Any) -> str:
    """Fill the plan B text template of this key (see fsq_core.fill_text for Latin names)."""
    return fc.fill_text(lang, BUNDLE_TEXT[lang][key], **values)


def units_text(lang: str, n: int) -> str:
    """A number of chore units with its noun: '1 unit', '3 units', '3 件'."""
    return BUNDLE_TEXT[lang][f"unit_{1 if n == 1 else 'n'}"].format(n=n)


# ---------------------------------------------------------------------------------------
# Plan B: the result
# ---------------------------------------------------------------------------------------

fmt = fc.fmt_cents


def exact_text(cents: Fraction) -> str:
    """An amount given in cents, as a decimal in units ('-25.00') or a fraction ('-55/3')."""
    if cents.denominator == 1:
        return fmt(int(cents))
    units = cents / 100
    return f"{units.numerator}/{units.denominator}"


def bundle_chores(lang: str, plan: BundlePlan, person: str) -> str:
    """The chores of a person's bundle, or the word for none."""
    chores = plan.bundles[person]
    return chore_list(lang, chores) if chores else TEXT[lang]["nothing"]


def holders_text(lang: str, holders: Sequence[str]) -> str:
    return BUNDLE_TEXT[lang]["or_sep"].join(holders)


def formula_text(cost: int, transfer: int) -> str:
    """Minus the cost, plus the money received or minus the money paid: '-25.00 - 20.00'."""
    head = "-" + fmt(cost) if cost else fmt(0)
    if transfer < 0:
        return f"{head} - {fmt(-transfer)}"
    return f"{head} + {fmt(transfer)}"


def compare_shares(plan: BundlePlan, person: str) -> tuple:
    """(tied, envied, skipped, gap): the other bundles that are as good for the person as their
    own, that look better by `gap` cents only because of rounding, and that they cannot take."""
    mine = plan.net[person]
    tied, envied, skipped = [], [], []
    for holder in plan.people:
        value = plan.shares[person][holder]
        if holder == person:
            continue
        if value is None:
            skipped.append(holder)
        elif value == mine:
            tied.append(holder)
        elif value > mine:
            envied.append(holder)
    gap = max((plan.shares[person][holder] - mine for holder in envied), default=0)
    return tied, envied, skipped, gap


def reason_text(lang: str, plan: BundlePlan, person: str, holder: str) -> str:
    """Why the person cannot take the holder's bundle."""
    problem = plan.problem
    reasons = []
    blocked = sorted({c for c in plan.bundles[holder] if c not in problem.costs[person]})
    if blocked:
        names = joined(lang, [quoted(lang, c) for c in blocked])
        reasons.append(bsay(lang, "why_cannot", chores=names))
    if len(plan.bundles[holder]) > problem.caps[person]:
        reasons.append(
            bsay(
                lang,
                "why_cap",
                k=units_text(lang, len(plan.bundles[holder])),
                cap=units_text(lang, problem.caps[person]),
            )
        )
    return BUNDLE_TEXT[lang]["why_sep"].join(reasons)


def bundle_certificate(plan: BundlePlan, person: str, lang: str) -> str:
    """The one-sentence certificate of a person, in the person's own numbers."""
    text = BUNDLE_TEXT[lang]
    tied, envied, skipped, gap = compare_shares(plan, person)
    head = bsay(lang, "cert_head", net=fmt(plan.net[person]))
    if envied:
        out = bsay(
            lang, "cert_envied", head=head, holders=holders_text(lang, envied), amount=fmt(gap)
        )
    else:
        out = bsay(lang, "cert_plain", head=head)
    if tied:
        out += bsay(lang, "cert_ties", holders=holders_text(lang, tied), net=fmt(plan.net[person]))
    if skipped:
        out += bsay(lang, "cert_skipped", holders=holders_text(lang, skipped))
    return out + text["end"]


def transfer_cell(lang: str, transfer: int) -> str:
    if transfer > 0:
        return bsay(lang, "cell_recv", amount=fmt(transfer))
    if transfer < 0:
        return bsay(lang, "cell_pay", amount=fmt(-transfer))
    return fmt(0)


def split_table(plan: BundlePlan, lang: str) -> fc.Table:
    text = BUNDLE_TEXT[lang]
    problem = plan.problem
    rows = [
        [
            person,
            bundle_chores(lang, plan, person),
            f"{len(plan.bundles[person])} / {problem.caps[person]}",
            fmt(plan.cost[person]),
            transfer_cell(lang, plan.transfer[person]),
            fmt(plan.net[person]),
        ]
        for person in plan.people
    ]
    rows.append(
        [
            text["total"],
            "",
            str(problem.total_units),
            fmt(plan.total_cost),
            fmt(sum(plan.transfer.values())),
            fmt(sum(plan.net.values())),
        ]
    )
    return fc.Table(text["hdr_split"], rows, text["cap_split"])


def shares_table(plan: BundlePlan, lang: str) -> fc.Table:
    text = BUNDLE_TEXT[lang]
    header = [text["hdr_person"]] + [bsay(lang, "share_of", holder=h) for h in plan.people]
    rows = []
    for person in plan.people:
        cells = [person]
        for holder in plan.people:
            value = plan.shares[person][holder]
            if value is None:
                cells.append(text["cant_take"])
            else:
                cells.append(fmt(value) + ("*" if holder == person else ""))
        rows.append(cells)
    return fc.Table(header, rows, text["cap_shares"])


def source_facts_table(plan: BundlePlan, lang: str) -> fc.Table:
    text = BUNDLE_TEXT[lang]
    problem = plan.problem
    rows = []
    if problem.description:
        rows.append([text["f_description"], problem.description])
    rows += [
        [text["f_source"], problem.source],
        [text["f_rule"], BUNDLE_RULE_NAME],
        [text["f_units"], str(problem.total_units)],
        [text["f_people"], ", ".join(sorted(problem.people))],
        [text["f_preimage"], plan.preimage],
        [text["f_seed"], plan.seed_hex],
        [text["f_order"], joined(lang, plan.priority)],
    ]
    return fc.Table(text["hdr_facts"], rows, text["cap_source"])


def pot_totals(plan: BundlePlan) -> tuple:
    """(paid in, taken out): the money the payers hand over and the money the receivers take."""
    paid = sum(-t for t in plan.transfer.values() if t < 0)
    received = sum(t for t in plan.transfer.values() if t > 0)
    return paid, received


def bundle_notes(plan: BundlePlan, lang: str) -> list:
    """Paragraphs under the tables: the rules, the totals, rounding, ties, recomputing."""
    problem = plan.problem
    worst = min(plan.net.values())
    names = [person for person in plan.people if plan.net[person] == worst]
    paid, received = pot_totals(plan)
    if len(names) == len(plan.people):
        total_note = bsay(lang, "n_total_all", total=fmt(plan.total_cost), worst=fmt(worst))
    else:
        total_note = bsay(
            lang,
            "n_total",
            total=fmt(plan.total_cost),
            names=joined(lang, names),
            worst=fmt(worst),
        )
    notes = [
        bsay(lang, "n_rule"),
        total_note,
        bsay(lang, "n_pot", paid=fmt(paid), received=fmt(received)),
    ]
    if plan.max_envy:
        notes.append(bsay(lang, "n_envy_some", amount=fmt(plan.max_envy)))
    else:
        notes.append(bsay(lang, "n_envy_zero"))
    notes.append(bsay(lang, "n_tie_rule"))
    if plan.was_tie:
        notes.append(
            bsay(lang, "n_tie_seed", seed=plan.seed_hex)
            if problem.source is not None
            else bsay(lang, "n_tie_names")
        )
    else:
        notes.append(bsay(lang, "n_seed_unused" if problem.source is not None else "n_tie_none"))
    if problem.source is not None:
        if "|" in plan.preimage:
            notes.append(bsay(lang, "n_pipe"))
        notes.append(bsay(lang, "n_algo"))
    lines = [bsay(lang, "n_one_liners")]
    lines += [
        bsay(lang, "n_one_liner", person=person, text=bundle_certificate(plan, person, lang))
        for person in plan.people
    ]
    notes.append("\n".join(lines))
    return notes


def bundle_not_modeled(lang: str) -> list:
    keys = (
        "nm_cost",
        "nm_strategy",
        "nm_additive",
        "nm_money",
        "nm_ties",
        "nm_best",
        "nm_weeks",
        "nm_outside",
        "nm_likes",
    )
    return [BUNDLE_TEXT[lang][key] for key in keys]


def bundle_person_lines(plan: BundlePlan, lang: str) -> dict:
    """The private message of every person: their own bundle and their own numbers only."""
    problem = plan.problem
    lines: dict = {}
    for person in plan.people:
        bundle = plan.bundles[person]
        rows = [
            bsay(lang, "dm_head", person=person),
            bsay(lang, "dm_cap", cap=units_text(lang, problem.caps[person])),
        ]
        if bundle:
            rows.append(
                bsay(
                    lang,
                    "dm_bundle",
                    chores=bundle_chores(lang, plan, person),
                    k=units_text(lang, len(bundle)),
                    cost=fmt(plan.cost[person]),
                )
            )
        else:
            rows.append(bsay(lang, "dm_bundle_none"))
        transfer = plan.transfer[person]
        if transfer > 0:
            rows.append(bsay(lang, "dm_recv", amount=fmt(transfer)))
        elif transfer < 0:
            rows.append(bsay(lang, "dm_pay", amount=fmt(-transfer)))
        else:
            rows.append(bsay(lang, "dm_even"))
        rows.append(bsay(lang, "dm_net", net=fmt(plan.net[person])))
        rows.append(bundle_certificate(plan, person, lang))
        rows.append(bsay(lang, "dm_table_head"))
        for holder in plan.people:
            chores = bundle_chores(lang, plan, holder)
            value = plan.shares[person][holder]
            if value is None:
                reason = reason_text(lang, plan, person, holder)
                rows.append(
                    bsay(lang, "dm_table_cant", holder=holder, chores=chores, reason=reason)
                )
            else:
                rows.append(
                    bsay(
                        lang,
                        "dm_table_row",
                        holder=holder,
                        chores=chores,
                        formula=formula_text(plan.cost_of[person][holder], plan.transfer[holder]),
                        net=fmt(value),
                        star="*" if holder == person else "",
                    )
                )
        if problem.cannot[person]:
            names = joined(lang, [quoted(lang, c) for c in problem.cannot[person]])
            rows.append(bsay(lang, "dm_cannot", chores=names))
        rows.append(bsay(lang, "dm_sum"))
        lines[person] = rows
    return lines


def bundle_group_lines(plan: BundlePlan, lang: str) -> list:
    """The card for the group chat: the split and the payments. No cost and no net."""
    problem = plan.problem
    seeded = problem.source is not None
    lines = [bsay(lang, "g_rule"), bsay(lang, "g_tie_seed" if seeded else "g_tie_names")]
    if seeded:
        if problem.description:
            lines.append(bsay(lang, "g_description", text=problem.description))
        lines += [
            bsay(lang, "g_source", text=problem.source),
            bsay(lang, "g_preimage", text=plan.preimage),
            bsay(lang, "g_seed", seed=plan.seed_hex),
            bsay(lang, "g_order", order=joined(lang, plan.priority)),
        ]
    lines.append(bsay(lang, "g_split_head"))
    for person in plan.people:
        bundle = plan.bundles[person]
        if bundle:
            lines.append(
                bsay(
                    lang,
                    "g_split",
                    person=person,
                    chores=bundle_chores(lang, plan, person),
                    k=units_text(lang, len(bundle)),
                    cap=problem.caps[person],
                )
            )
        else:
            lines.append(bsay(lang, "g_split_none", person=person, cap=problem.caps[person]))
    lines.append(bsay(lang, "g_comp_head"))
    for person in plan.people:
        transfer = plan.transfer[person]
        if transfer > 0:
            lines.append(bsay(lang, "g_comp_recv", person=person, amount=fmt(transfer)))
        elif transfer < 0:
            lines.append(bsay(lang, "g_comp_pay", person=person, amount=fmt(-transfer)))
        else:
            lines.append(bsay(lang, "g_comp_even", person=person))
    paid, received = pot_totals(plan)
    lines.append(bsay(lang, "g_sum", paid=fmt(paid), received=fmt(received)))
    lines.append(bsay(lang, "g_guarantee", amount=fmt(plan.max_envy)))
    lines.append(bsay(lang, "g_limits"))
    if seeded:
        lines.append(bsay(lang, "g_recompute"))
    return lines


def bundle_echo(plan: BundlePlan) -> dict:
    problem = plan.problem
    echo: dict = {
        "plan": PLAN_BUNDLE,
        "participants": list(plan.people),
        "chores": [{"name": name, "units": units} for name, units in sorted(problem.chores)],
        "total_units": problem.total_units,
        "costs": {
            person: {chore: fc.Cents(cost) for chore, cost in sorted(problem.costs[person].items())}
            for person in plan.people
        },
        "caps": {person: problem.caps[person] for person in plan.people},
    }
    cannot = {person: list(c) for person, c in sorted(problem.cannot.items()) if c}
    if cannot:
        echo["cannot"] = cannot
    if problem.source is not None:
        echo["random_source"] = problem.source
        if problem.description:
            echo["source_description"] = problem.description
    return echo


def bundle_result_json(plan: BundlePlan) -> dict:
    problem = plan.problem
    worst = min(plan.net.values())
    paid, received = pot_totals(plan)
    if not plan.was_tie:
        method = "not_needed"
    else:
        method = "random_source" if problem.source is not None else "sorted_names"
    return {
        "plan": PLAN_BUNDLE,
        "bundles": {person: list(plan.bundles[person]) for person in plan.people},
        "cost_cents": {person: fc.Cents(plan.cost[person]) for person in plan.people},
        "transfer_cents": {person: fc.Cents(plan.transfer[person]) for person in plan.people},
        "net_cents": {person: fc.Cents(plan.net[person]) for person in plan.people},
        "exact_net": {
            person: exact_text(plan.exact_transfer[person] - plan.cost[person])
            for person in plan.people
        },
        "total_cost_cents": fc.Cents(plan.total_cost),
        "paid_in_cents": fc.Cents(paid),
        "taken_out_cents": fc.Cents(received),
        "worst_off": {
            "people": [person for person in plan.people if plan.net[person] == worst],
            "net_cents": fc.Cents(worst),
        },
        "max_envy_cents": fc.Cents(plan.max_envy),
        "tie_break": {
            "was_tie": plan.was_tie,
            "method": method,
            "rule": BUNDLE_RULE_NAME if problem.source is not None else None,
            "seed_hex": plan.seed_hex,
            "order": list(plan.priority),
        },
    }


def bundle_certificate_json(plan: BundlePlan, lang: str) -> dict:
    problem = plan.problem
    certificate: dict = {
        "share_table": {
            person: {
                holder: None
                if plan.shares[person][holder] is None
                else fc.Cents(plan.shares[person][holder])
                for holder in plan.people
            }
            for person in plan.people
        },
        "one_liner": {person: bundle_certificate(plan, person, lang) for person in plan.people},
        "ties": {person: compare_shares(plan, person)[0] for person in plan.people},
        "cannot_take": {person: compare_shares(plan, person)[2] for person in plan.people},
    }
    if problem.source is not None:
        certificate["recompute"] = {
            "source_text": problem.source,
            "algorithm": fc.SEED_SPEC,
            "seed_hex": plan.seed_hex,
        }
    return certificate


def build_bundle_result(plan: BundlePlan, lang: str = "zh", reproduce: str = "") -> fc.Result:
    """Turn a plan of bundle_pay into the shared Result (md, dm, group and json come from it)."""
    if lang not in BUNDLE_TEXT:
        raise ValueError(f"lang must be one of {', '.join(BUNDLE_TEXT)}")
    problem = plan.problem
    tables = [split_table(plan, lang), shares_table(plan, lang)]
    if problem.source is not None:
        tables.append(source_facts_table(plan, lang))
    return fc.Result(
        title=bsay(
            lang,
            "title",
            people=len(plan.people),
            chores=quantity(lang, "q_chores", problem.total_units),
        ),
        inputs_echo=bundle_echo(plan),
        result=bundle_result_json(plan),
        certificate=bundle_certificate_json(plan, lang),
        not_modeled=bundle_not_modeled(lang),
        reproduce=reproduce,
        tables=tables,
        notes=bundle_notes(plan, lang),
        person_lines=bundle_person_lines(plan, lang),
        group_lines=bundle_group_lines(plan, lang),
    )


# ---------------------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------------------

# The scores the recorded example was first computed with. The rankings of DEMO_JSON are the ones
# these scores imply. They are used only to check the recorded totals.
RECORDED_SCORES = {
    "阿明": {"洗碗": 6, "倒垃圾": 1, "拖地": 4, "刷厕所": 9, "做饭": 2, "擦窗": 5},
    "小红": {"洗碗": 3, "倒垃圾": 2, "拖地": 5, "刷厕所": 8, "做饭": 9, "擦窗": 4},
    "大刘": {"洗碗": 7, "倒垃圾": 3, "拖地": 2, "刷厕所": 6, "做饭": 5, "擦窗": 8},
}
RECORDED_PICKS = [
    ("阿明", "倒垃圾"),
    ("小红", "洗碗"),
    ("大刘", "拖地"),
    ("阿明", "做饭"),
    ("小红", "擦窗"),
    ("大刘", "刷厕所"),
]


def brute_force_ef1(own: dict, other: dict, ranking: Sequence[str], top: int = 2) -> tuple:
    """(envy-free, EF1) for every integer cost from 0 to top that fits the ranking, by trying
    them all. A chore the person cannot do costs more than anything else."""
    big = 10**6
    answer = [True, True]

    def fill(index: int, floor: int, cost: dict) -> None:
        if index == len(ranking):
            mine = sum(units * cost[c] for c, units in own.items())
            theirs = sum(units * cost.get(c, big) for c, units in other.items())
            answer[0] = answer[0] and mine <= theirs
            if any(own.values()):
                best = min(mine - cost[c] for c, units in own.items() if units)
                answer[1] = answer[1] and best <= theirs
            return
        for value in range(floor, top + 1):
            cost[ranking[index]] = value
            fill(index + 1, value, cost)

    fill(0, 0, {})
    return answer[0], answer[1]


def selftest_checks() -> list:
    """Checks for --selftest: the recorded example, the guarantee against brute force and the
    rules of the script."""

    def demo_data() -> dict:
        return fc.parse_input(DEMO_JSON)

    def recorded_example() -> None:
        plan = compute(parse_problem(demo_data()))
        week = plan.weeks[0]
        fc.expect(week.order == ["阿明", "小红", "大刘"], f"pick order {week.order}")
        picks = [(pick.person, pick.chore) for pick in week.picks]
        fc.expect(picks == RECORDED_PICKS, f"picks {picks}")
        fc.expect(plan.ef1_holds and plan.n_comparisons_failed == 0, "EF1 on the recorded example")
        totals = {
            person: sum(RECORDED_SCORES[person][c] for c in week.bundles[person])
            for person in week.order
        }
        fc.expect(totals == {"阿明": 3, "小红": 7, "大刘": 8}, f"dislike totals {totals}")
        for person in week.order:
            for other in week.order:
                if other != person:
                    own = totals[person]
                    theirs = sum(RECORDED_SCORES[person][c] for c in week.bundles[other])
                    fc.expect(own <= theirs, f"{person} envies {other} under the recorded scores")

    def preimage_hashes_to_the_seed() -> None:
        plan = compute(parse_problem(demo_data()))
        digest = hashlib.sha256(plan.preimage.encode("utf-8")).hexdigest()
        fc.expect(digest == plan.seed_hex, "the printed preimage must hash to the seed")

    def random_instances(count: int, allow_cannot: bool) -> None:
        label = "with cannot" if allow_cannot else "without cannot"
        stream = fc.SeedStream(fc.make_seed("chore_split_selftest", [label], count, "selftest"))
        for _ in range(count):
            people = [f"p{i}" for i in range(2 + stream.below(3))]
            chores = [f"c{i}" for i in range(1 + stream.below(5))]
            units = [1 + stream.below(2) for _ in chores]
            cannot: dict = {p: [] for p in people}
            if allow_cannot:
                for p in people:
                    cannot[p] = [c for c in chores if stream.below(4) == 0]
                for c in chores:
                    if all(c in cannot[p] for p in people):
                        cannot[people[stream.below(len(people))]].remove(c)
            rankings = {}
            for p in people:
                options = [c for c in chores if c not in cannot[p]]
                rankings[p] = fc.shuffle(options, stream)
            data = {
                "people": people,
                "chores": [{"name": c, "units": u} for c, u in zip(chores, units)],
                "rankings": rankings,
                "cannot": cannot,
                "weeks": 1 + stream.below(3),
                "rules": {"random_source": f"selftest {stream.below(10**6)}"},
            }
            plan = compute(parse_problem(data))
            for week in plan.weeks:
                taken = counts_of([c for p in week.order for c in week.bundles[p]])
                fc.expect(taken == dict(zip(chores, units)), "every unit is taken exactly once")
            fc.expect(plan.n_comparisons_failed == 0, "a round-by-round comparison failed")
            for check in plan.checks:
                week = plan.weeks[check.week - 1]
                ranking = plan.problem.rankings[check.person]
                own = counts_of(week.bundles[check.person])
                other = counts_of(week.bundles[check.other])
                free, ef1 = brute_force_ef1(own, other, ranking)
                got = check.status
                if free:
                    fc.expect(got in (STATUS_FREE, STATUS_EXEMPT), f"{got}, brute force says free")
                elif ef1:
                    fc.expect(got == STATUS_EF1, f"{got}, brute force says EF1 only")
                else:
                    fc.expect(got == STATUS_FAILS, f"{got}, brute force says EF1 fails")
            if not allow_cannot:
                fc.expect(plan.ef1_holds, "EF1 must hold when nobody has a cannot list")

    def ef1_without_cannot() -> None:
        random_instances(60, False)

    def ef1_with_cannot() -> None:
        random_instances(60, True)

    def rotation() -> None:
        data = demo_data()
        data["weeks"] = 4
        plan = compute(parse_problem(data))
        base = plan.base_order
        for week in plan.weeks:
            shift = (week.number - 1) % 3
            fc.expect(week.order == base[shift:] + base[:shift], f"week {week.number} order")
        data["rules"]["rotate"] = "none"
        plan = compute(parse_problem(data))
        fc.expect(all(week.order == plan.base_order for week in plan.weeks), "no rotation")

    def listing_order_is_irrelevant() -> None:
        data = demo_data()
        first = fc.envelope(solve(data))
        data["people"] = list(reversed(data["people"]))
        data["rankings"] = dict(reversed(list(data["rankings"].items())))
        fc.expect(fc.envelope(solve(data)) == first, "listing order changed the result")

    def liked_task_is_refused() -> None:
        data = demo_data()
        data["likes"] = {"小红": ["做饭"]}
        try:
            parse_problem(data)
        except fc.InputError as err:
            fc.expect(err.field == "likes.小红" and "only chores" in err.message, err.message)
            return
        raise AssertionError("a liked task was accepted")

    def nobody_can_do_a_chore() -> None:
        data = demo_data()
        data["cannot"] = {"阿明": ["做饭"], "小红": ["做饭"], "大刘": ["做饭"]}
        for person in data["people"]:
            data["rankings"][person].remove("做饭")
        try:
            compute(parse_problem(data))
        except fc.NoSolution:
            return
        raise AssertionError("a chore nobody can do was accepted")

    def rankings_must_be_permutations() -> None:
        for broken in (
            ["倒垃圾", "做饭", "拖地", "擦窗", "洗碗"],
            ["倒垃圾", "做饭", "拖地", "擦窗", "洗碗", "洗碗"],
            ["倒垃圾", "做饭", "拖地", "擦窗", "洗碗", "刷厕所", "遛狗"],
        ):
            data = demo_data()
            data["rankings"]["阿明"] = broken
            try:
                parse_problem(data)
            except fc.InputError as err:
                fc.expect(err.field.startswith("rankings.阿明"), err.field)
            else:
                raise AssertionError(f"accepted the ranking {broken}")

    def texts_match() -> None:
        fc.expect(set(TEXT["zh"]) == set(TEXT["en"]), "zh and en text keys differ")

    def every_output_renders() -> None:
        data = demo_data()
        data["weeks"] = 2
        for lang in fc.LANGS:
            result = solve(data, lang)
            for fmt in fc.FORMATS:
                fc.expect(bool(fc.render(result, fmt, False, lang)), f"{fmt} {lang}")
            fc.expect(bool(fc.render(result, "md", True, lang)), f"json {lang}")

    return [
        ("recorded example: picks, totals 3 7 8, nobody envies anybody", recorded_example),
        ("seed preimage hashes to the seed", preimage_hashes_to_the_seed),
        ("EF1 against brute force, no cannot lists", ef1_without_cannot),
        ("EF1 detection against brute force, with cannot lists", ef1_with_cannot),
        ("the start order rotates as declared", rotation),
        ("listing order is irrelevant", listing_order_is_irrelevant),
        ("a liked task is refused", liked_task_is_refused),
        ("a chore nobody can do has no solution", nobody_can_do_a_chore),
        ("rankings must be permutations", rankings_must_be_permutations),
        ("zh and en texts have the same keys", texts_match),
        ("every output renders", every_output_renders),
    ] + bundle_selftest_checks()


def brute_force_split(problem: BundleProblem, priority: Sequence[str]) -> tuple:
    """(smallest total cost or None, its canonical split, number of different cheapest splits).

    Tries every way to give out the units, and takes the cheapest ones that respect the caps
    and the cannot lists. The canonical split is the one whose owners, read unit by unit in
    the order of unit_chores, come first in priority. A split is the sorted chores of each
    person, so units of one chore that are swapped between two people are not different."""
    units = unit_chores(problem)
    rank = {person: place for place, person in enumerate(priority)}
    best_cost = None
    best_owners: list = []
    for owners in itertools.product(priority, repeat=len(units)):
        if any(owners.count(p) > problem.caps[p] for p in priority):
            continue
        if any(chore not in problem.costs[o] for chore, o in zip(units, owners)):
            continue
        cost = sum(problem.costs[o][chore] for chore, o in zip(units, owners))
        if best_cost is None or cost < best_cost:
            best_cost, best_owners = cost, [owners]
        elif cost == best_cost:
            best_owners.append(owners)
    if best_cost is None:
        return None, None, 0

    def split_of(owners: Sequence[str]) -> frozenset:
        return frozenset(
            (p, tuple(sorted(c for c, o in zip(units, owners) if o == p))) for p in priority
        )

    first = min(best_owners, key=lambda owners: [rank[o] for o in owners])
    return best_cost, split_of(first), len({split_of(owners) for owners in best_owners})


def bundle_selftest_checks() -> list:
    """Checks of plan bundle_pay for --selftest: the recorded example, the cheapest split against
    brute force, the counterexample to a global maximin, and the rules of the script."""

    def demo_data() -> dict:
        return fc.parse_input(BUNDLE_DEMO_JSON)

    def recorded_example() -> None:
        plan = compute(parse_problem(demo_data()))
        fc.expect(plan.total_cost == 13500, f"total cost {plan.total_cost}")
        fc.expect(plan.was_tie, "the recorded example has two splits of the smallest cost")
        expected = {
            "阿明": ["倒垃圾", "拖地"],
            "小红": ["擦窗", "洗碗"],
            "大刘": ["做饭", "刷厕所"],
        }
        got = {p: sorted(b) for p, b in plan.bundles.items()}
        fc.expect(got == {p: sorted(b) for p, b in expected.items()}, f"split {got}")
        fc.expect(plan.transfer == {"阿明": -2000, "小红": -500, "大刘": 2500}, f"{plan.transfer}")
        fc.expect(set(plan.net.values()) == {-4500}, f"net amounts {plan.net}")

    def random_data(stream: fc.SeedStream) -> dict:
        people = [f"p{i}" for i in range(2 + stream.below(3))]
        chores = [f"c{i}" for i in range(1 + stream.below(3))]
        cannot = {p: [c for c in chores if stream.below(4) == 0] for p in people}
        data = {
            "people": people,
            "chores": [{"name": c, "units": 1 + stream.below(2)} for c in chores],
            "costs": {
                p: {c: stream.below(5) for c in chores if c not in cannot[p]} for p in people
            },
            "caps": {p: stream.below(4) for p in people},
            "rules": {"plan": PLAN_BUNDLE},
        }
        if any(cannot.values()):
            data["cannot"] = {p: c for p, c in cannot.items() if c}
        return data

    def cheapest_split_against_brute_force() -> None:
        stream = fc.SeedStream(fc.make_seed("chore_bundle_selftest", ["split"], 80, "selftest"))
        for _ in range(80):
            problem = parse_problem(random_data(stream))
            priority = sorted(problem.people)
            cost, split, count = brute_force_split(problem, priority)
            if cost is None:
                try:
                    compute(problem)
                except fc.NoSolution:
                    continue
                raise AssertionError("a case without a way to share out the chores was solved")
            plan = compute(problem)
            got = frozenset((p, tuple(sorted(plan.bundles[p]))) for p in priority)
            fc.expect(plan.total_cost == cost, f"total cost {plan.total_cost}, not {cost}")
            fc.expect(got == split, "not the first cheapest split in the order of the tie rule")
            fc.expect(plan.was_tie == (count > 1), "tie found or missed")

    def money_is_exact_and_fair() -> None:
        stream = fc.SeedStream(fc.make_seed("chore_bundle_selftest", ["money"], 60, "selftest"))
        done = 0
        while done < 60:
            problem = parse_problem(random_data(stream))
            try:
                plan = compute(problem)
            except fc.NoSolution:
                continue
            done += 1
            fc.expect(sum(plan.transfer.values()) == 0, "the payments do not add up to zero")
            fc.expect(plan.max_envy <= 1, f"envy of {plan.max_envy} cents")
            fc.expect(sum(plan.net.values()) == -plan.total_cost, "the nets do not add up")
            for p in plan.people:
                fc.expect(plan.shares[p][p] == plan.net[p], "own share differs from own net")
                gap = abs(plan.exact_transfer[p] - plan.transfer[p])
                fc.expect(gap < 1, "a payment is more than a cent from its exact value")

    def better_split_exists() -> None:
        names = ["阿明", "小红", "大刘"]
        chores = ["洗碗", "倒垃圾", "拖地", "刷厕所", "做饭", "擦窗"]
        table = [[28, 29, 5, 20, 9, 18], [13, 9, 4, 3, 26, 2], [2, 26, 24, 27, 1, 13]]
        problem = parse_problem(
            {
                "people": names,
                "chores": chores,
                "costs": {n: dict(zip(chores, row)) for n, row in zip(names, table)},
                "caps": {n: 2 for n in names},
                "rules": {"plan": PLAN_BUNDLE},
            }
        )
        plan = compute(problem)
        worst = min(plan.exact_transfer[p] - plan.cost[p] for p in plan.people)
        fc.expect(plan.total_cost == 3800 and worst == Fraction(-5500, 3), f"{worst}")
        other = {"阿明": ["拖地", "做饭"], "小红": ["倒垃圾", "刷厕所"], "大刘": ["洗碗", "擦窗"]}
        cost_of, _, exact = settle_exactly(problem, other)
        nets = [exact[p] - cost_of[p][p] for p in names]
        fc.expect(sum(cost_of[p][p] for p in names) == 4100, "the other split costs 41")
        fc.expect(set(nets) == {Fraction(-4100, 3)}, f"nets of the other split {nets}")
        fc.expect(min(nets) > worst, "a dearer split leaves the worst-off person better off")

    def fields_of_the_other_plan_are_refused() -> None:
        for name in ROUND_ROBIN_ONLY:
            data = demo_data()
            data[name] = {}
            try:
                parse_problem(data)
            except fc.InputError as err:
                fc.expect(err.field == name, err.field)
            else:
                raise AssertionError(f"{name} was accepted in plan {PLAN_BUNDLE}")
        data = fc.parse_input(DEMO_JSON)
        data["costs"] = {}
        try:
            parse_problem(data)
        except fc.InputError as err:
            fc.expect(err.field == "costs", err.field)
        else:
            raise AssertionError("costs was accepted in plan round_robin")

    def texts_match() -> None:
        zh, en = BUNDLE_TEXT["zh"], BUNDLE_TEXT["en"]
        fc.expect(set(zh) == set(en), "zh and en plan B text keys differ")

    def every_output_renders() -> None:
        without_source = demo_data()
        del without_source["rules"]["random_source"], without_source["rules"]["source_description"]
        with_limits = demo_data()
        with_limits["caps"] = {"阿明": 2, "小红": 1, "大刘": 3}
        with_limits["cannot"] = {"小红": ["做饭"]}
        del with_limits["costs"]["小红"]["做饭"]
        for data in (demo_data(), without_source, with_limits):
            for lang in fc.LANGS:
                result = solve(data, lang)
                for fmt in fc.FORMATS:
                    fc.expect(bool(fc.render(result, fmt, False, lang)), f"{fmt} {lang}")
                fc.expect(bool(fc.render(result, "md", True, lang)), f"json {lang}")

    return [
        ("plan B recorded example: two cheapest splits, -45.00 each", recorded_example),
        ("plan B cheapest split against brute force", cheapest_split_against_brute_force),
        ("plan B payments add up, no envy above a cent", money_is_exact_and_fair),
        ("plan B a dearer split can leave the worst-off person better off", better_split_exists),
        ("plan B refuses the fields of the other plan", fields_of_the_other_plan_are_refused),
        ("plan B zh and en texts have the same keys", texts_match),
        ("plan B every output renders", every_output_renders),
    ]


# ---------------------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------------------


def reproduce_command(args: argparse.Namespace) -> str:
    parts = ["python3", "scripts/chore_split.py"]
    if args.demo:
        parts += ["--demo"]
    elif args.demo_bundle:
        parts += ["--demo-bundle"]
    else:
        parts += ["--input", "-"]
    parts += ["--json"] if args.json else ["--format", args.format]
    if args.lang != "zh":
        parts += ["--lang", args.lang]
    return " ".join(parts)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chore_split.py",
        description=(
            "Share out household chores. Plan round_robin (the default) takes turns, envy-free "
            "up to one chore. Reads one JSON object (people, chores, rankings, cannot, weeks, "
            "rules) from standard input or --input FILE. Everybody ranks the chores from least "
            "to most disliked. The people pick in turn, each taking the remaining chore they "
            "mind least. The pick order of week 1 comes only from the public source text "
            "through SHA-256, never from the random module, and the start moves one place each "
            "week. Plan bundle_pay (rules.plan) gives each person a fixed bundle at the "
            "smallest total cost and settles the money between them: it reads costs and caps "
            "instead of rankings and weeks."
        ),
        epilog=(
            "chores: names, or objects with name and units (a chore that repeats during the "
            "week is several units). rankings: person to the chores they can do, least "
            "disliked first. cannot: person to the chores they cannot do (left out of their "
            "ranking). likes: a task somebody likes is not supported and is refused. "
            "rules: random_source (required), source_description, rotate shift or none, plan "
            "round_robin or bundle_pay. Plan bundle_pay: costs is person to chore to the cost "
            "of one unit (an amount of 0 or more), caps is person to the most units they take, "
            "and rules.random_source is optional and only settles ties between equally cheap "
            "splits. "
        )
        + fc.exit_codes_epilog(
            three="the agreed rules have no solution: some chore is on every person's cannot "
            "list or, in plan bundle_pay, the caps and cannot lists leave no way to share out "
            "all the chores"
        ),
    )
    fc.standard_args(parser)
    parser.add_argument(
        "--demo-bundle",
        action="store_true",
        help="run on the built-in fictional example of plan bundle_pay (fixed bundles with "
        "compensation)",
    )
    fc.add_lang_option(parser, "JSON keys and names do not change")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    fc.exclusive_modes(args, "--demo", "--selftest")
    fc.exclusive_modes(args, "--demo", "--demo-bundle", "--selftest")
    if args.selftest:
        return fc.run_selftest(selftest_checks())
    if args.demo_bundle:
        data = fc.parse_input(BUNDLE_DEMO_JSON)
    else:
        data = fc.read_object(args, DEMO_JSON)
    fc.emit(solve(data, args.lang, reproduce_command(args)), args, lang=args.lang)
    return 0


if __name__ == "__main__":
    fc.run_cli(main)
