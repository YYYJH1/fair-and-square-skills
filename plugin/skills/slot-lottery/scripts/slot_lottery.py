"""Draw limited slots, tickets or shifts with a lottery that anyone can recompute.

Two modes:

  lottery  n_slots identical slots (tickets, parking spaces). The script draws a full random
           order of the people. The first n_slots are drawn, the rest are the waiting list.
  rsd      different slots (holiday weeks, time slots) and each person's ranking of the slots
           they accept. Random serial dictatorship: the people pick in the random order and
           each takes the best slot that is still free. Someone whose acceptable slots are all
           gone gets none and joins the waiting list.

In mode rsd the group can pick another method in rules.method, before anything is drawn:

  rsd  (the default) random serial dictatorship, as above.
  ps   probabilistic serial. Everybody eats from their best slot that is not used up, at the same
       speed, and the share eaten is the chance of getting the slot. The table of chances is
       decomposed (Birkhoff-von Neumann) into fixed assignments with a probability each, and one
       of them is drawn from the public source. Slots may hold several people (capacities).
  da   deferred acceptance (Gale-Shapley), applicants propose. Every slot ranks the people by
       priority tiers (priorities), ties inside a tier are broken by one lottery order drawn from
       the public source, and slots may hold several people (capacities).

The randomness is either random_source, a public text fixed in the rules before anything is
drawn (for example the numbers of a named lottery draw on a stated date, copied exactly), or
commit_reveal, an option for technical groups. In commit_reveal every person makes a random
reveal code, posts a commitment to it and later posts the code. The text that seeds the draw is
then the canonical JSON of the verified codes. Seed and order follow fsq_core.SEED_SPEC: SHA-256
only, never the random module. The same input prints the same bytes on every Python version.

A person without a verified reveal, or (in rsd) without a ranking, is handled by a rule that
the group declares in advance: forfeit (out of the draw) or assigned (a chore: first in the
lottery, last in the queue). The rule is applied before the draw and reported. It cannot make
not revealing harmless to the others: see the warning the script prints. With ps and da a person
without a ranking is out (forfeit) or takes what is left after the draw (assigned), and
commit_reveal is not available: give random_source.

--verify recomputes the draw from the input and compares it with input["claimed"].
--commit makes one person's commitment and reveal code locally.

Input is JSON on standard input (--input -). Output is --format md|dm|group or --json, in
Chinese or English (--lang). Exit code 0 means success, 1 a failed --verify or self-test, 2
invalid input (the message names the field), 3 that the declared rules leave no draw to run.
Standard library only, Python 3.9+.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import math
import re
import shlex
import sys
from collections import Counter
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

RULE_NAMES = {"lottery": "uniform_lottery_v1", "rsd": "rsd_v1"}
MODES = tuple(RULE_NAMES)
METHODS = ("rsd", "ps", "da")  # rules.method in mode rsd; rsd is the default
METHOD_RULE_NAMES = {"ps": "ps_bvn_v1", "da": "da_tiebreak_v1"}
HANDLING = ("forfeit", "assigned")
REASON_REVEAL = "no_reveal"
REASON_RANKING = "no_ranking"
MAX_PEOPLE = 2000
MAX_SLOTS = 2000
MIN_REVEALS = 2  # fewer verified reveals would let one person decide the draw
MAX_PS_PEOPLE = 40  # ps: people with a ranking (the decomposition table grows with the square)
MAX_PS_TABLE = 150  # ps: side of the square table that is decomposed
MAX_DA_PEOPLE = 200  # da: people with a ranking (the rounds are printed)
TOP_FIELDS = (
    "mode",
    "people",
    "n_slots",
    "slot_names",
    "capacities",
    "prefs",
    "priorities",
    "rules",
    "random_source",
    "commit_reveal",
    "claimed",
)
RULE_FIELDS = ("source_description", "deadline", "non_reveal", "no_ranking", "method")
CLAIMED_FIELDS = ("order", "seed", "allocation")
DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}")
CODE_PATTERN = re.compile(r"[0-9a-f]{32}")

# The fictional 8-person example whose seed and order were recorded when the seed mapping was
# first specified: seed prefix 15b9c53a44270857eb442863, order Yuki 小周 大刘 Coco 小红 阿明 Mia 老王.
DEMO_JSON = """{
  "mode": "lottery",
  "people": ["阿明", "小红", "大刘", "Coco", "老王", "Yuki", "小周", "Mia"],
  "n_slots": 3,
  "random_source": "（虚构示例）2026-11-08 某公开开奖号码 03 11 19 24 33 + 02 07",
  "rules": {
    "source_description": "虚构示例：2026 年 11 月 8 日某公开开奖，按官网显示的格式原样抄写",
    "deadline": "2026-11-07 20:00 报名截止，名单和名额数随后锁定"
  }
}"""

# ---------------------------------------------------------------------------------------
# Texts (zh is the default, en says the same)
# ---------------------------------------------------------------------------------------

TEXT = {
    "zh": {
        "sep": "、",
        "none": "无",
        "title_lottery": "抽签结果：{people} 人抢 {slots} 个名额（均匀抽签）",
        "title_rsd": "排队挑选结果：{people} 人挑 {slots} 个时段（随机排队，轮到谁谁挑）",
        "cap_order": "完整顺序（前 {slots} 位抽中，其余按顺序候补）",
        "hdr_order": ["位次", "姓名", "结果"],
        "st_drawn": "抽中",
        "st_waiting": "候补 {k}",
        "st_front": "，未按约定揭示，直接排在最前面",
        "st_back": "，排在队尾",
        "cap_turns": "挑选过程（按排队顺序）",
        "hdr_turns": ["位次", "姓名", "挑到", "说明"],
        "pick_none": "（没有分到）",
        "why_rank1": "第 1 志愿",
        "why_rank": "第 {rank} 志愿（更想要的{passed}已被前面的人挑走）",
        "why_gone": "列出的时段都被前面的人挑走了，候补 {k}",
        "why_empty": "没有列出能接受的时段，候补 {k}",
        "why_left": "没交志愿，拿剩下的",
        "why_left_none": "没交志愿，轮到时没有剩下的时段，候补 {k}",
        "cap_slots": "时段分配",
        "hdr_slots": ["时段", "挑到的人"],
        "slot_free": "（没人挑）",
        "n_drawn": "抽中：{names}。",
        "n_waiting": "候补（有人放弃时按顺序递补，不重抽）：{names}。",
        "n_all_drawn": "名额不少于人数，所有人都抽中，没有候补。",
        "n_unplaced": "没分到（候补，按排队顺序）：{names}。",
        "n_free_slots": "没人挑走的时段：{names}。",
        "n_out": "退出抽签：{names}。按事先定的规则，他们不参加抽签，也不进候补。",
        "n_front": "直接排在最前面：{names}。按事先定的规则，他们先于抽签占用名额。",
        "n_back": "排在队尾：{names}。按事先定的规则，他们只能挑前面的人挑剩下的。",
        "reason_no_reveal": "没按约定揭示",
        "reason_no_ranking": "没交志愿",
        "reason_sep": "，",
        "n_lapse": "{names}：{reasons}。",
        "cap_source": "随机源与复算",
        "cap_source_draw": "复算：{group}",
        "group_main": "正常参加的人",
        "group_penalty": "按规则单独排序的人",
        "hdr_facts": ["项目", "内容"],
        "f_description": "随机源说明",
        "f_deadline": "截止时间",
        "f_source": "随机源原文（逐字）",
        "f_source_reveal": "随机源（各人的揭示码，已核对）",
        "f_rule": "规则名",
        "f_slots": "名额数（写进种子）",
        "f_people": "名单（按码位排序，写进种子）",
        "f_preimage": "种子原像（对这段文字取 SHA-256）",
        "f_seed": "种子（SHA-256，十六进制）",
        "f_order": "这一组的顺序",
        "n_algo": (
            "复算方法：① 种子 = 「种子原像」的 SHA-256（UTF-8）。② 第 c 次取数（c 从 0 起）"
            "= SHA-256（种子 + c 的 8 字节大端）的前 8 字节，按大端读成整数 x。要取 0 到 n−1 "
            "之间的整数时，x 小于 2^64 − (2^64 mod n) 就取 x 除以 n 的余数，否则 c 加 1 重取。"
            "③ 名单按码位排序，i 从 n−1 降到 1，每步取一个 0 到 i 之间的整数 j，交换第 i 位和第 j 位，"
            "最后得到的就是完整顺序。整个过程不用 random 模块。"
        ),
        "n_pipe": (
            "表格里的竖线 | 前面被加了一个反斜杠。复算时请用 --json 里的种子原像，"
            "或者群里卡片上的原文，不要从表格里复制。"
        ),
        "n_verify": (
            "核对：把本次的输入连同卡片上的结果（claimed）交给 "
            "python3 scripts/slot_lottery.py --verify，一致就退出 0，不一致退出 1。"
            "随机源原文请自己到公布处再抄一遍，用 --source 传给它。"
        ),
        "cap_reveals": "承诺与揭示核对",
        "hdr_reveals": ["姓名", "承诺码（前 12 位）", "揭示码（前 12 位）", "核对"],
        "rv_ok": "通过",
        "rv_no_commitment": "没有承诺码",
        "rv_no_reveal": "没有揭示",
        "rv_mismatch": "揭示与承诺码不一致",
        "n_reveal_source": (
            "随机源 = 通过核对的揭示码按姓名排序后的规范化 JSON（上表的原文）。"
            "只有通过核对的人的揭示码进入种子。"
        ),
        "n_reveal_rule": "未通过核对的人，按事先定的规则（{rule}）处理：{effect}。",
        "eff_forfeit": "退出抽签",
        "eff_assigned_lottery": "直接排在最前面",
        "eff_assigned_rsd": "排在队尾",
        "warn_commit": (
            "提醒：承诺–揭示堵不住所有操纵。最后一个揭示的人能先看到别人的揭示，再决定自己揭不揭示，"
            "这会改变别人的结果。例如 8 人抽 3 张票、不揭示算退出时，这个人能把朋友的中签率从 0.375 "
            "提高到 0.643。事先说好的处理方式只是让不揭示对本人不划算，没法让它对别人没有影响。"
        ),
        "dm_drawn": "你抽中了：顺序第 {pos} 位，在 {slots} 个名额之内（共 {people} 人）。",
        "dm_waiting": (
            "你没有抽中：顺序第 {pos} 位，候补第 {k} 位（{slots} 个名额，共 {people} 人）。"
            "有人放弃时按候补顺序递补，不重抽。"
        ),
        "dm_out": "你{reasons}，按事先定的规则退出这次抽签：没有名额，也不在候补里。",
        "dm_front": "你{reasons}，按事先定的规则直接排在最前面。",
        "dm_back": "你{reasons}，按事先定的规则排在队尾。",
        "dm_picked": "你的排队顺序是第 {pos} 位，你挑到了「{slot}」（你的第 {rank} 志愿）。",
        "dm_left": (
            "你的排队顺序是第 {pos} 位。你没有交志愿，按事先定的规则排在队尾，拿剩下的，"
            "你得到「{slot}」。"
        ),
        "dm_unplaced": (
            "你的排队顺序是第 {pos} 位，你列出的时段轮到你时都被挑走了，你在候补第 {k} 位。"
        ),
        "dm_empty": "你的排队顺序是第 {pos} 位，你没有列出能接受的时段，所以没有分到，候补第 {k} 位。",
        "dm_left_none": (
            "你的排队顺序是第 {pos} 位。你没有交志愿，按事先定的规则排在队尾，"
            "轮到你时没有剩下的时段，你在候补第 {k} 位。"
        ),
        "dm_ranking": (
            "你交的志愿顺序（最想要的在前）：{ranking}。如果和你发给组织者的不一样，请马上告诉大家。"
        ),
        "rank_sep": " > ",
        "g_description": "随机源说明：{text}",
        "g_deadline": "截止时间：{text}",
        "g_source": "随机源原文：{text}",
        "g_source_reveal": "随机源：各人的揭示码（已核对），按姓名排序后的规范化 JSON：{text}",
        "g_seed": "种子（SHA-256）：{seed}",
        "g_preimage": "种子原像（对这段文字取 SHA-256 就是种子）：{text}",
        "g_order": "完整顺序：{text}",
        "g_drawn": "抽中（前 {slots} 位）：{names}",
        "g_waiting": "候补（按顺序递补，不重抽）：{names}",
        "g_all_drawn": "名额不少于人数，所有人都抽中。",
        "g_queue": "排队顺序与结果：",
        "g_pick": "{pos} {name} 挑到「{slot}」",
        "g_waiting_line": "{pos} {name} 候补 {k}",
        "g_free_slots": "没人挑走的时段：{names}",
        "g_out": "退出抽签（{reasons}）：{names}",
        "g_front": "按规则直接排在最前面：{names}",
        "g_back": "按规则排在队尾：{names}",
        "g_reveal_ok": "承诺–揭示：{ok} 人的揭示与承诺码一致。",
        "g_reveal_bad": "没通过核对：{bad}。",
        "g_recompute": (
            "复算：随机源原文、名单（按码位排序）、名额数和规则名都在上面，"
            "按种子原像取 SHA-256，再用计数器洗牌。洗牌的写法见 github.com/YYYJH1/fair-and-square-skills 里 "
            "docs/THEORY.md 的 Public randomness 一节，也可以用同一仓库里的 slot_lottery.py "
            "--verify 核对。"
        ),
        "g_draw_label": "{group}的种子原像：{text}",
        "nm_source": (
            "随机源是否真的事先约定、事后无法更改、临场无人能预测：脚本核对不了。"
            "这三条只要有一条不成立，就有人能影响结果。"
        ),
        "nm_frozen": "名单、名额数和规则是否在随机源公布前就已冻结：由群里的记录证明，脚本只按输入计算。",
        "nm_ranking": (
            "志愿是否被如实录入：每人在自己的私信里核对。排队挑选保证说真话最优、"
            "抽完之后没有人能在不伤害别人的前提下变得更好，但不保证没有嫉妒，也不保证事前最优。"
        ),
        "nm_commit": (
            "承诺–揭示：不揭示的人仍然可能改变别人的结果，见上面的提醒。"
            "每人的承诺码是否都在第一个揭示码之前发出，只能从群聊记录看，脚本看不到先后。"
        ),
        "nm_waiting": "有人放弃后按候补顺序递补是群里的约定，不在脚本的保证里。",
        "t_verify_ok": "复算核对：一致",
        "t_verify_bad": "复算核对：不一致",
        "cap_verify": "核对项",
        "hdr_verify": ["核对项", "结果", "说明"],
        "hdr_verify_order": ["位次", "卡片上", "重新计算", "核对"],
        "v_ok": "一致",
        "v_bad": "不一致",
        "v_order": "顺序",
        "v_seed": "种子",
        "v_allocation": "分配结果",
        "v_source": "随机源原文",
        "v_order_ok": "{n} 个名字的顺序完全一致",
        "v_order_names": "名单不同：卡片上多出 {extra}，缺少 {missing}",
        "v_order_pos": "第 {pos} 位：卡片上是 {card}，重新计算是 {calc}",
        "v_seed_ok": "种子一致",
        "v_seed_bad": "卡片上的种子是 {card}，重新计算是 {calc}",
        "v_alloc_ok": "每个人拿到的时段完全一致",
        "v_alloc_bad": "{person}：卡片上是 {card}，重新计算是 {calc}",
        "v_alloc_none": "没有分到",
        "v_source_ok": "你给的随机源原文和卡片上的一致",
        "v_source_bad": "你给的随机源原文和卡片上的不同，下面以你给的为准重新计算",
        "v_pass": "结论：在这份输入下，卡片上的结果可以复现。",
        "v_fail": "结论：卡片上的结果无法复现。请先核对随机源原文、名单和名额数有没有抄错。",
        "commit_lines": [
            "承诺码（现在就发到群里）：{digest}",
            "揭示码（自己保管，不要给任何人，包括组织者；约定的时间到了再发到群里）：{code}",
            "承诺内容：{payload}",
            "",
            "怎么用：",
            "1. 现在只把承诺码发到群里。组织者也一样，而且最先发。",
            (
                "2. 等所有人的承诺码都发出来、到了约定的揭示时间，再把揭示码发到群里。"
                "不要私发给组织者。"
            ),
            "3. 任何人都可以核对：承诺码 = SHA-256（fsq-commit-v1 + 换行 + 揭示码 + 换行 + 承诺内容）。",
            "4. 请在你自己的设备或会话里运行这条命令。让别人代你运行，对方就知道你的揭示码了。",
            "5. 这个揭示码只用于这一次抽签，下一次重新生成。",
        ],
        "m_title_ps": "分配结果：{people} 人分 {slots} 个时段（概率序列 PS，分解后按随机源抽一种）",
        "m_title_da": "分配结果：{people} 人申请 {slots} 个时段（延迟接受 DA，申请方先提）",
        "m_hdr_slots": ["时段", "名额", "分到的人"],
        "m_free_seats": "（空 {free} 个）",
        "m_slot_free": "（没人分到）",
        "m_n_unassigned": "没分到：{names}。",
        "m_n_all_assigned": "参加的人都分到了时段。",
        "m_n_free": "还有空位的时段：{names}。",
        "m_n_late": ("拿剩下的：{names}。按事先定的规则，他们在抽取之后按这个顺序拿剩下的时段。"),
        "m_f_order": "抽签顺序（同档平局时靠前的人优先）",
        "m_nm_waiting": "没有候补名单：有人放弃名额时怎么办，要在规则消息里事先说好，脚本不管。",
        "m_dm_left": (
            "你没交志愿，按事先定的规则在抽取之后拿剩下的时段，你排第 {pos} 位。你得到「{slot}」。"
        ),
        "m_dm_left_none": (
            "你没交志愿，按事先定的规则在抽取之后拿剩下的时段，你排第 {pos} 位，"
            "但轮到你时没有剩下的。"
        ),
        "m_why_late_none": "没交志愿，轮到时没有剩下的",
        "m_dm_out": "你{reasons}，按事先定的规则退出这次分配：没有名额。",
        "m_chance_sep": "，",
        "ps_none_dm": "没分到",
        "m_g_got": "{name} 分到「{slot}」",
        "m_g_none": "没分到：{names}",
        "m_g_free": "还有空位：{names}",
        "m_g_late": "按规则拿剩下的：{names}",
        "m_g_result": "结果：",
        "ps_cap_matrix": "每人拿到每个时段的概率（概率序列）",
        "ps_hdr_name": "姓名",
        "ps_none": "没分到",
        "ps_cap_terms": "分解成确定的分配（共 {k} 种，概率之和为 1）",
        "ps_hdr_terms": ["序号", "概率", "分配（没有列出的人没分到）"],
        "ps_cap_draw": "抽取",
        "ps_f_modulus": "随机数的范围（各种分配概率的公分母）",
        "ps_v_modulus": "0 到 {last}（共 {count} 个数）",
        "ps_f_number": "抽到的随机数",
        "ps_f_term": "落在第几种分配",
        "ps_v_term": "第 {k} 种（这一种占随机数 {first} 到 {last}）",
        "ps_v_term_one": "第 {k} 种（这一种只占随机数 {first}）",
        "ps_n_algo": (
            "复算方法：① 种子 = 「种子原像」的 SHA-256（UTF-8）。② 第 c 次取数（c 从 0 起）"
            "= SHA-256（种子 + c 的 8 字节大端）的前 8 字节，按大端读成整数 x。"
            "整个过程不用 random 模块。"
        ),
        "ps_cap_eating": "吃的过程（所有人同时吃，速度相同）",
        "ps_hdr_eating": ["从", "到", "谁在吃什么", "这一段结束时吃完的时段"],
        "ps_eat_nothing": "没有可吃的",
        "ps_n_method": (
            "方法：概率序列（PS）。把每个时段看成一块可以切开的蛋糕，几个名额就是几块。"
            "从时间 0 到时间 1，所有人同时开吃，速度相同，每个人每一刻都吃自己列表里还没吃完的"
            "最想要的时段，吃完了就换下一个。每个人吃到每个时段的份额，就是他拿到这个时段的概率。"
            "列表里的时段都吃完了，剩下的时间算「没分到」。随后把这张概率表分解成若干种确定的分配"
            "（Birkhoff-von Neumann 分解），每一种有自己的概率，再由随机源抽出一种。"
        ),
        "ps_n_draw": (
            "抽取方法：种子的计数器流给出一个 0 到 D−1 的随机数（D 是各种分配概率的公分母，"
            "见上表）：取第 0 次取数 x，x 小于 2^64 − (2^64 mod D) 就取 x 除以 D 的余数，"
            "否则取下一次取数。D 超过 2^64 时，每次连续取 k 个数（k 是满足 D 不超过 2^(64k) 的"
            "最小整数），按大端拼成一个整数，再照同样的办法处理。各种分配按表里的顺序，"
            "各占「概率乘以 D」个连续的数，随机数落在哪一种里，就用哪一种。"
        ),
        "ps_nm_strategy": (
            "概率序列保证抽签之前没有人羡慕别人的概率分布（随机占优意义下），并且序数有效，"
            "但不防策略：知道别人志愿的人，有时能靠谎报志愿拿到更好的概率。"
            "抽出来的这一种分配，事后仍然可能有人羡慕别人。"
        ),
        "ps_nm_ranking": "志愿是否被如实录入：每人在自己的私信里核对。",
        "ps_dm_got": "你分到了「{slot}」（你的第 {rank} 志愿）。",
        "ps_dm_none": "你这次没有分到时段。",
        "ps_dm_empty": "你没有列出能接受的时段，所以没有分到。",
        "ps_dm_chances": "按你交的志愿，你拿到每个时段的概率是：{chances}。",
        "ps_dm_envy": (
            "脚本逐一核对过：按你自己的志愿顺序，其他每个人的概率分布都不比你的更好"
            "（随机占优意义下无嫉妒，抽签之前成立）。"
        ),
        "ps_g_method": "方法：概率序列（PS），把每人的概率表分解成确定的分配，再用随机源抽一种。",
        "ps_g_draw": "抽取：随机数在 0 到 {last} 之间，抽到 {number}。",
        "ps_g_recompute": (
            "复算：随机源原文、名单、名额数和规则名都在上面，按种子原像取 SHA-256 得到种子，"
            "再取随机数。概率表和分解表带有志愿信息，不放在群里。组织者手里有完整的 --json 证书，"
            "各人同意公开志愿后，可以用 python3 scripts/slot_lottery.py --verify 从同一份输入"
            "重新算出整个结果。"
        ),
        "da_cap_result": "结果与理由（按抽签顺序）",
        "da_hdr_result": ["抽签位次", "姓名", "分到", "说明"],
        "da_why_rank1": "第 1 志愿",
        "da_why_rank": "第 {rank} 志愿。更想要的：{reasons}",
        "da_why_none": "没分到。列出的时段：{reasons}",
        "da_why_empty": "没有列出能接受的时段",
        "da_r_ineligible": "「{slot}」不接受",
        "da_r_tier": "「{slot}」被更高档的人占满",
        "da_r_lottery": "「{slot}」被同档、抽签靠前的人占满",
        "da_reason_sep": "；",
        "da_cap_slots": "时段、优先级与结果",
        "da_hdr_slots": ["时段", "名额", "优先级", "分到的人"],
        "da_prio_all": "全体同档，按抽签顺序",
        "da_prio_tier": "第 {k} 档：{names}",
        "da_prio_sep": "；",
        "da_prio_excluded": "不接受：{names}",
        "da_cap_rounds": "申请过程（每一轮，没有被保留的人向自己列表里的下一个时段申请）",
        "da_hdr_rounds": ["轮次", "申请", "被拒绝", "目前保留"],
        "da_rej_ineligible": "不接受",
        "da_rej_outranked": "名额满，优先级较低",
        "da_hold_sep": "；",
        "da_n_method": (
            "方法：延迟接受（DA），申请方先提。每一轮，还没有被时段保留的人，向自己列表里的下一个"
            "时段申请。每个时段把它保留的人和新来的申请人放在一起，先拒绝它不接受的人，再按优先级"
            "（先看档次，同档看抽签顺序）只留下名额数那么多人，其余拒绝。被拒绝的人下一轮向下一个"
            "时段申请，列表用完的人不再申请，直到没有人再申请为止。最后每个人拿着的时段就是结果。"
        ),
        "da_n_tie": "同一档里的平局用一次抽签统一打破：所有时段共用上面的抽签顺序，顺序靠前的人优先。",
        "da_nm_guarantee": (
            "延迟接受保证没有阻塞对（没有人和时段互相更愿意在一起，除非那个时段已被优先级更高的人"
            "占满），并且对申请的人来说如实填写志愿最划算。它不保证帕累托有效：可能有另一种分配"
            "让几个人都更满意，代价是违反某个时段的优先级。"
        ),
        "da_nm_priorities": (
            "优先级档次是事先定的规则，脚本照单计算，不判断它合不合理，也核对不了谁该排在哪一档。"
        ),
        "da_dm_got": "你分到了「{slot}」（你的第 {rank} 志愿）。",
        "da_dm_none": "你这次没有分到时段。",
        "da_dm_empty": "你没有列出能接受的时段，所以没有分到。",
        "da_dm_why": "你更想要的「{slot}」没有给你：{reason}。",
        "da_dm_r_ineligible": "它不接受你（你不在它的优先名单里）",
        "da_dm_r_tier": "它的名额已被优先级更高的人占满",
        "da_dm_r_lottery": "它的名额已被同一档里抽签顺序在你之前的人占满",
        "da_dm_order": "你的抽签位次是第 {pos} 位（同一档里的平局，位次靠前的人优先）。",
        "da_g_method": "方法：延迟接受（DA），申请方先提。同一档里的平局，按下面的抽签顺序。",
        "da_g_order": "抽签顺序（同档平局时靠前的人优先）：{text}",
        "da_g_slot": "「{slot}」{seats} 个名额，优先级：{text}",
        "da_g_recompute": (
            "复算：随机源原文、名单、名额数和规则名都在上面，按种子原像取 SHA-256 得到种子，"
            "再用计数器洗牌得到抽签顺序。拿各人的志愿和上面的优先级，按延迟接受的规则算一遍，"
            "就能核对结果。志愿是私下交的，要各人同意才能放到一起核对，也可以用 "
            "python3 scripts/slot_lottery.py --verify 核对。"
        ),
    },
    "en": {
        "sep": ", ",
        "none": "none",
        "title_lottery": "Draw result: {people} people, {slots} slots (uniform lottery)",
        "title_rsd": "Pick-in-turn result: {people} people, {slots} slots (random queue)",
        "cap_order": "Full order (the first {slots} are drawn, the rest wait in order)",
        "hdr_order": ["Position", "Name", "Result"],
        "st_drawn": "drawn",
        "st_waiting": "waiting {k}",
        "st_front": ", did not reveal as agreed, placed first",
        "st_back": ", placed at the back of the queue",
        "cap_turns": "Who picked what (in queue order)",
        "hdr_turns": ["Position", "Name", "Got", "Why"],
        "pick_none": "(nothing)",
        "why_rank1": "first choice",
        "why_rank": "choice number {rank} (you liked {passed} better, taken by people ahead)",
        "why_gone": "every listed slot was taken by people ahead, waiting {k}",
        "why_empty": "listed no acceptable slot, waiting {k}",
        "why_left": "sent no ranking, takes what is left",
        "why_left_none": "sent no ranking and nothing was left, waiting {k}",
        "cap_slots": "Slots",
        "hdr_slots": ["Slot", "Taken by"],
        "slot_free": "(nobody)",
        "n_drawn": "Drawn: {names}.",
        "n_waiting": "Waiting list (if someone gives up, the next name moves up; no new draw): {names}.",
        "n_all_drawn": "There are at least as many slots as people, so everyone is drawn.",
        "n_unplaced": "No slot (waiting list, in queue order): {names}.",
        "n_free_slots": "Slots nobody took: {names}.",
        "n_out": "Out of the draw: {names}. By the agreed rule they take no part and are not on the waiting list.",
        "n_front": "Placed first: {names}. By the agreed rule they take slots ahead of the draw.",
        "n_back": "Placed at the back: {names}. By the agreed rule they only get what the others left.",
        "reason_no_reveal": "did not reveal as agreed",
        "reason_no_ranking": "sent no ranking",
        "reason_sep": " and ",
        "n_lapse": "{names}: {reasons}.",
        "cap_source": "Random source and how to recompute",
        "cap_source_draw": "Recompute: {group}",
        "group_main": "people in good standing",
        "group_penalty": "people placed by rule",
        "hdr_facts": ["Item", "Value"],
        "f_description": "Where the source comes from",
        "f_deadline": "Deadline",
        "f_source": "Source text (verbatim)",
        "f_source_reveal": "Source (the verified reveal codes)",
        "f_rule": "Rule name",
        "f_slots": "Slot count (part of the seed)",
        "f_people": "Names (sorted by code point, part of the seed)",
        "f_preimage": "Seed preimage (take the SHA-256 of this text)",
        "f_seed": "Seed (SHA-256, hex)",
        "f_order": "Order of this group",
        "n_algo": "Recompute: " + fc.SEED_SPEC,
        "n_pipe": (
            "A backslash was put in front of each vertical bar | in the tables. To recompute, "
            "use the seed preimage in the --json output or the text on the group card, not a "
            "copy from a table."
        ),
        "n_verify": (
            "Check it: give this input together with the claimed result (claimed) to "
            "python3 scripts/slot_lottery.py --verify. It exits 0 on a match and 1 otherwise. "
            "Copy the source text again from where it was published and pass it with --source."
        ),
        "cap_reveals": "Commitments and reveals",
        "hdr_reveals": ["Name", "Commitment (first 12)", "Reveal code (first 12)", "Check"],
        "rv_ok": "ok",
        "rv_no_commitment": "no commitment",
        "rv_no_reveal": "no reveal",
        "rv_mismatch": "reveal does not match the commitment",
        "n_reveal_source": (
            "The source is the canonical JSON of the verified reveal codes, sorted by name "
            "(the text in the table above). Only people whose reveal verified contribute."
        ),
        "n_reveal_rule": (
            "People whose reveal did not verify are handled by the agreed rule ({rule}): {effect}."
        ),
        "eff_forfeit": "out of the draw",
        "eff_assigned_lottery": "placed first",
        "eff_assigned_rsd": "placed at the back of the queue",
        "warn_commit": (
            "Warning: commit-reveal does not stop every kind of manipulation. The last person to "
            "reveal can see everyone else's reveals before deciding whether to reveal, and that "
            "changes the result for the others. For example, in a draw of 3 tickets among 8 people "
            "where not revealing means dropping out, that person can raise a friend's chance of "
            "winning from 0.375 to 0.643. The agreed handling only makes not revealing costly for "
            "the person who does it. It cannot make it harmless for everyone else."
        ),
        "dm_drawn": "You are drawn: position {pos}, inside the {slots} slots ({people} people).",
        "dm_waiting": (
            "You are not drawn: position {pos}, waiting list number {k} ({slots} slots, "
            "{people} people). If someone gives up, the waiting list moves up in order. "
            "There is no new draw."
        ),
        "dm_out": (
            "You {reasons}, so by the agreed rule you are out of this draw: no slot and no place "
            "on the waiting list."
        ),
        "dm_front": "You {reasons}, so by the agreed rule you are placed first.",
        "dm_back": "You {reasons}, so by the agreed rule you are placed at the back of the queue.",
        "dm_picked": 'Your queue position is {pos}. You got "{slot}" (your choice number {rank}).',
        "dm_left": (
            "Your queue position is {pos}. You sent no ranking, so by the agreed rule you are at "
            'the back of the queue and take what is left: "{slot}".'
        ),
        "dm_unplaced": (
            "Your queue position is {pos}. Every slot you listed was taken before your turn. "
            "You are number {k} on the waiting list."
        ),
        "dm_empty": (
            "Your queue position is {pos}. You listed no acceptable slot, so you got none. "
            "You are number {k} on the waiting list."
        ),
        "dm_left_none": (
            "Your queue position is {pos}. You sent no ranking, so by the agreed rule you are at "
            "the back of the queue, and nothing was left at your turn. You are number {k} on "
            "the waiting list."
        ),
        "dm_ranking": (
            "The ranking you sent (best first): {ranking}. If it differs from what you gave the "
            "organizer, tell the group now."
        ),
        "rank_sep": " > ",
        "g_description": "Where the source comes from: {text}",
        "g_deadline": "Deadline: {text}",
        "g_source": "Source text: {text}",
        "g_source_reveal": "Source: the verified reveal codes as canonical JSON sorted by name: {text}",
        "g_seed": "Seed (SHA-256): {seed}",
        "g_preimage": "Seed preimage (its SHA-256 is the seed): {text}",
        "g_order": "Full order: {text}",
        "g_drawn": "Drawn (first {slots}): {names}",
        "g_waiting": "Waiting list (moves up in order, no new draw): {names}",
        "g_all_drawn": "There are at least as many slots as people, so everyone is drawn.",
        "g_queue": "Queue and result:",
        "g_pick": '{pos} {name} got "{slot}"',
        "g_waiting_line": "{pos} {name} waiting {k}",
        "g_free_slots": "Slots nobody took: {names}",
        "g_out": "Out of the draw ({reasons}): {names}",
        "g_front": "Placed first by rule: {names}",
        "g_back": "Placed at the back by rule: {names}",
        "g_reveal_ok": "Commit-reveal: {ok} reveals match their commitments.",
        "g_reveal_bad": "Did not verify: {bad}.",
        "g_recompute": (
            "Recompute: the source text, the names (sorted by code point), the slot count and "
            "the rule name are all above. Take the SHA-256 of the seed preimage, then shuffle with "
            "the counter. The shuffle is specified under Public randomness in docs/THEORY.md of "
            "github.com/YYYJH1/fair-and-square-skills, and slot_lottery.py --verify from the same repository checks a result."
        ),
        "g_draw_label": "Seed preimage of the {group}: {text}",
        "nm_source": (
            "Whether the random source was really fixed in advance, cannot be changed afterwards "
            "and could not be predicted: the script cannot check this. If any of the three fails, "
            "the result can be steered."
        ),
        "nm_frozen": (
            "Whether the names, the slot count and the rules were frozen before the source was "
            "published: the group's records show it, the script only computes from the input."
        ),
        "nm_ranking": (
            "Whether the rankings were entered correctly: each person checks theirs in their own "
            "message. Pick-in-turn makes truthful rankings the best choice and leaves nobody who "
            "can do better without hurting someone else, but it does not remove envy and it is "
            "not optimal before the draw."
        ),
        "nm_commit": (
            "Commit-reveal: a person who does not reveal can still change the others' results, "
            "see the warning above. Whether every commitment was posted before the first reveal "
            "can only be seen from the group chat, the script cannot see the order."
        ),
        "nm_waiting": "Moving up the waiting list when someone gives up is the group's convention, not a guarantee of the script.",
        "t_verify_ok": "Recompute check: match",
        "t_verify_bad": "Recompute check: mismatch",
        "cap_verify": "Checks",
        "hdr_verify": ["Check", "Result", "Detail"],
        "hdr_verify_order": ["Position", "On the card", "Recomputed", "Check"],
        "v_ok": "match",
        "v_bad": "mismatch",
        "v_order": "Order",
        "v_seed": "Seed",
        "v_allocation": "Allocation",
        "v_source": "Source text",
        "v_order_ok": "all {n} names are in the same order",
        "v_order_names": "the names differ: the card has {extra} extra, and misses {missing}",
        "v_order_pos": "position {pos}: the card says {card}, the recomputation gives {calc}",
        "v_seed_ok": "same seed",
        "v_seed_bad": "the card gives {card}, the recomputation gives {calc}",
        "v_alloc_ok": "every person got the same slot",
        "v_alloc_bad": "{person}: the card says {card}, the recomputation gives {calc}",
        "v_alloc_none": "no slot",
        "v_source_ok": "the source text you gave equals the one on the card",
        "v_source_bad": "the source text you gave differs from the one on the card; the order below is recomputed from yours",
        "v_pass": "Conclusion: with this input, the result on the card can be reproduced.",
        "v_fail": (
            "Conclusion: the result on the card cannot be reproduced. First check that the source "
            "text, the names and the slot count were copied correctly."
        ),
        "commit_lines": [
            "Commitment (post it in the group now): {digest}",
            (
                "Reveal code (keep it to yourself, also from the organizer; post it in the "
                "group at the agreed time): {code}"
            ),
            "Committed text: {payload}",
            "",
            "How to use it:",
            "1. Post only the commitment now. The organizer does the same, and goes first.",
            (
                "2. When everybody's commitment is out and the agreed reveal time has come, "
                "post your reveal code in the group, not privately to the organizer."
            ),
            (
                "3. Anyone can check it: commitment = SHA-256 of fsq-commit-v1, newline, reveal "
                "code, newline and the committed text."
            ),
            (
                "4. Run this command on your own device or in your own session. If someone "
                "runs it for you, they know your reveal code."
            ),
            "5. Use this reveal code for this one draw only. Make a new one next time.",
        ],
        "m_title_ps": (
            "Assignment result: {people} people, {slots} slots "
            "(probabilistic serial, decomposed and drawn from the public source)"
        ),
        "m_title_da": (
            "Assignment result: {people} people, {slots} slots "
            "(deferred acceptance, applicants propose)"
        ),
        "m_hdr_slots": ["Slot", "Seats", "Taken by"],
        "m_free_seats": " ({free} free)",
        "m_slot_free": "(nobody)",
        "m_n_unassigned": "No slot: {names}.",
        "m_n_all_assigned": "Everybody who took part got a slot.",
        "m_n_free": "Slots with free seats: {names}.",
        "m_n_late": (
            "Take what is left: {names}. By the agreed rule they take the slots that are left, "
            "in this order, after the draw."
        ),
        "m_f_order": "Lottery order (earlier wins a tie inside a tier)",
        "m_nm_waiting": (
            "There is no waiting list: what happens when somebody gives up a slot has to be "
            "agreed in the rules message, the script does not cover it."
        ),
        "m_dm_left": (
            "You sent no ranking, so by the agreed rule you take what is left after the draw, "
            'and you are number {pos} in that order. You got "{slot}".'
        ),
        "m_dm_left_none": (
            "You sent no ranking, so by the agreed rule you take what is left after the draw, "
            "and you are number {pos} in that order, but nothing was left at your turn."
        ),
        "m_why_late_none": "sent no ranking and nothing was left",
        "m_dm_out": "You {reasons}, so by the agreed rule you are out of this assignment: no slot.",
        "m_chance_sep": ", ",
        "ps_none_dm": "no slot",
        "m_g_got": '{name} got "{slot}"',
        "m_g_none": "No slot: {names}",
        "m_g_free": "Free seats: {names}",
        "m_g_late": "Take what is left, by rule: {names}",
        "m_g_result": "Result:",
        "ps_cap_matrix": "Each person's chance of each slot (probabilistic serial)",
        "ps_hdr_name": "Name",
        "ps_none": "No slot",
        "ps_cap_terms": (
            "Decomposition into fixed assignments ({k} in all, the chances add up to 1)"
        ),
        "ps_hdr_terms": ["No.", "Chance", "Assignment (people not listed get nothing)"],
        "ps_cap_draw": "The draw",
        "ps_f_modulus": "Range of the random number (common denominator of the chances)",
        "ps_v_modulus": "0 to {last} ({count} numbers)",
        "ps_f_number": "Random number drawn",
        "ps_f_term": "Falls in assignment number",
        "ps_v_term": "number {k} (it owns the random numbers {first} to {last})",
        "ps_v_term_one": "number {k} (it owns only the random number {first})",
        "ps_n_algo": (
            "Recompute: seed = SHA-256 of the seed preimage (UTF-8). Draw number c, counting from "
            "0, = the first 8 bytes, big-endian, of SHA-256(seed + c as 8 big-endian bytes), read "
            "as an integer x. The random module is not used."
        ),
        "ps_cap_eating": "The eating schedule (everybody eats at once, at the same speed)",
        "ps_hdr_eating": ["From", "To", "Who eats what", "Slots used up at the end"],
        "ps_eat_nothing": "nothing left to eat",
        "ps_n_method": (
            "Method: probabilistic serial (PS). Think of each slot as a cake with one piece for "
            "each seat. From time 0 to time 1 everybody eats at once and at the same speed, "
            "always from the best slot on their own list that is not used up, and moves on to the "
            "next one when it is. The share of a slot that a person has eaten is that person's "
            "chance of getting it. Time left after every listed slot is used up counts as no "
            "slot. The table of chances is then decomposed into fixed assignments "
            "(Birkhoff-von Neumann), each with its own chance, and the public source picks one "
            "of them."
        ),
        "ps_n_draw": (
            "How the draw works: the counter stream of the seed gives a random number from 0 to "
            "D - 1, where D is the common denominator of the chances of the assignments. Take "
            "draw number 0 as x, use x mod D if x is below 2^64 - (2^64 mod D), else take the "
            "next draw. A D above 2^64 takes k draws at a time, k being the least number with D "
            "at most 2^(64 k), reads them big-endian as one integer and treats it the same way. "
            "The assignments in the table own D times their chance consecutive numbers each, in "
            "the order of the table, and the one that holds the random number is used."
        ),
        "ps_nm_strategy": (
            "Probabilistic serial guarantees, before the draw, that nobody would prefer the "
            "lottery of somebody else (in the sense of stochastic dominance), and that the "
            "table of chances is ordinally efficient. It does not prevent strategic reporting: a "
            "person who knows the other rankings can sometimes get better chances by reporting a "
            "ranking that is not their own. The one assignment that is drawn can still leave "
            "somebody envious afterwards."
        ),
        "ps_nm_ranking": (
            "Whether the rankings were entered correctly: each person checks theirs in their "
            "own message."
        ),
        "ps_dm_got": 'You got "{slot}" (your choice number {rank}).',
        "ps_dm_none": "You did not get a slot this time.",
        "ps_dm_empty": "You listed no acceptable slot, so you got none.",
        "ps_dm_chances": "By the ranking you sent, your chance of each slot was: {chances}.",
        "ps_dm_envy": (
            "The script checked, one by one: by your own ranking, the lottery of nobody else is "
            "better than yours (no envy in the sense of stochastic dominance, true before the "
            "draw)."
        ),
        "ps_g_method": (
            "Method: probabilistic serial (PS). The table of chances is decomposed into fixed "
            "assignments and the public source picks one of them."
        ),
        "ps_g_draw": "The draw: a random number from 0 to {last}, drawn {number}.",
        "ps_g_recompute": (
            "Recompute: the source text, the names, the slot count and the rule name are all "
            "above. Take the SHA-256 of the seed preimage for the seed, then draw the random "
            "number. The table of chances and the decomposition carry ranking information, so "
            "they are not posted in the group. The organizer holds the full --json certificate, "
            "and once everybody agrees to reveal their rankings, "
            "python3 scripts/slot_lottery.py --verify recomputes the whole result from the same "
            "input."
        ),
        "da_cap_result": "Result and reasons (in lottery order)",
        "da_hdr_result": ["Lottery position", "Name", "Got", "Why"],
        "da_why_rank1": "first choice",
        "da_why_rank": "choice number {rank}. Ranked higher: {reasons}",
        "da_why_none": "no slot. Listed slots: {reasons}",
        "da_why_empty": "listed no acceptable slot",
        "da_r_ineligible": '"{slot}" does not accept this person',
        "da_r_tier": '"{slot}" is full of higher tiers',
        "da_r_lottery": '"{slot}" is full of people in the same tier who come earlier in the lottery',
        "da_reason_sep": "; ",
        "da_cap_slots": "Slots, priorities and result",
        "da_hdr_slots": ["Slot", "Seats", "Priority", "Taken by"],
        "da_prio_all": "everybody in one tier, ordered by the lottery",
        "da_prio_tier": "tier {k}: {names}",
        "da_prio_sep": "; ",
        "da_prio_excluded": "not accepted: {names}",
        "da_cap_rounds": "The rounds (each round, everybody not on hold applies to the next slot on their list)",
        "da_hdr_rounds": ["Round", "Applications", "Turned away", "On hold"],
        "da_rej_ineligible": "not accepted",
        "da_rej_outranked": "full, lower priority",
        "da_hold_sep": "; ",
        "da_n_method": (
            "Method: deferred acceptance (DA), applicants propose. In every round, each person "
            "who is not on hold applies to the next slot on their list. A slot looks at the "
            "people it holds and the new applicants together, turns away those it does not "
            "accept, keeps as many as it has seats by priority (first the tier, inside a tier "
            "the lottery order) and turns the rest away. Those turned away apply to their next "
            "slot in the next round, and a person whose list is used up stops. It ends when "
            "nobody applies any more. What everybody holds at the end is the result."
        ),
        "da_n_tie": (
            "Ties inside a tier are broken by one lottery for all slots: the lottery order "
            "above, earlier first."
        ),
        "da_nm_guarantee": (
            "Deferred acceptance guarantees that there is no blocking pair (no person and slot "
            "both prefer each other to what they have, unless the slot is full of people with "
            "higher priority) and that reporting the true ranking is best for the people who "
            "apply. It does not guarantee Pareto efficiency: another assignment may suit "
            "several people better, at the price of ignoring a priority of some slot."
        ),
        "da_nm_priorities": (
            "The priority tiers are rules fixed in advance. The script computes with them as "
            "given. It does not judge whether they are reasonable and cannot check who belongs "
            "in which tier."
        ),
        "da_dm_got": 'You got "{slot}" (your choice number {rank}).',
        "da_dm_none": "You did not get a slot this time.",
        "da_dm_empty": "You listed no acceptable slot, so you got none.",
        "da_dm_why": 'You liked "{slot}" better, but it did not go to you: {reason}.',
        "da_dm_r_ineligible": "it does not accept you (you are not on its priority list)",
        "da_dm_r_tier": "its seats are full of people with higher priority",
        "da_dm_r_lottery": "its seats are full of people in your tier who come earlier in the lottery",
        "da_dm_order": "Your place in the lottery is {pos} (inside a tier, earlier places win ties).",
        "da_g_method": (
            "Method: deferred acceptance (DA), applicants propose. Ties inside a tier follow "
            "the lottery order below."
        ),
        "da_g_order": "Lottery order (earlier wins a tie inside a tier): {text}",
        "da_g_slot": '"{slot}" (seats: {seats}), priority: {text}',
        "da_g_recompute": (
            "Recompute: the source text, the names, the slot count and the rule name are all "
            "above. Take the SHA-256 of the seed preimage for the seed, then shuffle with the "
            "counter to get the lottery order. Run deferred acceptance on everybody's ranking "
            "and the priorities above to check the result. Rankings were handed in privately, "
            "so they can be put together only if everybody agrees, and "
            "python3 scripts/slot_lottery.py --verify checks the same."
        ),
    },
}


def joined(lang: str, items: Sequence[str]) -> str:
    """Names joined with the separator of the language, or the word for none."""
    text = TEXT[lang]
    return text["sep"].join(items) if items else text["none"]


def quoted(lang: str, slot: str) -> str:
    """A slot name in the quotation marks of the language."""
    return f"「{slot}」" if lang == "zh" else f'"{slot}"'


# ---------------------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------------------


@dataclass
class Problem:
    """A validated input."""

    mode: str
    people: list
    n_slots: int
    slot_names: list
    prefs: dict
    source: str | None  # the public text, or None under commit_reveal
    card_source: str | None  # the text the input itself carries when --source replaces it
    description: str
    deadline: str
    non_reveal: str | None
    no_ranking: str | None
    commitments: dict | None  # name -> commitment (64 hex), None without commit_reveal
    reveals: dict | None  # name -> reveal code (32 hex)
    claimed: dict | None  # --verify only
    method: str = "rsd"  # rules.method: rsd, ps or da (rsd mode only)
    capacities: dict = field(default_factory=dict)  # ps and da: slot -> seats, every slot listed
    priorities: dict = field(default_factory=dict)  # da: slot -> tiers (lists of names), as given

    @property
    def rule_name(self) -> str:
        return METHOD_RULE_NAMES.get(self.method) or RULE_NAMES[self.mode]

    @property
    def uses_commit_reveal(self) -> bool:
        return self.commitments is not None

    @property
    def seats(self) -> int:
        """The slot count that goes into the seed: seats in all for ps and da, else n_slots."""
        return sum(self.capacities.values()) if self.method != "rsd" else self.n_slots


def parse_prefs(value: Any, people: list, slot_names: list) -> dict:
    """prefs: person -> that person's acceptable slots, best first."""
    obj = fc.require_object(value, "prefs")
    if not obj:
        raise fc.InputError(
            "prefs", "needs at least one ranking (a person who sent none is left out of it)"
        )
    known = set(people)
    slots = set(slot_names)
    prefs: dict = {}
    for person, ranking in obj.items():
        if person not in known:
            raise fc.InputError(f"prefs.{person}", "is not a person listed in people")
        items = fc.require_list(ranking, f"prefs.{person}", 0, len(slot_names))
        seen: set = set()
        for index, slot in enumerate(items):
            where = f"prefs.{person}[{index}]"
            if not isinstance(slot, str) or slot not in slots:
                raise fc.InputError(where, f"{slot!r} is not one of slot_names")
            if slot in seen:
                raise fc.InputError(where, f"duplicate slot {slot!r}")
            seen.add(slot)
        prefs[person] = list(items)
    return prefs


