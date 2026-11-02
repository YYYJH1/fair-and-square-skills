---
name: slot-lottery
description: Use whenever a group has fewer places than people and needs a fair draw (tickets, parking spaces, holiday weeks, shifts, who picks first), even if nobody asks for an algorithm. Runs a bundled script that turns a public random source fixed in advance (a named lottery draw) into a full random order with SHA-256, so anyone can recompute it. Identical slots are drawn with the rest as a waiting list. Different slots are assigned by random serial dictatorship from each person's ranking, or by probabilistic serial or deferred acceptance (priorities, several seats per slot). Typical requests include fair draw, raffle, lottery, assign slots by preference, 抽签、抢名额、名额不够怎么分、排班抽签、值班怎么排、谁先挑. Not for ranking options by vote (use group-vote), for splitting money (use bill-split or rent-split) or for chores everyone must share (use chore-split).
license: MIT
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/slot_lottery.py *)
---

# slot-lottery

When there are fewer places than people, the argument is rarely about who won. It is about whether the draw could have been rigged. This skill fixes the way of drawing before anybody is drawn, takes the randomness from a public source that was named in advance, and turns it into a full random order with SHA-256. The order is the same on every machine, and anyone can recompute it.

Quote every name, position and slot exactly as the script prints it. Do not draw, shuffle, pick or reorder anything yourself, and never choose or guess the random source.

## The script

`${CLAUDE_SKILL_DIR}/scripts/slot_lottery.py`. If that variable was not replaced, the script is in the `scripts/` folder next to this file.

In Claude Code, give the script the input as a file and let the script delete it. Claude Code asks the user to approve any command whose heredoc body holds both braces and quotes, and the input of this skill always does (a session that cannot ask refuses the command). So write the input JSON with the Write tool to a new file in the session's scratchpad directory (in a temporary directory if the session has none), then run the script on that file with `--delete-input`:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/slot_lottery.py --format md --input <input-file> --delete-input
```

The script deletes the file as soon as it has read it, also when it then rejects the input, so the input is on disk only from the Write until that run. Use a file you wrote for this run, never one the user already had, because the script deletes it. Put the full path in the command, with no variable and nothing chained to it, because Claude Code asks for approval otherwise. If a run stops before it reads the file (a mistyped option, a wrong path), the file is still there, so run the corrected command. Step 3 runs the script several times on the same input. Run those one after another and add `--delete-input` to the last run only. A later run on the same input needs the file written again.

In Codex and other tools, pass the input on standard input through a heredoc, so that no input file is created. This is the eight-person example (the names and the draw are made up):

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/slot_lottery.py --format md --input - <<'EOF'
{
  "mode": "lottery",
  "people": ["阿明", "小红", "大刘", "Coco", "老王", "Yuki", "小周", "Mia"],
  "n_slots": 3,
  "random_source": "（虚构示例）2026-11-08 某公开开奖号码 03 11 19 24 33 + 02 07",
  "rules": {
    "source_description": "虚构示例：2026 年 11 月 8 日某公开开奖，按官网显示的格式原样抄写",
    "deadline": "2026-11-07 20:00 报名截止，名单和名额数随后锁定"
  }
}
EOF
```

The later commands in this file also show the input as a heredoc. In Claude Code, write the same JSON to a file instead and replace `--input -` and the heredoc with `--input <input-file> --delete-input`.

The input fields:

| Field | Meaning |
|---|---|
| `mode` | `lottery` for identical slots, `rsd` for different slots that people rank. The method for `rsd` is chosen in `rules.method`. |
| `people` | Distinct names, at least two (at most 40 with a ranking under `ps`, at most 200 under `da`). The order of listing does not change the result. |
| `n_slots` | `lottery` only: the number of identical slots. |
| `slot_names` | `rsd` only: one name per slot, one seat each unless `capacities` says more. |
| `capacities` | `ps` and `da` only: slot to its number of seats, 1 for a slot that is not listed. |
| `prefs` | `rsd` only: person to the list of slots they accept, best first. A slot that is not listed is unacceptable. |
| `priorities` | `da` only: slot to its priority tiers, best tier first, each tier a list of names that tie. A slot with an entry accepts only the people it lists. A slot without one accepts everybody and everybody ties. |
| `random_source` | The public text the draw is seeded from, copied exactly. Required unless `commit_reveal` is used. |
| `commit_reveal` | Optional, instead of `random_source`. See "Commit-reveal". Not with `ps` or `da`. |
| `rules.source_description` | Where the text comes from. Required with `random_source`. |
| `rules.deadline` | The deadline of the rules message, as text. It is echoed in the output. |
| `rules.no_ranking` | `rsd` only: `forfeit` or `assigned` (see Step 1). Required. |
| `rules.method` | `rsd` mode only: `rsd` (the default), `ps` or `da`. See "Choosing the method". |
| `rules.non_reveal` | With `commit_reveal`: `forfeit` or `assigned`. Required there. |

