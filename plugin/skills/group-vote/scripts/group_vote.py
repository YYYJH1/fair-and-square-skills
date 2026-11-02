"""Count a group vote under rules that were fixed before anyone voted. Exact integers only.

A vote is described by the options, the ballots and the rules:

  ballots         ranked ballots, {"count": 8, "ranking": ["A", "B"]}. A ranking may stop early
                  (a partial ballot), see rules.partial. A ballot with a "voter" name is one
                  person's ballot and gets a private receipt in --format dm.
  approvals       approval ballots, {"count": 3, "approve": ["A", "C"]}.
  approval_counts the totals of a chat poll, {"A": 12, "B": 9}. Counted as approval voting.
  csv             a questionnaire export pasted as text: one column per option holding the rank
                  (ranking rules) or a 1 (approval), one row per person.
  rules           method (plurality, runoff, irv, borda, condorcet, schulze, approval or
                  kemeny), partial (reject, or tie_last: the options a ballot leaves out tie
                  for last on it) and tie_break {"random_source": "..."}.

Every tie is broken by one order of the options that is fixed in advance: the options are
shuffled with a SHA-256 counter stream seeded by the public random source (fsq_core.shuffle),
and the option that comes first wins a tie. Without a random source a tie exits with code 3.
Condorcet and Schulze always agree on the winner: condorcet names the Condorcet winner when
there is one and falls back to Schulze, schulze is the Schulze method itself. Borda points are
kept doubled inside, so that the halves a partial ballot can create stay exact.

Input is JSON on standard input (--input -). Output is --format md|dm|group or --json. With
--all-rules the script also shows what every other rule would have chosen, to explain a result
after the fact. With --remove OPTION it counts again without that option. Exit code 0 means
success, 2 invalid input (the message names the field), 3 a tie that the agreed rules cannot
break. Standard library only, Python 3.9+.
"""

from __future__ import annotations

import argparse
import csv
import io
import itertools
import shlex
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import fsq_core as fc
except ModuleNotFoundError:  # python -I, -P and PYTHONSAFEPATH leave the script folder off sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import fsq_core as fc

# ---------------------------------------------------------------------------------------
# Limits, defaults and fixed names
# ---------------------------------------------------------------------------------------

METHODS = ("plurality", "runoff", "irv", "borda", "condorcet", "schulze", "approval", "kemeny")
RANKED_METHODS = tuple(name for name in METHODS if name != "approval")
PARTIAL_POLICIES = ("reject", "tie_last")
BALLOT_SOURCES = ("ballots", "approvals", "approval_counts", "csv")
TOP_FIELDS = ("topic", "options", "participants", "rules") + BALLOT_SOURCES
RULE_FIELDS = ("method", "partial", "tie_break", "random_source")
BALLOT_FIELDS = ("count", "voter")

MAX_OPTIONS = 20
MAX_KEMENY_OPTIONS = 8  # the exact Kemeny search is over subsets, 2**8 of them
MAX_BALLOT_LINES = 20000
MAX_COUNT = 10**6
MAX_LABEL = 80
MAX_SOURCE = 500
MAX_SHOWN_LINES = 30  # ballot lines listed in the md output (the json lists all)

TIE_RULE_NAME = "group_vote_tie_order_v1"
TIE_SLOTS = 1  # one winner, so a single slot in the seed

DEMO_SOURCE = "（虚构示例）2026-11-08 某公开开奖号码 03 11 19 24 33 + 02 07"
DEMO_JSON = (
    '{"topic": "团建去哪儿", '
    '"options": ["密室逃脱", "爬山", "剧本杀", "火锅", "KTV"], '
    '"ballots": ['
    '{"count": 8, "ranking": ["密室逃脱", "爬山", "KTV", "火锅", "剧本杀"]}, '
    '{"count": 6, "ranking": ["火锅", "KTV", "剧本杀", "爬山", "密室逃脱"]}, '
    '{"count": 4, "ranking": ["KTV", "火锅", "密室逃脱", "爬山", "剧本杀"]}, '
    '{"count": 2, "ranking": ["爬山", "剧本杀", "火锅", "密室逃脱", "KTV"]}, '
    '{"count": 7, "ranking": ["剧本杀", "爬山", "KTV", "火锅", "密室逃脱"]}], '
    '"rules": {"method": "condorcet", "tie_break": {"random_source": "' + DEMO_SOURCE + '"}}}'
)

Line = tuple[int, tuple[int, ...]]  # (number of identical ballots, option indices in order)


# ---------------------------------------------------------------------------------------
# Texts (zh is the default, en is the same content)
# ---------------------------------------------------------------------------------------

