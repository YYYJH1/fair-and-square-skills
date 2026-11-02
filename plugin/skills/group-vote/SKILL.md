---
name: group-vote
description: Use whenever a group has to pick one option by vote (a team outing, a restaurant, a name, a proposal) or asks how the votes should be counted, even if nobody asks for an algorithm. Runs a bundled script that counts ranked ballots, a questionnaire export or the totals of a chat poll under rules fixed before the vote (plurality, two-round runoff, instant runoff, Borda, Condorcet with Schulze, approval or Kemeny), breaks every tie with a public random source, shows the pairwise matrix and any cycle, and recounts when an option drops out. Typical requests include ranked choice, pick a restaurant by vote, vote on options, 团建投票、投票选去哪、几个选项怎么定、排序投票、群里投票结果怎么算. Not for allocating limited slots by lot (use slot-lottery) or for splitting money (use bill-split, rent-split or ride-split).
license: MIT
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/group_vote.py *)
---

# group-vote

With the same ballots, different counting rules can elect different options. In the bundled demo, 27 ballots make plurality pick 密室逃脱, a two-round runoff 剧本杀, instant runoff 火锅, Borda KTV and the Condorcet method 爬山. So the rule has to be chosen before anybody votes, and the votes have to be counted by a script that anyone can rerun. This skill fixes the rule, the tie-break and the handling of partial ballots in one message first, collects the ballots privately, and counts them with a script that uses exact integers.

Quote every winner, count and name exactly as the script prints it. Do not count, tally or break a tie yourself.

## The script

`${CLAUDE_SKILL_DIR}/scripts/group_vote.py`. If that variable was not replaced, the script is in the `scripts/` folder next to this file.

In Claude Code, give the script the input as a file and let the script delete it. Claude Code asks the user to approve any command whose heredoc body holds both braces and quotes, and the input of this skill always does (a session that cannot ask refuses the command). So write the input JSON with the Write tool to a new file in the session's scratchpad directory (in a temporary directory if the session has none), then run the script on that file with `--delete-input`:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/group_vote.py --format md --input <input-file> --delete-input
```

The script deletes the file as soon as it has read it, also when it then rejects the input, so the ballots are on disk only from the Write until that run. Use a file you wrote for this run, never one the user already had, because the script deletes it. Put the full path in the command, with no variable and nothing chained to it, because Claude Code asks for approval otherwise. If a run stops before it reads the file (a mistyped option, a wrong path), the file is still there, so run the corrected command. Step 3 runs the script several times on the same input. Run those one after another and add `--delete-input` to the last run only. A later run on the same input needs the file written again.

In Codex and other tools, pass the input on standard input through a heredoc, so that no input file is created. This is a small example with made-up names:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/group_vote.py --format md --input - <<'EOF'
{
  "topic": "团建去哪儿",
  "options": ["爬山", "火锅", "KTV"],
  "ballots": [
    {"count": 5, "ranking": ["火锅", "爬山", "KTV"]},
    {"count": 4, "ranking": ["爬山", "火锅", "KTV"]},
    {"count": 3, "ranking": ["KTV", "火锅", "爬山"]}
  ],
  "rules": {
    "method": "condorcet",
    "tie_break": {"random_source": "（虚构示例）2026-11-08 某公开开奖号码 03 11 19 24 33 + 02 07"}
  }
}
EOF
```

The input fields. Give exactly one of `ballots`, `approvals`, `approval_counts` and `csv`:

| Field | Meaning |
|---|---|
| `topic` | Optional title for the messages. |
| `options` | 2 to 20 distinct names. |
| `ballots` | Ranked ballots, `{"count": 5, "ranking": ["火锅", "爬山"]}`, best first. A ballot may stop early (see `rules.partial`). For one named person write `{"voter": "小红", "ranking": [...]}` instead of a count. |
| `approvals` | Approval ballots, `{"count": 3, "approve": ["火锅", "KTV"]}`, or with `voter`. The list may be empty. |
| `approval_counts` | The totals of a chat poll, `{"火锅": 12, "爬山": 9}`, every option listed (0 if nobody chose it). Optional `participants` is the number of people who took part. |
| `csv` | A questionnaire export pasted as text (see Step 2). |
| `rules.method` | Required, no default: `plurality`, `runoff`, `irv`, `borda`, `condorcet`, `schulze`, `approval` or `kemeny` (at most 8 options). |
| `rules.partial` | `reject` (default: every ballot ranks every option, except that plurality reads only the first name) or `tie_last` (options a ballot leaves out tie for last). |
| `rules.tie_break.random_source` | The public text that fixes the tie-break order, copied exactly. `rules.random_source`, the spelling rent-split uses, is accepted too. Without it, a tie ends the run with exit code 3. |