def parse_capacities(value: Any, slot_names: list) -> dict:
    """capacities: slot -> number of seats (default 1). Returns every slot with its seats."""
    obj = fc.require_object(value, "capacities")
    seats = {slot: 1 for slot in slot_names}
    for slot, count in obj.items():
        if slot not in seats:
            raise fc.InputError(f"capacities.{slot}", "is not one of slot_names")
        seats[slot] = fc.require_int(count, f"capacities.{slot}", 1, MAX_PEOPLE)
    return seats


def parse_priorities(value: Any, people: list, slot_names: list) -> dict:
    """priorities: slot -> tiers, best tier first, each tier a list of names that tie.

    A slot with an entry accepts only the people listed in it. A slot without one accepts
    everybody and everybody ties. Names inside a tier are sorted, so that the order they were
    typed in changes nothing.
    """
    obj = fc.require_object(value, "priorities")
    known = set(people)
    slots = set(slot_names)
    parsed: dict = {}
    for slot, tiers in obj.items():
        if slot not in slots:
            raise fc.InputError(f"priorities.{slot}", "is not one of slot_names")
        rows = fc.require_list(tiers, f"priorities.{slot}", 1)
        seen: set = set()
        clean = []
        for tier_index, tier in enumerate(rows):
            where = f"priorities.{slot}[{tier_index}]"
            names = fc.require_list(tier, where, 1)
            for name_index, name in enumerate(names):
                spot = f"{where}[{name_index}]"
                if not isinstance(name, str) or name not in known:
                    raise fc.InputError(spot, f"{name!r} is not a person listed in people")
                if name in seen:
                    raise fc.InputError(
                        spot, f"{name!r} appears twice in the priorities of {slot!r}"
                    )
                seen.add(name)
            clean.append(sorted(names))
        parsed[slot] = clean
    return parsed