TEXT: dict[str, dict[str, Any]] = {
    "zh": {
        "sep": "、",
        "gt": " > ",
        "nothing": "（不赞成任何选项）",
        "default_topic": "投票",
        "title": "{topic}：{method}",
        "title_recount": "{topic}：去掉{removed}后重新计票，按{method}",
        "method": {
            "plurality": "相对多数",
            "runoff": "两轮决选",
            "irv": "即时决选（IRV）",
            "borda": "博达计分",
            "condorcet": "孔多塞（Schulze 补全）",
            "schulze": "Schulze 法",
            "approval": "认可投票",
            "kemeny": "Kemeny 排名",
        },
        "method_short": {
            "plurality": "相对多数",
            "runoff": "两轮决选",
            "irv": "即时决选",
            "borda": "博达计分",
            "condorcet": "孔多塞",
            "schulze": "Schulze",
            "approval": "认可投票",
            "kemeny": "Kemeny",
        },
        # result table
        "cap_result": "结果",
        "hdr_result": ["项目", "内容"],
        "r_method": "计票规则（投票前已定）",
        "r_winner": "赢家",
        "r_original": "全部选项时的赢家",
        "r_recount": "去掉{removed}后的赢家",
        "r_changed": "赢家变了吗",
        "changed_yes": "变了",
        "changed_no": "没变",
        "r_ballots": "选票",
        "ballots_ranked": "{n} 张，{k} 种排法",
        "ballots_approval": "{n} 张，{k} 种勾法",
        "ballots_poll": "群投票计数，{n} 人参加",
        "ballots_poll_unknown": "群投票计数（参加人数未填）",
        "r_exhausted": "不再计入的选票",
        "exhausted_text": "{n} 张（排的选项都被去掉了）",
        "r_partial": "残缺排序",
        "partial_reject": "不允许，每张票排满所有选项",
        "partial_tie_last": "没排的选项算并列最后",
        "partial_first_only": "只看第一选择，所以一个名字也可以",
        "r_tiebreak": "平票",
        "tie_none": "没有设随机源，出现平票就无法计票",
        "tie_source": "按事先排定的随机顺序打破，排前面的占优",
        "r_order": "平票顺序",
        "r_source": "随机源",
        "r_seed": "种子（SHA-256）前 16 位",
        # ballots
        "cap_lines": "选票（相同的合并）",
        "hdr_lines_ranked": ["票数", "排序"],
        "hdr_lines_approval": ["票数", "赞成的选项"],
        "more_lines": "（另有 {count} 种没有列出，完整列表见 --json。）",
        # method tables
        "cap_first": "第一选择的得票",
        "hdr_first": ["选项", "得票"],
        "cap_round1": "第 1 轮：第一选择的得票",
        "hdr_round1": ["选项", "得票", "去向"],
        "fate_elected": "过半，直接当选",
        "fate_final": "进入决选",
        "fate_out": "淘汰",
        "cap_round2": "第 2 轮：决选（两个选项比一比）",
        "hdr_round2": ["选项", "排在对方前面的票数"],
        "row_abstain": "没有排这两个选项的票（不计）",
        "cap_irv": "逐轮计票（每轮每张票算给它还没被淘汰的最靠前的选择）",
        "hdr_irv_head": "轮次",
        "hdr_irv_exhausted": "已无可算的选择",
        "hdr_irv_result": "结果",
        "irv_round": "第 {n} 轮",
        "irv_out": "淘汰 {names}",
        "irv_out_zero": "淘汰 {names}（都是 0 票）",
        "irv_elected": "{name} 当选",
        "cap_borda": "博达得分（第 1 名得 {top} 分，依次少 1 分，最后一名 0 分）",
        "hdr_borda": ["选项", "得分"],
        "cap_approval": "认可票数",
        "hdr_approval": ["选项", "赞成票数"],
        "cap_kemeny": "Kemeny 排名（和所有选票在每一对选项上的意见一致得分最高）",
        "hdr_kemeny": ["名次", "选项"],
        "cap_pairwise": "两两比较矩阵（每格是「行选项排在列选项前面」的票数）",
        "cap_cycle": "循环：每个选项都输给下一个",
        "hdr_cycle": ["胜", "负", "票数", "差"],
        "cap_ties": "平票处理（排在平票顺序前面的占优）",
        "hdr_ties": ["环节", "并列的选项", "结果"],
        "cap_all": "各规则的赢家",
        "hdr_all": ["规则", "赢家", "关键数字"],
        "hdr_all_remove": ["规则", "全部选项", "去掉{removed}后", "变了吗"],
        "all_marker": "（事先说好的规则）",
        "all_tied": "平票，无法决定（{names}）",
        "all_skipped": "不适用（选项超过 {limit} 个）",
        # stages of a tie
        "st_winner": "选赢家",
        "st_finalists": "选进入决选的两个选项",
        "st_final": "决选的两个选项打平",
        "st_irv": "即时决选第 {n} 轮，选淘汰的选项",
        "st_kemeny": "Kemeny 排名第 {n} 位",
        "ev_elected": "{names} 当选",
        "ev_finalists": "{names} 进入决选",
        "ev_out": "淘汰 {names}",
        "ev_place": "{names} 排在这一位",
        "event": "{where}（{tied}）→ {result}",
        "event_sep": "；",
        # key numbers
        "s_plurality": "{w} {n} 张第一选择（共 {total} 张）",
        "s_runoff_1": "第 1 轮 {w} 得 {n} 张第一选择，过半（共 {total} 张）",
        "s_runoff_2": "决选 {w} {a} : {l} {b}",
        "s_irv": "{rounds} 轮后 {w} 当选，最后一轮 {n} 票（当时有效选票 {c} 张）",
        "s_borda": "{w} {a} 分，第二名 {s} {b} 分",
        "s_cw": "{w} 在两两比较中胜过其他所有选项",
        "s_schulze_one": "没有孔多塞赢家，Schulze 选出 {w}",
        "s_schulze_many": "没有孔多塞赢家，Schulze 的候选赢家有 {names}，按平票顺序选出 {w}",
        "s_kemeny": "{w} 排第一，排名总分 {score}",
        "s_approval": "{w} 得 {n} 张赞成票",
        # notes
        "note_cw_yes": "孔多塞赢家：{name}，在两两比较中胜过其他所有选项。",
        "note_cw_no": "没有孔多塞赢家：没有哪个选项在两两比较中胜过其他所有选项。",
        "note_cw_no_cycle": "没有循环：有的选项在两两比较中恰好打平。",
        "note_schulze": "Schulze 的候选赢家：{names}。",
        "note_kemeny": "Kemeny 总分 {score}，共有 {ways} 种排名得分最高。",
        "note_partial": (
            "残缺排序：没排的选项算并列最后。两两比较时，排了的选项胜过没排的，两个都没排的"
            "这张票不计。博达计分里没排的选项平分剩下的分。即时决选里，排了的选项都被淘汰"
            "后这张票作废。相对多数只看第一选择。"
        ),
        "note_order": (
            "平票顺序在开票前就由随机源确定，这次{used}平票顺序。算法见 --json 里 certificate "
            "的 how_to_verify。"
        ),
        "used_yes": "用到了",
        "used_no": "没有用到",
        "note_removed": "去掉的选项在每张选票上都被删掉，平票顺序保持不变，只是把被去掉的选项从中拿走。",
        "note_recount_same": "去掉{removed}后按同一规则重新计票，赢家没变，仍是 {new}。",
        "note_recount_changed": "去掉{removed}后按同一规则重新计票，赢家从 {old} 变成 {new}。",
        "note_all": (
            "这张表只用来事后讲解：同一批选票换一种规则，赢家可能不同。规则必须在投票前定"
            "好，不能看了结果再挑。事先说好的规则是{method}，赢家是{winner}。"
        ),
        "note_distinct": "这 {rules} 种规则里，一共出现了 {distinct} 个不同的赢家。",
        "note_same": "这 {rules} 种规则选出的赢家相同。",
        "nm_strategy": (
            "没有防策略保证：选项在三个及以上时，任何能选出每个选项、又不是独裁的排序规则，"
            "都可能被某个投票人在某种情形下操纵（Gibbard–Satterthwaite 定理）。"
        ),
        "nm_ties_in_ballot": "同一张选票里不能并列同一个名次。",
        "nm_eligibility": "谁有资格投票、有没有重复投票、选票是否真实，脚本不核对，请组织者核对。",
        # private messages and group summary
        "everyone": "每位投票人",
        "dm_ballot": "你的选票按这样记录：{ranking}。",
        "dm_approve": "你的选票按这样记录：赞成 {names}。",
        "dm_unranked": "你没排的 {names} 按事先说好的规则算并列最后。",
        "dm_result": "投票结果：{winner} 当选。规则是{method}。",
        "dm_result_recount": "去掉{removed}后按同一规则重新计票：{winner} 当选。",
        "dm_place": "你把 {winner} 排在第 {k} 位。",
        "dm_place_unranked": "你没有排 {winner}，按规则算并列最后。",
        "dm_approved": "你赞成 {winner}。",
        "dm_not_approved": "你没有赞成 {winner}。",
        "dm_check": "如果这条记录和你发给组织者的选票不一致，请现在告诉组织者。",
        "g_result": "规则（投票前已定）：{method}。{winner} 当选。",
        "g_ballots": "共 {n} 张选票。",
        "g_ballots_poll": "群投票计数。",
        "g_numbers": "关键数字：{numbers}。",
        "g_partial": "没排的选项算并列最后。",
        "g_ties_used": "出现平票，已按事先排定的随机顺序打破：{events}。",
        "g_ties_ready": "平票顺序已事先排定（随机源「{source}」），这次没有用到。",
        "g_recount": "去掉{removed}后按同一规则重新计票：赢家{change}。",
        "g_recount_same": "没变，仍是 {new}",
        "g_recount_changed": "从 {old} 变成 {new}",
        "g_all_intro": "事后对照（只用来讲解，规则不能事后改）：",
        "g_all_line": "{method}：{winner}",
    },
    "en": {
        "sep": ", ",
        "gt": " > ",
        "nothing": "(approves nothing)",
        "default_topic": "Vote",
        "title": "{topic}: {method}",
        "title_recount": "{topic}: recount without {removed}, {method}",
        "method": {
            "plurality": "Plurality",
            "runoff": "Two-round runoff",
            "irv": "Instant runoff (IRV)",
            "borda": "Borda count",
            "condorcet": "Condorcet (Schulze completion)",
            "schulze": "Schulze method",
            "approval": "Approval voting",
            "kemeny": "Kemeny ranking",
        },
        "method_short": {
            "plurality": "Plurality",
            "runoff": "Runoff",
            "irv": "IRV",
            "borda": "Borda",
            "condorcet": "Condorcet",
            "schulze": "Schulze",
            "approval": "Approval",
            "kemeny": "Kemeny",
        },
        "cap_result": "Result",
        "hdr_result": ["Item", "Value"],
        "r_method": "Counting rule (fixed before the vote)",
        "r_winner": "Winner",
        "r_original": "Winner with all options",
        "r_recount": "Winner without {removed}",
        "r_changed": "Did the winner change",
        "changed_yes": "Changed",
        "changed_no": "Unchanged",
        "r_ballots": "Ballots",
        "ballots_ranked": "{n}, in {k} different rankings",
        "ballots_approval": "{n}, in {k} different sets",
        "ballots_poll": "poll counts, {n} people took part",
        "ballots_poll_unknown": "poll counts (number of participants not given)",
        "r_exhausted": "Ballots no longer counted",
        "exhausted_text": "{n} (every option they rank was removed)",
        "r_partial": "Partial rankings",
        "partial_reject": "not allowed, every ballot ranks all options",
        "partial_tie_last": "options left out tie for last",
        "partial_first_only": "only the first choice is read, so a single name is fine",
        "r_tiebreak": "Ties",
        "tie_none": "no random source is set, so a tie cannot be counted",
        "tie_source": "broken by a random order fixed in advance, the earlier option wins",
        "r_order": "Tie-break order",
        "r_source": "Random source",
        "r_seed": "Seed (SHA-256), first 16 hex digits",
        "cap_lines": "Ballots (equal ones merged)",
        "hdr_lines_ranked": ["Ballots", "Ranking"],
        "hdr_lines_approval": ["Ballots", "Approved options"],
        "more_lines": "({count} more are not listed; see --json for the full list.)",
        "cap_first": "First-choice votes",
        "hdr_first": ["Option", "Votes"],
        "cap_round1": "Round 1: first-choice votes",
        "hdr_round1": ["Option", "Votes", "What happens"],
        "fate_elected": "more than half, elected at once",
        "fate_final": "goes to the final",
        "fate_out": "out",
        "cap_round2": "Round 2: the final (two options head to head)",
        "hdr_round2": ["Option", "Ballots ranking it above the other"],
        "row_abstain": "Ballots that rank neither (not counted)",
        "cap_irv": "Round by round (each ballot counts for its highest option still in the race)",
        "hdr_irv_head": "Round",
        "hdr_irv_exhausted": "No option left",
        "hdr_irv_result": "Result",
        "irv_round": "Round {n}",
        "irv_out": "{names} out",
        "irv_out_zero": "{names} out (all have 0 votes)",
        "irv_elected": "{name} elected",
        "cap_borda": "Borda points (first place gets {top}, one less for each place, last gets 0)",
        "hdr_borda": ["Option", "Points"],
        "cap_approval": "Approvals",
        "hdr_approval": ["Option", "Approvals"],
        "cap_kemeny": "Kemeny ranking (the order that agrees most with all ballots on every pair)",
        "hdr_kemeny": ["Place", "Option"],
        "cap_pairwise": "Pairwise matrix (each cell: ballots ranking the row option above the column option)",
        "cap_cycle": "A cycle: each option loses to the next one",
        "hdr_cycle": ["Wins", "Loses", "Ballots", "Margin"],
        "cap_ties": "How ties were broken (the option earlier in the tie-break order wins)",
        "hdr_ties": ["Step", "Tied options", "Result"],
        "cap_all": "Winner under each rule",
        "hdr_all": ["Rule", "Winner", "Key numbers"],
        "hdr_all_remove": ["Rule", "All options", "Without {removed}", "Changed?"],
        "all_marker": " (the agreed rule)",
        "all_tied": "tie, cannot decide ({names})",
        "all_skipped": "not available (more than {limit} options)",
        "st_winner": "choosing the winner",
        "st_finalists": "choosing the two finalists",
        "st_final": "the two finalists are tied",
        "st_irv": "IRV round {n}, choosing who is eliminated",
        "st_kemeny": "Kemeny ranking, place {n}",
        "ev_elected": "{names} elected",
        "ev_finalists": "{names} go to the final",
        "ev_out": "{names} eliminated",
        "ev_place": "{names} takes this place",
        "event": "{where} ({tied}): {result}",
        "event_sep": "; ",
        "s_plurality": "{w} has {n} first choices (of {total})",
        "s_runoff_1": "round 1: {w} has {n} first choices, more than half of {total}",
        "s_runoff_2": "final {w} {a} : {l} {b}",
        "s_irv": "{w} elected after {rounds} rounds, {n} votes in the last (of {c} ballots still counting)",
        "s_borda": "{w} {a} points, second place {s} {b} points",
        "s_cw": "{w} beats every other option in pairwise comparisons",
        "s_schulze_one": "no Condorcet winner, Schulze picks {w}",
        "s_schulze_many": "no Condorcet winner, Schulze's potential winners are {names}, the tie-break order picks {w}",
        "s_kemeny": "{w} is first, ranking score {score}",
        "s_approval": "{w} has {n} approvals",
        "note_cw_yes": "Condorcet winner: {name} beats every other option in pairwise comparisons.",
        "note_cw_no": "No Condorcet winner: no option beats every other option in pairwise comparisons.",
        "note_cw_no_cycle": "There is no cycle: some pairs of options are exactly tied.",
        "note_schulze": "Schulze's potential winners: {names}.",
        "note_kemeny": "Kemeny score {score}. {ways} rankings reach the highest score.",
        "note_partial": (
            "Partial rankings: options a ballot leaves out tie for last on that ballot. In a pairwise "
            "comparison an option that is ranked beats one that is not, and a ballot that ranks neither "
            "does not count. In the Borda count the options left out share the remaining points equally. "
            "In IRV a ballot stops counting once every option it ranks is out. Plurality reads only the "
            "first choice."
        ),
        "note_order": (
            "The tie-break order was fixed by the random source before the vote. This time it was "
            "{used}. The algorithm is in how_to_verify under certificate in the --json output."
        ),
        "used_yes": "used",
        "used_no": "not needed",
        "note_removed": (
            "Removed options are deleted from every ballot. The tie-break order is the original one "
            "with the removed options taken out."
        ),
        "note_recount_same": "Counting again without {removed} under the same rule: the winner stays {new}.",
        "note_recount_changed": (
            "Counting again without {removed} under the same rule: the winner changes from {old} to {new}."
        ),
        "note_all": (
            "This table is for explaining a result after the fact: with the same ballots, another rule can "
            "pick another winner. The rule has to be fixed before the vote and must not be chosen after "
            "seeing results. The agreed rule is {method} and its winner is {winner}."
        ),
        "note_distinct": "Among these {rules} rules, {distinct} different winners appear.",
        "note_same": "All {rules} rules name the same winner.",
        "nm_strategy": (
            "No protection against strategic voting: with three or more options, every ranking "
            "rule that can elect each option and is not a dictatorship can be manipulated by some "
            "voter in some situation (the Gibbard-Satterthwaite theorem)."
        ),
        "nm_ties_in_ballot": "A ballot cannot rank two options equally.",
        "nm_eligibility": (
            "The script does not check who may vote, whether someone voted twice or whether a ballot is "
            "genuine. The organizer does."
        ),
        "everyone": "Every voter",
        "dm_ballot": "Your ballot was recorded as: {ranking}.",
        "dm_approve": "Your ballot was recorded as approving: {names}.",
        "dm_unranked": "The options you left out ({names}) count as tied for last, as agreed in advance.",
        "dm_result": "Result: {winner} is elected. The rule is {method}.",
        "dm_result_recount": "Counted again without {removed} under the same rule: {winner} is elected.",
        "dm_place": "You ranked {winner} number {k}.",
        "dm_place_unranked": "You did not rank {winner}, so it counts as tied for last.",
        "dm_approved": "You approved {winner}.",
        "dm_not_approved": "You did not approve {winner}.",
        "dm_check": "If this record differs from the ballot you sent, tell the organizer now.",
        "g_result": "Rule (fixed before the vote): {method}. {winner} is elected.",
        "g_ballots": "{n} ballots.",
        "g_ballots_poll": "Poll counts.",
        "g_numbers": "Key numbers: {numbers}.",
        "g_partial": "Options a ballot leaves out tie for last.",
        "g_ties_used": "There was a tie, broken by the random order fixed in advance: {events}.",
        "g_ties_ready": 'The tie-break order was fixed in advance (random source "{source}") and was not needed.',
        "g_recount": "Counted again without {removed} under the same rule: the winner {change}.",
        "g_recount_same": "stays {new}",
        "g_recount_changed": "changes from {old} to {new}",
        "g_all_intro": "For comparison after the fact (explanation only, the rule cannot change now):",
        "g_all_line": "{method}: {winner}",
    },
}


