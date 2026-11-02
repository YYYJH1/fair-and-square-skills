---
name: chore-split
description: Use whenever roommates, flatmates or a household need to share out recurring chores (dishes, cooking, trash) or want a fair rota, even if nobody asks for an algorithm. Runs a bundled script that takes each person's private ranking of the chores, lets people pick in turns, rotates who picks first each week, and returns the weekly schedule with one line per person to check against their own ranking. Handles repeating chores and chores a person cannot do. A second plan gives each person a fixed bundle and settles the difference with payments between housemates. Typical requests include divide chores fairly, chore chart, roommate chores, who does the dishes, 分家务、家务怎么分才公平、合租值日表、谁洗碗. Only for chores, not for tasks someone enjoys. Not for deciding by lot (use slot-lottery) or for splitting bills and what a cleaner costs (use bill-split).
license: MIT
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/chore_split.py *)
---

# chore-split

Sharing out chores is rarely a fight about the total. It is about who got stuck with what. This skill uses the oldest fair rule there is: people take turns, and whoever is up takes the chore they mind least. Each person ranks the chores privately from least to most disliked, so nobody has to put a number on how much they hate cleaning the toilet. The start order rotates every week. Each person can check one line against their own ranking: in every round, the chore they took was no worse for them than the one another person took right after.

That is plan A, round-robin picking, and it is the default. Plan B, bundles with compensation, is for groups that are happy to move money between them and can put a number on what each chore costs them. The chores go to the people at the smallest total cost within each person's cap, and payments that add up to zero leave nobody wishing to swap their share, with its payment, for another person's. The group picks the plan in the rules message, before anybody gives a number.

Quote every name, chore, round and number exactly as the script prints it. Do not pick, rank, count or compare anything yourself, and never choose or guess the random source.

## The script

`${CLAUDE_SKILL_DIR}/scripts/chore_split.py`. If that variable was not replaced, the script is in the `scripts/` folder next to this file.

In Claude Code, give the script the input as a file and let the script delete it. Claude Code asks the user to approve any command whose heredoc body holds both braces and quotes, and the input of this skill always does (a session that cannot ask refuses the command). So write the input JSON with the Write tool to a new file in the session's scratchpad directory (in a temporary directory if the session has none), then run the script on that file with `--delete-input`:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/chore_split.py --format md --input <input-file> --delete-input
```

The script deletes the file as soon as it has read it, also when it then rejects the input, so the rankings (in plan B, the costs) are on disk only from the Write until that run. Use a file you wrote for this run, never one the user already had, because the script deletes it. Put the full path in the command, with no variable and nothing chained to it, because Claude Code asks for approval otherwise. If a run stops before it reads the file (a mistyped option, a wrong path), the file is still there, so run the corrected command. Step 3 runs the script several times on the same input. Run those one after another and add `--delete-input` to the last run only. A later run on the same input needs the file written again.

In Codex and other tools, pass the input on standard input through a heredoc, so that no input file is created. This is the three-roommate example (the names and the draw are made up):

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/chore_split.py --format md --input - <<'EOF'
{
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
}
EOF
```

The input fields:

| Field | Meaning |
|---|---|
| `people` | Distinct names, 2 to 12. The order of listing does not change the result. |
| `chores` | The chores of one week, up to 40, with at most 120 units in all. Each is a name, or `{"name": "洗碗", "units": 3}` for a chore that repeats during the week. Dishes three times a week is three units, and each unit is picked on its own. |
| `rankings` | Plan A, required. Person to the list of the chores they can do, from least to most disliked. Every such chore exactly once. |
| `cannot` | Optional, both plans. Person to the chores they cannot do at all. These stay out of that person's ranking (plan A) or costs (plan B). |
| `likes` | Plan A, optional. Person to the tasks they like doing. The script refuses them (exit code 2). Plan B has no `likes`: a task somebody likes costs them 0. |
| `weeks` | Plan A. How many weeks to plan, 1 to 12. Default 1. Plan B settles one typical week and refuses `weeks`. |
| `costs` | Plan B, required. Person to a table of chore to cost: what the person would want per week for doing the chore once, in money or points, 0 or more, at most two decimals. Every chore the person can do exactly once. |
| `caps` | Plan B, required. Person to the most chore units they take in a week, 0 or more. State it for every person. |
| `rules.plan` | `round_robin` (plan A, the default) or `bundle_pay` (plan B). |
| `rules.random_source` | Plan A, required. The public text the pick order of week 1 is drawn from, copied exactly. Plan B, optional: the text only settles a tie between splits of the same total cost. |
| `rules.source_description` | Optional. Where the text comes from, as one line. Plan B accepts it only together with a source. |
| `rules.rotate` | Plan A. `shift` (default) moves the start one place each week. `none` keeps the order of week 1. |