def parse_entries(value: Any, where: str, key: str, pattern: Any, size: int, people: list) -> dict:
    """A list of {name, <key>} entries -> {name: hex text}; each person at most once."""
    entries = fc.require_list(value, where, 1 if key == "commitment" else 0)
    known = set(people)
    found: dict = {}
    for index, entry in enumerate(entries):
        spot = f"{where}[{index}]"
        obj = fc.require_object(entry, spot)
        fc.check_fields(obj, ("name", key), spot)
        name = fc.require_text(obj.get("name"), f"{spot}.name")
        if name not in known:
            raise fc.InputError(f"{spot}.name", f"{name!r} is not a person listed in people")
        if name in found:
            raise fc.InputError(f"{spot}.name", f"{name!r} appears twice")
        text = fc.require_text(obj.get(key), f"{spot}.{key}").strip().lower()
        if pattern.fullmatch(text) is None:
            raise fc.InputError(f"{spot}.{key}", f"must be {size} hexadecimal characters")
        found[name] = text
    return found


def parse_claimed(value: Any, method: str = "rsd") -> dict:
    """The result printed on the card, as far as it is given.

    The order is required, except for the methods ps and da, whose cards are checked by the
    allocation (da may add the lottery order, ps has none).
    """
    obj = fc.require_object(value, "claimed")
    fc.check_fields(obj, CLAIMED_FIELDS, "claimed")
    claimed: dict = {}
    if method == "ps" and "order" in obj:
        raise fc.InputError("claimed.order", "is not used with rules.method ps: it has no order")
    if method != "rsd" and "allocation" not in obj:
        raise fc.InputError(
            "claimed.allocation",
            "is required with rules.method ps or da: the result printed on the card",
        )
    if method == "rsd" or "order" in obj:
        order = fc.require_list(obj.get("order"), "claimed.order", 1)
        for index, name in enumerate(order):
            fc.require_text(name, f"claimed.order[{index}]")
        claimed["order"] = list(order)
    if "seed" in obj:
        seed = fc.require_text(obj["seed"], "claimed.seed").strip().lower()
        if DIGEST_PATTERN.fullmatch(seed) is None:
            raise fc.InputError("claimed.seed", "must be 64 hexadecimal characters")
        claimed["seed"] = seed
    if "allocation" in obj:
        allocation = fc.require_object(obj["allocation"], "claimed.allocation")
        for person, slot in allocation.items():
            if slot is not None:
                fc.require_text(slot, f"claimed.allocation.{person}")
        claimed["allocation"] = dict(allocation)
    return claimed