# ---------------------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------------------


@dataclass
class Election:
    """A validated vote: options, merged ballot lines, named voters and the agreed rules."""

    topic: str | None
    options: list[str]
    kind: str  # "ranked", "approval" or "poll"
    lines: list[Line]  # ranked: ranking, approval: sorted approved options
    poll: list[int] | None  # kind "poll": approvals per option
    participants: int | None
    voters: list[tuple[str, tuple[int, ...]]]  # named ballots in input order
    n_ballots: int
    method: str
    partial: str
    source: str | None
    first_partial: tuple[str, int] | None = None  # where the first partial ballot is, its length


@dataclass
class TieEvent:
    """One tie that the order broke: where, who was tied (best first), who was picked."""

    stage: tuple
    tied: tuple[int, ...]
    picked: tuple[int, ...]
    eliminated: bool


class TieUnresolved(Exception):
    """A tie came up and the rules fix no random source to break it."""

    def __init__(self, stage: tuple, tied: Sequence[int]) -> None:
        super().__init__(f"tie at {stage}")
        self.stage = stage
        self.tied = tuple(tied)


@dataclass
class Outcome:
    """The result of one rule on one set of options (winner is None when a tie is unresolved)."""

    method: str
    winner: int | None
    data: dict[str, Any] = field(default_factory=dict)
    events: list[TieEvent] = field(default_factory=list)
    tied: tuple[int, ...] = ()
    stage: tuple | None = None


@dataclass
class Count:
    """Everything counted for one set of options still in the race."""

    alive: list[int]
    lines: list[Line]
    matrix: list[list[int]] | None
    cw: int | None
    schulze: list[int]
    cycle: list[int] | None
    exhausted: int
    outcome: Outcome
    rules: dict[str, Outcome]


# ---------------------------------------------------------------------------------------
# Reading the input
# ---------------------------------------------------------------------------------------


def clean_label(value: Any, where: str) -> str:
    """A name or title: text, one line, no edge spaces, encodable, not too long."""
    if not isinstance(value, str):
        raise fc.InputError(where, "must be text")
    if not value or value != value.strip():
        raise fc.InputError(where, "must be non-empty text without leading or trailing spaces")
    if any(ord(ch) < 32 or ord(ch) == 127 or ch in "\u2028\u2029" for ch in value):
        raise fc.InputError(where, "must be one line without control characters")
    if len(value) > MAX_LABEL:
        raise fc.InputError(where, f"is longer than {MAX_LABEL} characters")
    return fc.encodable(value, where)


def clean_source(value: Any, where: str) -> str:
    """The public random source: one line of text, exactly as published."""
    text = fc.require_text(value, where)
    if any(ord(ch) < 32 or ord(ch) == 127 or ch in "\u2028\u2029" for ch in text):
        raise fc.InputError(where, "must be one line without control characters")
    if len(text) > MAX_SOURCE:
        raise fc.InputError(where, f"is longer than {MAX_SOURCE} characters")
    return fc.encodable(text, where)


def parse_options(raw: Any) -> list[str]:
    names = fc.require_names(raw, "options", 2, MAX_OPTIONS)
    for index, name in enumerate(names):
        clean_label(name, f"options[{index}]")
    return names


def parse_rules(raw: Any) -> tuple[str, str, str | None]:
    """The agreed rules: counting method, partial-ballot policy, random source (or None)."""
    if raw is None:
        raise fc.InputError(
            "rules",
            "is required: the counting method, the tie-break and the handling of partial "
            "ballots are fixed before the vote",
        )
    rules = fc.require_object(raw, "rules")
    fc.check_fields(rules, RULE_FIELDS, "rules")
    method = fc.require_choice(rules.get("method"), "rules.method", METHODS)
    partial = fc.require_choice(rules.get("partial", "reject"), "rules.partial", PARTIAL_POLICIES)
    source: str | None = None
    tie_break = rules.get("tie_break")
    if isinstance(tie_break, str):
        if tie_break != "random_source":
            raise fc.InputError("rules.tie_break", 'must be {"random_source": "..."}')
    elif tie_break is not None:
        spec = fc.require_object(tie_break, "rules.tie_break")
        fc.check_fields(spec, ("random_source",), "rules.tie_break")
        if "random_source" in spec:
            source = clean_source(spec["random_source"], "rules.tie_break.random_source")
    if "random_source" in rules:  # the spelling rent-split uses
        flat = clean_source(rules["random_source"], "rules.random_source")
        if source is not None and flat != source:
            raise fc.InputError(
                "rules.random_source", "differs from rules.tie_break.random_source; give it once"
            )
        source = flat
    if tie_break == "random_source" and source is None:
        raise fc.InputError("rules.tie_break", "names a random source but gives none")
    return method, partial, source


def ballot_header(item: Any, where: str, allowed: str) -> tuple[dict[str, Any], int, str | None]:
    """Common checks of a ranked or approval ballot object: its count and voter name."""
    example = '{"count": 2, "' + allowed + '": [...]}'
    if not isinstance(item, dict):
        raise fc.InputError(where, f"must be an object like {example}")
    fc.check_fields(item, (allowed, *BALLOT_FIELDS), where)
    count = 1
    if "count" in item:
        count = fc.require_int(item["count"], f"{where}.count", 1, MAX_COUNT)
    voter = None
    if "voter" in item:
        voter = clean_label(item["voter"], f"{where}.voter")
        if count != 1:
            raise fc.InputError(
                f"{where}.count",
                "a ballot with a voter name is one person's ballot: leave count out",
            )
    return item, count, voter


def option_list(raw: Any, where: str, index: dict[str, int], min_len: int) -> tuple[int, ...]:
    """Option names to indices, each option at most once, in the order given."""
    names = fc.require_list(raw, where, min_len)
    seen: set = set()
    out: list[int] = []
    for position, name in enumerate(names):
        if not isinstance(name, str) or name not in index:
            raise fc.InputError(f"{where}[{position}]", f"{name!r} is not one of the options")
        if name in seen:
            raise fc.InputError(f"{where}[{position}]", f"{name!r} appears twice on this ballot")
        seen.add(name)
        out.append(index[name])
    return tuple(out)


def merge_lines(counts: dict[tuple[int, ...], int]) -> list[Line]:
    """Canonical order, so the ballots can be listed in any order: most ballots first."""
    return sorted(((count, key) for key, count in counts.items()), key=lambda l: (-l[0], l[1]))


class Ballots:
    """The ballots read so far, merged by identical content, with the voters' names."""

    def __init__(self) -> None:
        self.counts: dict[tuple[int, ...], int] = {}
        self.voters: list[tuple[str, tuple[int, ...]]] = []
        self.names: set[str] = set()
        self.total = 0
        self.first_partial: tuple[str, int] | None = None

    def add(self, key: tuple[int, ...], count: int, voter: str | None, where: str) -> None:
        self.counts[key] = self.counts.get(key, 0) + count
        self.total += count
        if voter is not None:
            if voter in self.names:
                raise fc.InputError(f"{where}.voter", f"{voter!r} appears twice: one ballot each")
            self.names.add(voter)
            self.voters.append((voter, key))


def parse_ranked(raw: Any, options: list[str], index: dict[str, int]) -> Ballots:
    items = fc.require_list(raw, "ballots", 1, MAX_BALLOT_LINES)
    ballots = Ballots()
    for position, item in enumerate(items):
        where = f"ballots[{position}]"
        obj, count, voter = ballot_header(item, where, "ranking")
        ranking = option_list(obj.get("ranking"), f"{where}.ranking", index, 1)
        if len(ranking) < len(options) and ballots.first_partial is None:
            ballots.first_partial = (where, len(ranking))
        ballots.add(ranking, count, voter, where)
    return ballots


def parse_approvals(raw: Any, options: list[str], index: dict[str, int]) -> Ballots:
    items = fc.require_list(raw, "approvals", 1, MAX_BALLOT_LINES)
    ballots = Ballots()
    for position, item in enumerate(items):
        where = f"approvals[{position}]"
        obj, count, voter = ballot_header(item, where, "approve")
        approved = option_list(obj.get("approve"), f"{where}.approve", index, 0)
        ballots.add(tuple(sorted(approved)), count, voter, where)
    return ballots


def parse_poll(raw: Any, options: list[str]) -> list[int]:
    obj = fc.require_object(raw, "approval_counts")
    for key in obj:
        if key not in options:
            raise fc.InputError(f"approval_counts.{key}", "is not one of the options")
    scores: list[int] = []
    for name in options:
        if name not in obj:
            raise fc.InputError(
                f"approval_counts.{name}", "is missing (write 0 if nobody approved it)"
            )
        scores.append(fc.require_int(obj[name], f"approval_counts.{name}", 0, 10**9))
    return scores