Options are listed by `--help`. In short: `--format dm` writes one private message per person, `--format group` the card for the group chat, `--json` the full result, `--lang en` switches the text to English, `--verify` checks a result card, `--commit` makes a commitment, `--demo` runs the example above and `--selftest` runs the built-in checks. Exit code 2 means invalid input and the message names the field. Exit code 3 means the rules declared in advance leave no draw to run. Exit code 1 means a failed `--verify` or a failed self-test. Python 3.9 or later, standard library only.

The `examples/` folder holds five complete inputs: `examples/tickets_8_for_3.json`, `examples/shifts_rsd.json` (six people picking among four holiday weeks), `examples/commit_reveal.json`, `examples/ps_holiday_weeks.json` (the same six people and rankings under `ps`, with two seats in one week) and `examples/da_parking.json` (parking spaces with priorities and seats under `da`).

## Choosing the method

Identical slots (`lottery`) need no choice. For different slots that people rank (`rsd` mode), the group picks one of three methods in `rules.method` before any ranking is collected, and the rules message of Step 1 says which. What each method guarantees and what it costs is listed under "Guarantees and limits".

| Method | Use it when |
|---|---|
| `rsd` (the default) | the group wants the simplest story: draw an order, then everybody picks in turn |
| `ps` (probabilistic serial) | the group cares about the chances each person has before the draw |
| `da` (deferred acceptance) | slots have priorities (seniority, need, who is eligible) or several seats |

`ps` and `da` take the seats of each slot in `capacities`. `da` takes the priority tiers of each slot in `priorities`, and ties inside a tier are broken by one lottery for all slots, drawn from the public source. The two fields look like this:

```json
"capacities": {"春节前一周": 2},
"priorities": {"充电车位": [["阿明", "Coco"]], "地面车位": [["老王"], ["阿明", "小红", "大刘", "Coco", "Yuki"]]}
```

In this example only 阿明 and Coco are accepted at the charging space. At the ground space 老王 comes first and the others tie. `ps` and `da` work with `random_source` and not with `commit_reveal`.

## Step 1. Fix the rules before anybody is drawn

Done when the organizer has posted one rules message and nobody objected.

Draft the rules message for the organizer. It fixes in advance:

1. How to draw. `lottery` for identical slots: the first n names of a random order are drawn and the rest are the waiting list, in order. `rsd` for different slots: the people pick in the random order and each takes the best slot that is still free from their own ranking (random serial dictatorship). Someone whose acceptable slots are all gone gets none and joins the waiting list. For different slots the group can instead choose `ps` or `da` (see "Choosing the method"). For something nobody wants, say plainly in the rules message that being drawn means having to do it, and use `lottery` or `rsd` with `assigned`.
2. The public source. A text that nobody in the group controls, that cannot be guessed before it is published, and that anyone can look up afterwards, for example the winning numbers of a named lottery draw on a stated date. Name the source and the date now, say how the text will be copied (exactly as shown, with every space and sign), and choose one with many possible values. A temperature, a score or one digit is too easy to guess.
3. The deadline. After it, the list of people, the number of slots and, for `rsd`, who sent a ranking are frozen and posted. With `ps` and `da` the rankings, the seats and the tiers are frozen as well, because the seed does not contain them. Nobody is added or removed once the source is known.
4. What happens to a person who sends no ranking (`rsd`). `forfeit`: they get no slot. `assigned`: they pick after everybody else and take the first slot that is still free in the order the slots are listed. Use `forfeit` for something good and `assigned` for something nobody wants.
5. After the draw. The full order is the waiting list. If someone gives up, the next name moves up. There is no new draw, and the group does not vote on the rules after seeing the result. `ps` and `da` have no waiting list, so the rules message says what happens instead, for example that the slot goes to the person without a slot who ranked it highest.
6. For `da` only, the seats and the priority tiers of every slot, and for `ps` the seats. They are public rules, fixed before any ranking is collected, and the group agrees who is in which tier before it knows the lottery order.

