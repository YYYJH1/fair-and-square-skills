---
name: gift-exchange
description: Use whenever a group wants a gift exchange draw (Secret Santa) in which everybody gives one gift to one other person, nobody draws themselves and some pairs must not be matched (couples, last year's pairs), even if nobody asks for an algorithm. Runs a bundled script that first checks that a legal draw exists and, when none does, names the people with too few possible receivers (Hall's theorem). It then picks one legal plan from a public random source fixed in advance, so anyone can recompute the draw. Offers any derangement or one single circle, with one private message per person that says only whom they give to. Typical requests include Secret Santa draw, who gives to whom, 交换礼物、圣诞交换礼物、抽签送礼、年会互送礼物、情侣不能抽到对方. Not for splitting gift costs (use bill-split), drawing lots (use slot-lottery) or choosing by vote (use group-vote).
license: MIT
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/gift_exchange.py *)
---

# gift-exchange

A gift exchange goes wrong in two ways. Either nobody trusts the draw, because the organizer might have picked who gets whom, or the draw cannot work at all: three friends of whom two are a couple have no legal draw, and the organizer finds that out only after drawing again and again. This skill checks that a legal draw exists before it draws. It fixes the way of drawing in advance and takes the randomness from a public source that is named before anybody is drawn. From that text to the result only SHA-256 is used, so anyone can recompute the draw.

Quote every name and number exactly as the script prints it. Do not draw, pair or reorder anybody yourself, and never choose or guess the random source. Show a pairing only to the organizer and, in a person's own message, to that person.

## The script

`${CLAUDE_SKILL_DIR}/scripts/gift_exchange.py`. If that variable was not replaced, the script is in the `scripts/` folder next to this file.

In Claude Code, give the script the input as a file and let the script delete it. Claude Code asks the user to approve any command whose heredoc body holds both braces and quotes, and the input of this skill always does (a session that cannot ask refuses the command). So write the input JSON with the Write tool to a new file in the session's scratchpad directory (in a temporary directory if the session has none), then run the script on that file with `--delete-input`:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/gift_exchange.py --format md --input <input-file> --delete-input
```

The script deletes the file as soon as it has read it, also when it then rejects the input, so the input is on disk only from the Write until that run. Use a file you wrote for this run, never one the user already had, because the script deletes it. Put the full path in the command, with no variable and nothing chained to it, because Claude Code asks for approval otherwise. If a run stops before it reads the file (a mistyped option, a wrong path), the file is still there, so run the corrected command. Step 3 runs the script several times on the same input. Run those one after another and add `--delete-input` to the last run only. A later run on the same input needs the file written again.

In Codex and other tools, pass the input on standard input through a heredoc, so that no input file is created. This is the six-person example (the names and the draw are made up):

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/gift_exchange.py --format md --input - <<'EOF'
{
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
}
EOF
```

The later commands in this file also show the input as a heredoc. In Claude Code, write the same JSON to a file instead and replace `--input -` and the heredoc with `--input <input-file> --delete-input`.

The input fields:

| Field | Meaning |
|---|---|
| `people` | Distinct names, 2 to 100. The order of listing does not change the draw. |
| `mode` | Optional. `any` (default): any derangement, everybody gives to one other person who is allowed. `ring`: everybody is in one single circle and gives to the next person in it. |
| `forbidden` | Optional. A list of `{"pair": ["A", "B"]}` (neither gives to the other) and `{"giver": "A", "receiver": "B"}` (A may not give to B, B may give to A). |
| `random_source` | The public text the draw is seeded from, copied exactly. Required, except with `--check`. |
| `rules.source_description` | Where the text comes from, as one line. Required, except with `--check`. |
| `rules.deadline` | The deadline of the rules message, as text. It is echoed in the output. Required, except with `--check`. |

Options are listed by `--help`. In short: `--check` asks only whether a legal draw exists and needs no random source, `--format dm` writes one private message per person, `--format group` the card for the group chat, `--json` the full result with the certificate, `--lang en` switches the text to English, `--demo` runs the example above and `--selftest` runs the built-in checks. Exit code 2 means invalid input and the message names the field. Exit code 3 means that no legal draw exists or that none was found, and the message says why. Exit code 1 means a failed self-test. Python 3.9 or later, standard library only.

The `examples/` folder holds three complete inputs: `examples/six_with_couples.json` (the example above), `examples/six_circle.json` (the same people in one circle) and `examples/office_twelve.json` (twelve people, which are drawn by random proposals and not by listing every plan).