def table_rows(text: Any) -> tuple[list[str], list[tuple[int, list[str]]]]:
    """The header row and the data rows (with their line numbers) of a pasted table."""
    if not isinstance(text, str):
        raise fc.InputError("csv", "must be the table pasted as text")
    text = text.lstrip("\ufeff")
    first = text.split("\n", 1)[0]
    delimiter = "\t" if "\t" in first and "," not in first else ","
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    rows: list[tuple[int, list[str]]] = []
    try:
        for row in reader:
            if any(cell.strip() for cell in row):
                rows.append((reader.line_num, row))
    except csv.Error as err:
        raise fc.InputError("csv", f"cannot read the table: {err}") from err
    if len(rows) < 2:
        raise fc.InputError("csv", "needs a header row and at least one row of ballots")
    if len(rows) - 1 > MAX_BALLOT_LINES:
        raise fc.InputError("csv", f"has more than {MAX_BALLOT_LINES} rows of ballots")
    return [cell.strip() for cell in rows[0][1]], rows[1:]


def parse_table(text: Any, options: list[str], index: dict[str, int], approval: bool) -> Ballots:
    """A questionnaire export: one column per option, one row per person."""
    header, rows = table_rows(text)
    column: dict[int, int] = {}
    for position, cell in enumerate(header):
        if cell in index:
            if index[cell] in column:
                raise fc.InputError("csv", f"the header row names {cell!r} twice")
            column[index[cell]] = position
    for number, name in enumerate(options):
        if number not in column:
            raise fc.InputError(
                "csv", f"the header row has no column named {name!r} (use the exact option names)"
            )
    ballots = Ballots()
    for line_no, row in rows:
        where = f"csv line {line_no}"
        cells = {
            number: (row[at].strip() if at < len(row) else "") for number, at in column.items()
        }
        if approval:
            approved = []
            for number, cell in cells.items():
                if cell == "1":
                    approved.append(number)
                elif cell not in ("", "0"):
                    raise fc.InputError(
                        where,
                        f"{options[number]!r} holds {cell!r}: write 1 to approve, or leave blank",
                    )
            ballots.add(tuple(sorted(approved)), 1, None, where)
            continue
        ranks: dict[int, list[int]] = {}
        for number, cell in cells.items():
            if cell == "":
                continue
            if not (cell.isascii() and cell.isdigit()) or len(cell) > 9 or int(cell) < 1:
                raise fc.InputError(
                    where,
                    f"the rank for {options[number]!r} is {cell!r}: use whole numbers from 1, "
                    "1 is best, blank means not ranked",
                )
            ranks.setdefault(int(cell), []).append(number)
        if not ranks:
            raise fc.InputError(where, "ranks no option: delete the row or fill it in")
        for rank, tied in ranks.items():
            if len(tied) > 1:
                raise fc.InputError(
                    where,
                    f"rank {rank} is given to both {options[tied[0]]!r} and {options[tied[1]]!r}: "
                    "an option needs its own rank",
                )
        ranking = tuple(ranks[rank][0] for rank in sorted(ranks))
        if len(ranking) < len(options) and ballots.first_partial is None:
            ballots.first_partial = (where, len(ranking))
        ballots.add(ranking, 1, None, where)
    return ballots


def parse_election(raw: Any) -> Election:
    """Validate one input object and return the Election, or raise InputError naming a field."""
    data = fc.require_object(raw, "input")
    fc.check_fields(data, TOP_FIELDS, "")
    topic = clean_label(data["topic"], "topic") if "topic" in data else None
    options = parse_options(data.get("options"))
    index = {name: number for number, name in enumerate(options)}
    method, partial, source = parse_rules(data.get("rules"))
    given = [key for key in BALLOT_SOURCES if key in data]
    if len(given) != 1:
        raise fc.InputError(
            "ballots", "give exactly one of " + ", ".join(BALLOT_SOURCES) + f" (found {len(given)})"
        )
    key = given[0]
    approval = method == "approval"
    if key == "ballots" and approval:
        raise fc.InputError(
            "rules.method",
            "approval counts approvals, not rankings: use approvals, approval_counts or a csv of 1s",
        )
    if key in ("approvals", "approval_counts") and not approval:
        raise fc.InputError(
            "rules.method",
            f"{key} only say which options a person accepts: rules.method must be approval",
        )
    if "participants" in data and key != "approval_counts":
        raise fc.InputError("participants", "belongs to approval_counts, the poll totals")
    if method == "kemeny" and len(options) > MAX_KEMENY_OPTIONS:
        raise fc.InputError(
            "rules.method",
            f"kemeny searches all rankings and takes at most {MAX_KEMENY_OPTIONS} options",
        )
    poll: list[int] | None = None
    participants: int | None = None
    if key == "approval_counts":
        poll = parse_poll(data[key], options)
        if "participants" in data:
            participants = fc.require_int(data["participants"], "participants", 1, 10**9)
            if participants < max(poll):
                raise fc.InputError("participants", "is smaller than the largest approval count")
        ballots = Ballots()
    elif key == "ballots":
        ballots = parse_ranked(data[key], options, index)
    elif key == "approvals":
        ballots = parse_approvals(data[key], options, index)
    else:
        ballots = parse_table(data[key], options, index, approval)
    kind = "poll" if key == "approval_counts" else ("approval" if approval else "ranked")
    return Election(
        topic=topic,
        options=options,
        kind=kind,
        lines=merge_lines(ballots.counts),
        poll=poll,
        participants=participants,
        voters=ballots.voters,
        n_ballots=ballots.total,
        method=method,
        partial=partial,
        source=source,
        first_partial=ballots.first_partial,
    )


def check_partial(election: Election, needs_complete: bool) -> None:
    """Under the reject policy every ballot must rank every option (plurality reads one name)."""
    if election.kind != "ranked" or election.first_partial is None:
        return
    if election.partial == "tie_last" or not needs_complete:
        return
    where, length = election.first_partial
    raise fc.InputError(
        where,
        f"ranks {length} of {len(election.options)} options, and rules.partial is "
        '"reject". Rank every option, or set rules.partial to "tie_last" if the group agreed '
        "in advance that options left out tie for last",
    )


# ---------------------------------------------------------------------------------------
# Ties: one order of the options, fixed in advance
# ---------------------------------------------------------------------------------------


def tie_order(election: Election) -> tuple[list[int] | None, str | None]:
    """The tie-break order (option indices, best first) and its seed in hex, or (None, None).

    The options are put in order by fsq_core.seeded_order, whose seed comes from the options
    and the public random source. The order covers all options, also those removed later, so
    a recount uses the same order with the removed options taken out.
    """
    if election.source is None:
        return None, None
    drawn = fc.seeded_order(TIE_RULE_NAME, election.options, TIE_SLOTS, election.source)
    index = {name: number for number, name in enumerate(election.options)}
    return [index[name] for name in drawn.order], drawn.seed_hex


class Breaker:
    """Breaks ties with the order. The option that comes first in the order wins a tie."""

    def __init__(self, order: Sequence[int] | None) -> None:
        self.rank = None if order is None else {o: p for p, o in enumerate(order)}
        self.events: list[TieEvent] = []

    def favoured(self, tied: Sequence[int], stage: tuple, keep: int = 1) -> list[int]:
        """The `keep` options that come first in the order (all of them if there is no tie)."""
        tied = sorted(tied)
        if len(tied) <= keep:
            return tied
        if self.rank is None:
            raise TieUnresolved(stage, tied)
        ordered = sorted(tied, key=lambda o: self.rank[o])
        picked = ordered[:keep]
        self.events.append(TieEvent(stage, tuple(ordered), tuple(picked), False))
        return picked

    def eliminated(self, tied: Sequence[int], stage: tuple) -> int:
        """The one to eliminate: the tied option that comes last in the order."""
        tied = sorted(tied)
        if len(tied) == 1:
            return tied[0]
        if self.rank is None:
            raise TieUnresolved(stage, tied)
        ordered = sorted(tied, key=lambda o: self.rank[o])
        self.events.append(TieEvent(stage, tuple(ordered), (ordered[-1],), True))
        return ordered[-1]


# ---------------------------------------------------------------------------------------
# The counting rules (all on integers)
# ---------------------------------------------------------------------------------------


def restrict_lines(lines: Sequence[Line], alive: Sequence[int]) -> list[Line]:
    """Delete the options that are out of the race from every ranking, dropping empty ones."""
    keep = set(alive)
    out: list[Line] = []
    for count, ranking in lines:
        kept = tuple(o for o in ranking if o in keep)
        if kept:
            out.append((count, kept))
    return out


def pairwise_matrix(lines: Sequence[Line], alive: Sequence[int], size: int) -> list[list[int]]:
    """matrix[a][b]: ballots that put a above b. A ranked option beats an unranked one."""
    matrix = [[0] * size for _ in range(size)]
    for count, ranking in lines:
        ranked = set(ranking)
        unranked = [o for o in alive if o not in ranked]
        for at, first in enumerate(ranking):
            for second in ranking[at + 1 :]:
                matrix[first][second] += count
            for second in unranked:
                matrix[first][second] += count
    return matrix


def condorcet_winner(matrix: list[list[int]], alive: Sequence[int]) -> int | None:
    for a in alive:
        if all(matrix[a][b] > matrix[b][a] for b in alive if b != a):
            return a
    return None


def schulze_winners(matrix: list[list[int]], alive: Sequence[int]) -> list[int]:
    """Potential winners of the Schulze method, with winning votes as the strength of a link."""
    strength = {
        (a, b): (matrix[a][b] if matrix[a][b] > matrix[b][a] else 0)
        for a in alive
        for b in alive
        if a != b
    }
    for k in alive:
        for a in alive:
            if a == k:
                continue
            for b in alive:
                if b == a or b == k:
                    continue
                through = min(strength[a, k], strength[k, b])
                strength[a, b] = max(strength[a, b], through)
    return [a for a in alive if all(strength[a, b] >= strength[b, a] for b in alive if b != a)]


def find_cycle(matrix: list[list[int]], alive: Sequence[int]) -> list[int] | None:
    """A shortest cycle in the "beats" graph (a beats b when more ballots put a above b).

    Among the shortest cycles the one through the lowest-numbered option is returned, written
    from that option onward, so the answer depends only on the matrix.
    """
    beats = {a: [b for b in alive if b != a and matrix[a][b] > matrix[b][a]] for a in alive}
    best: list[int] | None = None
    for start in alive:
        parent = {start: -1}
        frontier = [start]
        found: list[int] | None = None
        while frontier and found is None:
            following: list[int] = []
            for node in frontier:
                for nxt in beats[node]:
                    if nxt == start:
                        path = [node]
                        while parent[path[-1]] != -1:
                            path.append(parent[path[-1]])
                        found = path[::-1]
                        break
                    if nxt not in parent:
                        parent[nxt] = node
                        following.append(nxt)
                if found is not None:
                    break
            frontier = following
        if found is not None and (best is None or len(found) < len(best)):
            best = found
    return best


def tally_first_choices(lines: Sequence[Line], alive: Sequence[int]) -> dict[int, int]:
    scores = dict.fromkeys(alive, 0)
    for count, ranking in lines:
        scores[ranking[0]] += count
    return scores


def count_plurality(lines: Sequence[Line], alive: Sequence[int], brk: Breaker) -> Outcome:
    scores = tally_first_choices(lines, alive)
    top = max(scores.values())
    winner = brk.favoured([o for o in alive if scores[o] == top], ("winner",))[0]
    data = {"scores": scores, "total": sum(scores.values())}
    return Outcome("plurality", winner, data, brk.events)