If AskUserQuestion is available, confirm the rule choices with it: one sentence restating the situation, the recommended option first. Otherwise ask numbered questions, each with the recommended answer.

Example for tickets (Chinese):

> 抽签规则（先定再收，发出后不改）：
> 1. 8 个人抢 3 张票，每人中签机会相同。抽完的完整顺序当候补：中签的人放弃，就按顺序递补，不重抽。
> 2. 随机源：11 月 8 日某某公开开奖的号码，按官网显示的样子原样抄写（含空格和加号）。号码公布之前，名单和名额数锁定，之后不增不减。
> 3. 11 月 7 日晚 8 点前在群里回复「参加」，过时不候。
> 4. 抽完后我把完整顺序、随机源原文和复算方法发到群里，谁都可以自己再算一遍。

Example for holiday weeks (Chinese):

> 休假时段规则（先定再收，发出后不改）：
> 1. 先抽出挑选顺序，轮到谁谁从剩下的时段里挑自己最想要的。
> 2. 随机源同上：11 月 8 日某某公开开奖的号码，原样抄写。
> 3. 11 月 7 日晚 8 点前私聊把你能接受的时段按想要的程度排好发给我，没写的时段算不能接受。志愿私聊交，不发群里。
> 4. 到点没交志愿的人没有时段。
> 5. 结果出来后不重抽，不改规则。

Example for parking spaces under `da` (Chinese):

> 车位规则（先定再收，发出后不改）：
> 1. 用延迟接受：每个人按志愿向车位申请，车位按优先级留人，同一档里的平局用一次抽签统一打破。
> 2. 优先级：充电车位只接受有电车的阿明和 Coco，地面车位老王优先，其余人同档，地下车位大家同档。
> 3. 名额：充电车位 1 个，地面车位 2 个，地下车位 2 个。
> 4. 随机源同上：11 月 8 日某某公开开奖的号码，原样抄写。
> 5. 11 月 7 日晚 8 点前私聊交志愿，志愿私聊交，不发群里。没交志愿的人没有车位。
> 6. 结果出来后不重抽，没有候补。有人放弃车位怎么办，现在先说好。

## Step 2. Collect the people and the rankings, and read them back

Done when the organizer has confirmed the input table and the list of people has been posted to the group.

- People: one name each, spelled the way the group will see it. The names go into the seed, so another spelling is another draw.
- `lottery`: the number of slots.
- `rsd`: the slot names, and for every person who sent one, their acceptable slots in order, best first. Rankings reach the organizer privately. Do not put a ranking in the group.
- `ps` and `da`: also the seats of each slot in `capacities` and, for `da`, the tiers in `priorities`. They come from the rules message and not from the private rankings, so show them in the table too.
- Build the JSON, show it back to the organizer as a table (one row per person, with the ranking for `rsd`), and wait for confirmation. Post the list of people (and for `rsd` the names of those who sent a ranking) to the group before the source is published.

## Step 3. Wait for the source, then run

Done when the script has exited with code 0, or with code 3 (see Step 4).

- If the source has not been published yet, say so and stop. Do not run the script with a placeholder, because a wrong text gives a different order that looks just as real.
- When it is published, ask the organizer to paste the text exactly as it appears. Put it into `random_source` unchanged and read it back to them character by character. One changed space or sign gives a different order.
- Run the script three times on the same input: `--format md` for the organizer, `--format dm` for one message per person, `--format group` for the group chat. If it exits with code 2, show the message to the organizer, fix the named field with them and run again. Do not guess a value.
- With `ps` also keep the `--json` output. It is the full certificate: the table of chances, the eating schedule, the decomposition into fixed assignments and the draw. With `da` it holds the rounds and the reason each person did not get a better slot.

## Step 4. Present

Done when the organizer has the tables, every person has their own message and the group has the card.

1. Give the organizer the `md` output. It has the order or the picks with the reason for each, the random source, the seed and the way to recompute it. It names every person's result, so it is for the organizer.
2. Give each person their own block from `--format dm`, privately. For example: "你抽中了：顺序第 1 位，在 3 个名额之内（共 8 人）。" or, for `rsd`, "你的排队顺序是第 3 位，你挑到了「端午」（你的第 2 志愿）。" followed by the ranking the person sent, so that they can catch a wrong entry at once.
3. Post the `--format group` card. It holds the full order, the source text, the seed and the exact text that was hashed, and nobody's ranking. Say that anyone can recompute it.
4. If someone gives up their slot, offer it to the next name on the waiting list, in order. Do not draw again.
5. With `ps` and `da` the output differs a little. The `md` output of `ps` has the table of chances, the decomposition and the draw, and each private message has the person's own chances. The `md` output of `da` has the result with the reason for every better slot that a person did not get, the priorities and the rounds. The group card of `ps` does not hold the table of chances, because it carries ranking information. The group card of `da` holds the tiers and the lottery order, which are public. Neither has a waiting list.