def parse_problem(
    data: Any, *, verify: bool = False, source_override: str | None = None
) -> Problem:
    """Validate an input object. verify=True is for --verify: claimed is required, the notes
    (deadline, source description) are optional, and source_override replaces random_source."""
    data = fc.require_object(data, "input")
    fc.check_fields(data, TOP_FIELDS, "")
    mode = fc.require_choice(data.get("mode"), "mode", MODES)
    people = fc.require_encodable_names(data.get("people"), "people", 2, MAX_PEOPLE)
    prefs: dict = {}
    if mode == "lottery":
        for name in ("slot_names", "prefs"):
            if name in data:
                raise fc.InputError(name, "is only used in rsd mode (lottery has n_slots)")
        for name in ("capacities", "priorities"):
            if name in data:
                raise fc.InputError(name, "is only used in rsd mode with rules.method ps or da")
        n_slots = fc.require_int(data.get("n_slots"), "n_slots", 1, MAX_PEOPLE)
        slot_names: list = []
    else:
        if "n_slots" in data:
            raise fc.InputError(
                "n_slots", "is not used in rsd mode: the slots are the names in slot_names"
            )
        slot_names = fc.require_encodable_names(data.get("slot_names"), "slot_names", 1, MAX_SLOTS)
        n_slots = len(slot_names)
        prefs = parse_prefs(data.get("prefs"), people, slot_names)

    has_source = "random_source" in data
    has_reveal = "commit_reveal" in data
    if has_source and has_reveal:
        raise fc.InputError("commit_reveal", "give either random_source or commit_reveal, not both")
    source: str | None = None
    card_source: str | None = None
    commitments: dict | None = None
    reveals: dict | None = None
    if source_override is not None:
        if has_reveal:
            raise fc.InputError("--source", "cannot be used with commit_reveal input")
        source = fc.require_source_text(source_override, "--source")
        if has_source:
            card_source = fc.require_source_text(data["random_source"], "random_source")
    elif has_source:
        source = fc.require_source_text(data["random_source"], "random_source")
    elif has_reveal:
        block = fc.require_object(data["commit_reveal"], "commit_reveal")
        fc.check_fields(block, ("commitments", "reveals"), "commit_reveal")
        commitments = parse_entries(
            block.get("commitments"),
            "commit_reveal.commitments",
            "commitment",
            DIGEST_PATTERN,
            64,
            people,
        )
        reveals = parse_entries(
            block.get("reveals"), "commit_reveal.reveals", "reveal", CODE_PATTERN, 32, people
        )
    else:
        raise fc.InputError(
            "random_source",
            "is required: the public text the draw is seeded from, copied exactly "
            "(or give commit_reveal instead)",
        )

    rules = fc.require_object(data.get("rules", {} if verify else None), "rules")
    fc.check_fields(rules, RULE_FIELDS, "rules")
    need_notes = not verify
    deadline = ""
    if "deadline" in rules or need_notes:
        deadline = fc.one_line(rules.get("deadline"), "rules.deadline")
    description = ""
    if "source_description" in rules or (need_notes and commitments is None):
        description = fc.one_line(rules.get("source_description"), "rules.source_description")
    non_reveal: str | None = None
    if commitments is not None:
        non_reveal = fc.require_choice(rules.get("non_reveal"), "rules.non_reveal", HANDLING)
    elif "non_reveal" in rules:
        raise fc.InputError("rules.non_reveal", "is only used with commit_reveal")
    no_ranking: str | None = None
    if mode == "rsd":
        no_ranking = fc.require_choice(rules.get("no_ranking"), "rules.no_ranking", HANDLING)
    elif "no_ranking" in rules:
        raise fc.InputError("rules.no_ranking", "is only used in rsd mode")
    method = "rsd"
    capacities: dict = {}
    priorities: dict = {}
    if "method" in rules:
        if mode != "rsd":
            raise fc.InputError("rules.method", "is only used in rsd mode")
        method = fc.require_choice(rules["method"], "rules.method", METHODS)
    if mode == "rsd" and method == "rsd":
        for name in ("capacities", "priorities"):
            if name in data:
                raise fc.InputError(name, "is only used with rules.method ps or da")
    elif mode == "rsd":
        if commitments is not None:
            raise fc.InputError(
                "commit_reveal",
                "is not available with rules.method ps or da: give random_source instead",
            )
        capacities = parse_capacities(data.get("capacities", {}), slot_names)
        if method == "da":
            priorities = parse_priorities(data.get("priorities", {}), people, slot_names)
        elif "priorities" in data:
            raise fc.InputError("priorities", "is only used with rules.method da")

    claimed: dict | None = None
    if "claimed" in data:
        if not verify:
            raise fc.InputError("claimed", "is only used with --verify; add --verify to check it")
        claimed = parse_claimed(data["claimed"], method)
        if "allocation" in claimed and mode != "rsd":
            raise fc.InputError("claimed.allocation", "is only used in rsd mode")
    elif verify:
        raise fc.InputError(
            "claimed",
            "is required with --verify: the result printed on the card "
            + ("(at least order)" if method == "rsd" else "(at least allocation)"),
        )
    return Problem(
        mode=mode,
        people=people,
        n_slots=n_slots,
        slot_names=slot_names,
        prefs=prefs,
        source=source,
        card_source=card_source,
        description=description,
        deadline=deadline,
        non_reveal=non_reveal,
        no_ranking=no_ranking,
        commitments=commitments,
        reveals=reveals,
        claimed=claimed,
        method=method,
        capacities=capacities,
        priorities=priorities,
    )


# ---------------------------------------------------------------------------------------
# Commitments and reveals
# ---------------------------------------------------------------------------------------


def commit_payload(person: str) -> dict:
    """The text a commitment covers besides the reveal code: whose commitment it is."""
    return {"person": person}


def make_commitment(person: str, code: str | None = None) -> tuple:
    """(commitment, reveal code) for one person.

    The reveal code is a fresh 128-bit value from fsq_core.new_nonce (the system's cryptographic
    random generator) and acts as the nonce of fsq_core.commit. A code can be passed in for
    tests and examples only.
    """
    made = fc.commit(commit_payload(person), code)
    return made.digest, made.nonce


@dataclass
class RevealCheck:
    """What the group's posts show for one person."""

    person: str
    status: str  # ok | no_commitment | no_reveal | mismatch
    commitment: str | None
    reveal: str | None


def check_reveals(problem: Problem) -> list:
    """Check every person's reveal against their commitment, sorted by name."""
    assert problem.commitments is not None and problem.reveals is not None
    checks = []
    for person in sorted(problem.people):
        digest = problem.commitments.get(person)
        code = problem.reveals.get(person)
        if digest is None:
            status = "no_commitment"
        elif code is None:
            status = "no_reveal"
        elif fc.verify_commit(digest, commit_payload(person), code):
            status = "ok"
        else:
            status = "mismatch"
        checks.append(RevealCheck(person, status, digest, code))
    return checks


def reveal_source(verified: dict) -> str:
    """The text that seeds a commit-reveal draw: canonical JSON of {name: reveal code}."""
    return fc.canonical_json(dict(verified))


# ---------------------------------------------------------------------------------------
# The draw
# ---------------------------------------------------------------------------------------


@dataclass
class Draw:
    """One shuffle: the people it covered, the exact seed text and the resulting order."""

    group: str  # main | penalty
    members: list  # sorted by code point
    preimage: str
    seed_hex: str
    order: list


@dataclass
class Turn:
    """One person's turn in the serial dictatorship."""

    position: int
    person: str
    slot: str | None
    rank: int | None  # 1 = first choice; None without a ranking
    passed: list  # slots they ranked higher than their pick, all taken before their turn


@dataclass
class Outcome:
    problem: Problem
    source_text: str
    checks: list
    reasons: dict  # person -> lapse codes
    tier: dict  # person -> main | penalty | out
    draws: list
    order: list
    removed: list  # people out of the draw, sorted
    penalized: list  # people placed by the assigned rule, in queue order
    winners: list  # lottery: the first n_slots of the order
    waiting: list  # people in the queue who got nothing, in order
    allocation: dict  # rsd: person -> slot
    turns: list
    free_slots: list = field(default_factory=list)
    positions: dict = field(init=False)  # person -> place in the order, counted from 1

    def __post_init__(self) -> None:
        self.positions = {person: index for index, person in enumerate(self.order, 1)}


def make_draw(
    group: str, members: Sequence[str], rule_name: str, n_slots: int, source_text: str
) -> Draw:
    """Shuffle members with the seed of (rule, members, n_slots, source text)."""
    drawn = fc.seeded_order(rule_name, members, n_slots, source_text)
    return Draw(group, sorted(members), drawn.preimage, drawn.seed_hex, drawn.order)


def serial_dictatorship(order: Sequence[str], prefs: dict, slot_names: Sequence[str]) -> tuple:
    """People pick in order, each the best free slot of their ranking.

    A person with a ranking only ever takes a slot from it. A person without one (the assigned
    rule for people who sent none) takes the first free slot in slot_names order. Returns
    (allocation, turns, slots nobody took in slot_names order).
    """
    free = set(slot_names)
    allocation: dict = {}
    turns = []
    for position, person in enumerate(order, 1):
        ranking = prefs.get(person)
        candidates = slot_names if ranking is None else ranking
        pick = next((slot for slot in candidates if slot in free), None)
        rank = None
        passed: list = []
        if pick is not None:
            free.discard(pick)
            allocation[person] = pick
        if ranking is not None:
            passed = list(ranking if pick is None else ranking[: ranking.index(pick)])
            if pick is not None:
                rank = ranking.index(pick) + 1
        turns.append(Turn(position, person, pick, rank, passed))
    return allocation, turns, [slot for slot in slot_names if slot in free]


def compute(problem: Problem) -> Outcome | MatchOutcome:
    """Check the reveals, apply the declared rules, then draw."""
    if problem.method != "rsd":
        return compute_match(problem)
    checks: list = []
    if problem.uses_commit_reveal:
        checks = check_reveals(problem)
        verified = {c.person: c.reveal for c in checks if c.status == "ok"}
        if len(verified) < MIN_REVEALS:
            raise fc.NoSolution(
                f"only {len(verified)} of {len(problem.people)} reveals match their commitments; "
                f"at least {MIN_REVEALS} are needed so that no single person decides the draw. "
                "Under the agreed rules there is no draw to run: start again with fresh commitments"
            )
        source_text = reveal_source(verified)
    else:
        assert problem.source is not None
        source_text = problem.source
    status = {c.person: c.status for c in checks}
    handling = {REASON_REVEAL: problem.non_reveal, REASON_RANKING: problem.no_ranking}
    reasons: dict = {}
    tier: dict = {}
    for person in problem.people:
        found = []
        if problem.uses_commit_reveal and status[person] != "ok":
            found.append(REASON_REVEAL)
        if problem.mode == "rsd" and person not in problem.prefs:
            found.append(REASON_RANKING)
        reasons[person] = found
        applied = [handling[reason] for reason in found]
        if "forfeit" in applied:
            tier[person] = "out"
        else:
            tier[person] = "penalty" if applied else "main"
    groups = {name: [p for p in problem.people if tier[p] == name] for name in ("main", "penalty")}
    draws = []
    orders: dict = {"main": [], "penalty": []}
    for name in ("main", "penalty"):
        if groups[name]:
            draw = make_draw(name, groups[name], problem.rule_name, problem.n_slots, source_text)
            draws.append(draw)
            orders[name] = draw.order
    if problem.mode == "lottery":
        order = orders["penalty"] + orders["main"]  # a chore: the people who lapsed come first
    else:
        order = orders["main"] + orders["penalty"]  # picking: the people who lapsed come last
    if not order:
        raise fc.NoSolution("nobody is left to draw after the agreed rules were applied")
    removed = sorted(p for p in problem.people if tier[p] == "out")
    winners: list = []
    allocation: dict = {}
    turns: list = []
    free_slots: list = []
    if problem.mode == "lottery":
        winners = order[: problem.n_slots]
        waiting = order[problem.n_slots :]
    else:
        allocation, turns, free_slots = serial_dictatorship(
            order, problem.prefs, problem.slot_names
        )
        waiting = [person for person in order if person not in allocation]
    return Outcome(
        problem=problem,
        source_text=source_text,
        checks=checks,
        reasons=reasons,
        tier=tier,
        draws=draws,
        order=order,
        removed=removed,
        penalized=orders["penalty"],
        winners=winners,
        waiting=waiting,
        allocation=allocation,
        turns=turns,
        free_slots=free_slots,
    )


# ---------------------------------------------------------------------------------------
# Probabilistic serial (ps): the chances, their decomposition and the draw
# ---------------------------------------------------------------------------------------


@dataclass
class EatStage:
    """One stretch of the eating schedule, in which nobody changes what they eat."""

    start: Fraction
    end: Fraction
    eating: dict  # person -> slot being eaten, None when nothing on the list is left
    used_up: list  # slots that are used up at the end of the stretch, sorted


@dataclass
class Term:
    """One fixed assignment of the decomposition, with its probability."""

    weight: Fraction
    assignment: dict  # person -> slot, None when the person gets no slot in this assignment


def probabilistic_serial(people: Sequence[str], prefs: dict, capacity: dict) -> tuple:
    """The eating algorithm of Bogomolnaia and Moulin (2001), in exact fractions.

    people are the names that take part, prefs maps each of them to the slots they accept, best
    first, and capacity maps every slot to its number of seats. From time 0 to time 1 everybody
    eats at speed 1 from the best slot on their list that is not used up. A slot with k seats is
    used up when k units have been eaten. Time spent with nothing left to eat counts as "no slot".
    Returns (chances, stages): chances[person][slot] and chances[person][None] are exact
    fractions that add up to 1 for each person, and stages lists the EatStage objects.
    """
    remaining = {slot: Fraction(seats) for slot, seats in capacity.items()}
    chances: dict = {person: {slot: Fraction(0) for slot in capacity} for person in people}
    for person in people:
        chances[person][None] = Fraction(0)
    pointer = {person: 0 for person in people}
    now = Fraction(0)
    stages: list = []
    while now < 1:
        target: dict = {}
        for person in people:
            ranking = prefs[person]
            index = pointer[person]
            while index < len(ranking) and remaining[ranking[index]] == 0:
                index += 1
            pointer[person] = index
            target[person] = ranking[index] if index < len(ranking) else None
        eaters = Counter(slot for slot in target.values() if slot is not None)
        span = 1 - now
        for slot, count in eaters.items():
            span = min(span, remaining[slot] / count)
        for person in people:
            chances[person][target[person]] += span
        for slot, count in eaters.items():
            remaining[slot] -= count * span
        used = sorted(slot for slot in eaters if remaining[slot] == 0)
        stages.append(EatStage(now, now + span, dict(target), used))
        now += span
    return chances, stages


def completion_table(people: Sequence[str], slots: Sequence[str], capacity: dict, chances: dict):
    """A square table with every row and column adding up to 1 that holds the chances.

    Birkhoff-von Neumann needs such a table. Columns: for each slot, in the order of slots,
    min(seats, people who have a chance of it) seat columns, each with an equal part of every
    person's chance of the slot. Then one column of their own for "no slot" for every person
    who has a chance of that, in the order of people. Rows: the people, then as many filler rows
    as it takes to make the table square. What the people leave free in a column is poured into
    the filler rows column by column, one unit per row. Returns (table, owners): owners[j] is the
    slot of column j and None for a "no slot" column.
    """
    owners: list = []
    seat_columns: dict = {}
    for slot in slots:
        wanting = sum(1 for person in people if chances[person][slot] > 0)
        for _ in range(min(capacity[slot], wanting)):
            seat_columns.setdefault(slot, []).append(len(owners))
            owners.append(slot)
    none_column: dict = {}
    for person in people:
        if chances[person][None] > 0:
            none_column[person] = len(owners)
            owners.append(None)
    size = len(owners)
    if size < len(people):
        raise AssertionError("the chances of the people need more columns than the table has")
    table = [[Fraction(0)] * size for _ in range(size)]
    for row, person in enumerate(people):
        for slot, columns in seat_columns.items():
            share = chances[person][slot] / len(columns)
            for column in columns:
                table[row][column] = share
        if person in none_column:
            table[row][none_column[person]] = chances[person][None]
    row, room = len(people), Fraction(1)
    for column in range(size):
        rest = 1 - sum(table[r][column] for r in range(len(people)))
        while rest > 0:
            put = min(rest, room)
            table[row][column] += put
            rest -= put
            room -= put
            if room == 0:
                row, room = row + 1, Fraction(1)
    if row != size or room != 1:
        raise AssertionError("the filler rows do not add up to a square table")
    return table, owners


def bvn_decompose(table: list) -> list:
    """Birkhoff-von Neumann: [(weight, columns)] with sum of weight * permutation = table.

    table is a square table of Fractions with every row and column adding up to 1. Each step
    takes a perfect matching in the cells that are still positive, found by the augmenting-path
    search of Kuhn (rows in order, columns in increasing order, the matching of the previous step
    kept where its cells are still positive), gives it the smallest of its cells as its weight
    and subtracts that weight from the cells. At least one cell becomes zero in every step, so the
    loop ends, and it takes no more steps than the table has positive cells.
    columns[row] is the column that the row is matched to.
    """
    size = len(table)
    work = [list(row) for row in table]
    match_row = [-1] * size
    match_col = [-1] * size
    pieces: list = []
    left = Fraction(1)

    def augment(row: int, seen: set) -> bool:
        for column in range(size):
            if work[row][column] > 0 and column not in seen:
                seen.add(column)
                if match_col[column] < 0 or augment(match_col[column], seen):
                    match_row[row] = column
                    match_col[column] = row
                    return True
        return False

    while left > 0:
        for row in range(size):
            if match_row[row] < 0 and not augment(row, set()):
                raise AssertionError("the positive cells of the table have no perfect matching")
        weight = min(work[row][match_row[row]] for row in range(size))
        pieces.append((weight, list(match_row)))
        left -= weight
        for row in range(size):
            column = match_row[row]
            work[row][column] -= weight
            if work[row][column] == 0:
                match_row[row] = -1
                match_col[column] = -1
    return pieces