def count_runoff(lines: Sequence[Line], alive: Sequence[int], brk: Breaker) -> Outcome:
    """Round 1 on first choices. More than half wins at once, otherwise the top two meet."""
    first = tally_first_choices(lines, alive)
    total = sum(first.values())
    top = max(first.values())
    data: dict[str, Any] = {"first": first, "total": total, "finalists": None, "votes": None}
    if 2 * top > total:
        data["decided_in_round_1"] = True
        return Outcome("runoff", next(o for o in alive if first[o] == top), data, brk.events)
    data["decided_in_round_1"] = False
    by_votes = sorted(alive, key=lambda o: (-first[o], o))
    cut = first[by_votes[1]]
    sure = [o for o in alive if first[o] > cut]
    level = [o for o in alive if first[o] == cut]
    chosen = brk.favoured(level, ("finalists",), 2 - len(sure))
    x, y = sorted(sure + chosen, key=lambda o: (-first[o], o))
    votes = {x: 0, y: 0}
    abstain = 0
    for count, ranking in lines:
        for option in ranking:
            if option in votes:
                votes[option] += count
                break
        else:
            abstain += count
    data.update(finalists=(x, y), votes=votes, abstain=abstain)
    if votes[x] != votes[y]:
        winner = x if votes[x] > votes[y] else y
    else:
        winner = brk.favoured([x, y], ("final",))[0]
    return Outcome("runoff", winner, data, brk.events)


def count_irv(lines: Sequence[Line], alive: Sequence[int], brk: Breaker) -> Outcome:
    """Instant runoff. Options without any vote leave together, otherwise the lowest one leaves."""
    total = sum(count for count, _ in lines)
    remaining = list(alive)
    rounds: list[dict[str, Any]] = []
    while True:
        counts = dict.fromkeys(remaining, 0)
        exhausted = 0
        for count, ranking in lines:
            for option in ranking:
                if option in counts:
                    counts[option] += count
                    break
            else:
                exhausted += count
        continuing = total - exhausted
        top = max(counts.values())
        entry: dict[str, Any] = {
            "counts": dict(counts),
            "exhausted": exhausted,
            "continuing": continuing,
            "eliminated": [],
            "winner": None,
        }
        rounds.append(entry)
        if 2 * top > continuing or len(remaining) == 1:
            winner = next(o for o in remaining if counts[o] == top)
            entry["winner"] = winner
            return Outcome("irv", winner, {"rounds": rounds}, brk.events)
        low = min(counts.values())
        lowest = [o for o in remaining if counts[o] == low]
        if low == 0:
            out = lowest
        else:
            out = [brk.eliminated(lowest, ("irv", len(rounds)))]
        entry["eliminated"] = sorted(out)
        remaining = [o for o in remaining if o not in out]


def count_borda(lines: Sequence[Line], alive: Sequence[int], brk: Breaker) -> Outcome:
    """Borda points, doubled so that options left out can share the remaining points exactly."""
    size = len(alive)
    twice = dict.fromkeys(alive, 0)
    for count, ranking in lines:
        ranked = set(ranking)
        for place, option in enumerate(ranking):
            twice[option] += count * 2 * (size - 1 - place)
        left_out = size - len(ranking)
        if left_out:
            for option in alive:
                if option not in ranked:
                    twice[option] += count * (left_out - 1)
    top = max(twice.values())
    winner = brk.favoured([o for o in alive if twice[o] == top], ("winner",))[0]
    return Outcome("borda", winner, {"twice": twice, "size": size}, brk.events)


def count_condorcet(
    method: str, matrix: list[list[int]], alive: Sequence[int], brk: Breaker
) -> Outcome:
    """condorcet and schulze: the Condorcet winner if there is one, else the Schulze winner."""
    cw = condorcet_winner(matrix, alive)
    potential = schulze_winners(matrix, alive)
    if cw is not None:
        winner = cw
    else:
        winner = brk.favoured(potential, ("winner",))[0]
    return Outcome(method, winner, {"cw": cw, "schulze": potential}, brk.events)


def count_kemeny(matrix: list[list[int]], alive: Sequence[int], brk: Breaker) -> Outcome:
    """The ranking that agrees most with the ballots on every pair (exact, over subsets).

    best[S] is the highest score for ranking the set S among themselves. Ties between equally
    good rankings are broken place by place, top down, with the tie-break order.
    """
    size = len(alive)
    w = [[matrix[alive[a]][alive[b]] for b in range(size)] for a in range(size)]
    full = (1 << size) - 1

    def above(j: int, rest: int) -> int:
        return sum(w[j][k] for k in range(size) if rest >> k & 1)

    best = [0] * (full + 1)
    ways = [1] * (full + 1)
    for mask in range(1, full + 1):
        top, count = -1, 0
        for j in range(size):
            if mask >> j & 1:
                rest = mask ^ (1 << j)
                value = best[rest] + above(j, rest)
                if value > top:
                    top, count = value, ways[rest]
                elif value == top:
                    count += ways[rest]
        best[mask], ways[mask] = top, count
    ranking: list[int] = []
    mask = full
    while mask:
        candidates = [
            alive[j]
            for j in range(size)
            if mask >> j & 1 and best[mask ^ (1 << j)] + above(j, mask ^ (1 << j)) == best[mask]
        ]
        pick = brk.favoured(candidates, ("kemeny", len(ranking) + 1))[0]
        mask ^= 1 << alive.index(pick)
        ranking.append(pick)
    data = {"ranking": ranking, "score": best[full], "ways": ways[full]}
    return Outcome("kemeny", ranking[0], data, brk.events)


def count_approval(scores: dict[int, int], brk: Breaker) -> Outcome:
    top = max(scores.values())
    winner = brk.favoured([o for o, n in scores.items() if n == top], ("winner",))[0]
    return Outcome("approval", winner, {"scores": dict(scores)}, brk.events)


def count_method(
    method: str,
    election: Election,
    alive: list[int],
    lines: list[Line],
    matrix: list[list[int]] | None,
    order: Sequence[int] | None,
) -> Outcome:
    """Run one rule. A tie that the order cannot break comes back as an Outcome without winner."""
    brk = Breaker(order)
    try:
        if method == "plurality":
            return count_plurality(lines, alive, brk)
        if method == "runoff":
            return count_runoff(lines, alive, brk)
        if method == "irv":
            return count_irv(lines, alive, brk)
        if method == "borda":
            return count_borda(lines, alive, brk)
        if method == "kemeny":
            assert matrix is not None
            return count_kemeny(matrix, alive, brk)
        if method == "approval":
            return count_approval(approval_scores(election, alive), brk)
        assert matrix is not None
        return count_condorcet(method, matrix, alive, brk)
    except TieUnresolved as tie:
        return Outcome(method, None, {}, brk.events, tie.tied, tie.stage)


def approval_scores(election: Election, alive: Sequence[int]) -> dict[int, int]:
    """Approvals per option still in the race (from ballots or from the poll totals)."""
    if election.poll is not None:
        return {o: election.poll[o] for o in alive}
    scores = dict.fromkeys(alive, 0)
    for count, approved in election.lines:
        for option in approved:
            if option in scores:
                scores[option] += count
    return scores


def run_count(
    election: Election, alive: list[int], order: Sequence[int] | None, all_rules: bool
) -> Count:
    """Count the vote for the options in `alive`: the agreed rule, and all rules if asked."""
    if election.kind == "ranked":
        lines = restrict_lines(election.lines, alive)
        if not lines:
            raise fc.NoSolution("no ballot ranks any option that is still in the race")
        matrix: list[list[int]] | None = pairwise_matrix(lines, alive, len(election.options))
        exhausted = election.n_ballots - sum(count for count, _ in lines)
    else:
        lines = election.lines
        matrix = None
        exhausted = 0
    cw = condorcet_winner(matrix, alive) if matrix is not None else None
    schulze = schulze_winners(matrix, alive) if matrix is not None else []
    cycle = find_cycle(matrix, alive) if matrix is not None and cw is None else None
    methods = [election.method]
    if all_rules:
        methods = [m for m in RANKED_METHODS if m != "kemeny" or len(alive) <= MAX_KEMENY_OPTIONS]
        if election.method not in methods:
            methods.append(election.method)
    rules = {m: count_method(m, election, alive, lines, matrix, order) for m in methods}
    outcome = rules[election.method]
    if outcome.winner is None:
        raise fc.NoSolution(unresolved_message(election, outcome))
    return Count(alive, lines, matrix, cw, schulze, cycle, exhausted, outcome, rules)


def stage_text(lang: str, stage: tuple) -> str:
    text = TEXT[lang]
    name = stage[0]
    if name == "irv":
        return text["st_irv"].format(n=stage[1])
    if name == "kemeny":
        return text["st_kemeny"].format(n=stage[1])
    return text["st_" + name]


def unresolved_message(election: Election, outcome: Outcome) -> str:
    names = ", ".join(election.options[o] for o in outcome.tied)
    assert outcome.stage is not None
    return (
        f"{names} are tied ({stage_text('en', outcome.stage)}, rule {outcome.method}) and the agreed "
        "rules fix no random source to break the tie. Agree on a public random source before "
        "counting, put it in rules.tie_break.random_source and run again"
    )


# ---------------------------------------------------------------------------------------
# Words and numbers for the output
# ---------------------------------------------------------------------------------------


def join_names(lang: str, names: Sequence[str]) -> str:
    return TEXT[lang]["sep"].join(names)


def say(lang: str, key: str, **values: Any) -> str:
    """Fill the text template of this key (see fsq_core.fill_text for the Latin-name spacing).

    The sentences in which a name or a rule name can sit right next to a Chinese character go
    through here: those that only --remove and --all-rules print, and the result line of a
    private message. The other templates already keep their names apart from Chinese characters.
    """
    return fc.fill_text(lang, TEXT[lang][key], **values)


def half_points(twice: int) -> str:
    """Exact decimal text of twice / 2 (Borda points are whole numbers or end in .5)."""
    whole, rest = divmod(twice, 2)
    return f"{whole}.5" if rest else str(whole)


def line_text(election: Election, lang: str, line: tuple[int, ...]) -> str:
    """One ballot line as text: the ranking, or the approved options."""
    text = TEXT[lang]
    names = [election.options[o] for o in line]
    if election.kind == "ranked":
        return text["gt"].join(names)
    return join_names(lang, names) if names else text["nothing"]


def event_result(election: Election, lang: str, event: TieEvent) -> str:
    text = TEXT[lang]
    names = join_names(lang, [election.options[o] for o in event.picked])
    kind = event.stage[0]
    if event.eliminated:
        return text["ev_out"].format(names=names)
    if kind == "finalists":
        return text["ev_finalists"].format(names=names)
    if kind == "kemeny":
        return text["ev_place"].format(names=names)
    return text["ev_elected"].format(names=names)