Options are listed by `--help`. In short: `--format dm` writes one private message per person, `--format group` a card for the group chat, `--json` the full result, `--lang en` switches the text to English, `--demo` runs the example above, `--demo-bundle` runs the example of plan B below and `--selftest` runs the built-in checks. Exit code 2 means invalid input and the message names the field. Exit code 3 means a chore is on every person's `cannot` list, so nobody can do it, or, in plan B, that the caps and the `cannot` lists leave no way to share out all the chores. Exit code 1 means a failed self-test. Python 3.9 or later, standard library only.

The `examples/` folder holds five complete inputs. For plan A: `examples/three_roommates.json` (the demo), `examples/weekly_rota.json` (four weeks, with dishes and trash that repeat) and `examples/cannot_cook.json` (one person cannot cook). For plan B: `examples/bundle_three_roommates.json` (the demo) and `examples/bundle_uneven_caps.json` (four housemates with different caps, a chore that repeats and one person who cannot cook).

Plan B is chosen with `"plan": "bundle_pay"` in `rules` and takes `costs` and `caps` in place of `rankings` and `weeks`. This is its three-roommate example, to be given to the script in either of the two ways above (the names and the draw are made up):

```json
{
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
}
```

The script prints each housemate's chores, the payments, which add up to zero, and for every person a table of what they would get from each other housemate's share, so that they can check the result against their own costs.

## Step 1. Fix the rules before anybody ranks anything

Done when the organizer has posted one rules message and nobody objected.

First settle which plan the group wants, because it decides what everybody has to enter. Plan A, round-robin picking (`round_robin`), needs rankings only and moves no money. Plan B, bundles with compensation (`bundle_pay`), needs a cost for every chore from every person and a cap, and moves money between the housemates. Offer plan B when the group is happy to pay each other and ready to say what each chore costs them. Put the plan in the rules message, and in `rules.plan` of the input.

Draft the rules message for the organizer. It fixes in advance:

1. How picking works. Each week the people take turns in a fixed order. Whoever is up takes the remaining chore they mind least, until every chore is taken. A chore that repeats during the week counts once for every time, so dishes three times a week is three chores that anybody can pick.
2. The order. A public random source named now decides who starts in week 1. It must be a text that nobody in the group controls, that cannot be guessed before it is published and that anyone can look up afterwards, for example the winning numbers of a named lottery draw on a stated date, copied exactly as shown. Then say how the start moves: by default one place each week, so everybody starts first in turn. It only decides who picks first, so the stakes are small, but it has to be fixed before anybody ranks.
3. How to rank. Each person lists every chore from the one they mind least to the one they mind most. Two chores that feel the same go in either order. A chore somebody cannot do at all, for example because of an injury or an allergy, is not ranked and is named separately. Somebody who actually likes a task says so.
4. The deadline, and how many weeks the rota covers. Rankings go to the organizer privately and at the same time, so nobody needs to guess what the others will say.
5. The organizer goes first. The organizer hands their own ranking to another housemate to hold before collecting the others.
6. After the result there is no re-pick and no new vote on the rules.

For plan B the message fixes these things in place of items 1 to 3. Items 4 to 6 stay as they are: the deadline, the organizer going first, and no re-pick.

