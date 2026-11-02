---
name: stuff-split
description: Use whenever a group needs to divide shared belongings or asks who gets the fridge, even if nobody asks for an algorithm. Runs a bundled script that takes each person's private money value for every item and applies one of three rules that the group picks first, namely envy_free (every item to whoever values it most, then cash so that nobody envies anybody), knaster (Knaster's sealed bids, a fair share for everybody, unequal shares allowed) or max_nash (no money moves, envy-free up to one item, Pareto efficient). Returns one checkable line per person, private messages and a group summary. Typical requests include divide our stuff fairly, split an inheritance, who gets the sofa, roommates moving out, 毕业分家当、搬家分东西、合租散伙东西怎么分、遗产怎么分. Not for rent or bills (use rent-split or bill-split), chores (chore-split) or drawing lots (slot-lottery).
license: MIT
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/stuff_split.py *)
---

# stuff-split

When a group breaks up, every shared thing has to go somewhere, and "whoever shouts loudest" or "whoever was there first" leaves somebody feeling cheated. This skill asks each person for a private value for every item and then divides by a rule that the group chose before anyone gave a number. Each person gets one line they can check against their own values.

Quote every name, item, amount and count exactly as the script prints it. Do not compute, compare or adjust anything yourself, and never choose or guess the random source.

## The three rules

The group picks one before anybody gives a number, and does not change it after the result.

| `rules.method` | What it does |
|---|---|
| `envy_free` | Every item goes to a person who values it most. Cash then makes everybody's final worth (the value of their items plus their cash) the same. |
| `knaster` | Every item goes to a person who values it most. Everybody is first owed a fair share (1/n of their own total value, or a share by agreed weights) and the surplus is shared in proportion to the shares. |
| `max_nash` | No money moves. Of all the ways to give out the items, the script takes the one that gives something to the most people and then has the largest product of the values people receive. |

## The script

`${CLAUDE_SKILL_DIR}/scripts/stuff_split.py`. If that variable was not replaced, the script is in the `scripts/` folder next to this file.

In Claude Code, give the script the input as a file and let the script delete it. Claude Code asks the user to approve any command whose heredoc body holds both braces and quotes, and the input of this skill always does (a session that cannot ask refuses the command). So write the input JSON with the Write tool to a new file in the session's scratchpad directory (in a temporary directory if the session has none), then run the script on that file with `--delete-input`:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/stuff_split.py --format md --input <input-file> --delete-input
```

The script deletes the file as soon as it has read it, also when it then rejects the input, so the values are on disk only from the Write until that run. Use a file you wrote for this run, never one the user already had, because the script deletes it. Put the full path in the command, with no variable and nothing chained to it, because Claude Code asks for approval otherwise. If a run stops before it reads the file (a mistyped option, a wrong path), the file is still there, so run the corrected command. Step 3 runs the script several times on the same input. Run those one after another and add `--delete-input` to the last run only. A later run on the same input needs the file written again.

In Codex and other tools, pass the input on standard input through a heredoc, so that no input file is created. This is the three-roommate example (the names and numbers are made up):

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/stuff_split.py --format md --input - <<'EOF'
{
  "note": "虚构示例：三个室友毕业搬家，分合租期间一起买的六件东西",
  "people": ["阿明", "小红", "大刘"],
  "items": ["冰箱", "洗衣机", "沙发", "电视", "微波炉", "书架"],
  "values": {
    "阿明": [30, 25, 15, 15, 10, 5],
    "小红": [25, 30, 10, 20, 5, 10],
    "大刘": [35, 10, 25, 10, 15, 5]
  },
  "rules": {"method": "max_nash"}
}
EOF
```

The later commands in this file also show the input as a heredoc. In Claude Code, write the same JSON to a file instead and replace `--input -` and the heredoc with `--input <input-file> --delete-input`.

The input fields:

| Field | Meaning |
|---|---|
| `note` | Optional. One line, for example the occasion. It is shown in the outputs. |
| `people` | Distinct names, 2 to 12. The order of listing does not change the result. |
| `items` | Distinct item names, 1 to 60. Each item is a whole that is not split. |
| `values` | Person to a list with one value per item, in the order of `items`. A value is 0 or more with at most two decimals. |
| `rules.method` | `envy_free`, `knaster` or `max_nash`. Required, with no default. |
| `rules.weights` | Optional and only for `knaster`. Person to a positive number, for example 2, 1 and 1 for shares of 1/2, 1/4 and 1/4. Without it the shares are equal. |
| `rules.random_source` | Optional public text, such as a published lottery draw. It only settles ties, see Step 1. Without it, ties go by name. |

Options are listed by `--help`. `--lang en` writes the text output in English. Exit code 2 means invalid input and the message names the field. Exit code 1 means a failed self-test. Every valid input has a result, so there is no exit code 3. Python 3.9 or later, standard library only.

`--demo` prints a finished example without any input, and `--selftest` checks the script itself:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/stuff_split.py --demo
```

The `examples/` folder holds five complete inputs: `examples/three_roommates.json` (the demo, `max_nash`), `examples/piano_knaster.json` and `examples/piano_envy_free.json` (one piano and three heirs under the two rules with cash, which give different answers), `examples/weighted_knaster.json` (unequal shares and a tie settled by a public random source) and `examples/moving_out_14_items.json` (too many items to try every way, so the script takes turns and says so).

## Step 1. Fix the rules before anyone gives numbers

Done when the organizer has posted one rules message and nobody objected.

Draft the rules message for the organizer. It fixes in advance:

1. The rule. Ask first whether money can change hands. If not, only `max_nash` applies. If it can, the group chooses among the three, using the table above and the guarantees and limits below. Say plainly what each costs. Nobody should be told that one rule is simply better.
2. What is in the split. A thing that one person keeps in any case, or that will be thrown away, stays out. Two things that are worth more together than apart, such as a TV and its stand, are entered as one item.
3. How to value. Each person gives every item a value in money, privately: what it is worth to you, or the most you would pay for it if you had to buy it from the others. The values do not need to add up to anything. With `max_nash` no money moves, so the numbers are only points for comparing one person's items with each other, and everybody may use their own scale.
4. Shares, for `knaster` only. They are equal unless the group agrees on weights now, for example because one person paid more of the cost.
5. Optionally, a public random source, for example a lottery draw that will be published on a known date. It is used only when people tie and the script has to decide who comes first. Without one, ties go by name, which favors names that sort first.
6. The deadline. Everyone gives their values privately and at the same time, so nobody needs to guess what others will say. The organizer goes first: before collecting, the organizer hands their own values to another member to hold.
7. After the result there is no new vote on the rule and no re-division.

If AskUserQuestion is available, confirm the rule choice with it: one sentence restating the situation, with the options in the order of the table. Otherwise ask numbered questions.

Example (Chinese):

> 分家当规则（先定再收，发出后不改）：
> 1. 分法三选一：envy_free（无嫉妒加转账：每件东西给最看重它的人，再用现金往来把每个人最后得到的调成一样多，没人羡慕别人那一份）。knaster（Knaster 暗标法：每人先拿到自己估值的 1/3，剩下的盈余平分，可能有人羡慕）。max_nash（不转钱：选出去掉一件东西后没人羡慕的分法）。我们用 max_nash。
> 2. 请给每件东西一个数：如果要你自己出钱买下它，你最多愿意出多少？选 C 的话不转钱，这个数只是你自己的打分，用什么分制都行。合在一起更值钱的东西（比如电视和电视柜）算一件。
> 3. 周五晚 8 点前私聊发我，大家同时交，不必猜别人怎么报。我先交：我的数已经交给小红保管，收齐后公开。
> 4. 如果有两个人并列需要排先后，用 11 月 8 日公开的开奖号码来定。
> 5. 结果出来后不再换分法，也不重新分。

## Step 2. Collect the values privately and read them back

Done when the organizer has confirmed the input table.

- Values reach the organizer privately, never in a public chain message. Ask each person for a number for every item, including the organizer, who handed theirs over first.
- A person who does not want an item gives it 0. An item that every person values at 0 is still handed to somebody by the tie rule, and the output says so. Offer to take such an item out of the split.
- Do not change a value to make a result look better. If the script exits with code 2, show the message to the organizer, fix the named field with the person concerned and run again. Do not guess a value.
- Build the JSON, show it back to the organizer as a table (one row per person, one column per item), and wait for confirmation before running.

## Step 3. Run

Done when the script has exited with code 0.

If the rules named a random source, wait until it is published and copy its text exactly into `rules.random_source`, then read it back to the organizer. One changed space or sign gives a different order. Do not run the script with a placeholder. Run it three times on the same input: `--format md` for the organizer's tables, `--format dm` for one message per person, and `--format group` for the group-chat summary.

## Step 4. Present

Done when the organizer has the tables, every person has their own message and the group has the summary.

1. Give the organizer the `--format md` output: who gets what, the envy table, and the numbers behind the rule. It holds everybody's values, so it is for the organizer only.
2. Give each person their own block from `--format dm`, privately. It holds their items, their cash if any, one line of proof against their own values, and a check table with a row for each person. For example, under `max_nash`: "按你的估值，阿明那份值 45.00，比你的 40.00 多 5.00。去掉那份里你最看重的冰箱（值 25.00）后只剩 20.00，不比你的多，所以去掉一件后你不羡慕阿明；其余的人那一份都不比你的多。" Setting aside one item is exactly what the guarantee allows.
3. Post the `--format group` summary. It contains nobody's private values.
4. The cash column is each person's net amount, and the amounts add up to zero. The script does not say who hands money to whom. The group arranges that among themselves.
5. If the output says that `max_nash` took turns because there were too many ways to try, say so as printed.
6. If the output says that people envy somebody under `knaster` or `max_nash`, report it as printed.

## Guarantees and limits

- `envy_free`: every item goes to a person who values it most, the cash adds up to exactly zero, and every person ends with the same worth (the highest values added up, divided by the number of people). Nobody prefers another person's package plus cash to their own, and nobody ends below 1/n of their own total value (rounded down to the cent). No division with cash gives the poorest-off person more. The surplus is not necessarily shared equally, and somebody can end up with less than under `knaster`. After rounding to whole cents, worths differ by at most one cent and the largest envy is at most one cent, and the output says so when it happens.
- `knaster`: every item goes to a person who values it most, and everybody ends with their fair share plus their part of the surplus, never below the fair share (up to one cent of rounding). Somebody may envy somebody, and the output says who and by how much. In the piano example one heir envies another.
- `max_nash`: the script tries every way to give out the items when there are at most 2,000,000 of them, and takes the one with the most people better off than nothing and then the largest product. The result is EF1 and Pareto efficient. EF1 means that nobody envies anybody once one item is set aside, and Pareto efficient means that no other way is at least as good for everybody and better for somebody. It is not free of envy: in the roommate example two people envy the one who got the fridge, and one item set aside removes that. When the result gives everybody something, multiplying all of one person's numbers by a positive number changes nothing. With more ways to try, the script takes turns in the priority order instead and says so, and only EF1 is promised.
- Not strategy-proof, under any of the three rules. A person who shades their values can sometimes gain.
- Ties never change what anybody ends with under `envy_free` and `knaster`: only who holds the item and who pays or receives the matching cash.
- Values are added up over the items of a package. Two items that belong together are entered as one. The script does not look at budgets or ownership, and the items are never split.

## When not to use

- Rent and room prices: rent-split. Shared bills and trip expenses: bill-split.
- Chores and other things nobody wants to do: chore-split.
- Deciding who gets one scarce thing by lot: slot-lottery.
- One person keeps an item whatever the result: take it out of the split first.

## Reference

Caragiannis, I., Kurokawa, D., Moulin, H., Procaccia, A. D., Shah, N., Wang, J. The Unreasonable Fairness of Maximum Nash Welfare. ACM Transactions on Economics and Computation 7(3):1-32, 2019. doi:10.1145/3355902.

Brams, S. J., Taylor, A. D. Fair Division. Cambridge University Press, 1996. doi:10.1017/cbo9780511598975.