def event_text(election: Election, lang: str, event: TieEvent) -> str:
    """One sentence: where the tie was, who was tied and what the order decided."""
    return TEXT[lang]["event"].format(
        where=stage_text(lang, event.stage),
        tied=join_names(lang, [election.options[o] for o in event.tied]),
        result=event_result(election, lang, event),
    )


def summary_text(election: Election, outcome: Outcome, lang: str) -> str:
    """The key numbers behind a winner, in one phrase."""
    text = TEXT[lang]
    names = election.options
    assert outcome.winner is not None
    win = outcome.winner
    data = outcome.data
    method = outcome.method
    if method == "plurality":
        return text["s_plurality"].format(w=names[win], n=data["scores"][win], total=data["total"])
    if method == "runoff":
        if data["decided_in_round_1"]:
            return text["s_runoff_1"].format(
                w=names[win], n=data["first"][win], total=data["total"]
            )
        other = next(o for o in data["finalists"] if o != win)
        return text["s_runoff_2"].format(
            w=names[win], a=data["votes"][win], l=names[other], b=data["votes"][other]
        )
    if method == "irv":
        last = data["rounds"][-1]
        return text["s_irv"].format(
            w=names[win], rounds=len(data["rounds"]), n=last["counts"][win], c=last["continuing"]
        )
    if method == "borda":
        twice = data["twice"]
        ranked = sorted(twice, key=lambda o: (-twice[o], o))
        second = ranked[1]
        return text["s_borda"].format(
            w=names[win],
            a=half_points(twice[win]),
            s=names[second],
            b=half_points(twice[second]),
        )
    if method == "kemeny":
        return text["s_kemeny"].format(w=names[win], score=data["score"])
    if method == "approval":
        return text["s_approval"].format(w=names[win], n=data["scores"][win])
    if data["cw"] is not None:
        return text["s_cw"].format(w=names[win])
    if len(data["schulze"]) == 1:
        return text["s_schulze_one"].format(w=names[win])
    potential = join_names(lang, [names[o] for o in data["schulze"]])
    return text["s_schulze_many"].format(names=potential, w=names[win])


# ---------------------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------------------


def ballots_cell(election: Election, lang: str) -> str:
    text = TEXT[lang]
    if election.kind == "poll":
        if election.participants is None:
            return text["ballots_poll_unknown"]
        return text["ballots_poll"].format(n=election.participants)
    key = "ballots_ranked" if election.kind == "ranked" else "ballots_approval"
    return text[key].format(n=election.n_ballots, k=len(election.lines))


def partial_cell(election: Election, lang: str) -> str:
    text = TEXT[lang]
    if election.method == "plurality":
        return text["partial_first_only"]
    return text["partial_tie_last" if election.partial == "tie_last" else "partial_reject"]


def order_names(election: Election, order: Sequence[int] | None, alive: Sequence[int]) -> list[str]:
    return [election.options[o] for o in (order or []) if o in alive]


def result_table(
    election: Election,
    main: Count,
    original: Count | None,
    removed: list[int],
    order: Sequence[int] | None,
    seed_hex: str | None,
    lang: str,
) -> fc.Table:
    text = TEXT[lang]
    names = election.options
    rows = [[text["r_method"], text["method"][election.method]]]
    winner = names[main.outcome.winner]
    if original is not None:
        gone = join_names(lang, [names[o] for o in removed])
        before = names[original.outcome.winner]
        rows.append([text["r_original"], before])
        rows.append([say(lang, "r_recount", removed=gone), winner])
        rows.append([text["r_changed"], text["changed_yes" if before != winner else "changed_no"]])
    else:
        rows.append([text["r_winner"], winner])
    rows.append([text["r_ballots"], ballots_cell(election, lang)])
    if original is not None and main.exhausted:
        rows.append([text["r_exhausted"], text["exhausted_text"].format(n=main.exhausted)])
    if election.kind == "ranked":
        rows.append([text["r_partial"], partial_cell(election, lang)])
    if election.source is None:
        rows.append([text["r_tiebreak"], text["tie_none"]])
    else:
        rows.append([text["r_tiebreak"], text["tie_source"]])
        rows.append([text["r_order"], text["gt"].join(order_names(election, order, main.alive))])
        rows.append([text["r_source"], election.source])
        rows.append([text["r_seed"], (seed_hex or "")[:16]])
    return fc.Table(text["hdr_result"], rows, text["cap_result"])


def lines_table(election: Election, lang: str) -> tuple[fc.Table | None, list[str]]:
    """The ballots as counted, identical ones merged (for the organizer's read-back)."""
    if election.kind == "poll":
        return None, []
    text = TEXT[lang]
    header = text["hdr_lines_ranked" if election.kind == "ranked" else "hdr_lines_approval"]
    shown = election.lines[:MAX_SHOWN_LINES]
    rows = [[str(count), line_text(election, lang, line)] for count, line in shown]
    notes = []
    if len(election.lines) > len(shown):
        notes.append(text["more_lines"].format(count=len(election.lines) - len(shown)))
    return fc.Table(header, rows, text["cap_lines"]), notes


def method_tables(election: Election, count: Count, lang: str) -> list[fc.Table]:
    """The tables that belong to the agreed rule: its scores or rounds."""
    text = TEXT[lang]
    names = election.options
    outcome = count.outcome
    data = outcome.data
    method = outcome.method
    if method == "plurality":
        scores = data["scores"]
        rows = [[names[o], str(scores[o])] for o in sorted(scores, key=lambda o: (-scores[o], o))]
        return [fc.Table(text["hdr_first"], rows, text["cap_first"])]
    if method == "runoff":
        first = data["first"]
        finalists = data["finalists"] or ()
        rows = []
        for option in sorted(first, key=lambda o: (-first[o], o)):
            if data["decided_in_round_1"]:
                fate = text["fate_elected"] if option == outcome.winner else ""
            else:
                fate = text["fate_final" if option in finalists else "fate_out"]
            rows.append([names[option], str(first[option]), fate])
        tables = [fc.Table(text["hdr_round1"], rows, text["cap_round1"])]
        if not data["decided_in_round_1"]:
            votes = data["votes"]
            rows = [[names[o], str(votes[o])] for o in finalists]
            if data["abstain"]:
                rows.append([text["row_abstain"], str(data["abstain"])])
            tables.append(fc.Table(text["hdr_round2"], rows, text["cap_round2"]))
        return tables
    if method == "irv":
        everyone = count.alive
        header = [text["hdr_irv_head"]] + [names[o] for o in everyone]
        header += [text["hdr_irv_exhausted"], text["hdr_irv_result"]]
        rows = []
        for number, entry in enumerate(data["rounds"], start=1):
            cells = [entry["counts"].get(o) for o in everyone]
            row = [text["irv_round"].format(n=number)]
            row += ["-" if cell is None else str(cell) for cell in cells]
            row.append(str(entry["exhausted"]))
            if entry["winner"] is not None:
                row.append(text["irv_elected"].format(name=names[entry["winner"]]))
            else:
                gone = join_names(lang, [names[o] for o in entry["eliminated"]])
                zero = all(entry["counts"][o] == 0 for o in entry["eliminated"])
                row.append(text["irv_out_zero" if zero else "irv_out"].format(names=gone))
            rows.append(row)
        return [fc.Table(header, rows, text["cap_irv"])]
    if method == "borda":
        twice = data["twice"]
        rows = [
            [names[o], half_points(twice[o])] for o in sorted(twice, key=lambda o: (-twice[o], o))
        ]
        caption = text["cap_borda"].format(top=data["size"] - 1)
        return [fc.Table(text["hdr_borda"], rows, caption)]
    if method == "approval":
        scores = data["scores"]
        rows = [[names[o], str(scores[o])] for o in sorted(scores, key=lambda o: (-scores[o], o))]
        return [fc.Table(text["hdr_approval"], rows, text["cap_approval"])]
    if method == "kemeny":
        rows = [[str(place), names[o]] for place, o in enumerate(data["ranking"], start=1)]
        return [fc.Table(text["hdr_kemeny"], rows, text["cap_kemeny"])]
    return []


def pairwise_tables(election: Election, count: Count, lang: str) -> list[fc.Table]:
    """The pairwise matrix, and the cycle if there is one."""
    if count.matrix is None:
        return []
    text = TEXT[lang]
    names = election.options
    matrix = count.matrix
    header = [""] + [names[b] for b in count.alive]
    rows = [
        [names[a]] + ["-" if a == b else str(matrix[a][b]) for b in count.alive]
        for a in count.alive
    ]
    tables = [fc.Table(header, rows, text["cap_pairwise"])]
    if count.cycle:
        cycle = count.cycle
        links = []
        for at, a in enumerate(cycle):
            b = cycle[(at + 1) % len(cycle)]
            links.append(
                [
                    names[a],
                    names[b],
                    f"{matrix[a][b]} : {matrix[b][a]}",
                    str(matrix[a][b] - matrix[b][a]),
                ]
            )
        tables.append(fc.Table(text["hdr_cycle"], links, text["cap_cycle"]))
    return tables


def ties_table(election: Election, count: Count, lang: str) -> list[fc.Table]:
    events = count.outcome.events
    if not events:
        return []
    text = TEXT[lang]
    rows = [
        [
            stage_text(lang, event.stage),
            join_names(lang, [election.options[o] for o in event.tied]),
            event_result(election, lang, event),
        ]
        for event in events
    ]
    return [fc.Table(text["hdr_ties"], rows, text["cap_ties"])]


def rule_cell(
    election: Election, count: Count, method: str, lang: str
) -> tuple[int | None, str, str]:
    """(winner, winner text, key numbers) of one rule in the all-rules table."""
    text = TEXT[lang]
    outcome = count.rules.get(method)
    if outcome is None:
        return None, text["all_skipped"].format(limit=MAX_KEMENY_OPTIONS), ""
    if outcome.winner is None:
        names = join_names(lang, [election.options[o] for o in outcome.tied])
        return None, text["all_tied"].format(names=names), ""
    return (
        outcome.winner,
        election.options[outcome.winner],
        summary_text(election, outcome, lang),
    )


def all_rules_table(
    election: Election, main: Count, original: Count | None, removed: list[int], lang: str
) -> fc.Table:
    text = TEXT[lang]
    rows = []
    for method in RANKED_METHODS:
        label = text["method_short"][method]
        if method == election.method:
            label += text["all_marker"]
        win, win_text, numbers = rule_cell(election, main, method, lang)
        if original is None:
            rows.append([label, win_text, numbers])
            continue
        before, before_text, _ = rule_cell(election, original, method, lang)
        if win is None or before is None:
            change = ""
        else:
            change = text["changed_yes" if win != before else "changed_no"]
        rows.append([label, before_text, win_text, change])
    if original is None:
        return fc.Table(text["hdr_all"], rows, text["cap_all"])
    gone = join_names(lang, [election.options[o] for o in removed])
    header = [fc.fill_text(lang, cell, removed=gone) for cell in text["hdr_all_remove"]]
    return fc.Table(header, rows, text["cap_all"])


def all_rules_winners(election: Election, count: Count) -> dict[str, str | None]:
    return {
        method: (None if out.winner is None else election.options[out.winner])
        for method, out in count.rules.items()
    }


