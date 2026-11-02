---
name: rent-split
description: Use whenever roommates or flatmates need to decide who gets which room and who pays how much, or want to know whether their current rent split is fair, even if nobody asks for an algorithm. Runs a bundled script (envy-free rent division as on Spliddit, exact to the cent) that returns one line of proof per person, a group-chat summary and an audit of an existing split. Typical requests include split rent, rent division, who gets which room, is our rent split fair, 分房租、合租房租怎么分、主卧次卧怎么算钱、室友谁住哪间、我们现在这么分公平吗. Not for utility bills or groceries (use bill-split), for drawing lots (use slot-lottery) or for splitting text or files.
license: MIT
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/rent_split.py *)
---

# rent-split

Roommates rarely fight about the total rent. They fight about who pays how much for which room. This skill runs a short sealed-bid procedure with a guarantee each person can check with their own numbers: after the split, nobody prefers another room at that room's rent.

Quote every amount, room and surplus exactly as the script prints it. Do not compute, estimate or adjust any of them yourself.

## The script

`${CLAUDE_SKILL_DIR}/scripts/rent_split.py`. If that variable was not replaced, the script is in the `scripts/` folder next to this file.

In Claude Code, give the script the input as a file and let the script delete it. Claude Code asks the user to approve any command whose heredoc body holds both braces and quotes, and the input of this skill always does (a session that cannot ask refuses the command). So write the input JSON with the Write tool to a new file in the session's scratchpad directory (in a temporary directory if the session has none), then run the script on that file with `--delete-input`:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/rent_split.py --format md --input <input-file> --delete-input
```

The script deletes the file as soon as it has read it, also when it then rejects the input, so the bids are on disk only from the Write until that run. Use a file you wrote for this run, never one the user already had, because the script deletes it. Put the full path in the command, with no variable and nothing chained to it, because Claude Code asks for approval otherwise. If a run stops before it reads the file (a mistyped option, a wrong path), the file is still there, so run the corrected command. Step 3 runs the script several times on the same input. Run those one after another and add `--delete-input` to the last run only. A later run on the same input needs the file written again.

In Codex and other tools, pass the input on standard input through a heredoc, so that no input file is created. This is the four-roommate example (the names are made up):

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/rent_split.py --format md --input - <<'EOF'
{
  "total_rent": 8000,
  "rooms": ["主卧带卫", "南次卧", "北次卧", "小书房"],
  "bids": {
    "阿明": [3000, 2200, 1600, 1200],
    "小红": [2600, 2500, 1700, 1200],
    "大刘": [3400, 2000, 1500, 1100],
    "Coco": [2400, 2300, 2000, 1300]
  },
  "rules": {"negative_rent": "spliddit"}
}
EOF
```

The later commands in this file also show the input as a heredoc. In Claude Code, write the same JSON to a file instead and replace `--input -` and the heredoc with `--input <input-file> --delete-input`.

The input fields:

| Field | Meaning |
|---|---|
| `total_rent` | Rent of the whole home per month, with at most two decimals. |
| `rooms` | The room names. There must be exactly as many rooms as people. |
| `bids` | Person name to a list with one bid per room, in the order of `rooms`. Each list should add up to `total_rent`. |
| `rules.negative_rent` | `spliddit`, `allow` or `forbid` (see Step 1). Required, with no default. |
| `rules.random_source` | Optional public text, such as a published lottery draw. It only breaks exact ties between equally good room assignments. Without it, ties go by name. |
| `audit` | Optional. `assignment` (person to room) and `rent` (person to current rent) of the split the group uses today, for `--audit`. |

Options are listed by `--help`. `--lang en` writes the text output in English. Exit code 2 means invalid input and the message names the field. Exit code 3 means the agreed rule has no solution for these bids. Exit code 1 means a commitment did not match or a self-test failed. Python 3.9 or later, standard library only.

`--demo` prints a finished example without any input, and `--selftest` checks the script itself:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/rent_split.py --demo
```

The `examples/` folder holds three complete inputs: `examples/four_roommates.json`, `examples/storage_room.json` (a storage room that nobody wants, where `allow` gives a different split from the other two rules) and `examples/audit_equal_split.json` (the four roommates paying equal shares).

## Step 1. Fix the rules before anyone gives numbers

Done when the organizer has posted one rules message and nobody objected.

Draft the rules message for the organizer. It fixes in advance:

1. How to bid. Each person privately prices every room so that their prices add up to the total rent. Ask it this way: "If you set the prices of the rooms yourself, adding up to exactly the total rent, how would you price them?"
2. Negative rent. Choose `spliddit` (the recommended rule: first look for a split where nobody is paid to live in a room, and only if none exists allow it), `allow` (the person in the least wanted room may be paid to live there), or `forbid` (if no such split exists, everyone bids again). The group will not vote on the rule after seeing results.
3. The organizer goes first. Before collecting, the organizer either hands their own bids to another roommate to hold, or posts a commitment code (see the next section) and reveals the bids after everyone else has submitted.
4. Everyone submits privately and at the same time, by a deadline. Nobody needs to guess what others will bid.
5. Optionally, a public random source, for example a lottery draw that will be published on a known date. It is used only if two room assignments are exactly equally good. Without one, ties go by name.

If AskUserQuestion is available, confirm the rule choices with it: one sentence restating the situation, the recommended option first. Otherwise ask numbered questions, each with the recommended answer.

Example (Chinese):

> 分房租规则（先定再收）：
> 1. 假如由你给四个房间定价，四个价加起来正好 8000，你怎么定？周五晚 8 点前私聊发我。大家同时交，不必猜别人怎么报。
> 2. 用无嫉妒分租算法（Spliddit 同款）：先找没人倒贴的分法，找不到再允许倒贴。结果出来后不再改规则。
> 3. 我先交：我的报价已经交给小红保管，收齐后公开。
> 4. 如果有两种住法完全一样好，用 11 月 8 日公开的开奖号码来定。

## The organizer goes first

The organizer sees everyone's bids when the script runs, so their own bids must be fixed before the others arrive. To commit instead of handing the bids to a roommate, give the script the organizer's row alone:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/rent_split.py --commit --input - <<'EOF'
{
  "total_rent": 8000,
  "rooms": ["主卧带卫", "南次卧", "北次卧", "小书房"],
  "bids": {"阿明": [3000, 2200, 1600, 1200]}
}
EOF
```