- The split. Each person has a cap, the most chore units they take in a week, and a chore somebody cannot do is not given to them. Within those limits the chores go out so that the total cost, by the costs the people enter, is as small as possible. A chore that repeats counts once for every time.
- The money. Payments add up to zero. They are worked out so that nobody, by their own costs, would rather have another person's chores and payment, and so that the person who ends up worst off is as well off as possible among such payments. The people who pay put their money into a common pot and the people who receive take theirs from it.
- What a cost is. For each chore a person can do, what they would want per week for doing it once, in money or in points, never below 0. A task somebody likes costs 0. A chore somebody cannot do gets no cost and is named separately.
- Ties. When several splits have the same total cost, the order of the names decides, or, if the group names a public random source now, the order drawn from it. That source follows the same rules as in plan A: a text that nobody controls, that cannot be guessed before it is published and that anyone can look up afterwards.

If AskUserQuestion is available, confirm the rule choices with it: one sentence restating the situation, the recommended option first. Otherwise ask numbered questions, each with the recommended answer.

Example (Chinese):

> 分家务规则（先定再收，发出后不改）：
> 1. 每周大家轮流挑：轮到谁，谁就从剩下的家务里挑自己最不讨厌的一件，挑到没有为止。一周里重复出现的家务拆开算，比如洗碗每周 3 次就是 3 件，谁都可以挑。
> 2. 先后顺序：第 1 周谁先挑，用 11 月 8 日某某公开开奖的号码来定，按官网显示的样子原样抄写。之后每周先手往后轮一位，每个人轮流当先手。
> 3. 请把所有家务按你有多不想干，从最不讨厌到最讨厌排好，周五晚 8 点前私聊发我，大家同时交，不必猜别人怎么排。两件一样讨厌的，随便哪件排前面。完全做不了的（比如受伤、过敏）不用排，单独告诉我。要是有哪件你其实喜欢做，也告诉我。
> 4. 先排 4 周。我先交：我的排序已经交给小红保管。
> 5. 结果出来后不重挑，也不改规则。

Example for plan B (Chinese):

> 分家务规则（包干加补偿，先定再收，发出后不改）：
> 1. 每人每周最多接几件有上限，上限在下面列出。做不了的家务不分给他。一周里重复出现的家务拆开算，洗碗每周 3 次就是 3 件。
> 2. 在这些限制内，选每周总代价最小的分法，总代价按大家各自填的代价算。
> 3. 再用加起来为 0 的补偿：有人付钱，有人收钱。补偿算好之后，每个人按自己填的代价，都不想换成别人那份（连同那份的补偿或付出）。付钱的人把钱放进公用的钱罐，收钱的人从里面拿。
> 4. 请把你能做的每件家务，按你每周做一次要多少钱（或多少分）填给我，不能小于 0，喜欢做的填 0。完全做不了的（比如受伤、过敏）不用填，单独告诉我。周五晚 8 点前私聊发我，大家同时交，不必猜别人怎么填。
> 5. 总代价一样的几种分法，按姓名顺序取第一种。想用公开随机源来定的话，现在就说，并写明是哪个公开开奖。
> 6. 我先交：我的数已经交给小红保管。结果出来后不重分，也不改规则。

## Step 2. Collect the rankings privately and read them back

Done when the organizer has confirmed the input table.

- Rankings reach the organizer privately, never in a public chain message. Ask each person for the whole list, least disliked first, including the organizer, who handed theirs over first.
- A chore a person cannot do goes into `cannot` for that person and stays out of their ranking. The ranking lists every other chore exactly once. Do not guess the missing ones.
- If somebody says they like a task, record it in `likes`. The script then refuses to run (exit code 2) and says why. Settle that task some other way, for example by agreeing openly who takes it, then take it out of `chores` and `likes` and share out the rest.
- Chores that repeat during the week get `units`. Ask how many times a week.
- Build the JSON, show it back to the organizer as a table (one row per person, the chores in ranking order, the `cannot` chores beside it), and wait for confirmation.

For plan B, collect costs and caps in the same way:

- Costs reach the organizer privately, never in a public chain message, and the organizer's own go first. Ask each person for a cost for every chore they can do and for their cap. Never fill in a cost yourself or guess a missing one.
- A chore a person cannot do goes into `cannot` for that person and gets no cost. A task somebody likes gets the cost 0, and there is no `likes` in plan B.
- Chores that repeat during the week get `units`, and a cost is for doing the chore once.
- Build the JSON with `costs` and `caps`, show it back to the organizer as a table (one row per person: the cost of every chore, the `cannot` chores and the cap), and wait for confirmation.