def decompose_chances(
    people: Sequence[str], slots: Sequence[str], capacity: dict, chances: dict
) -> list:
    """The chances as a convex combination of fixed assignments: a list of Term.

    The table of completion_table is decomposed by bvn_decompose, each piece is read as an
    assignment of the people (a seat column of a slot gives the slot, a "no slot" column gives
    None), pieces with the same assignment are added up, and the terms are listed by falling
    weight, equal weights in the order in which they first came up.
    """
    table, owners = completion_table(people, slots, capacity, chances)
    merged: dict = {}
    for weight, columns in bvn_decompose(table):
        key = tuple(owners[columns[row]] for row in range(len(people)))
        merged[key] = merged.get(key, 0) + weight
    keys = list(merged)
    ranked = sorted(range(len(keys)), key=lambda index: (-merged[keys[index]], index))
    return [Term(merged[keys[i]], dict(zip(people, keys[i]))) for i in ranked]


def check_terms(
    people: Sequence[str], slots: Sequence[str], capacity: dict, chances: dict, terms: list
) -> None:
    """Raise AssertionError unless the terms are fixed assignments that add up to the chances."""
    if sum((term.weight for term in terms), Fraction(0)) != 1:
        raise AssertionError("the weights of the terms do not add up to 1")
    for term in terms:
        if term.weight <= 0:
            raise AssertionError("a term has no positive weight")
        used = Counter(slot for slot in term.assignment.values() if slot is not None)
        if any(count > capacity[slot] for slot, count in used.items()):
            raise AssertionError("a term gives a slot to more people than it has seats")
    for person in people:
        for slot in [*slots, None]:
            got = sum((t.weight for t in terms if t.assignment[person] == slot), Fraction(0))
            if got != chances[person][slot]:
                raise AssertionError("the terms do not add up to the chances")


def envy_violations(people: Sequence[str], prefs: dict, chances: dict) -> list:
    """Pairs (i, j) where, by the ranking of i, person j has a better lottery than i.

    The lottery of j is better for i when, for some prefix of the slots that i accepts, j has a
    larger chance than i of getting a slot in it. Slots that i does not accept rank below "no
    slot" for i, and they never give j a better lottery. Probabilistic serial has none.
    """
    found = []
    for i in people:
        order = [*prefs[i], None]
        for j in people:
            if j == i:
                continue
            mine = Fraction(0)
            theirs = Fraction(0)
            for slot in order:
                mine += chances[i][slot]
                theirs += chances[j][slot]
                if theirs > mine:
                    found.append((i, j))
                    break
    return found


def uniform_below(stream: fc.SeedStream, n: int) -> int:
    """A uniform integer in [0, n) for any n >= 1, from the counter stream.

    For n up to 2**64 this is the rejection sampling of SEED_SPEC. A larger n takes k consecutive
    draws, where k is the least number with n <= 2**(64 k), reads them big-endian as one integer
    x below 2**(64 k), and keeps x mod n if x is below the largest multiple of n that is at most
    2**(64 k), else it draws k new ones.
    """
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise ValueError("n must be a positive int")
    if n <= 1 << 64:
        return stream.below(n)
    words = ((n - 1).bit_length() + 63) // 64
    span = 1 << (64 * words)
    limit = span - span % n
    while True:
        x = 0
        for _ in range(words):
            x = (x << 64) | stream.next_u64()
        if x < limit:
            return x % n


def common_denominator(terms: list) -> int:
    """The least common multiple of the denominators of the weights."""
    modulus = 1
    for term in terms:
        modulus = math.lcm(modulus, term.weight.denominator)
    return modulus


def pick_term(terms: list, modulus: int, x: int) -> tuple:
    """(index, low, high): the term whose stretch [low, high) of 0..modulus-1 holds x.

    Term k owns weight * modulus consecutive numbers, in the order of the list.
    """
    low = 0
    for index, term in enumerate(terms):
        size = term.weight * modulus
        if size.denominator != 1:
            raise AssertionError("the modulus is not a common denominator of the weights")
        high = low + size.numerator
        if x < high:
            return index, low, high
        low = high
    raise AssertionError("the random number is outside every term")


def percent(value: Fraction) -> str:
    """Exact value as a percentage with one decimal, halves going up (1/3 gives 33.3%)."""
    tenths = fc.round_half_up(value * 1000)
    return f"{tenths // 10}.{tenths % 10}%"


def chance_text(value: Fraction, lang: str) -> str:
    """A chance as an exact fraction with its percentage, or 0."""
    if value == 0:
        return "0"
    exact = str(value)
    return f"{exact}（{percent(value)}）" if lang == "zh" else f"{exact} ({percent(value)})"


# ---------------------------------------------------------------------------------------
# Deferred acceptance (da)
# ---------------------------------------------------------------------------------------


@dataclass
class DARound:
    """One round: who applied where, who was turned away and who is on hold afterwards."""

    number: int
    proposals: dict  # person -> slot applied to
    rejections: list  # (person, slot, reason) with reason "ineligible" or "outranked"
    holds: dict  # slot -> people on hold after the round, sorted by name


def priority_key(priorities: dict, position: dict):
    """key(slot, person): (tier, lottery position), smaller is better, None when not accepted.

    A slot with an entry in priorities accepts only the people it lists, the first tier is the
    best. A slot without an entry accepts everybody in one tier. Inside a tier the lottery order
    decides: position[person] is the place of the person in it, counted from 1.
    """
    tier_of = {
        slot: {name: index for index, tier in enumerate(tiers) for name in tier}
        for slot, tiers in priorities.items()
    }

    def key(slot: str, person: str):
        table = tier_of.get(slot)
        if table is None:
            return (0, position[person])
        tier = table.get(person)
        return None if tier is None else (tier, position[person])

    return key


def deferred_acceptance(people: Sequence[str], prefs: dict, capacity: dict, key) -> tuple:
    """Gale and Shapley (1962) with the people applying: returns (allocation, rounds).

    Every round, each person who is not on hold applies to the next slot on their ranking.
    A slot looks at the people it holds and the new applicants together, drops everybody it does
    not accept, keeps the best capacity[slot] by key and turns the rest away. The people who
    were turned away apply to their next slot in the next round, and a person whose ranking is
    used up stops. It ends when nobody applies any more. allocation maps each person who holds a
    slot to it, rounds lists the DARound objects.
    """
    pointer = {person: 0 for person in people}
    held: dict = {slot: [] for slot in capacity}
    waiting = [person for person in people if prefs[person]]
    rounds: list = []
    while waiting:
        proposals = {person: prefs[person][pointer[person]] for person in waiting}
        by_slot: dict = {}
        for person in sorted(proposals):
            by_slot.setdefault(proposals[person], []).append(person)
        rejections: list = []
        for slot in sorted(by_slot):
            pool = held[slot] + by_slot[slot]
            kept = sorted(
                (person for person in pool if key(slot, person) is not None),
                key=lambda person: key(slot, person),
            )[: capacity[slot]]
            for person in sorted(pool):
                if person not in kept:
                    why = "ineligible" if key(slot, person) is None else "outranked"
                    rejections.append((person, slot, why))
            held[slot] = kept
        rounds.append(
            DARound(
                len(rounds) + 1,
                proposals,
                rejections,
                {slot: sorted(holders) for slot, holders in sorted(held.items()) if holders},
            )
        )
        waiting = []
        for person, _, _ in rejections:
            pointer[person] += 1
            if pointer[person] < len(prefs[person]):
                waiting.append(person)
    allocation = {person: slot for slot, holders in held.items() for person in holders}
    return allocation, rounds


def blocking_pairs(
    people: Sequence[str], prefs: dict, capacity: dict, key, allocation: dict
) -> list:
    """Pairs (person, slot) that prefer each other to what they have: none for a stable result.

    A person and a slot block when the slot accepts the person, the person ranks it above their
    own result (or has no result), and the slot has a free seat or holds somebody whom it likes
    less than this person.
    """
    holders: dict = {slot: [] for slot in capacity}
    for person, slot in allocation.items():
        holders[slot].append(person)
    found = []
    for person in people:
        ranking = prefs[person]
        got = allocation.get(person)
        better = ranking if got is None else ranking[: ranking.index(got)]
        for slot in better:
            mine = key(slot, person)
            if mine is None:
                continue
            if len(holders[slot]) < capacity[slot] or any(
                key(slot, other) > mine for other in holders[slot]
            ):
                found.append((person, slot))
    return found


def da_reasons(person: str, prefs: dict, capacity: dict, key, allocation: dict) -> list:
    """For each slot that the person ranks above their result: (slot, why not).

    why is "ineligible" (the slot does not accept the person), "tier" (it is full of people
    in a better tier) or "lottery" (it is full of people in the same tier who come earlier in
    the lottery). In a stable result a slot that blocks nobody is full of people whom it likes
    better, so no other reason can occur.
    """
    ranking = prefs[person]
    got = allocation.get(person)
    better = ranking if got is None else ranking[: ranking.index(got)]
    holders: dict = {}
    for other, slot in allocation.items():
        holders.setdefault(slot, []).append(other)
    reasons = []
    for slot in better:
        mine = key(slot, person)
        if mine is None:
            reasons.append((slot, "ineligible"))
            continue
        full = holders.get(slot, [])
        if len(full) < capacity[slot]:
            raise AssertionError("the result has a blocking pair")
        worst = max(key(slot, other) for other in full)
        if worst > mine:
            raise AssertionError("the result has a blocking pair")
        reasons.append((slot, "tier" if worst[0] < mine[0] else "lottery"))
    return reasons


# ---------------------------------------------------------------------------------------
# Running method ps or da
# ---------------------------------------------------------------------------------------


@dataclass
class PSResult:
    """What method ps produced besides the final assignment."""

    chances: dict  # person -> {slot or None: Fraction}, each row adds up to 1
    stages: list  # EatStage objects
    terms: list  # Term objects in the order the draw uses
    modulus: int  # the random number lies in 0 .. modulus - 1
    number: int  # the random number from the counter stream
    index: int  # the term that holds the number, counted from 0
    low: int  # the stretch of that term is low .. high - 1
    high: int


@dataclass
class DAResult:
    """What method da produced besides the final assignment."""

    order: list  # the lottery order of the people who took part (earlier wins a tie in a tier)
    rounds: list  # DARound objects
    reasons: dict  # person -> [(slot, why)] for every slot they rank above their result


@dataclass
class MatchOutcome:
    """The outcome of method ps or da."""

    problem: Problem
    source_text: str
    reasons: dict  # person -> lapse codes (only no_ranking can occur)
    tier: dict  # person -> main | penalty | out
    draws: list  # Draw objects: the main one, then the one of the people who take what is left
    people: list  # the people who took part (they sent a ranking), sorted
    removed: list  # people out of the draw, sorted
    penalized: list  # people who take what is left, in the order drawn for them
    allocation: dict  # person -> slot for everybody who has one
    unassigned: list  # people in the draw without a slot, sorted
    free_seats: dict  # slot -> seats that nobody took, only slots that have any, in slot order
    ps: PSResult | None = None
    da: DAResult | None = None
    order: list = field(default_factory=list)  # da: lottery order of the people, then penalized
    positions: dict = field(init=False)

    def __post_init__(self) -> None:
        self.positions = {person: index for index, person in enumerate(self.order, 1)}


def table_size(people: Sequence[str], slots: Sequence[str], capacity: dict, chances: dict) -> int:
    """The side of the square table that completion_table builds for these chances."""
    seat_columns = sum(
        min(capacity[slot], sum(1 for person in people if chances[person][slot] > 0))
        for slot in slots
    )
    return seat_columns + sum(1 for person in people if chances[person][None] > 0)


def run_ps(problem: Problem, people: list, source_text: str) -> tuple:
    """Method ps for the people with a ranking: (draw, PSResult, assignment of the term drawn)."""
    if len(people) > MAX_PS_PEOPLE:
        raise fc.InputError(
            "people",
            f"method ps handles at most {MAX_PS_PEOPLE} people who sent a ranking, "
            f"got {len(people)}",
        )
    slots = sorted(problem.slot_names)
    chances, stages = probabilistic_serial(people, problem.prefs, problem.capacities)
    size = table_size(people, slots, problem.capacities, chances)
    if size > MAX_PS_TABLE:
        raise fc.InputError(
            "rules.method",
            f"ps needs a table of {size} by {size} cells for this input and handles at most "
            f"{MAX_PS_TABLE} by {MAX_PS_TABLE}: fewer people, fewer slots or fewer seats",
        )
    terms = decompose_chances(people, slots, problem.capacities, chances)
    check_terms(people, slots, problem.capacities, chances, terms)
    if envy_violations(people, problem.prefs, chances):
        raise AssertionError("a person would prefer the lottery of somebody else")
    modulus = common_denominator(terms)
    seats = problem.seats
    seed = fc.make_seed(problem.rule_name, people, seats, source_text)
    number = uniform_below(fc.SeedStream(seed), modulus)
    index, low, high = pick_term(terms, modulus, number)
    draw = Draw(
        "main",
        sorted(people),
        fc.seed_preimage(problem.rule_name, people, seats, source_text),
        seed.hex(),
        [],
    )
    result = PSResult(chances, stages, terms, modulus, number, index, low, high)
    return draw, result, terms[index].assignment


def run_da(problem: Problem, people: list, source_text: str) -> tuple:
    """Method da for the people with a ranking: (draw, DAResult, allocation)."""
    if len(people) > MAX_DA_PEOPLE:
        raise fc.InputError(
            "people",
            f"method da handles at most {MAX_DA_PEOPLE} people who sent a ranking, "
            f"got {len(people)}",
        )
    draw = make_draw("main", people, problem.rule_name, problem.seats, source_text)
    position = {person: index for index, person in enumerate(draw.order, 1)}
    key = priority_key(problem.priorities, position)
    allocation, rounds = deferred_acceptance(people, problem.prefs, problem.capacities, key)
    if blocking_pairs(people, problem.prefs, problem.capacities, key, allocation):
        raise AssertionError("the result has a blocking pair")
    reasons = {
        person: da_reasons(person, problem.prefs, problem.capacities, key, allocation)
        for person in people
    }
    return draw, DAResult(list(draw.order), rounds, reasons), allocation


def compute_match(problem: Problem) -> MatchOutcome:
    """Method ps or da. The people with a ranking take part. A person without one is out
    (forfeit) or takes, after the draw, the first slot with a free seat in the order of
    slot_names (assigned), in an order drawn for them."""
    assert problem.source is not None
    source_text = problem.source
    reasons: dict = {}
    tier: dict = {}
    for person in problem.people:
        reasons[person] = [] if person in problem.prefs else [REASON_RANKING]
        if person in problem.prefs:
            tier[person] = "main"
        else:
            tier[person] = "out" if problem.no_ranking == "forfeit" else "penalty"
    people = sorted(p for p in problem.people if tier[p] == "main")
    penalty = [p for p in problem.people if tier[p] == "penalty"]
    removed = sorted(p for p in problem.people if tier[p] == "out")
    if not people:
        raise fc.NoSolution("nobody is left to draw after the agreed rules were applied")
    ps: PSResult | None = None
    da: DAResult | None = None
    if problem.method == "ps":
        draw, ps, fixed = run_ps(problem, people, source_text)
        allocation = {person: slot for person, slot in fixed.items() if slot is not None}
    else:
        draw, da, allocation = run_da(problem, people, source_text)
    draws = [draw]
    taken = Counter(allocation.values())
    penalized: list = []
    if penalty:
        late = make_draw("penalty", penalty, problem.rule_name, problem.seats, source_text)
        draws.append(late)
        penalized = late.order
        for person in penalized:
            slot = next((s for s in problem.slot_names if taken[s] < problem.capacities[s]), None)
            if slot is not None:
                allocation[person] = slot
                taken[slot] += 1
    unassigned = sorted(p for p in problem.people if tier[p] != "out" and p not in allocation)
    free = {
        slot: problem.capacities[slot] - taken[slot]
        for slot in problem.slot_names
        if taken[slot] < problem.capacities[slot]
    }
    return MatchOutcome(
        problem=problem,
        source_text=source_text,
        reasons=reasons,
        tier=tier,
        draws=draws,
        people=people,
        removed=removed,
        penalized=penalized,
        allocation=allocation,
        unassigned=unassigned,
        free_seats=free,
        ps=ps,
        da=da,
        order=(da.order + penalized) if da is not None else [],
    )


# ---------------------------------------------------------------------------------------
# Verification of a result card
# ---------------------------------------------------------------------------------------


@dataclass
class VerifyCheck:
    name: str  # order | seed | allocation | source
    ok: bool
    detail: str


def verify_checks(outcome: Outcome | MatchOutcome, lang: str) -> list:
    """Compare every part of problem.claimed that was given with the recomputation."""
    problem = outcome.problem
    claimed = problem.claimed
    assert claimed is not None
    text = TEXT[lang]
    checks = []
    if problem.card_source is not None:
        same = problem.card_source == problem.source
        checks.append(VerifyCheck("source", same, text["v_source_ok" if same else "v_source_bad"]))
    if "order" in claimed:  # always for lottery and rsd, optional for da, never for ps
        card = claimed["order"]
        calc = outcome.order
        if card == calc:
            checks.append(VerifyCheck("order", True, text["v_order_ok"].format(n=len(calc))))
        elif sorted(card) != sorted(calc):
            extra = sorted((Counter(card) - Counter(calc)).elements())
            missing = sorted((Counter(calc) - Counter(card)).elements())
            detail = text["v_order_names"].format(
                extra=joined(lang, extra), missing=joined(lang, missing)
            )
            checks.append(VerifyCheck("order", False, detail))
        else:
            index = next(i for i, (a, b) in enumerate(zip(card, calc)) if a != b)
            detail = text["v_order_pos"].format(pos=index + 1, card=card[index], calc=calc[index])
            checks.append(VerifyCheck("order", False, detail))
    if "seed" in claimed:
        main = outcome.draws[0].seed_hex
        ok = claimed["seed"] == main
        detail = (
            text["v_seed_ok"] if ok else text["v_seed_bad"].format(card=claimed["seed"], calc=main)
        )
        checks.append(VerifyCheck("seed", ok, detail))
    if "allocation" in claimed:
        card_alloc = claimed["allocation"]
        bad = None
        for person in sorted(set(card_alloc) | set(outcome.allocation)):
            if card_alloc.get(person) != outcome.allocation.get(person):
                bad = person
                break
        if bad is None:
            checks.append(VerifyCheck("allocation", True, text["v_alloc_ok"]))
        else:
            none = text["v_alloc_none"]
            detail = text["v_alloc_bad"].format(
                person=bad,
                card=card_alloc.get(bad) or none,
                calc=outcome.allocation.get(bad) or none,
            )
            checks.append(VerifyCheck("allocation", False, detail))
    return checks