It prints a commitment code, a nonce and the committed text. Post the code in the group now and keep the nonce and the text private. Once everyone else has submitted, the organizer reveals the nonce, and the full input is checked against the code before anything is computed. The code and nonce below belong to the example row above, so use the ones printed by your own commit step:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/rent_split.py --verify-commit 6ea1ffc78ecc8af6f20b004156b7815d7554f3ac5bbccd704222e26123a30227 --nonce 00112233445566778899aabbccddeeff --person 阿明 --input - <<'EOF'
{
  "total_rent": 8000,
  "rooms": ["主卧带卫", "南次卧", "北次卧", "小书房"],
  "bids": {
    "阿明": [3000, 2200, 1600, 1200],
    "小红": [2600, 2500, 1700, 1200],
    "大刘": [3400, 2000, 1500, 1100],
    "Coco": [2400, 2300, 2000, 1300]
  },
  "rules": {"negative_rent": "spliddit"}
}
EOF
```

It prints 核对通过 and exits with 0 when the organizer's row is the committed one. Any other result (exit code 1) means the organizer changed a bid or the nonce is wrong: do not run the split on that input.

## Step 2. Collect and read back

Done when the organizer has confirmed the input table.

- Bids reach the organizer privately, never in a public chain message.
- If someone's prices do not add up to the total, the script shifts all of that person's prices by the same amount. This keeps every difference between rooms, so their own envy check is unchanged. It never scales the prices, which would change the differences. The person's private message says what was done. Ask them to confirm the shifted prices or to bid again.
- A couple sharing one room agrees on a single set of prices, adding up to the total, and counts as one person.
- Build the JSON, show it back to the organizer as a table (one row per person, one column per room), and wait for confirmation before running.

## Step 3. Run

Done when the script has exited with code 0, or with code 3 (see Step 4).

If the rules named a random source, wait until it is published and copy its text exactly into `rules.random_source`. Run the script three times on the same input, as in the first example: `--format md` for the organizer's tables, `--format dm` for one message per person, and `--format group` for the group-chat summary. If the script exits with code 2, fix the field named in the message with the person concerned. Do not guess a value.

## Step 4. Present

Done when every person has their own message and the group has the summary.

1. Give the organizer the `--format md` output: the assignment table and the envy table. It holds everyone's bids, so it is for the organizer only.
2. Give each person their own block from `--format dm`, privately, for example: "按你报的价，南次卧比你心里价位便宜 250.00，换哪间都不会更划算；小书房对你来说一样划算（也便宜 250.00），打平不算吃亏。" A tie means two rooms are equally good for that person at these rents. It is not a loss. A negative rent reads as 倒收: that person is paid to live there.
3. Post the `--format group` summary. It contains nobody's private bids.
4. If the script exited with code 3 under `forbid`, say that under the agreed rule there is no split where nobody envies anyone and nobody is paid to live, so everyone bids again. Do not switch rules.

## Checking an existing split

If the group already splits the rent some way (for example equally), add the current rooms and rents as an `audit` block and run with `--audit`:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/rent_split.py --audit --format md --input - <<'EOF'
{
  "total_rent": 8000,
  "rooms": ["主卧带卫", "南次卧", "北次卧", "小书房"],
  "bids": {
    "阿明": [3000, 2200, 1600, 1200],
    "小红": [2600, 2500, 1700, 1200],
    "大刘": [3400, 2000, 1500, 1100],
    "Coco": [2400, 2300, 2000, 1300]
  },
  "rules": {"negative_rent": "spliddit"},
  "audit": {
    "assignment": {"阿明": "小书房", "小红": "南次卧", "大刘": "主卧带卫", "Coco": "北次卧"},
    "rent": {"阿明": 2000, "小红": 2000, "大刘": 2000, "Coco": 2000}
  }
}
EOF
```

Report, per person and in their own numbers, whether they envy another room and by how much, and how far their current rent is from the rule's rent. If the current room assignment is not one with the highest total of bids, say that no rents can make it envy-free and show the assignment the script suggests. The audit only compares, and the group decides. The `--format dm` and `--format group` outputs carry the audit too.

## Guarantees and limits

- Nobody envies anyone, judged by their own prices. Among such splits, the worst-off person is as well off as possible (unique with `allow`, and the leximin split when negative rent is excluded). Rents add up exactly to the total. Nobody pays more than their own price for their own room. Rounding to whole cents can leave an envy of at most one cent, or a rent at most one cent above a person's own price, and the script says so when it happens.
- Not strategy-proof: a person who sees everyone else's bids before bidding can sometimes gain by misreporting.

## When not to use

- Utilities, groceries or any shared bill: bill-split. Deciding rooms by lot without prices: slot-lottery.
- More people than rooms, or two people who are not a couple sharing a room: not supported. Say so.

## Reference

Gal, Y., Mash, M., Procaccia, A. D., Zick, Y. Which Is the Fairest (Rent Division) of Them All? Journal of the ACM 64(6), 2017. doi:10.1145/3131361.

Spliddit rent calculator: http://www.spliddit.org/apps/rent