## Step 1. Fix the rules before anybody is drawn

Done when the organizer has posted one rules message and nobody objected.

Draft the rules message for the organizer. It fixes in advance:

1. The way of giving. `any` (the default): everybody gives one gift and gets one, nobody draws themselves or a person who is excluded, and two people may end up giving to each other. `ring`: everybody is in one single circle, so with three or more people nobody gives to the person who gives to them.
2. The exclusions. Who may not give to whom: couples (both ways), people who were matched last year (one way). Say how they are collected and that the list is frozen with the names.
3. The public source. A text that nobody in the group controls, that cannot be guessed before it is published, and that anyone can look up afterwards, for example the winning numbers of a named lottery draw on a stated date. Name the source and the date now, say how the text will be copied (exactly as shown, with every space and sign), and choose one with many possible values. A temperature, a score or one digit is too easy to guess.
4. The deadline. After it, the names and the exclusions are frozen and posted. Nobody is added or removed once the source is known.
5. Who sees the table. Whoever runs the script sees every pairing, the organizer's own included. If the organizer wants to be surprised too, somebody else runs the draw. This skill cannot hide the table from the person who runs it.
6. After the draw. There is no new draw because someone dislikes the result. Decide now what happens if a person drops out, for example a new draw of the remaining people with a source named now. The script does not repair a plan.

If AskUserQuestion is available, confirm the rule choices with it: one sentence restating the situation, the recommended option first. Otherwise ask numbered questions, each with the recommended answer.

Example (Chinese):

> 交换礼物规则（先定再收，发出后不改）：
> 1. 每人送一份礼物给一个人，也收到一份。不会抽到自己，也不会抽到不能互送的人。抽法是「任意错排」，两个人有可能互送。想让大家连成一个圈，就改用「一圈传下去」，现在说。
> 2. 不能互送的人：情侣之间，还有去年已经送过的人。请在 11 月 7 日晚 8 点前私聊告诉我，之后冻结。
> 3. 随机源：11 月 8 日某某公开开奖的号码，按官网显示的样子原样抄写（含空格和加号）。号码公布之前，名单和不能互送的规则锁定，之后不增不减。
> 4. 11 月 7 日晚 8 点前在群里回复「参加」，过时不候。
> 5. 抽完后每人只收到一条私信，写着自己送给谁。我跑脚本，会看到全表（想要惊喜的话，请别人来跑）。礼物交换完之后，我把随机源原文、不能互送的规则和抽到的方案序号发到群里，谁都可以自己再算一遍。
> 6. 有人中途退出：剩下的人用下一期同一个公开开奖的号码重抽一次。

## Step 2. Collect the names and the exclusions, and check that a draw exists

Done when the organizer has confirmed the input table, the list of names has been posted to the group, and `--check` has exited with code 0.

- People: one name each, spelled the way the group will see it. The names go into the seed, so another spelling is another draw.
- Exclusions: ask for couples, for last year's pairs and for anything else the group agreed. Each is a pair (neither gives to the other) or one direction. Do not guess a pair from the names or from how people talk.
- Build the JSON, show it back to the organizer as a table (one row per person, with whom that person may not give to), and wait for confirmation. Post the list of names to the group before the source is published.
- Run the script with `--check` on the input. It needs no `random_source` and no `rules`, so it can run before the source exists. Exit code 3 means that the rules have no solution, and the message names the people who have too few possible receivers, for example "甲、乙这 2 个人能送的只有丙（1 人）". Show it as printed. The group changes the exclusions or adds people, openly. Do not drop an exclusion yourself. With `--check` in Claude Code, write the input to a file and add `--delete-input` as usual.

## Step 3. Wait for the source, then run

Done when the script has exited with code 0, or with code 3 (see Step 4).

- If the source has not been published yet, say so and stop. Do not run the script with a placeholder, because a wrong text gives a different draw that looks just as real.
- When it is published, ask the organizer to paste the text exactly as it appears. Put it into `random_source` unchanged and read it back to them character by character. One changed space or sign gives a different draw.
- Run the script three times on the same input: `--format md` for the organizer, `--format dm` for one message per person, `--format group` for the group chat. If it exits with code 2, show the message to the organizer, fix the named field with them and run again. Do not guess a value.

## Step 4. Present

Done when the organizer has the table, every person has their own message and the group has the card.