# ---------------------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------------------


def reason_text(lang: str, reasons: Sequence[str]) -> str:
    text = TEXT[lang]
    return text["reason_sep"].join(text[f"reason_{code}"] for code in reasons)


def status_label(outcome: Outcome, person: str, lang: str) -> str:
    """The result column of the lottery's order table."""
    text = TEXT[lang]
    n_slots = outcome.problem.n_slots
    position = outcome.positions[person]
    if position <= n_slots:
        label = text["st_drawn"]
    else:
        label = text["st_waiting"].format(k=position - n_slots)
    if outcome.tier[person] == "penalty":
        label += text["st_front"]
    return label


def turn_why(turn: Turn, problem: Problem, waiting_index: int, lang: str) -> str:
    """The explanation column of the pick table."""
    text = TEXT[lang]
    ranked = turn.person in problem.prefs
    if turn.slot is not None:
        if not ranked:
            return text["why_left"]
        if turn.rank == 1:
            return text["why_rank1"]
        joiner = "" if lang == "zh" else ", "
        passed = joiner.join(quoted(lang, slot) for slot in turn.passed)
        return text["why_rank"].format(rank=turn.rank, passed=passed)
    if not ranked:
        return text["why_left_none"].format(k=waiting_index)
    if not problem.prefs[turn.person]:
        return text["why_empty"].format(k=waiting_index)
    return text["why_gone"].format(k=waiting_index)


def waiting_indices(outcome: Outcome) -> dict:
    return {person: k for k, person in enumerate(outcome.waiting, 1)}


def order_tables(outcome: Outcome, lang: str) -> list:
    """The tables of the md output: the order or the picks, then the slots."""
    text = TEXT[lang]
    problem = outcome.problem
    tables = []
    if problem.mode == "lottery":
        rows = [
            [str(index), person, status_label(outcome, person, lang)]
            for index, person in enumerate(outcome.order, 1)
        ]
        caption = text["cap_order"].format(slots=problem.n_slots)
        tables.append(fc.Table(text["hdr_order"], rows, caption))
        return tables
    wait = waiting_indices(outcome)
    rows = []
    for turn in outcome.turns:
        got = quoted(lang, turn.slot) if turn.slot is not None else text["pick_none"]
        why = turn_why(turn, problem, wait.get(turn.person, 0), lang)
        if outcome.tier[turn.person] == "penalty":
            why += text["st_back"]
        rows.append([str(turn.position), turn.person, got, why])
    tables.append(fc.Table(text["hdr_turns"], rows, text["cap_turns"]))
    holder = {slot: person for person, slot in outcome.allocation.items()}
    slot_rows = [[slot, holder.get(slot, text["slot_free"])] for slot in problem.slot_names]
    tables.append(fc.Table(text["hdr_slots"], slot_rows, text["cap_slots"]))
    return tables


def group_label(name: str, lang: str) -> str:
    return TEXT[lang][f"group_{name}"]


def source_tables(outcome: Outcome, lang: str) -> list:
    """Where the randomness came from and everything needed to recompute the order."""
    text = TEXT[lang]
    problem = outcome.problem
    tables = []
    single = len(outcome.draws) == 1
    for number, draw in enumerate(outcome.draws):
        rows = []
        if number == 0:
            if problem.description:
                rows.append([text["f_description"], problem.description])
            if problem.deadline:
                rows.append([text["f_deadline"], problem.deadline])
            key = "f_source_reveal" if problem.uses_commit_reveal else "f_source"
            rows.append([text[key], outcome.source_text])
        rows += [
            [text["f_rule"], problem.rule_name],
            [text["f_slots"], str(problem.n_slots)],
            [text["f_people"], ", ".join(draw.members)],
            [text["f_preimage"], draw.preimage],
            [text["f_seed"], draw.seed_hex],
        ]
        if not single:
            rows.append([text["f_order"], ", ".join(draw.order)])
        caption = (
            text["cap_source"]
            if single
            else text["cap_source_draw"].format(group=group_label(draw.group, lang))
        )
        tables.append(fc.Table(text["hdr_facts"], rows, caption))
    return tables


def reveal_table(outcome: Outcome, lang: str) -> fc.Table | None:
    if not outcome.checks:
        return None
    text = TEXT[lang]
    rows = []
    for check in outcome.checks:
        rows.append(
            [
                check.person,
                (check.commitment or "")[:12],
                (check.reveal or "")[:12],
                text[f"rv_{check.status}"],
            ]
        )
    return fc.Table(text["hdr_reveals"], rows, text["cap_reveals"])


def lapse_effect(problem: Problem, lang: str) -> str:
    """What the declared non-reveal rule does, in words."""
    text = TEXT[lang]
    if problem.non_reveal == "forfeit":
        return text["eff_forfeit"]
    return text["eff_assigned_lottery" if problem.mode == "lottery" else "eff_assigned_rsd"]


def summary_notes(outcome: Outcome, lang: str) -> list:
    """Short paragraphs under the tables: who is drawn, who waits, who lapsed."""
    text = TEXT[lang]
    problem = outcome.problem
    notes = []
    if problem.mode == "lottery":
        notes.append(text["n_drawn"].format(names=joined(lang, outcome.winners)))
        if outcome.waiting:
            notes.append(text["n_waiting"].format(names=joined(lang, outcome.waiting)))
        else:
            notes.append(text["n_all_drawn"])
    else:
        if outcome.waiting:
            notes.append(text["n_unplaced"].format(names=joined(lang, outcome.waiting)))
        if outcome.free_slots:
            notes.append(
                text["n_free_slots"].format(
                    names=joined(lang, [quoted(lang, s) for s in outcome.free_slots])
                )
            )
    lapsed: dict = {}
    for person in problem.people:
        if outcome.reasons[person]:
            lapsed.setdefault(tuple(outcome.reasons[person]), []).append(person)
    for codes, names in sorted(lapsed.items()):
        notes.append(
            text["n_lapse"].format(
                names=joined(lang, sorted(names)), reasons=reason_text(lang, codes)
            )
        )
    if outcome.removed:
        notes.append(text["n_out"].format(names=joined(lang, outcome.removed)))
    if outcome.penalized:
        key = "n_front" if problem.mode == "lottery" else "n_back"
        notes.append(text[key].format(names=joined(lang, outcome.penalized)))
    return notes


def not_modeled(problem: Problem, lang: str) -> list:
    text = TEXT[lang]
    items = [text["nm_source"], text["nm_frozen"]]
    if problem.mode == "rsd":
        items.append(text["nm_ranking"])
    else:
        items.append(text["nm_waiting"])
    if problem.uses_commit_reveal:
        items.append(text["nm_commit"])
    return items


def person_lines(outcome: Outcome, lang: str) -> dict:
    """The private message of every person, holding only their own result."""
    text = TEXT[lang]
    problem = outcome.problem
    lines: dict = {}
    wait = waiting_indices(outcome)
    total = len(outcome.order)
    turns = {turn.person: turn for turn in outcome.turns}
    queue = list(outcome.order) + outcome.removed
    for person in queue:
        reasons = reason_text(lang, outcome.reasons[person])
        position = outcome.positions.get(person)
        tier = outcome.tier[person]
        if tier == "out":
            lines[person] = [text["dm_out"].format(reasons=reasons)]
            if problem.mode == "rsd" and person in problem.prefs:
                lines[person].append(ranking_line(problem, person, lang))
            continue
        prefix = ""
        if tier == "penalty" and REASON_REVEAL in outcome.reasons[person]:
            key = "dm_front" if problem.mode == "lottery" else "dm_back"
            said = reason_text(lang, [REASON_REVEAL])
            prefix = text[key].format(reasons=said) + (" " if lang == "en" else "")
        if problem.mode == "lottery":
            if position <= problem.n_slots:
                line = text["dm_drawn"].format(pos=position, slots=problem.n_slots, people=total)
            else:
                line = text["dm_waiting"].format(
                    pos=position, k=position - problem.n_slots, slots=problem.n_slots, people=total
                )
            lines[person] = [prefix + line]
            continue
        turn = turns[person]
        ranked = person in problem.prefs
        if turn.slot is not None:
            if ranked:
                line = text["dm_picked"].format(pos=position, slot=turn.slot, rank=turn.rank)
            else:
                line = text["dm_left"].format(pos=position, slot=turn.slot)
        else:
            k = wait[person]
            if not ranked:
                line = text["dm_left_none"].format(pos=position, k=k)
            elif not problem.prefs[person]:
                line = text["dm_empty"].format(pos=position, k=k)
            else:
                line = text["dm_unplaced"].format(pos=position, k=k)
        lines[person] = [prefix + line]
        if ranked:
            lines[person].append(ranking_line(problem, person, lang))
    return lines


def ranking_line(problem: Problem, person: str, lang: str) -> str:
    text = TEXT[lang]
    ranking = problem.prefs[person]
    shown = text["rank_sep"].join(ranking) if ranking else text["none"]
    return text["dm_ranking"].format(ranking=shown)


def group_lines(outcome: Outcome, lang: str) -> list:
    """The card for the group chat: the order and how to verify it, nothing private."""
    text = TEXT[lang]
    problem = outcome.problem
    lines = []
    if problem.description:
        lines.append(text["g_description"].format(text=problem.description))
    if problem.deadline:
        lines.append(text["g_deadline"].format(text=problem.deadline))
    key = "g_source_reveal" if problem.uses_commit_reveal else "g_source"
    lines.append(text[key].format(text=outcome.source_text))
    if len(outcome.draws) == 1:
        draw = outcome.draws[0]
        lines.append(text["g_preimage"].format(text=draw.preimage))
        lines.append(text["g_seed"].format(seed=draw.seed_hex))
    else:
        for draw in outcome.draws:
            lines.append(
                text["g_draw_label"].format(group=group_label(draw.group, lang), text=draw.preimage)
            )
            lines.append(text["g_seed"].format(seed=draw.seed_hex))
    if problem.mode == "lottery":
        shown = text["sep"].join(f"{i} {name}" for i, name in enumerate(outcome.order, 1))
        lines.append(text["g_order"].format(text=shown))
        lines.append(
            text["g_drawn"].format(slots=problem.n_slots, names=joined(lang, outcome.winners))
        )
        if outcome.waiting:
            lines.append(text["g_waiting"].format(names=joined(lang, outcome.waiting)))
        else:
            lines.append(text["g_all_drawn"])
    else:
        lines.append(text["g_queue"])
        wait = waiting_indices(outcome)
        for turn in outcome.turns:
            if turn.slot is not None:
                lines.append(
                    text["g_pick"].format(pos=turn.position, name=turn.person, slot=turn.slot)
                )
            else:
                lines.append(
                    text["g_waiting_line"].format(
                        pos=turn.position, name=turn.person, k=wait[turn.person]
                    )
                )
        if outcome.free_slots:
            lines.append(
                text["g_free_slots"].format(
                    names=joined(lang, [quoted(lang, s) for s in outcome.free_slots])
                )
            )
    if outcome.removed:
        removed_reasons = sorted({r for p in outcome.removed for r in outcome.reasons[p]})
        lines.append(
            text["g_out"].format(
                reasons=reason_text(lang, removed_reasons), names=joined(lang, outcome.removed)
            )
        )
    if outcome.penalized:
        lines.append(
            text["g_front" if problem.mode == "lottery" else "g_back"].format(
                names=joined(lang, outcome.penalized)
            )
        )
    if outcome.checks:
        good = sum(1 for c in outcome.checks if c.status == "ok")
        lines.append(text["g_reveal_ok"].format(ok=good))
        bad = [c.person for c in outcome.checks if c.status != "ok"]
        if bad:
            lines.append(text["g_reveal_bad"].format(bad=joined(lang, bad)))
        lines.append(text["warn_commit"])
    lines.append(text["g_recompute"])
    return lines


def inputs_echo(problem: Problem, outcome: Outcome) -> dict:
    echo: dict = {
        "mode": problem.mode,
        "participants": sorted(problem.people),
        "n_slots": problem.n_slots,
        "randomness": "commit_reveal" if problem.uses_commit_reveal else "public_source",
    }
    if problem.deadline:
        echo["deadline"] = problem.deadline
    if problem.description:
        echo["source_description"] = problem.description
    if problem.mode == "rsd":
        echo["slot_names"] = list(problem.slot_names)
        echo["prefs"] = {person: list(problem.prefs[person]) for person in sorted(problem.prefs)}
        echo["no_ranking"] = problem.no_ranking
    if problem.uses_commit_reveal:
        echo["non_reveal"] = problem.non_reveal
    else:
        echo["random_source"] = problem.source
    return echo


def result_json(outcome: Outcome) -> dict:
    problem = outcome.problem
    result: dict = {
        "rule": problem.rule_name,
        "order": list(outcome.order),
        "positions": outcome.positions,
        "waiting": list(outcome.waiting),
        "seed_hex": outcome.draws[0].seed_hex,
        "source_text": outcome.source_text,
        "draws": [
            {
                "group": draw.group,
                "participants": draw.members,
                "seed_preimage": draw.preimage,
                "seed_hex": draw.seed_hex,
                "order": list(draw.order),
            }
            for draw in outcome.draws
        ],
        "removed": list(outcome.removed),
        "placed_by_rule": list(outcome.penalized),
        "lapses": {
            person: {"reasons": list(codes), "tier": outcome.tier[person]}
            for person, codes in sorted(outcome.reasons.items())
            if codes
        },
    }
    if problem.mode == "lottery":
        result["winners"] = list(outcome.winners)
    else:
        result["allocation"] = {p: outcome.allocation[p] for p in sorted(outcome.allocation)}
        result["unassigned_slots"] = list(outcome.free_slots)
        result["turns"] = [
            {
                "position": turn.position,
                "person": turn.person,
                "slot": turn.slot,
                "rank": turn.rank,
                "passed_over": list(turn.passed),
            }
            for turn in outcome.turns
        ]
    return result


def build_result(
    outcome: Outcome | MatchOutcome, lang: str = "zh", reproduce: str = ""
) -> fc.Result:
    """Turn an outcome into the shared Result (md, dm, group and json all come from it)."""
    if isinstance(outcome, MatchOutcome):
        return build_match_result(outcome, lang, reproduce)
    if lang not in TEXT:
        raise ValueError(f"lang must be one of {', '.join(TEXT)}")
    text = TEXT[lang]
    problem = outcome.problem
    title_key = "title_lottery" if problem.mode == "lottery" else "title_rsd"
    title = text[title_key].format(people=len(problem.people), slots=problem.n_slots)
    tables = order_tables(outcome, lang)
    notes = summary_notes(outcome, lang)
    table = reveal_table(outcome, lang)
    tables += source_tables(outcome, lang)
    if table is not None:
        tables.append(table)
        notes.append(text["n_reveal_source"])
        notes.append(
            text["n_reveal_rule"].format(
                rule=problem.non_reveal, effect=lapse_effect(problem, lang)
            )
        )
        notes.append(text["warn_commit"])
    if any("|" in draw.preimage for draw in outcome.draws):
        notes.append(text["n_pipe"])
    notes.append(text["n_algo"])
    notes.append(text["n_verify"])
    lines = person_lines(outcome, lang)
    certificate: dict = {
        "one_liner": {person: " ".join(rows) for person, rows in lines.items()},
        "recompute": {
            "source_text": outcome.source_text,
            "algorithm": fc.SEED_SPEC,
            "seeds": {draw.group: draw.seed_hex for draw in outcome.draws},
        },
    }
    if outcome.checks:
        certificate["reveal_check"] = {
            check.person: {
                "status": check.status,
                "commitment": check.commitment,
                "reveal": check.reveal,
            }
            for check in outcome.checks
        }
    return fc.Result(
        title=title,
        inputs_echo=inputs_echo(problem, outcome),
        result=result_json(outcome),
        certificate=certificate,
        not_modeled=not_modeled(problem, lang),
        reproduce=reproduce,
        tables=tables,
        notes=notes,
        person_lines=lines,
        group_lines=group_lines(outcome, lang),
    )


# ---------------------------------------------------------------------------------------
# Output of methods ps and da
# ---------------------------------------------------------------------------------------


def holders_of(outcome: MatchOutcome) -> dict:
    """slot -> the people who hold it, sorted by name."""
    held: dict = {}
    for person in sorted(outcome.allocation):
        held.setdefault(outcome.allocation[person], []).append(person)
    return held


def seats_cell(outcome: MatchOutcome, slot: str, lang: str) -> str:
    """Who holds a slot, with a note when seats are free."""
    text = TEXT[lang]
    names = holders_of(outcome).get(slot, [])
    if not names:
        return text["m_slot_free"]
    cell = joined(lang, names)
    free = outcome.free_seats.get(slot, 0)
    if free:
        cell += fc.fill_text(lang, text["m_free_seats"], free=free)
    return cell


def match_slot_table(outcome: MatchOutcome, lang: str) -> fc.Table:
    text = TEXT[lang]
    problem = outcome.problem
    rows = [
        [slot, str(problem.capacities[slot]), seats_cell(outcome, slot, lang)]
        for slot in problem.slot_names
    ]
    return fc.Table(text["m_hdr_slots"], rows, text["cap_slots"])


def assignment_text(lang: str, assignment: dict) -> str:
    """The people who have a slot in an assignment, as 'name -> slot' joined by the separator."""
    parts = [
        f"{person} → {quoted(lang, slot)}"
        for person, slot in sorted(assignment.items())
        if slot is not None
    ]
    return joined(lang, parts)