# ---------------------------------------------------------------------------------------
# Notes, private messages, group summary
# ---------------------------------------------------------------------------------------


def not_modeled(election: Election, lang: str) -> list[str]:
    text = TEXT[lang]
    lines = [text["nm_strategy"]]
    if election.kind == "ranked":
        lines.append(text["nm_ties_in_ballot"])
    return lines + [text["nm_eligibility"]]


def condorcet_notes(election: Election, count: Count, lang: str) -> list[str]:
    if count.matrix is None:
        return []
    text = TEXT[lang]
    names = election.options
    if count.cw is not None:
        return [text["note_cw_yes"].format(name=names[count.cw])]
    notes = [text["note_cw_no"]]
    if count.cycle is None:
        notes.append(text["note_cw_no_cycle"])
    if len(count.schulze) > 1:
        potential = join_names(lang, [names[o] for o in count.schulze])
        notes.append(text["note_schulze"].format(names=potential))
    return notes


def receipt_lines(
    election: Election, count: Count, key: tuple[int, ...], removed: list[int], lang: str
) -> list[str]:
    """One person's private message: their ballot as recorded, and how it relates to the result."""
    text = TEXT[lang]
    names = election.options
    win = count.outcome.winner
    assert win is not None
    method = text["method"][election.method]
    if removed:
        gone = join_names(lang, [names[o] for o in removed])
        result = say(lang, "dm_result_recount", removed=gone, method=method, winner=names[win])
    else:
        result = say(lang, "dm_result", method=method, winner=names[win])
    lines: list[str] = []
    if election.kind == "ranked":
        lines.append(text["dm_ballot"].format(ranking=line_text(election, lang, key)))
        left_out = [names[o] for o in range(len(names)) if o not in key]
        if left_out:
            lines.append(text["dm_unranked"].format(names=join_names(lang, left_out)))
        lines.append(result)
        shown = [o for o in key if o in count.alive]
        if win in shown:
            place = text["dm_place"].format(winner=names[win], k=shown.index(win) + 1)
        else:
            place = text["dm_place_unranked"].format(winner=names[win])
        lines.append(place)
    else:
        approved = join_names(lang, [names[o] for o in key]) if key else text["nothing"]
        if key:
            lines.append(text["dm_approve"].format(names=approved))
        else:
            lines.append(text["dm_ballot"].format(ranking=text["nothing"]))
        lines.append(result)
        lines.append(
            text["dm_approved" if win in key else "dm_not_approved"].format(winner=names[win])
        )
    lines.append(text["dm_check"])
    return lines


def group_lines_for(
    election: Election,
    main: Count,
    original: Count | None,
    removed: list[int],
    all_rules: bool,
    lang: str,
) -> list[str]:
    text = TEXT[lang]
    names = election.options
    outcome = main.outcome
    assert outcome.winner is not None
    lines = [
        text["g_result"].format(
            method=text["method"][election.method], winner=names[outcome.winner]
        )
    ]
    lines.append(
        text["g_ballots_poll"]
        if election.kind == "poll"
        else text["g_ballots"].format(n=election.n_ballots)
    )
    lines.append(text["g_numbers"].format(numbers=summary_text(election, outcome, lang)))
    if election.kind == "ranked" and election.partial == "tie_last" and election.first_partial:
        lines.append(text["g_partial"])
    if outcome.events:
        events = text["event_sep"].join(event_text(election, lang, e) for e in outcome.events)
        lines.append(text["g_ties_used"].format(events=events))
    elif election.source is not None:
        lines.append(text["g_ties_ready"].format(source=election.source))
    if original is not None and original.outcome.winner is not None:
        gone = join_names(lang, [names[o] for o in removed])
        old, new = names[original.outcome.winner], names[outcome.winner]
        key = "g_recount_same" if old == new else "g_recount_changed"
        change = text[key].format(old=old, new=new)
        lines.append(say(lang, "g_recount", removed=gone, change=change))
    if all_rules:
        lines.append(text["g_all_intro"])
        for method in RANKED_METHODS:
            if method in main.rules:
                _, win_text, _ = rule_cell(election, main, method, lang)
                lines.append(
                    text["g_all_line"].format(method=text["method_short"][method], winner=win_text)
                )
    return lines


def all_rules_notes(election: Election, main: Count, lang: str) -> list[str]:
    text = TEXT[lang]
    names = election.options
    winners = {out.winner for out in main.rules.values() if out.winner is not None}
    last = "note_same" if len(winners) == 1 else "note_distinct"
    return [
        say(
            lang,
            "note_all",
            method=text["method"][election.method],
            winner=names[main.outcome.winner],
        ),
        text[last].format(rules=len(main.rules), distinct=len(winners)),
    ]


def tie_order_note(election: Election, main: Count, lang: str) -> list[str]:
    if election.source is None:
        return []
    text = TEXT[lang]
    used = text["used_yes" if main.outcome.events else "used_no"]
    return [text["note_order"].format(used=used)]


# ---------------------------------------------------------------------------------------
# The Result (md, dm, group and json all come from it)
# ---------------------------------------------------------------------------------------


def matrix_json(election: Election, count: Count) -> dict[str, dict[str, int]] | None:
    if count.matrix is None:
        return None
    names = election.options
    return {
        names[a]: {names[b]: count.matrix[a][b] for b in count.alive if b != a} for a in count.alive
    }


def cycle_json(election: Election, count: Count) -> dict[str, Any] | None:
    if not count.cycle or count.matrix is None:
        return None
    names = election.options
    links = []
    for at, a in enumerate(count.cycle):
        b = count.cycle[(at + 1) % len(count.cycle)]
        links.append(
            {
                "winner": names[a],
                "loser": names[b],
                "for": count.matrix[a][b],
                "against": count.matrix[b][a],
                "margin": count.matrix[a][b] - count.matrix[b][a],
            }
        )
    return {"links": links}


def stage_key(stage: tuple) -> str:
    return stage[0] if len(stage) == 1 else f"{stage[0]}_{stage[1]}"


def events_json(election: Election, outcome: Outcome) -> list[dict[str, Any]]:
    names = election.options
    return [
        {
            "stage": stage_key(event.stage),
            "tied": [names[o] for o in event.tied],
            "picked": [names[o] for o in event.picked],
            "eliminated": event.eliminated,
        }
        for event in outcome.events
    ]


def detail_json(election: Election, outcome: Outcome) -> dict[str, Any]:
    """The parts of the result that belong to one rule: scores, rounds or ranking."""
    names = election.options
    data = outcome.data
    method = outcome.method
    if method in ("plurality", "approval"):
        scores = data["scores"]
        return {"scores": {names[o]: scores[o] for o in sorted(scores)}}
    if method == "runoff":
        first = data["first"]
        detail: dict[str, Any] = {
            "round_1": {
                "votes": {names[o]: first[o] for o in sorted(first)},
                "decided": data["decided_in_round_1"],
            },
            "round_2": None,
        }
        if not data["decided_in_round_1"]:
            votes = data["votes"]
            detail["round_2"] = {
                "finalists": [names[o] for o in data["finalists"]],
                "votes": {names[o]: votes[o] for o in data["finalists"]},
                "abstain": data["abstain"],
            }
        return detail
    if method == "irv":
        rounds = []
        for number, entry in enumerate(data["rounds"], start=1):
            rounds.append(
                {
                    "round": number,
                    "counts": {names[o]: n for o, n in sorted(entry["counts"].items())},
                    "exhausted": entry["exhausted"],
                    "continuing": entry["continuing"],
                    "eliminated": [names[o] for o in entry["eliminated"]],
                    "winner": None if entry["winner"] is None else names[entry["winner"]],
                }
            )
        return {"rounds": rounds}
    if method == "borda":
        twice = data["twice"]
        return {"scores": {names[o]: half_points(twice[o]) for o in sorted(twice)}}
    if method == "kemeny":
        return {
            "ranking": [names[o] for o in data["ranking"]],
            "score": data["score"],
            "optimal_rankings": data["ways"],
        }
    return {}


def per_rule_json(election: Election, count: Count) -> dict[str, Any]:
    """For every rule of --all-rules: the winner (or the options left tied) and its numbers."""
    names = election.options
    out: dict[str, Any] = {}
    for method, outcome in count.rules.items():
        if outcome.winner is None:
            out[method] = {"winner": None, "tied": [names[o] for o in outcome.tied]}
        else:
            out[method] = {"winner": names[outcome.winner], **detail_json(election, outcome)}
    return out


def rules_echo(election: Election) -> dict[str, Any]:
    rules: dict[str, Any] = {"method": election.method}
    if election.kind == "ranked":
        rules["partial"] = election.partial
    if election.source is not None:
        rules["tie_break"] = {"random_source": election.source}
    return rules


def inputs_echo(election: Election, removed: list[int], all_rules: bool) -> dict[str, Any]:
    names = election.options
    echo: dict[str, Any] = {
        "options": list(names),
        "kind": election.kind,
        "rules": rules_echo(election),
        "all_rules": all_rules,
    }
    if election.topic is not None:
        echo["topic"] = election.topic
    if election.kind == "poll":
        assert election.poll is not None
        echo["approval_counts"] = {name: election.poll[o] for o, name in enumerate(names)}
        if election.participants is not None:
            echo["participants"] = election.participants
    else:
        echo["ballot_total"] = election.n_ballots
        key = "ranking" if election.kind == "ranked" else "approve"
        echo["ballot_lines"] = [
            {"count": count, key: [names[o] for o in line]} for count, line in election.lines
        ]
    if removed:
        echo["removed"] = [names[o] for o in removed]
    return echo


