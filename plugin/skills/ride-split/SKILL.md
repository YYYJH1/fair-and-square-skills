---
name: ride-split
description: Use whenever people who shared a taxi, ride-hail or carpool need to split the fare by who rode how far, got off in which order or took a detour, or want to know whether an equal split of the fare is fair, even if nobody asks for an algorithm. Runs a bundled script (Shapley value, exact to the cent) that returns each rider's share with a line they can check, a group-chat summary, a check that no rider and no group pays more than riding alone, and an audit of a split already made. Works from meter readings, from each rider's app estimate for a solo ride, or from a distance matrix. Typical requests include carpool split, split a taxi fare, who pays what when people get off in turn, 拼车怎么分钱、打车 AA、顺路下车怎么算、先下车的人为什么该少付、自驾油费过路费按路程分. Not for meals, trips or other shared bills (use bill-split) or for rent (use rent-split).
license: MIT
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/ride_split.py *)
---

# ride-split

Splitting a taxi equally sounds fair, but the first person to get off then pays more than a ride of their own would have cost. This skill splits the fare by a rule each rider can check with their own numbers: every stretch of road is paid for by the riders still in the car. In meter and estimates mode, no rider and no group of riders pays more than the same people would pay riding alone.

Quote every amount, name and count exactly as the script prints it. Do not compute, estimate or adjust any of them yourself.

## The script

`${CLAUDE_SKILL_DIR}/scripts/ride_split.py`. If that variable was not replaced, the script is in the `scripts/` folder next to this file.

In Claude Code, give the script the input as a file and let the script delete it. Claude Code asks the user to approve any command whose heredoc body holds both braces and quotes, and the input of this skill always does (a session that cannot ask refuses the command). So write the input JSON with the Write tool to a new file in the session's scratchpad directory (in a temporary directory if the session has none), then run the script on that file with `--delete-input`:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/ride_split.py --format md --input <input-file> --delete-input
```

The script deletes the file as soon as it has read it, also when it then rejects the input, so the input is on disk only from the Write until that run. Use a file you wrote for this run, never one the user already had, because the script deletes it. Put the full path in the command, with no variable and nothing chained to it, because Claude Code asks for approval otherwise. If a run stops before it reads the file (a mistyped option, a wrong path), the file is still there, so run the corrected command. Step 3 runs the script several times on the same input. Run those one after another and add `--delete-input` to the last run only. A later run on the same input needs the file written again.

In Codex and other tools, pass the input on standard input through a heredoc, so that no input file is created:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/ride_split.py --format md --input - <<'EOF'
{"mode": "meter", "riders": ["小周", "阿杰", "Mia", "老陈"], "meter_at_dropoff": [14, 26, 41, 63]}
EOF
```

The input fields:

| Field | Meaning |
|---|---|
| `mode` | `meter`, `estimates` or `general`. Required. |
| `riders` | Distinct names. `meter` and `estimates` take 2 to 12 and list them in drop-off order, `general` takes 2 to 6. |
| `meter_at_dropoff` | `meter` only. The cumulative meter reading when each rider gets off, in the order of `riders`. |
| `solo_estimate` | `estimates` only. What the app shows for each rider riding alone from the shared start. |
| `actual_total` | `estimates`: required, the amount actually paid. `general`: optional, scales all prices to it. |
| `subset_costs` | `general` only. The price of every group riding alone. Give this or `distance_matrix`, not both. |
| `distance_matrix` | `general` only. Row 0 is the start and row i the stop of rider i. It needs `tariff`. |
| `tariff` | `general` only, with `distance_matrix`. `per_unit` is required, `base` and `minimum` are optional. |
| `paid_by` | Optional. The rider who paid the driver. |
| `ride_id` | Optional. Any text. It only decides who gets a leftover cent when shares tie exactly. |
| `rules.method` | Optional. `shapley` is the only method. |
| `audit` | Optional, for `--audit`. `current` is what each rider pays now, or the text `equal` or `proportional`. |

Options are listed by `--help`. In short: `--format dm` writes one private message per rider, `--format group` a summary for the group chat, `--json` the full result, `--audit` compares a split that already exists (see "Checking an existing split"), `--lang en` switches the text to English, `--demo` runs a built-in example and `--selftest` runs the built-in checks. Exit code 2 means invalid input and the message names the field. Exit code 1 means a failed self-test. Every valid input has a result, so there is no exit code 3. Python 3.9 or later, standard library only.

The `examples/` folder holds four complete inputs: `examples/meter_four_riders.json` (the demo), `examples/app_estimates.json`, `examples/general_detour.json` (a distance matrix with a tariff) and `examples/audit_equal.json` (an equal split to audit).

## Step 1. Fix the rules before anyone gives numbers

Done when the organizer has posted one rules message and nobody objected.

Draft the rules message for the organizer. It fixes in advance:

1. How the fare is split. Each stretch of the trip is paid for by the riders still in the car, so whoever rides the last stretch alone pays all of it. The script also shows an equal split and a split in proportion to solo fares, only for comparison. Choosing among such rules is a decision for the group, and it is made before the numbers are known. The group does not vote again after seeing results.
2. Which facts go in. Either the meter reading when each rider gets off, or each rider's app estimate for riding alone from the shared start, plus the amount actually paid.
3. The amount to split is what was actually paid, tolls and tip included.

If AskUserQuestion is available, confirm the choices with it: one sentence restating the situation, the recommended option first. Otherwise ask numbered questions, each with the recommended answer.