1. Give the organizer the `md` output. It names every pairing and holds the material for recomputing, so it is for the organizer only until the exchange is over.
2. Give each person their own block from `--format dm`, privately. It says only whom that person gives to, for example: "你要送礼物给：Yuki。" No message names anybody else's receiver.
3. Post the `--format group` card. It lists the names, the way of giving, the number of legal plans and how the source was named, and says that the way of drawing is public and can be recomputed. It does not say who gives to whom. It also holds back the source text, the seed, the exclusions and the number of the plan drawn, because with those anybody who runs the script can work out every pairing.
4. After the exchange, publish the recompute material: the `md` output, or the `--json` output whose certificate holds the source text, the seed preimage, the number of legal plans and the number drawn. Anyone can then run the script on the same input, or follow "Recomputing without this script".
5. If the script exited with code 3, show the message as printed. The group decides what to change, openly. Do not run it again with changed inputs until it has.

## Recomputing without this script

For up to nine people a few lines of Python give the same plan (this is the six-person example). The certificate in the `--json` output holds the source text, the seed preimage, the number of legal plans and the number of the plan drawn, to compare with:

```python
import hashlib
import itertools
import json

names = sorted(["阿明", "小红", "大刘", "Coco", "老王", "Yuki"])
blocked = {("阿明", "小红"), ("小红", "阿明"), ("大刘", "Coco"), ("Coco", "大刘"), ("老王", "Yuki")}
source = "（虚构示例）2026-11-08 某公开开奖号码 03 11 19 24 33 + 02 07"
text = json.dumps(
    {
        "rule": "gift_exchange_any_enum_v1",
        "participants": names,
        "n_slots": len(names),
        "source": source,
    },
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
)
seed = hashlib.sha256(text.encode("utf-8")).digest()
n = len(names)
plans = [
    plan
    for plan in itertools.permutations(range(n))
    if all(plan[i] != i and (names[i], names[plan[i]]) not in blocked for i in range(n))
]

counter, count = 0, len(plans)
while True:
    block = hashlib.sha256(seed + counter.to_bytes(8, "big")).digest()
    counter += 1
    x = int.from_bytes(block[:8], "big")
    if x < 2**64 - 2**64 % count:
        break
print(f"plan {x % count + 1} of {count}")
for giver, receiver in enumerate(plans[x % count]):
    print(names[giver], "->", names[receiver])
```

`itertools.permutations` lists the plans in increasing order, which is the order the script uses. For one circle the rule name is `gift_exchange_ring_enum_v1` and only the plans in which the gifts, followed from the first name, visit everybody before coming back are kept. With more than nine people the script does not list the plans. Its `md` output gives the steps for random proposals, and the rule names are `gift_exchange_any_reject_v1` and `gift_exchange_ring_reject_v1`.

## Guarantees and limits

- Legal. Everybody gives exactly one gift and receives exactly one. Nobody draws themselves or a direction that is excluded. In the way `ring` the gifts form one single circle. This is checked against a plain search over all permutations.
- The check is exact. The script reports that no legal draw exists exactly when none does, and for the way `any` the reason is a group of people who may give to fewer people than the group has (Hall's theorem). For the way `ring` with more than nine people it can only rule out the cases that it can show: too few receivers, or a group that cannot be left. Otherwise the random search may still find nothing and then exits with code 3.
- Equal chances. If nobody could predict or influence the source text when the rules were fixed, and SHA-256 behaves like a random function, every legal plan is equally likely. Up to nine people all plans are listed and one is drawn by its number. With more people random plans are proposed and the first legal one is kept, which is also equally likely among the legal plans. This is checked statistically and, for the shuffle, exactly.
- Reproducible. The same input gives the same output on every machine and Python version. The script never calls the `random` module.
- The pairing is private only from people who do not recompute it. The way of drawing is public, so anybody who has the names, the exclusions and the source text can run it and get the whole table too.
- In the way `any` two people may give to each other. List them as a pair, or use `ring`, to avoid it.
- A predictable source, or one chosen after the rules, breaks the equal chances. Whoever can guess or choose the text can try variants (another day's numbers, one more name, one exclusion less) until the draw suits them.
- Not supported: a person who drops out after the draw, budgets and wish lists, and games in which gifts are stolen or swapped.

## When not to use

- Splitting what the gifts cost: bill-split.
- Drawing scarce tickets, shifts or a prize: slot-lottery.
- Choosing a plan or a place by vote: group-vote.
- Fewer than two people: there is nothing to draw.

## Reference

Hall, P. On Representatives of Subsets. Journal of the London Mathematical Society s1-10(1):26-30, 1935. doi:10.1112/jlms/s1-10.37.26.