def build_result(
    election: Election,
    main: Count,
    original: Count | None,
    removed: list[int],
    order: Sequence[int] | None,
    seed_hex: str | None,
    all_rules: bool,
    lang: str,
    reproduce: str,
) -> fc.Result:
    """Turn the counts into the shared Result."""
    if lang not in TEXT:
        raise ValueError(f"lang must be one of {', '.join(TEXT)}")
    text = TEXT[lang]
    names = election.options
    outcome = main.outcome
    assert outcome.winner is not None
    topic = election.topic or text["default_topic"]
    method_name = text["method"][election.method]
    if removed:
        gone = join_names(lang, [names[o] for o in removed])
        title = say(lang, "title_recount", topic=topic, removed=gone, method=method_name)
    else:
        title = text["title"].format(topic=topic, method=method_name)

    tables = [result_table(election, main, original, removed, order, seed_hex, lang)]
    notes: list[str] = []
    lines_tab, line_notes = lines_table(election, lang)
    if lines_tab is not None:
        tables.append(lines_tab)
    tables += method_tables(election, main, lang)
    tables += pairwise_tables(election, main, lang)
    tables += ties_table(election, main, lang)
    if all_rules:
        tables.append(all_rules_table(election, main, original, removed, lang))
    notes += line_notes + condorcet_notes(election, main, lang)
    if election.method == "kemeny":
        kemeny = outcome.data
        notes.append(text["note_kemeny"].format(score=kemeny["score"], ways=kemeny["ways"]))
    if election.kind == "ranked" and election.partial == "tie_last" and election.first_partial:
        notes.append(text["note_partial"])
    notes += tie_order_note(election, main, lang)
    if removed:
        notes.append(text["note_removed"])
        old, new = names[original.outcome.winner], names[outcome.winner]
        key = "note_recount_same" if old == new else "note_recount_changed"
        gone = join_names(lang, [names[o] for o in removed])
        notes.append(say(lang, key, removed=gone, old=old, new=new))
    if all_rules:
        notes += all_rules_notes(election, main, lang)

    group = group_lines_for(election, main, original, removed, all_rules, lang)
    person_lines = {
        voter: receipt_lines(election, main, key, removed, lang) for voter, key in election.voters
    }
    if not person_lines:
        person_lines = {text["everyone"]: list(group)}

    result: dict[str, Any] = {
        "method": election.method,
        "winner": names[outcome.winner],
        "tie_break_order": order_names(election, order, main.alive) if order else None,
        "tie_events": events_json(election, outcome),
        "pairwise_matrix": matrix_json(election, main),
        "condorcet_winner": None if main.cw is None else names[main.cw],
        "schulze_winners": [names[o] for o in main.schulze],
        "cycle": cycle_json(election, main),
        "removed_ballots": main.exhausted,
    }
    result.update(detail_json(election, outcome))
    if all_rules:
        result["per_rule_winners"] = all_rules_winners(election, main)
        result["per_rule"] = per_rule_json(election, main)
    if original is not None:
        before = names[original.outcome.winner]
        result["recount"] = {
            "removed": [names[o] for o in removed],
            "original_winner": before,
            "winner": names[outcome.winner],
            "changed": before != names[outcome.winner],
        }
        if all_rules:
            result["recount"]["per_rule_winners_before"] = all_rules_winners(election, original)

    certificate: dict[str, Any] = {
        "seed_hex": seed_hex,
        "tie_break_order": [names[o] for o in order] if order else None,
        "how_to_verify": None,
    }
    if seed_hex is not None:
        certificate["how_to_verify"] = (
            f'{fc.SEED_SPEC} Here the rule is "{TIE_RULE_NAME}", the participants are the '
            f"options and n_slots is {TIE_SLOTS}. The first option of the order wins a tie."
        )
    if election.voters:
        certificate["one_liner"] = {voter: " ".join(lines) for voter, lines in person_lines.items()}
    return fc.Result(
        title=title,
        inputs_echo=inputs_echo(election, removed, all_rules),
        result=result,
        certificate=certificate,
        not_modeled=not_modeled(election, lang),
        reproduce=reproduce,
        tables=tables,
        notes=notes,
        person_lines=person_lines,
        group_lines=group,
    )


def parse_removed(election: Election, remove: Sequence[str]) -> list[int]:
    index = {name: number for number, name in enumerate(election.options)}
    gone = set()
    for name in remove:
        if name not in index:
            raise fc.InputError("--remove", f"{name!r} is not one of the options")
        gone.add(index[name])
    if len(election.options) - len(gone) < 2:
        raise fc.InputError("--remove", "at least two options must stay in the race")
    return sorted(gone)


def solve(
    data: Any,
    lang: str = "zh",
    all_rules: bool = False,
    remove: Sequence[str] = (),
    reproduce: str = "",
) -> fc.Result:
    """Validate one input object, count it and build the Result."""
    election = parse_election(data)
    if all_rules and election.kind != "ranked":
        raise fc.InputError(
            "--all-rules",
            "compares ranking rules, so it needs ranked ballots (ballots or a csv of ranks)",
        )
    check_partial(election, election.method != "plurality" or all_rules)
    removed = parse_removed(election, remove)
    order, seed_hex = tie_order(election)
    everyone = list(range(len(election.options)))
    original = run_count(election, everyone, order, all_rules)
    if not removed:
        return build_result(
            election, original, None, [], order, seed_hex, all_rules, lang, reproduce
        )
    alive = [o for o in everyone if o not in removed]
    main = run_count(election, alive, order, all_rules)
    return build_result(
        election, main, original, removed, order, seed_hex, all_rules, lang, reproduce
    )


# ---------------------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------------------


def selftest_checks() -> list:
    """Checks for --selftest: the demo numbers and a few cross-checks, all fast."""

    def demo_count(remove: Sequence[str] = ()) -> tuple[Election, Count]:
        election = parse_election(fc.parse_input(DEMO_JSON))
        order, _ = tie_order(election)
        alive = [o for o in range(len(election.options)) if election.options[o] not in remove]
        return election, run_count(election, alive, order, True)

    def winners(election: Election, count: Count) -> dict[str, str]:
        return {m: election.options[o.winner] for m, o in count.rules.items()}

    def check_five_winners() -> None:
        election, count = demo_count()
        got = winners(election, count)
        want = {
            "plurality": "密室逃脱",
            "runoff": "剧本杀",
            "irv": "火锅",
            "borda": "KTV",
            "condorcet": "爬山",
            "schulze": "爬山",
            "kemeny": "爬山",
        }
        fc.expect(got == want, f"winners {got}")
        names = election.options
        votes = count.rules["runoff"].data["votes"]
        fc.expect(
            {names[o]: n for o, n in votes.items()} == {"剧本杀": 15, "密室逃脱": 12}, "runoff"
        )
        twice = count.rules["borda"].data["twice"]
        fc.expect(twice[names.index("KTV")] == 128 and twice[names.index("爬山")] == 126, "borda")

    def check_removal() -> None:
        for gone in ("剧本杀", "密室逃脱"):
            election, count = demo_count((gone,))
            fc.expect(set(winners(election, count).values()) == {"爬山"}, f"without {gone}")

    def check_cycle() -> None:
        data = {
            "options": ["A", "B", "C"],
            "ballots": [
                {"count": 1, "ranking": ["A", "B", "C"]},
                {"count": 1, "ranking": ["B", "C", "A"]},
                {"count": 1, "ranking": ["C", "A", "B"]},
            ],
            "rules": {"method": "schulze"},
        }
        try:
            solve(data)
        except fc.NoSolution:
            pass
        else:
            raise AssertionError("a three-way cycle needs a random source")
        data["rules"]["tie_break"] = {"random_source": "selftest"}
        first = fc.envelope(solve(data))["result"]
        second = fc.envelope(solve(data))["result"]
        fc.expect(first == second and first["cycle"] is not None, "cycle with a source")
        fc.expect(first["condorcet_winner"] is None and len(first["schulze_winners"]) == 3, "set")

    def check_kemeny_brute_force() -> None:
        lines = [(3, (0, 1, 2, 3)), (2, (2, 3, 1, 0)), (2, (1, 2, 0, 3)), (1, (3, 0, 1, 2))]
        alive = [0, 1, 2, 3]
        matrix = pairwise_matrix(lines, alive, 4)
        best = -1
        for perm in itertools.permutations(alive):
            score = sum(matrix[perm[i]][perm[j]] for i in range(4) for j in range(i + 1, 4))
            best = max(best, score)
        fc.expect(
            count_kemeny(matrix, alive, Breaker(list(range(4)))).data["score"] == best, "kemeny"
        )

    def check_partial_ballots() -> None:
        alive = [0, 1, 2]
        matrix = pairwise_matrix([(1, (1,)), (1, (0, 2))], alive, 3)
        # the first ballot ranks only option 1, the second ranks 0 above 2 and leaves 1 out
        fc.expect(matrix[1][0] == 1 and matrix[1][2] == 1, "a ranked option beats an unranked one")
        fc.expect(
            matrix[0][2] == 1 and matrix[0][1] == 1 and matrix[2][1] == 1, "the second ballot"
        )
        fc.expect(matrix[2][0] == 0, "nobody ranks 2 above 0")
        borda = count_borda([(1, (1,))], alive, Breaker(None)).data["twice"]
        fc.expect(borda == {0: 1, 1: 4, 2: 1}, f"borda shares the rest {borda}")

    def check_rejections() -> None:
        base = {
            "options": ["A", "B"],
            "ballots": [{"count": 1, "ranking": ["A", "B"]}],
            "rules": {"method": "plurality"},
        }
        bad = (
            (dict(base, options=["A", "A"]), "options[1]"),
            (dict(base, ballots=[{"ranking": ["A", "C"]}]), "ballots[0].ranking[1]"),
            (dict(base, rules={}), "rules.method"),
            (dict(base, rules={"method": "irv", "partial": "x"}), "rules.partial"),
        )
        for data, name in bad:
            try:
                parse_election(data)
            except fc.InputError as err:
                fc.expect(name in err.field, f"{name} named as {err.field}")
            else:
                raise AssertionError(f"{name} was accepted")

    return [
        ("27 ballots, five rules, five winners", check_five_winners),
        ("removing an option changes the winners", check_removal),
        ("cycle needs a random source", check_cycle),
        ("Kemeny equals brute force", check_kemeny_brute_force),
        ("partial ballots", check_partial_ballots),
        ("bad input names its field", check_rejections),
    ]


# ---------------------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="group_vote.py",
        description=(
            "Count a group vote under rules fixed in advance (plurality, two-round runoff, IRV, "
            "Borda, Condorcet with Schulze, approval or Kemeny), with exact integers. Every tie "
            "is broken by an order of the options fixed with a public random source."
        ),
        epilog=(
            "Input is a JSON object: options, rules (method, optional partial and tie_break) and "
            "one of ballots, approvals, approval_counts or csv. "
        )
        + fc.exit_codes_epilog(three="a tie that the agreed rules cannot break"),
    )
    fc.standard_args(parser)
    fc.add_lang_option(parser, "names and JSON keys do not change")
    parser.add_argument(
        "--all-rules",
        action="store_true",
        help="also show the winner under every other rule. Only for explaining a result after "
        "the fact: the rule is fixed before the vote and never chosen from this table",
    )
    parser.add_argument(
        "--remove",
        action="append",
        default=[],
        metavar="OPTION",
        help="count again without this option (repeat to remove several) and report whether "
        "the winner changes",
    )
    return parser


def reproduce_command(args: argparse.Namespace) -> str:
    parts = ["python3", "scripts/group_vote.py"]
    parts += ["--demo"] if args.demo else ["--input", "-"]
    parts += ["--json"] if args.json else ["--format", args.format]
    if args.all_rules and not args.demo:
        parts.append("--all-rules")
    for name in args.remove:
        parts += ["--remove", shlex.quote(name)]
    if args.lang != "zh":
        parts += ["--lang", args.lang]
    return " ".join(parts)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    fc.exclusive_modes(args, "--demo", "--selftest")
    if args.selftest:
        return fc.run_selftest(selftest_checks())
    data = fc.read_object(args, DEMO_JSON)
    result = solve(
        data,
        args.lang,
        args.all_rules or args.demo,
        args.remove,
        reproduce_command(args),
    )
    fc.emit(result, args, lang=args.lang)
    return 0


if __name__ == "__main__":
    fc.run_cli(main)