## Recomputing without this script

The card holds everything needed. A few lines of Python give the same order (this is the eight-person example):

```python
import hashlib, json

names = ["阿明", "小红", "大刘", "Coco", "老王", "Yuki", "小周", "Mia"]
slots, source = 3, "（虚构示例）2026-11-08 某公开开奖号码 03 11 19 24 33 + 02 07"
text = json.dumps(
    {
        "rule": "uniform_lottery_v1",
        "participants": sorted(names),
        "n_slots": slots,
        "source": source,
    },
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
)
seed, counter = hashlib.sha256(text.encode("utf-8")).digest(), 0


def below(n):
    global counter
    while True:
        block = hashlib.sha256(seed + counter.to_bytes(8, "big")).digest()
        counter += 1
        x = int.from_bytes(block[:8], "big")
        if x < 2**64 - 2**64 % n:
            return x % n


order = sorted(names)
for i in range(len(order) - 1, 0, -1):
    j = below(i + 1)
    order[i], order[j] = order[j], order[i]
print(order)
```

In mode `lottery` the first `n_slots` names of the order are drawn. For mode `rsd` the rule name is `rsd_v1`, `n_slots` is the number of slots, and the order is the pick order: each person in turn takes the best free slot on their list.

For `da` the rule name is `da_tiebreak_v1`, `n_slots` is the number of seats in all, and the order is the lottery that breaks ties inside a tier, earlier first. For `ps` the rule name is `ps_bvn_v1`, `n_slots` is again the number of seats, and the shuffle is replaced by one random number: the first draw of the same counter stream, reduced modulo the common denominator of the chances of the fixed assignments. The `md` output spells out the rule for a denominator above 2^64 and lists the fixed assignments in the order in which they own the random numbers.

## Checking a result card