## Step 3. Wait for the source, then run

Done when the script has exited with code 0, or with code 3 (see Step 4).

- If the source has not been published yet, say so and stop. Do not run the script with a placeholder, because a wrong text gives a different order that looks just as real.
- When it is published, ask the organizer to paste the text exactly as it appears. Put it into `rules.random_source` unchanged and read it back to them character by character. One changed space or sign gives a different order.
- In plan B the source is optional. If the rules name none, there is nothing to wait for: run the script at once, and tell the organizer that ties between splits of the same total cost are settled by the order of the names. If the rules name a source, wait for it as above.
- Run the script three times on the same input: `--format md` for the organizer, `--format dm` for one message per person, `--format group` for the group chat. If it exits with code 2, show the message to the organizer, fix the named field with the person concerned and run again. Do not guess a value.

## Step 4. Present

Done when the organizer has the tables, every person has their own message and the group has the card.

1. Give the organizer the `md` output: the schedule, who picked what in each round, the round-by-round check of every pair, the source and the EF1 status. It shows where every chore stands in every person's ranking, so it is for the organizer only.
2. Give each person their own block from `--format dm`, privately. It holds their picks, one line of proof and the comparison against each other person in their own ranking, then the ranking the person sent, so that a typing mistake shows at once. For example: "第 1 周，对阿明（阿明每轮先挑）：第 1 轮你挑的「洗碗」（你的第 2 位）不比阿明下一轮（第 2 轮）挑的「做饭」（第 6 位）更讨厌；去掉你最后挑的「擦窗」，你就不羡慕阿明。" A person who picks after another compares with that person's next round, because the other has already taken a chore in the current one.
3. Post the `--format group` card. It holds the pick order, who took what in every round, the source text and the seed, and nobody's ranking. Anybody can check their own line against it.
4. If the EF1 status says the guarantee fails for some pairs, say so as printed, with the reason. The script does not repair the split. The group decides what to do, openly. Do not run it again with changed inputs until the numbers look better.
5. If the script exited with code 3, a chore is on every person's `cannot` list. Tell the organizer that somebody has to be found for it, or it has to be taken out of `chores`, by agreement of the group. Do not remove a name from `cannot` yourself.

In plan B the same three outputs are used. The `md` output has, for every person, the chores, the cost, the payment and the net of the week, then the table of what each person would get from each other share, the total cost, the worst-off people and the note on ties. Each `dm` message holds the person's chores and cap, their payment, their own check table and one sentence, for example "按你自己填的代价，你这份每周的折算是 -45.00，换成别人那份（连同那份的补偿或付出）都不会更划算。" The net, here -45.00, is minus the cost of the person's chores plus the payment they receive, or minus the payment they make. The group card holds the split and the payments and nobody's costs. Say who pays and who receives as the script prints it, and say that the payments add up to zero: the people who pay put the money into a common pot and the people who receive take theirs from it. Do not work out who pays whom. Do not call the split the best one for everybody, because the guarantees below say what is promised. If the script exited with code 3 in plan B, the caps and the `cannot` lists leave no way to share out all the chores. Show the organizer the message, which names the chores and the people concerned, and let the group raise a cap, change a `cannot` list or take a chore out, openly.

## When someone cannot do a chore

Run as usual with `cannot`. A person never picks a chore on their own `cannot` list, and a chore that sits on everybody's list stops the run (exit code 3), so somebody has to be found or the chore taken out. If a person has nothing left that they can do, they are skipped for the rest of that week.

That can break the guarantee, because the others then hold more chores than that person. The script checks every pair of people in every week and says whether the guarantee holds and, if it fails, why. A person who cannot do the chore that another holds cannot envy that holding, and the script says that as well. In `examples/cannot_cook.json` one housemate cannot cook, dinner is five of the ten chores a week, and the three others end up with more chores than that housemate.