def ps_tables(outcome: MatchOutcome, lang: str) -> list:
    """The chances, the decomposition, the draw and the eating schedule of method ps."""
    text = TEXT[lang]
    problem = outcome.problem
    ps = outcome.ps
    assert ps is not None
    rows = [
        [
            person,
            *[chance_text(ps.chances[person][slot], lang) for slot in problem.slot_names],
            chance_text(ps.chances[person][None], lang),
        ]
        for person in outcome.people
    ]
    header = [text["ps_hdr_name"], *problem.slot_names, text["ps_none"]]
    tables = [fc.Table(header, rows, text["ps_cap_matrix"])]
    rows = [
        [str(number), chance_text(term.weight, lang), assignment_text(lang, term.assignment)]
        for number, term in enumerate(ps.terms, 1)
    ]
    caption = fc.fill_text(lang, text["ps_cap_terms"], k=len(ps.terms))
    tables.append(fc.Table(text["ps_hdr_terms"], rows, caption))
    rows = [
        [
            text["ps_f_modulus"],
            fc.fill_text(lang, text["ps_v_modulus"], last=ps.modulus - 1, count=ps.modulus),
        ],
        [text["ps_f_number"], str(ps.number)],
        [
            text["ps_f_term"],
            fc.fill_text(
                lang,
                text["ps_v_term" if ps.high - ps.low > 1 else "ps_v_term_one"],
                k=ps.index + 1,
                first=ps.low,
                last=ps.high - 1,
            ),
        ],
    ]
    tables.append(fc.Table(text["hdr_facts"], rows, text["ps_cap_draw"]))
    rows = []
    for stage in ps.stages:
        eating = [
            f"{person} → " + (quoted(lang, slot) if slot is not None else text["ps_eat_nothing"])
            for person, slot in sorted(stage.eating.items())
        ]
        used = joined(lang, [quoted(lang, slot) for slot in stage.used_up])
        rows.append([str(stage.start), str(stage.end), text["sep"].join(eating), used])
    tables.append(fc.Table(text["ps_hdr_eating"], rows, text["ps_cap_eating"]))
    return tables


def priority_text(outcome: MatchOutcome, slot: str, lang: str) -> str:
    """The priority tiers of a slot in words, and who it does not accept."""
    text = TEXT[lang]
    tiers = outcome.problem.priorities.get(slot)
    if tiers is None:
        return text["da_prio_all"]
    parts = [
        fc.fill_text(lang, text["da_prio_tier"], k=number, names=joined(lang, tier))
        for number, tier in enumerate(tiers, 1)
    ]
    listed = {name for tier in tiers for name in tier}
    excluded = sorted(p for p in outcome.problem.people if p not in listed)
    if excluded:
        parts.append(fc.fill_text(lang, text["da_prio_excluded"], names=joined(lang, excluded)))
    return text["da_prio_sep"].join(parts)


def reason_phrases(lang: str, reasons: list, prefix: str) -> str:
    """The reasons of da_reasons as short phrases, joined by the separator of the language."""
    text = TEXT[lang]
    return text["da_reason_sep"].join(
        fc.fill_text(lang, text[f"{prefix}{why}"], slot=slot) for slot, why in reasons
    )


def da_tables(outcome: MatchOutcome, lang: str) -> list:
    """The result with reasons, the slots with their priorities, and the rounds of method da."""
    text = TEXT[lang]
    problem = outcome.problem
    da = outcome.da
    assert da is not None
    colon = "：" if lang == "zh" else ": "
    rows = []
    for person in outcome.order:
        position = outcome.positions[person]
        got = outcome.allocation.get(person)
        if person in da.reasons:
            ranking = problem.prefs[person]
            reasons = reason_phrases(lang, da.reasons[person], "da_r_")
            if got is not None and ranking.index(got) == 0:
                why = text["da_why_rank1"]
            elif got is not None:
                why = fc.fill_text(
                    lang, text["da_why_rank"], rank=ranking.index(got) + 1, reasons=reasons
                )
            elif not ranking:
                why = text["da_why_empty"]
            else:
                why = fc.fill_text(lang, text["da_why_none"], reasons=reasons)
        else:
            why = text["why_left"] if got is not None else text["m_why_late_none"]
        shown = quoted(lang, got) if got is not None else text["pick_none"]
        rows.append([str(position), person, shown, why])
    tables = [fc.Table(text["da_hdr_result"], rows, text["da_cap_result"])]
    rows = [
        [
            slot,
            str(problem.capacities[slot]),
            priority_text(outcome, slot, lang),
            seats_cell(outcome, slot, lang),
        ]
        for slot in problem.slot_names
    ]
    tables.append(fc.Table(text["da_hdr_slots"], rows, text["da_cap_slots"]))
    rows = []
    for round_ in da.rounds:
        applications = [
            f"{person} → {quoted(lang, slot)}" for person, slot in sorted(round_.proposals.items())
        ]
        turned = []
        for person, slot, why in round_.rejections:
            shown = text[f"da_rej_{why}"]
            turned.append(
                f"{person}（{quoted(lang, slot)}，{shown}）"
                if lang == "zh"
                else f"{person} ({quoted(lang, slot)}, {shown})"
            )
        holds = [
            f"{quoted(lang, slot)}{colon}{joined(lang, names)}"
            for slot, names in sorted(round_.holds.items())
        ]
        rows.append(
            [
                str(round_.number),
                text["sep"].join(applications),
                text["sep"].join(turned) if turned else text["none"],
                text["da_hold_sep"].join(holds) if holds else text["none"],
            ]
        )
    tables.append(fc.Table(text["da_hdr_rounds"], rows, text["da_cap_rounds"]))
    return tables


def match_source_tables(outcome: MatchOutcome, lang: str) -> list:
    """Where the randomness came from and everything needed to recompute the draws."""
    text = TEXT[lang]
    problem = outcome.problem
    tables = []
    single = len(outcome.draws) == 1
    for number, draw in enumerate(outcome.draws):
        rows = []
        if number == 0:
            if problem.description:
                rows.append([text["f_description"], problem.description])
            if problem.deadline:
                rows.append([text["f_deadline"], problem.deadline])
            rows.append([text["f_source"], outcome.source_text])
        rows += [
            [text["f_rule"], problem.rule_name],
            [text["f_slots"], str(problem.seats)],
            [text["f_people"], ", ".join(draw.members)],
            [text["f_preimage"], draw.preimage],
            [text["f_seed"], draw.seed_hex],
        ]
        if draw.order:
            label = text["m_f_order"] if draw.group == "main" else text["f_order"]
            rows.append([label, ", ".join(draw.order)])
        caption = (
            text["cap_source"]
            if single
            else text["cap_source_draw"].format(group=group_label(draw.group, lang))
        )
        tables.append(fc.Table(text["hdr_facts"], rows, caption))
    return tables


def match_notes(outcome: MatchOutcome, lang: str) -> list:
    """Short paragraphs under the tables: who has no slot, who lapsed, how the method works."""
    text = TEXT[lang]
    problem = outcome.problem
    notes = []
    if outcome.unassigned:
        notes.append(text["m_n_unassigned"].format(names=joined(lang, outcome.unassigned)))
    else:
        notes.append(text["m_n_all_assigned"])
    if outcome.free_seats:
        shown = [
            quoted(lang, slot) + fc.fill_text(lang, text["m_free_seats"], free=free)
            for slot, free in outcome.free_seats.items()
        ]
        notes.append(text["m_n_free"].format(names=joined(lang, shown)))
    lapsed: dict = {}
    for person in problem.people:
        if outcome.reasons[person]:
            lapsed.setdefault(tuple(outcome.reasons[person]), []).append(person)
    for codes, names in sorted(lapsed.items()):
        notes.append(
            text["n_lapse"].format(
                names=joined(lang, sorted(names)), reasons=reason_text(lang, codes)
            )
        )
    if outcome.removed:
        notes.append(text["n_out"].format(names=joined(lang, outcome.removed)))
    if outcome.penalized:
        notes.append(text["m_n_late"].format(names=joined(lang, outcome.penalized)))
    if outcome.ps is not None:
        notes += [text["ps_n_method"], text["ps_n_draw"]]
    else:
        notes += [text["da_n_method"], text["da_n_tie"]]
    if any("|" in draw.preimage for draw in outcome.draws):
        notes.append(text["n_pipe"])
    notes += [text["ps_n_algo" if outcome.ps is not None else "n_algo"], text["n_verify"]]
    return notes


def match_not_modeled(outcome: MatchOutcome, lang: str) -> list:
    text = TEXT[lang]
    items = [text["nm_source"], text["nm_frozen"], text["ps_nm_ranking"]]
    if outcome.ps is not None:
        items.append(text["ps_nm_strategy"])
    else:
        items += [text["da_nm_priorities"], text["da_nm_guarantee"]]
    items.append(text["m_nm_waiting"])
    return items


def chances_line(outcome: MatchOutcome, person: str, lang: str) -> str:
    """The person's own chances in the order of their ranking, then 'no slot'."""
    text = TEXT[lang]
    ps = outcome.ps
    assert ps is not None
    row = ps.chances[person]
    gap = "" if lang == "zh" else " "
    parts = [
        f"{quoted(lang, slot)}{gap}{chance_text(row[slot], lang)}"
        for slot in outcome.problem.prefs[person]
        if row[slot] > 0
    ]
    if row[None] > 0:
        parts.append(f"{text['ps_none_dm']} {chance_text(row[None], lang)}")
    return fc.fill_text(lang, text["ps_dm_chances"], chances=text["m_chance_sep"].join(parts))


def match_person_lines(outcome: MatchOutcome, lang: str) -> dict:
    """The private message of every person, holding only their own result."""
    text = TEXT[lang]
    problem = outcome.problem
    lines: dict = {}
    method = "ps" if outcome.ps is not None else "da"
    penalized = {person: index for index, person in enumerate(outcome.penalized, 1)}
    main_order = outcome.order[: len(outcome.people)] if method == "da" else outcome.people
    for person in [*main_order, *outcome.penalized, *outcome.removed]:
        got = outcome.allocation.get(person)
        if outcome.tier[person] == "out":
            reasons = reason_text(lang, outcome.reasons[person])
            lines[person] = [fc.fill_text(lang, text["m_dm_out"], reasons=reasons)]
            continue
        if outcome.tier[person] == "penalty":
            key = "m_dm_left" if got is not None else "m_dm_left_none"
            lines[person] = [fc.fill_text(lang, text[key], pos=penalized[person], slot=got or "")]
            continue
        ranking = problem.prefs[person]
        if got is not None:
            result = fc.fill_text(
                lang, text[f"{method}_dm_got"], slot=got, rank=ranking.index(got) + 1
            )
        else:
            result = text[f"{method}_dm_none" if ranking else f"{method}_dm_empty"]
        rows = [result]
        if method == "ps":
            if ranking:
                rows.append(chances_line(outcome, person, lang))
                rows.append(text["ps_dm_envy"])
        else:
            assert outcome.da is not None
            rows.append(fc.fill_text(lang, text["da_dm_order"], pos=outcome.positions[person]))
            for slot, why in outcome.da.reasons[person]:
                reason = text[f"da_dm_r_{why}"]
                rows.append(fc.fill_text(lang, text["da_dm_why"], slot=slot, reason=reason))
        rows.append(ranking_line(problem, person, lang))
        lines[person] = rows
    return lines


def match_group_lines(outcome: MatchOutcome, lang: str) -> list:
    """The card for the group chat: the result and how to recompute the draw, no ranking."""
    text = TEXT[lang]
    problem = outcome.problem
    lines = []
    if problem.description:
        lines.append(text["g_description"].format(text=problem.description))
    if problem.deadline:
        lines.append(text["g_deadline"].format(text=problem.deadline))
    lines.append(text["g_source"].format(text=outcome.source_text))
    if len(outcome.draws) == 1:
        draw = outcome.draws[0]
        lines.append(text["g_preimage"].format(text=draw.preimage))
        lines.append(text["g_seed"].format(seed=draw.seed_hex))
    else:
        for draw in outcome.draws:
            lines.append(
                text["g_draw_label"].format(group=group_label(draw.group, lang), text=draw.preimage)
            )
            lines.append(text["g_seed"].format(seed=draw.seed_hex))
    if outcome.ps is not None:
        lines.append(text["ps_g_method"])
        lines.append(
            fc.fill_text(
                lang, text["ps_g_draw"], last=outcome.ps.modulus - 1, number=outcome.ps.number
            )
        )
    else:
        assert outcome.da is not None
        lines.append(text["da_g_method"])
        shown = text["sep"].join(f"{i} {name}" for i, name in enumerate(outcome.da.order, 1))
        lines.append(text["da_g_order"].format(text=shown))
        for slot in problem.slot_names:
            lines.append(
                fc.fill_text(
                    lang,
                    text["da_g_slot"],
                    slot=slot,
                    seats=problem.capacities[slot],
                    text=priority_text(outcome, slot, lang),
                )
            )
    lines.append(text["m_g_result"])
    for person in sorted(outcome.allocation):
        lines.append(
            fc.fill_text(lang, text["m_g_got"], name=person, slot=outcome.allocation[person])
        )
    if outcome.unassigned:
        lines.append(text["m_g_none"].format(names=joined(lang, outcome.unassigned)))
    if outcome.free_seats:
        shown = [
            quoted(lang, slot) + fc.fill_text(lang, text["m_free_seats"], free=free)
            for slot, free in outcome.free_seats.items()
        ]
        lines.append(text["m_g_free"].format(names=joined(lang, shown)))
    if outcome.removed:
        removed_reasons = sorted({r for p in outcome.removed for r in outcome.reasons[p]})
        lines.append(
            text["g_out"].format(
                reasons=reason_text(lang, removed_reasons), names=joined(lang, outcome.removed)
            )
        )
    if outcome.penalized:
        lines.append(text["m_g_late"].format(names=joined(lang, outcome.penalized)))
    lines.append(text["ps_g_recompute" if outcome.ps is not None else "da_g_recompute"])
    return lines


def match_inputs_echo(problem: Problem) -> dict:
    echo: dict = {
        "mode": problem.mode,
        "method": problem.method,
        "participants": sorted(problem.people),
        "n_slots": problem.n_slots,
        "seats": problem.seats,
        "randomness": "public_source",
        "slot_names": list(problem.slot_names),
        "capacities": {slot: problem.capacities[slot] for slot in problem.slot_names},
        "prefs": {person: list(problem.prefs[person]) for person in sorted(problem.prefs)},
        "no_ranking": problem.no_ranking,
        "random_source": problem.source,
    }
    if problem.deadline:
        echo["deadline"] = problem.deadline
    if problem.description:
        echo["source_description"] = problem.description
    if problem.method == "da":
        echo["priorities"] = {
            slot: [list(tier) for tier in tiers] for slot, tiers in problem.priorities.items()
        }
    return echo


def match_result_json(outcome: MatchOutcome) -> dict:
    problem = outcome.problem
    result: dict = {
        "method": problem.method,
        "rule": problem.rule_name,
        "allocation": {person: outcome.allocation[person] for person in sorted(outcome.allocation)},
        "unassigned_people": list(outcome.unassigned),
        "free_seats": dict(outcome.free_seats),
        "seed_hex": outcome.draws[0].seed_hex,
        "source_text": outcome.source_text,
        "draws": [
            {
                "group": draw.group,
                "participants": draw.members,
                "seed_preimage": draw.preimage,
                "seed_hex": draw.seed_hex,
                "order": list(draw.order),
            }
            for draw in outcome.draws
        ],
        "removed": list(outcome.removed),
        "placed_by_rule": list(outcome.penalized),
        "lapses": {
            person: {"reasons": list(codes), "tier": outcome.tier[person]}
            for person, codes in sorted(outcome.reasons.items())
            if codes
        },
    }
    if outcome.ps is not None:
        result["drawn_term"] = outcome.ps.index + 1
        result["random_number"] = outcome.ps.number
    else:
        result["order"] = list(outcome.order)
        result["positions"] = outcome.positions
    return result


def ps_certificate(outcome: MatchOutcome) -> dict:
    """The table of chances, the eating schedule, the decomposition and the draw of method ps."""
    ps = outcome.ps
    assert ps is not None
    people = outcome.people
    return {
        "probabilities": {
            person: {
                "slots": {
                    slot: str(chance)
                    for slot, chance in ps.chances[person].items()
                    if slot is not None and chance > 0
                },
                "no_slot": str(ps.chances[person][None]),
            }
            for person in people
        },
        "eating": [
            {
                "from": str(stage.start),
                "to": str(stage.end),
                "eating": dict(sorted(stage.eating.items())),
                "used_up": list(stage.used_up),
            }
            for stage in ps.stages
        ],
        "decomposition": [
            {"weight": str(term.weight), "assignment": dict(sorted(term.assignment.items()))}
            for term in ps.terms
        ],
        "draw": {
            "modulus": ps.modulus,
            "random_number": ps.number,
            "term": ps.index + 1,
            "first": ps.low,
            "last": ps.high - 1,
        },
        "checks": {
            "terms_add_up_to_the_chances": True,
            "pairs_checked_for_envy": len(people) * (len(people) - 1),
            "pairs_with_envy": [],
        },
    }


def da_certificate(outcome: MatchOutcome) -> dict:
    """The priorities, the lottery order, the rounds and the stability check of method da."""
    da = outcome.da
    assert da is not None
    return {
        "capacities": {
            slot: outcome.problem.capacities[slot] for slot in outcome.problem.slot_names
        },
        "priorities": {
            slot: [list(tier) for tier in tiers]
            for slot, tiers in outcome.problem.priorities.items()
        },
        "tie_break_order": list(da.order),
        "rounds": [
            {
                "round": round_.number,
                "proposals": dict(sorted(round_.proposals.items())),
                "rejections": [
                    {"person": person, "slot": slot, "reason": why}
                    for person, slot, why in round_.rejections
                ],
                "holds": {slot: list(names) for slot, names in round_.holds.items()},
            }
            for round_ in da.rounds
        ],
        "why_not": {
            person: [{"slot": slot, "why": why} for slot, why in reasons]
            for person, reasons in sorted(da.reasons.items())
        },
        "stable": True,
        "blocking_pairs": [],
    }