To check a card, take the input of the draw, add the result printed on the card as `claimed` (`order`, and optionally `seed` and, for `rsd`, `allocation`) and run `--verify`. Copy the source text again from where it was published and pass it with `--source`, so that the text printed on the card is not trusted. The input needs no `random_source` and no `rules` for this:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/slot_lottery.py --verify --source "（虚构示例）2026-11-08 某公开开奖号码 03 11 19 24 33 + 02 07" --input - <<'EOF'
{
  "mode": "lottery",
  "people": ["阿明", "小红", "大刘", "Coco", "老王", "Yuki", "小周", "Mia"],
  "n_slots": 3,
  "claimed": {"order": ["Yuki", "小周", "大刘", "Coco", "小红", "阿明", "Mia", "老王"]}
}
EOF
```

For `ps` and `da` the card is the allocation (person to slot, or null) in `claimed.allocation`, which is required. `claimed.order` is optional for `da` and refused for `ps`, which has no order. Checking needs the rankings of everybody, so it is for the organizer or for a group that agrees to reveal them.

Exit code 0 means the card can be reproduced. Exit code 1 means it cannot, and the output shows the first position that differs. A card that does not verify is a reason to look at the source text, the list of names and the slot count first, because a single copied character changes everything.

## Commit-reveal (optional, for technical groups)

A public source is the default. If the group cannot name one, or does not want to rely on one, every person can contribute the randomness. Say so in the rules message in Step 1, and add the deadline for commitments, the time for reveals and `rules.non_reveal`: `forfeit` for something good (a person without a verified reveal is out of the draw) or `assigned` for something nobody wants (that person is placed first in a `lottery`, or last in the queue in `rsd`).

1. Every person runs this on their own device or in their own session, not through the organizer, who would then learn the reveal code:

   ```bash
   python3 ${CLAUDE_SKILL_DIR}/scripts/slot_lottery.py --commit --person 阿明
   ```

   It prints a commitment and a reveal code. The commitment goes into the group now, the organizer's first. The reveal code stays private. Use a new one for every draw.
2. When everybody's commitment is posted and the agreed time has come, every person posts their reveal code in the group, not privately to the organizer.
3. Build the input with `commit_reveal.commitments` (a list of `{"name": ..., "commitment": ...}`) and `commit_reveal.reveals` (a list of `{"name": ..., "reveal": ...}`) copied from the group chat, and no `random_source`. See `examples/commit_reveal.json`. Check the times in the chat first: every commitment must have been posted before the first reveal, and the script cannot see that. The script checks every reveal against its commitment. Anybody without a verified reveal is handled by the declared rule before the draw, and the output says so. The verified reveal codes, sorted by name and written as canonical JSON, are the source text. At least two verified reveals are needed, otherwise the script exits with code 3.
4. Always give the organizer and the group the warning that the script prints. Do not shorten it.

Commit-reveal does not remove every way to influence the result. The person who reveals last sees all the other reveals first and can then decide whether to reveal at all, which changes the result for everybody else. In a draw of 3 tickets among 8 people where not revealing means dropping out, that person can raise a friend's chance of winning from 0.375 to 0.643. The declared rule only makes withholding costly for the person who does it.

## Guarantees and limits

- Equal chances. If nobody could predict or influence the source text when the rules were fixed, and SHA-256 behaves like a random function, every order of the people is equally likely. Each person then has the same chance of being drawn, `n_slots` out of the number of people, and the same chance of every place on the waiting list. This is checked statistically and, for the shuffle, exactly.
- Reproducible. The same input gives the same output on every machine and Python version. The script never calls the `random` module.
- The organizer cannot choose the outcome once the source is fixed in advance and the list, the slot count and the rules are frozen. They can still mistype a ranking, and they can still try to add or drop a name.
- `rsd` is strategy-proof for the order that was drawn: nobody gains by ranking dishonestly. After the draw, no other assignment makes somebody better off without making somebody else worse off (ex post Pareto efficiency, Abdulkadiroğlu and Sönmez 1998). It is not envy-free, because whoever picks early takes what the others wanted. People with the same ranking have equal chances, but the chances can be worse than possible: if two people rank a, b, c, d and two others rank b, a, d, c, each of the first two gets slot a with chance 5/12 where `ps` gives 1/2.
- `ps` gives every person chances that no other person's chances beat by their own ranking, and its table of chances is ordinally efficient (no other table is at least as good for everybody and better for somebody). The table is split into fixed assignments with a probability each, and one is drawn from the public source, so each person gets each slot with the chance in the table. `ps` is not strategy-proof, and the one assignment that is drawn can still leave somebody envious.
- `da` leaves no blocking pair, gives every applicant the best slot that any stable assignment gives them, and an honest ranking is the best an applicant can report. It is not Pareto efficient: another assignment may suit several people better, at the price of ignoring a priority. The tiers are taken as given.
- A predictable source, or one chosen after the rules, breaks all of this. Whoever can guess or choose the text can try variants (another day's numbers, one more name, one slot more or fewer) until the order suits them.

## When not to use

- Ranking options by vote, such as a restaurant or a team-building plan: group-vote.
- Everybody gets something and only the amounts differ: bill-split or rent-split.
- Chores that everybody shares in turn: chore-split. A one-off draw of who takes an unwanted task is fine here, with `assigned`.
- Fewer than two people: there is nothing to draw.

## Reference

Abdulkadiroğlu, A., Sönmez, T. Random Serial Dictatorship and the Core from Random Endowments in House Allocation Problems. Econometrica 66(3):689, 1998. doi:10.2307/2998580.

Bogomolnaia, A., Moulin, H. A New Solution to the Random Assignment Problem. Journal of Economic Theory 100(2):295-328, 2001. doi:10.1006/jeth.2000.2710.

Dubins, L. E., Freedman, D. A. Machiavelli and the Gale-Shapley Algorithm. The American Mathematical Monthly 88(7):485-494, 1981. doi:10.1080/00029890.1981.11995301.

Gale, D., Shapley, L. S. College Admissions and the Stability of Marriage. The American Mathematical Monthly 69(1):9-15, 1962. doi:10.1080/00029890.1962.11989827.

Roth, A. E. The Economics of Matching: Stability and Incentives. Mathematics of Operations Research 7(4):617-628, 1982. doi:10.1287/moor.7.4.617.

von Neumann, J. A Certain Zero-sum Two-person Game Equivalent to the Optimal Assignment Problem. In Contributions to the Theory of Games, Volume II, Princeton University Press, 1953, pp. 5-12. doi:10.1515/9781400881970-002.