In plan B the `cannot` list is part of the split. A chore is never given to somebody who cannot do it, and nobody envies a share that holds a chore they cannot do or that has more units than their cap, because they could not take it. If the caps and the `cannot` lists leave no way to share out all the chores, the script says which chores and which people are the problem and exits with code 3. In `examples/bundle_uneven_caps.json` one housemate takes one chore at most and cannot cook, so that housemate is not compared with the shares of the others, and their line says why.

## Guarantees and limits

Plan A, taking turns:

- Envy-free up to one chore (EF1), every week, when nobody has a `cannot` list. Take any way of putting a cost of zero or more on each chore, as long as it agrees with a person's ranking (a chore they rank later never costs less). Then once one of their own chores is set aside, nobody finds another person's chores lighter than their own. This holds for all such costs at once, so nobody has to say how much they mind anything. The script checks every pair and says in each case whether the exception was needed.
- Not full envy-freeness. A person who picks after another can still prefer that person's set, because their last pick is compared with nothing. When the number of chores does not divide evenly, somebody also holds one more chore than a housemate. Setting aside one chore covers both.
- Rankings only. The script does not see how much worse one chore is than the next, so it cannot promise equal time, effort or total burden.
- Not strategy-proof. A person who knows the other rankings can sometimes lighten their own set by ranking untruthfully.
- One week at a time. Every week has the guarantee on its own. Nothing is promised about the weeks added together. Rotating the start only evens out who picks first.
- Only chores. A task that somebody likes breaks the argument, so the script refuses it (exit code 2). Tasks that are liked by some and disliked by others need a different method.
- With `cannot` lists the guarantee can fail, and the script says when and for whom.
- Money. Plan A moves no money. Paying somebody to take a chore is what plan B does between housemates. What an outside cleaner costs is not calculated by either plan, so use bill-split.
- The random source only decides who picks first in week 1. The script cannot check that it was fixed in advance. A source that somebody could predict or choose after the rules lets that person pick the start.

Plan B, bundles with compensation:

- Cheapest split. Within the caps and the `cannot` lists, the chores go out so that the total cost, by the costs the people entered, is as small as possible. Splits of the same total cost are settled by the order of the names or by the public source, and the script says whether there was such a tie.
- No envy by their own costs. With the payments, nobody would rather have the chores and the payment of another person whose share they could take. In exact numbers this holds without exception, also for different caps and `cannot` lists, because a share that a person cannot take is left out of their comparison. After every payment is rounded to the cent, one cent of envy can remain, and the script says so.
- The worst-off person. Among the payments that add up to zero and leave nobody envious, the person who ends up worst off is as well off as possible. That is for the cheapest split only. A split that costs more sometimes leaves the worst-off person better off, and the script does not look for it. When the payments can leave everybody with the same amount, that amount is minus the total cost divided by the number of people, and no split does better for the worst-off person.
- Not strategy-proof. A person who knows the other costs can sometimes gain by entering costs that are not their own.
- Costs as entered. The script takes the costs as given: a person's cost is the sum over their chores, and money and cost trade one for one. It cannot see effort or time, and it cannot check that the numbers are honest.
- One typical week, repeated. Nothing rotates between weeks.
- The random source only settles ties between splits of the same total cost. The script cannot check that it was fixed in advance.

## When not to use

- Deciding who gets something scarce or an unwanted one-off task by lot: slot-lottery.
- Splitting bills: bill-split.
- Tasks that some people enjoy and others do not: plan A does not support them. In plan B a person who likes a task enters the cost 0 for it.

## Reference

Aziz, H., Caragiannis, I., Igarashi, A., Walsh, T. Fair Allocation of Indivisible Goods and Chores. Proceedings of the Twenty-Eighth International Joint Conference on Artificial Intelligence (IJCAI 2019), pp. 53-59. doi:10.24963/ijcai.2019/8. Journal version: Autonomous Agents and Multi-Agent Systems 36(1):article 3, 2022. doi:10.1007/s10458-021-09532-8.

Plan B uses the payment rule of rent-split with a total rent of zero: Gal, Y., Mash, M., Procaccia, A. D., Zick, Y. Which Is the Fairest (Rent Division) of Them All? Journal of the ACM 64(6), 2017. doi:10.1145/3131361.