def build_match_result(outcome: MatchOutcome, lang: str = "zh", reproduce: str = "") -> fc.Result:
    """Turn the outcome of method ps or da into the shared Result."""
    if lang not in TEXT:
        raise ValueError(f"lang must be one of {', '.join(TEXT)}")
    text = TEXT[lang]
    problem = outcome.problem
    title = text[f"m_title_{problem.method}"].format(
        people=len(problem.people), slots=len(problem.slot_names)
    )
    if outcome.ps is not None:
        tables = [match_slot_table(outcome, lang), *ps_tables(outcome, lang)]
    else:
        tables = da_tables(outcome, lang)
    tables += match_source_tables(outcome, lang)
    lines = match_person_lines(outcome, lang)
    certificate: dict = {
        "one_liner": {person: " ".join(rows) for person, rows in lines.items()},
        "recompute": {
            "source_text": outcome.source_text,
            "algorithm": fc.SEED_SPEC,
            "seeds": {draw.group: draw.seed_hex for draw in outcome.draws},
        },
    }
    certificate.update(
        ps_certificate(outcome) if outcome.ps is not None else da_certificate(outcome)
    )
    return fc.Result(
        title=title,
        inputs_echo=match_inputs_echo(problem),
        result=match_result_json(outcome),
        certificate=certificate,
        not_modeled=match_not_modeled(outcome, lang),
        reproduce=reproduce,
        tables=tables,
        notes=match_notes(outcome, lang),
        person_lines=lines,
        group_lines=match_group_lines(outcome, lang),
    )


def solve(data: Any, lang: str = "zh", reproduce: str = "") -> fc.Result:
    """Validate, draw and build the Result for one input object."""
    return build_result(compute(parse_problem(data)), lang, reproduce)


def verify_result(
    data: Any,
    lang: str = "zh",
    reproduce: str = "",
    source_override: str | None = None,
) -> tuple:
    """Recompute the draw and compare it with data["claimed"]. Returns (Result, matched)."""
    if lang not in TEXT:
        raise ValueError(f"lang must be one of {', '.join(TEXT)}")
    problem = parse_problem(data, verify=True, source_override=source_override)
    outcome = compute(problem)
    checks = verify_checks(outcome, lang)
    matched = all(check.ok for check in checks)
    text = TEXT[lang]
    rows = [
        [text[f"v_{check.name}"], text["v_ok" if check.ok else "v_bad"], check.detail]
        for check in checks
    ]
    tables = [fc.Table(text["hdr_verify"], rows, text["cap_verify"])]
    if not matched and "order" in problem.claimed:
        card = problem.claimed["order"]
        width = max(len(card), len(outcome.order))
        order_rows = []
        for index in range(width):
            a = card[index] if index < len(card) else ""
            b = outcome.order[index] if index < len(outcome.order) else ""
            order_rows.append([str(index + 1), a, b, text["v_ok" if a == b else "v_bad"]])
        tables.append(fc.Table(text["hdr_verify_order"], order_rows))
    conclusion = text["v_pass" if matched else "v_fail"]
    title = text["t_verify_ok" if matched else "t_verify_bad"]
    details: dict = {
        "match": matched,
        "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in checks],
        "recomputed_order": list(outcome.order),
        "seed_hex": outcome.draws[0].seed_hex,
    }
    if isinstance(outcome, MatchOutcome):
        details["recomputed_allocation"] = {
            p: outcome.allocation[p] for p in sorted(outcome.allocation)
        }
        echo = match_inputs_echo(problem)
        modeled = match_not_modeled(outcome, lang)
    else:
        echo = inputs_echo(problem, outcome)
        modeled = not_modeled(problem, lang)
    result = fc.Result(
        title=title,
        inputs_echo=echo,
        result=details,
        certificate={"conclusion": conclusion},
        not_modeled=modeled,
        reproduce=reproduce,
        tables=tables,
        notes=[conclusion],
        group_lines=[conclusion],
    )
    return result, matched


# ---------------------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------------------


def run_commit(args: argparse.Namespace) -> int:
    """--commit: make one person's commitment and reveal code and print both."""
    if args.person is None:
        raise fc.InputError("--person", "is required with --commit: whose commitment this is")
    person = fc.encodable(fc.require_text(args.person, "--person"), "--person")
    if person != person.strip():
        raise fc.InputError("--person", "must not have leading or trailing spaces")
    digest, code = make_commitment(person)
    payload = commit_payload(person)
    if args.json:
        record = {"commitment": digest, "payload": payload, "person": person, "reveal": code}
        sys.stdout.write(fc.canonical_json(record) + "\n")
        return 0
    text = TEXT[args.lang]
    lines = [
        line.format(digest=digest, code=code, payload=fc.canonical_json(payload))
        for line in text["commit_lines"]
    ]
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


def reproduce_command(args: argparse.Namespace) -> str:
    parts = ["python3", "scripts/slot_lottery.py"]
    parts += ["--demo"] if args.demo else ["--input", "-"]
    if args.verify:
        parts.append("--verify")
        if args.source is not None:
            parts += ["--source", shlex.quote(args.source)]
    parts += ["--json"] if args.json else ["--format", args.format]
    if args.lang != "zh":
        parts += ["--lang", args.lang]
    return " ".join(parts)


GOLDEN_ORDER = ["Yuki", "小周", "大刘", "Coco", "小红", "阿明", "Mia", "老王"]
GOLDEN_SEED_PREFIX = "15b9c53a44270857eb442863"


def selftest_checks() -> list:
    """Checks for --selftest: the recorded golden values and the rules of the script."""

    def demo_data() -> dict:
        return fc.parse_input(DEMO_JSON)

    def golden_lottery() -> None:
        out = compute(parse_problem(demo_data()))
        fc.expect(out.draws[0].seed_hex.startswith(GOLDEN_SEED_PREFIX), "golden seed")
        fc.expect(out.order == GOLDEN_ORDER, f"golden order {out.order}")
        fc.expect(out.winners == ["Yuki", "小周", "大刘"], "golden winners")

    def preimage_is_what_is_hashed() -> None:
        out = compute(parse_problem(demo_data()))
        digest = hashlib.sha256(out.draws[0].preimage.encode("utf-8")).hexdigest()
        fc.expect(digest == out.draws[0].seed_hex, "the printed preimage must hash to the seed")

    def golden_rsd() -> None:
        people = ["阿明", "小红", "大刘", "Coco", "老王", "Yuki"]
        slots = ["国庆后一周", "春节前一周", "五一", "端午"]
        ranks = {
            "阿明": [1, 0, 2, 3],
            "小红": [1, 2, 0, 3],
            "大刘": [0, 1, 3, 2],
            "Coco": [1, 0, 3, 2],
            "老王": [2, 1, 0, 3],
            "Yuki": [1, 3, 2, 0],
        }
        data = demo_data()
        data.update(mode="rsd", people=people, slot_names=slots)
        del data["n_slots"]
        data["prefs"] = {p: [slots[i] for i in r] for p, r in ranks.items()}
        data["rules"] = dict(data["rules"], no_ranking="forfeit")
        out = compute(parse_problem(data))
        fc.expect(out.order == ["阿明", "大刘", "Yuki", "Coco", "老王", "小红"], f"rsd {out.order}")
        fc.expect(
            out.allocation
            == {"阿明": "春节前一周", "大刘": "国庆后一周", "Yuki": "端午", "Coco": "五一"},
            f"allocation {out.allocation}",
        )
        fc.expect(out.waiting == ["老王", "小红"], "waiting list")

    def reveal_data(rule: str, revealing: list, tampered: list) -> dict:
        people = ["甲", "乙", "丙", "丁"]
        made = {p: make_commitment(p) for p in people}
        reveals = [
            {"name": p, "reveal": "0" * 32 if p in tampered else made[p][1]} for p in revealing
        ]
        return {
            "mode": "lottery",
            "people": people,
            "n_slots": 2,
            "rules": {"deadline": "d", "non_reveal": rule},
            "commit_reveal": {
                "commitments": [{"name": p, "commitment": made[p][0]} for p in people],
                "reveals": reveals,
            },
        }

    def forfeit_rule() -> None:
        out = compute(parse_problem(reveal_data("forfeit", ["甲", "乙", "丙"], ["丙"])))
        statuses = {c.person: c.status for c in out.checks}
        fc.expect(
            statuses == {"丁": "no_reveal", "丙": "mismatch", "乙": "ok", "甲": "ok"}, "status"
        )
        fc.expect(out.removed == sorted(["丙", "丁"]), f"forfeited {out.removed}")
        fc.expect(sorted(out.order) == ["乙", "甲"], "only verified people are drawn")

    def assigned_rule() -> None:
        out = compute(parse_problem(reveal_data("assigned", ["甲", "乙", "丙"], [])))
        fc.expect(out.order[0] == "丁" and "丁" in out.winners, "the non-revealer is placed first")
        fc.expect(sorted(out.order[1:]) == ["丙", "乙", "甲"], "the others follow")

    def too_few_reveals() -> None:
        try:
            compute(parse_problem(reveal_data("forfeit", ["甲"], [])))
        except fc.NoSolution:
            return
        raise AssertionError("one verified reveal must not be enough")

    def no_randomness_is_refused() -> None:
        data = demo_data()
        del data["random_source"]
        try:
            parse_problem(data)
        except fc.InputError as err:
            fc.expect(err.field == "random_source", err.field)
        else:
            raise AssertionError("a draw without a random source was accepted")

    def order_does_not_depend_on_listing() -> None:
        data = demo_data()
        data["people"] = list(reversed(data["people"]))
        fc.expect(compute(parse_problem(data)).order == GOLDEN_ORDER, "listing order")

    classic_prefs = {"A": list("abcd"), "B": list("abcd"), "C": list("badc"), "D": list("badc")}

    def classic_data(method: str) -> dict:
        data = demo_data()
        data.update(mode="rsd", people=list("ABCD"), slot_names=list("abcd"))
        del data["n_slots"]
        data["prefs"] = {person: list(ranking) for person, ranking in classic_prefs.items()}
        data["random_source"] = "（虚构示例）classic"
        data["rules"] = dict(data["rules"], no_ranking="forfeit", method=method)
        return data

    def ps_beats_rsd_on_the_classic_example() -> None:
        out = compute(parse_problem(classic_data("ps")))
        assert out.ps is not None
        fc.expect(out.ps.chances["A"]["a"] == Fraction(1, 2), "ps: A gets a with chance 1/2")
        fc.expect(out.ps.chances["C"]["b"] == Fraction(1, 2), "ps: C gets b with chance 1/2")
        slots = list("abcd")
        orders = list(itertools.permutations("ABCD"))
        wins = sum(
            serial_dictatorship(list(order), classic_prefs, slots)[0].get("A") == "a"
            for order in orders
        )
        fc.expect(Fraction(wins, len(orders)) == Fraction(5, 12), "rsd: A gets a with chance 5/12")

    def ps_decomposition_adds_up() -> None:
        out = compute(parse_problem(classic_data("ps")))
        assert out.ps is not None
        slots = list("abcd")
        capacity = {slot: 1 for slot in slots}
        check_terms(out.people, slots, capacity, out.ps.chances, out.ps.terms)
        fc.expect([t.weight for t in out.ps.terms] == [Fraction(1, 2)] * 2, "two terms of 1/2")
        fc.expect(not envy_violations(out.people, classic_prefs, out.ps.chances), "no envy")

    def ps_seats_and_unassigned_places() -> None:
        people = ["p", "q", "r", "s"]
        slots = ["x", "y"]
        prefs = {"p": ["x", "y"], "q": ["x", "y"], "r": ["x"], "s": ["x"]}
        capacity = {"x": 2, "y": 1}
        chances, _ = probabilistic_serial(people, prefs, capacity)
        terms = decompose_chances(people, slots, capacity, chances)
        check_terms(people, slots, capacity, chances, terms)
        fc.expect(chances["r"][None] > 0, "r can be left without a slot")
        fc.expect(not envy_violations(people, prefs, chances), "no envy")

    def ps_draw_follows_the_counter_stream() -> None:
        out = compute(parse_problem(classic_data("ps")))
        assert out.ps is not None
        seed = bytes.fromhex(out.draws[0].seed_hex)
        raw = int.from_bytes(hashlib.sha256(seed + (0).to_bytes(8, "big")).digest()[:8], "big")
        limit = 2**64 - 2**64 % out.ps.modulus
        fc.expect(raw < limit, "the first draw is not rejected in this example")
        fc.expect(out.ps.number == raw % out.ps.modulus, "the random number is x mod D")
        fixed = out.ps.terms[out.ps.index].assignment
        fc.expect(out.allocation == {p: s for p, s in fixed.items() if s is not None}, "the term")

    def draw_above_two_to_the_64() -> None:
        seed = hashlib.sha256(b"selftest").digest()
        modulus = 2**70 + 1
        stream = fc.SeedStream(seed)
        high, low = stream.next_u64(), stream.next_u64()
        x = (high << 64) | low
        fc.expect(x < 2**128 - 2**128 % modulus, "the first two draws are not rejected")
        fc.expect(uniform_below(fc.SeedStream(seed), modulus) == x % modulus, "two draws")

    def da_has_no_blocking_pair() -> None:
        out = compute(parse_problem(classic_data("da")))
        assert out.da is not None
        key = priority_key({}, {p: i for i, p in enumerate(out.da.order, 1)})
        capacity = {slot: 1 for slot in "abcd"}
        fc.expect(
            not blocking_pairs(out.people, classic_prefs, capacity, key, out.allocation), "stable"
        )
        expected = fc.draw_order("da_tiebreak_v1", list("ABCD"), 4, "（虚构示例）classic")
        fc.expect(out.da.order == expected, "the lottery order uses the shared seed mapping")

    def da_priorities_beat_the_lottery() -> None:
        data = classic_data("da")
        data.update(
            people=["m", "n"],
            slot_names=["z"],
            prefs={"m": ["z"], "n": ["z"]},
            priorities={"z": [["n"], ["m"]]},
        )
        out = compute(parse_problem(data))
        fc.expect(out.allocation == {"n": "z"}, "the higher tier wins whatever the lottery says")

    return [
        ("golden lottery", golden_lottery),
        ("seed preimage hashes to the seed", preimage_is_what_is_hashed),
        ("golden serial dictatorship", golden_rsd),
        ("commit-reveal: forfeit", forfeit_rule),
        ("commit-reveal: assigned", assigned_rule),
        ("commit-reveal: at least two reveals", too_few_reveals),
        ("no randomness is refused", no_randomness_is_refused),
        ("listing order is irrelevant", order_does_not_depend_on_listing),
        ("ps: 1/2 against 5/12 on the classic example", ps_beats_rsd_on_the_classic_example),
        ("ps: the decomposition adds up to the chances", ps_decomposition_adds_up),
        ("ps: seats and unassigned places", ps_seats_and_unassigned_places),
        ("ps: the draw follows the counter stream", ps_draw_follows_the_counter_stream),
        ("ps: a random number above 2^64", draw_above_two_to_the_64),
        ("da: no blocking pair, shared seed mapping", da_has_no_blocking_pair),
        ("da: a higher tier beats the lottery", da_priorities_beat_the_lottery),
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="slot_lottery.py",
        description=(
            "Draw limited slots with a lottery anyone can recompute. Reads one JSON object "
            "(mode, people, n_slots or slot_names with prefs, random_source or commit_reveal, "
            "rules) from standard input or --input FILE. The random numbers come only from the "
            "public source text through SHA-256, never from the random module."
        ),
        epilog=(
            "mode lottery: n_slots identical slots, the first n_slots of the order are drawn, "
            "the rest are the waiting list. mode rsd: slot_names and prefs (person to the "
            "acceptable slots, best first), people pick in the random order. rules.method in "
            "mode rsd: rsd (the default), ps (probabilistic serial, decomposed into fixed "
            "assignments, one drawn) or da (deferred acceptance with priorities); ps and da "
            "also take capacities (seats per slot), da takes priorities (tiers per slot). "
            "rules: deadline, "
            "source_description (with random_source), non_reveal forfeit or assigned (with "
            "commit_reveal), no_ranking forfeit or assigned (rsd). "
        )
        + fc.exit_codes_epilog(
            one="a --verify mismatch or a failed self-test",
            three="the agreed rules leave no draw to run",
        ),
    )
    fc.standard_args(parser)
    fc.add_lang_option(parser, "JSON keys and names do not change")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="recompute the draw from the input and compare it with the input's claimed result "
        "(claimed.order, optionally claimed.seed and claimed.allocation; with rules.method ps "
        "or da claimed.allocation is required and claimed.order is optional, for da only); "
        "exit 0 on a match, 1 otherwise",
    )
    parser.add_argument(
        "--source",
        metavar="TEXT",
        help="--verify: use this published source text instead of the input's random_source, "
        "copied exactly from where it was published",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="make one person's commitment and reveal code on this device and print both "
        "(needs --person; run it yourself, not through the organizer)",
    )
    parser.add_argument("--person", metavar="NAME", help="--commit: whose commitment to make")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    fc.exclusive_modes(args, "--demo", "--selftest", "--commit", "--verify")
    if args.person is not None and not args.commit:
        raise fc.InputError("options", "--person belongs to --commit")
    if args.source is not None and not args.verify:
        raise fc.InputError("options", "--source belongs to --verify")
    if args.selftest:
        return fc.run_selftest(selftest_checks())
    if args.commit:
        return run_commit(args)
    data = fc.read_object(args, DEMO_JSON)
    reproduce = reproduce_command(args)
    if args.verify:
        if args.format == "dm":
            raise fc.InputError("--format", "dm is not available with --verify")
        result, matched = verify_result(data, args.lang, reproduce, args.source)
        fc.emit(result, args, lang=args.lang)
        return 0 if matched else 1
    fc.emit(solve(data, args.lang, reproduce), args, lang=args.lang)
    return 0


if __name__ == "__main__":
    fc.run_cli(main)