Example (Chinese):

> 拼车分摊规则（先定再收）：
> 1. 每一段路的车费，由当时还在车上的人平摊。先下车的人少付，最后一段只有谁坐，那一段就由谁付。
> 2. 请每个人报下车时计价器上的累计车费（起步价算在第一段里）。没有计价器的话，各自在打车 App 里查「从出发地单独打车到我下车的地方」的预估价，再报一下实付总价。
> 3. 结果出来以后不再改规则。

## Step 2. Collect the facts and read them back

Done when the organizer has confirmed the input table.

Ask for the riders in the order they get off, then pick the input mode:

- `meter`: the cumulative meter reading at each drop-off, in drop-off order, with the starting fare inside the first reading. `{"mode": "meter", "riders": [...], "meter_at_dropoff": [14, 26, 41, 63]}`. Riders who get off at the same place have equal readings.
- `estimates`: no meter. Every rider looks up the fare of riding alone from the shared start to their own stop in the same ride-hailing app, and someone reports what was actually paid. `{"mode": "estimates", "riders": [...], "solo_estimate": [15, 27, 40, 66], "actual_total": 63}`. The script scales the estimates to the paid total and then shares each stretch. This assumes everyone is on the same road, so say that a detour is spread over all riders in proportion. The estimates are public facts, so anyone can look theirs up again. For a private car shared by distance, put each rider's cumulative distance (any unit) in `solo_estimate` and the total fuel and tolls in `actual_total`.
- `general`: the riders do not simply drop off in a line, for example one needs a detour. Give either the price of every group riding alone (`"subset_costs": {"小周": 15, "阿杰": 40, "小周+阿杰": 40, ...}`, one entry per non-empty group, practical only up to 4 riders, which is 15 prices), or a distance matrix and a tariff (`"distance_matrix": [[0, 2, 12, 11], ...]`, row 0 is the start and row i the stop of rider i, `"tariff": {"base": 10, "per_unit": 2.5}`). The script tries every route. A list of `{"riders": [...], "cost": ...}` objects also works for `subset_costs` and is the form for names that contain a plus sign. Optional `"actual_total"` scales all prices to what was really paid.

Optional fields in every mode: `"paid_by": "老陈"` (the rider who paid the driver, so the messages say who sends what to whom), `"ride_id": "..."` (any text, for example the date and route, which only decides who gets a leftover cent when shares tie exactly).

Size limits: `meter` and `estimates` take 2 to 12 riders, `general` takes 2 to 6.

Build the JSON, show it back to the organizer as a table, and wait for confirmation before running.

## Step 3. Run

Done when the script has exited with code 0.

Run it three times on the same input: `--format md` for the organizer's tables, `--format dm` for one message per rider, `--format group` for the group-chat summary. If it exits with code 2, show the message to the organizer, fix the named field with them and run again. Do not guess a value.

## Step 4. Present

Done when the organizer has the tables and every rider has their own message.

1. Give the organizer the `md` output: the stretches, what each rider pays against riding alone, the comparison with the equal and proportional splits, and the core check.
2. Give each rider their block from `--format dm`, privately, for example: "最后那段 22.00 元只有你一个人坐，所以你多付。" The last rider pays most because nobody else is in the car for the last stretch. The first rider pays little because everybody shares the first one.
3. Post the `--format group` summary.
4. If the equal split broke the core check, say which groups pay more than riding alone, as the table lists them. That is the reason an equal split is not offered as the answer. If the proportional split also passes, the difference to the stretch-by-stretch split is a choice of rule, and that choice was made in Step 1.

## Checking an existing split

If the riders already split the fare some way (for example equally), add `"audit": {"current": {"小周": 15.75, "阿杰": 15.75, "Mia": 15.75, "老陈": 15.75}}` to the input and run with `--audit`. The value may also be the text `"equal"` or `"proportional"`, which the script fills in itself. Report per rider, in their own numbers, how much more or less they pay than the fair share, who pays more than riding alone, and which groups break the core check. The audit compares. The group decides whether to change anything. See `examples/audit_equal.json`.

## Guarantees and limits

- Guarantees, checked by tests: the shares add up to the fare to the cent. Riders who are interchangeable, for example with the same solo price, pay the same, up to one cent of rounding. A rider who adds nothing to the fare pays nothing. The share of two fares added together is the sum of the shares of each (additivity). In `meter` and `estimates` mode the result is always in the core: no rider and no group pays more than the same people would pay riding alone, also after rounding to cents.
- `general` mode can fall outside the core, and the core can be empty, for instance when sharing a car costs more than separate cars. The script lists the groups concerned and says whether the core is empty. It does not offer another rule in that case.
- Not strategy-proof. Meter readings and app estimates are reported by the riders themselves.
- Not modeled: tolls and tips (add them to the paid total first), waiting time, traffic, and pick-up detours with a common destination. Use `general` mode with prices from the app for those.

## When not to use

- Meals, trips, group orders or any bill that has to be settled together with other expenses: bill-split.
- Rent and room prices: rent-split.

## Reference

Littlechild, S. C., Owen, G. A Simple Expression for the Shapley Value in a Special Case. Management Science 20(3):370-372, 1973. doi:10.1287/mnsc.20.3.370.

Shapley, L. S. Cores of Convex Games. International Journal of Game Theory 1(1):11-26, 1971. doi:10.1007/bf01753431.