Options are listed by `--help`. In short: `--format dm` writes one private message per named voter, `--format group` a summary for the group chat, `--json` the full result, `--lang en` switches the text to English, `--remove OPTION` counts again without that option, `--all-rules` explains a result after the fact, `--demo` runs the 27-ballot example and `--selftest` runs the built-in checks. Exit code 2 means invalid input and the message names the field. Exit code 3 means a tie that the agreed rules cannot break. Exit code 1 means a failed self-test. Python 3.9 or later, standard library only.

The `examples/` folder holds four complete inputs: `examples/team_outing_27.json` (the demo), `examples/cycle_three.json` (a Condorcet cycle), `examples/poll_counts.json` (a chat poll counted as approval voting) and `examples/questionnaire.csv.json` (a questionnaire export with partial ballots).

## Step 1. Fix the rules before anyone votes

Done when the organizer has posted one rules message and nobody objected.

Draft the rules message for the organizer. It fixes in advance:

1. How to vote. Either each person ranks the options from best to worst, or ticks every option they would accept (approval). Say whether a ranking may stop early. If it may, the options left out tie for last on that ballot.
2. The counting rule, with one sentence of what it does. `condorcet` is a reasonable default for ranked ballots: an option that beats every other option in head-to-head comparisons wins, and the Schulze method decides when none does. `condorcet` and `schulze` always name the same winner. `plurality` is the easiest to explain (one name each, most names wins). `runoff` lets the top two meet in a second round. `irv` drops the weakest option round by round. `borda` gives points by position. `approval` fits a chat poll where people tick several options. `kemeny` finds the ranking that agrees most with all ballots.
3. The tie-break. A public random source named now and published later, for example the winning numbers of a named lottery draw on a named date. The script turns it into one order of the options with SHA-256, and the option earlier in that order wins every tie. Name a source even if you expect no tie.
4. Everyone votes privately and at the same time, by a deadline. Nobody needs to guess what others will vote. Ballots that do not arrive in time do not count.
5. The organizer goes first. The organizer hands their own ballot to another member before looking at anyone else's.

The group does not vote on the rule after seeing results. If AskUserQuestion is available, confirm the rule choices with it: one sentence restating the situation, the recommended option first. Otherwise ask numbered questions, each with the recommended answer.

Example (Chinese):

> 团建投票规则（先定再收）：
> 1. 把五个去处按喜欢程度从高到低排好，可以只排前几个，没排的算并列最后。周五晚 8 点前私聊发我，大家同时交，不必猜别人怎么排。
> 2. 计票用孔多塞法：如果有一个去处在两两比较中胜过其他所有去处，就选它。没有的话用 Schulze 法补全。
> 3. 如果出现平票，用 11 月 8 日公开的开奖号码排出一个顺序，排前面的占优。
> 4. 我先交：我的选票已经交给小红保管。
> 5. 结果出来后不再改规则。

## Step 2. Collect and read back

Done when the organizer has confirmed the input table.

- Ballots reach the organizer privately, by direct message or an anonymous questionnaire, never in the group. The organizer's own ballot goes in too, and it was handed over first.
- A questionnaire export goes into `csv` as text. The first row holds the column names. Every option needs one column named exactly like the option, holding its rank (1 is best, leave it blank if the person did not rank it), or a 1 for an option that was ticked under approval voting. Other columns, such as a time stamp, are ignored. Each row is one person. A row that ranks nothing, or gives one rank to two options, is rejected: ask the person, then fix the row. Tab-separated text works too.
- A chat poll gives only the total per option. Put the totals in `approval_counts`. They can only be counted as approval voting.
- To send each person a receipt of their own ballot, give every ballot a `voter` name. The names appear only in `--format dm`, which holds one person's ballot and nobody else's.
- Build the JSON, show it back to the organizer as a table of ballots and options, and wait for confirmation before running.

## Step 3. Run

Done when the script has exited with code 0.

If the rules named a random source, wait until it is published and copy its text exactly into `rules.tie_break.random_source`. Run the script three times on the same input, as in the first example: `--format md` for the organizer's tables, `--format dm` for the private messages and `--format group` for the group-chat summary. If it exits with code 2, show the message to the organizer, fix the named field with the person concerned and run again. Do not guess a value.

If it exits with code 3, a tie came up and the rules named no random source. Tell the organizer. The group has to agree openly on a public random source, put it in `rules.tie_break.random_source` and count again. Do not choose the winner, and do not break the tie by name, by coin or by who asks.

## Step 4. Present

Done when the organizer has the tables, every named voter has their own message and the group has the summary.

1. Give the organizer the `md` output: the result, the ballots as counted, the rounds or scores of the rule, the pairwise matrix and the cycle if there is one. It lists every distinct ballot, which can identify a person in a small group, so keep it with the organizer.
2. Give each named voter their block from `--format dm`, privately. It shows their ballot as the script recorded it, so a mistake in typing shows up. It never holds another person's ballot. Without voter names, `dm` prints one block for everyone.
3. Post the `--format group` summary. It holds the winner, the key numbers and how any tie was broken, and no ballot.
4. If a tie was broken, say so and point to the tie table. The order came from the random source the group chose in advance.

## When an option drops out

If an option turns out to be unavailable, count again with `--remove`, once for each option, for example `--remove 火锅`. The ballots are counted again without that option, under the same rule and with the same tie-break order. The output says whether the winner changed. A new winner can appear: in the demo, removing 剧本杀 or 密室逃脱 makes all five rules pick 爬山. Report the script's statement as printed.

## Explaining after the fact

If the group asks why the rule mattered, or what another rule would have chosen, run with `--all-rules` on ranked ballots. The table lists the winner under every rule and says it is for explanation only. The rule was fixed before the vote and is not chosen from this table. With `--remove` the table shows each rule before and after the removal.

## Guarantees and limits

- The count is exact. Winners, tallies and tables do not depend on the order in which ballots arrive. Ballots with the same ranking are merged without changing any count.
- An option that beats every other option in head-to-head comparisons, a Condorcet winner, wins under `condorcet`, `schulze` and `kemeny`. The Schulze method is also monotonic (ranking an option higher never makes it lose) and independent of clones (adding near-copies of an option does not change who wins), as proved in the paper below. More than one potential winner can remain. The tie-break order then decides.
- Instant runoff and the two-round runoff are not monotonic: an option can lose because more voters rank it higher. Borda is sensitive to clones: near-copies of an option can change the winner. Plurality lets similar options split their votes.
- No protection against strategic voting: with three or more options, every ranking rule that can elect each option and is not a dictatorship can be manipulated by some voter in some situation (Gibbard, Satterthwaite). The script cannot detect a person who votes against their own preference.
- Ties are broken by one order of the options, fixed in advance. Anyone with the random source can recompute it from `certificate.how_to_verify` in the `--json` output. If a rule meets a tie and the rules name no source, the run stops with exit code 3.
- Partial ballots follow `rules.partial`. Under `tie_last`, in a pairwise comparison an option that is ranked beats one that is not, a ballot that ranks neither does not count, Borda points left over are shared by the options left out, and in instant runoff a ballot stops counting once every option it ranks is out.
- Limits: 2 to 20 options (8 for Kemeny), up to 20000 ballot lines, no two options on the same rank within a ballot, no weighted votes. The script does not check who may vote or whether anybody voted twice.

## When not to use

- Handing out a limited number of slots by lot, for example 8 people for 3 tickets: slot-lottery.
- Splitting money: bill-split for shared bills, rent-split for rent, ride-split for fares.

## Reference

Schulze, M. A New Monotonic, Clone-Independent, Reversal Symmetric, and Condorcet-Consistent Single-Winner Election Method. Social Choice and Welfare 36(2):267-303, 2011. doi:10.1007/s00355-010-0475-4.

Gibbard, A. Manipulation of Voting Schemes: A General Result. Econometrica 41(4):587, 1973. doi:10.2307/1914083.

Satterthwaite, M. A. Strategy-proofness and Arrow's Conditions: Existence and Correspondence Theorems for Voting Procedures and Social Welfare Functions. Journal of Economic Theory 10(2):187-217, 1975. doi:10.1016/0022-0531(75)90050-2.
