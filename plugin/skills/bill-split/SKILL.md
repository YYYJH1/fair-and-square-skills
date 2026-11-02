---
name: bill-split
description: Use whenever people need to split a shared bill (a meal where some people did not drink, a trip with several payers, a takeaway group order with delivery fees and full-reduction coupons) or ask who owes whom, even if nobody asks for an algorithm. Runs a bundled script that splits item by item, shares fees and discounts, rounds exactly to the cent and returns the fewest transfers, one private message per person and a group-chat summary. For group orders it shares a coupon by Shapley value and checks that nobody pays more than ordering alone. It can also audit a split the group already uses and show who overpays. Typical requests include split the bill, settle up, who owes whom, AA、分账、聚餐怎么分钱、旅行账单、谁该给谁转账、外卖拼单、凑满减. Not for taxi fares by drop-off order (use ride-split) or for rent and rooms (use rent-split).
license: MIT
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/bill_split.py *)
---

# bill-split

Splitting a bill equally is easy and often unfair: the people who skipped the wine pay for it. This skill splits each item among the people who shared it, shares fees and discounts by a rule the group agreed on, and settles up with the fewest transfers. For takeaway group orders it also shares a coupon fairly and checks that joining the order does not cost anyone more than ordering alone.

Quote every amount, name and count exactly as the script prints it. Do not compute, estimate, round or adjust any of them yourself.

## The script

`${CLAUDE_SKILL_DIR}/scripts/bill_split.py`. If that variable was not replaced, the script is in the `scripts/` folder next to this file.

In Claude Code, give the script the input as a file and let the script delete it. Claude Code asks the user to approve any command whose heredoc body holds both braces and quotes, and the input of this skill always does (a session that cannot ask refuses the command). So write the input JSON with the Write tool to a new file in the session's scratchpad directory (in a temporary directory if the session has none), then run the script on that file with `--delete-input`:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/bill_split.py --format md --input <input-file> --delete-input
```

The script deletes the file as soon as it has read it, also when it then rejects the input, so the input is on disk only from the Write until that run. Use a file you wrote for this run, never one the user already had, because the script deletes it. Put the full path in the command, with no variable and nothing chained to it, because Claude Code asks for approval otherwise. If a run stops before it reads the file (a mistyped option, a wrong path), the file is still there, so run the corrected command. Step 3 runs the script several times on the same input. Run those one after another and add `--delete-input` to the last run only. A later run on the same input needs the file written again.

In Codex and other tools, pass the input on standard input through a heredoc, so that no input file is created:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/bill_split.py --format md --input - <<'EOF'
{"people": ["A", "B", "C"],
 "expenses": [{"id": "dinner-1", "paid_by": {"A": 90},
               "items": [{"name": "food", "amount": 90, "everyone": true}]}]}
EOF
```

Options are listed by `--help`. Text output is Chinese by default, `--lang en` gives English, and `--json` has no prose at all. `--demo` prints three worked examples and `--selftest` runs the built-in checks. Exit code 2 means invalid input and the message names the field: fix the JSON if it was a transcription slip, otherwise ask the user, and never change an amount to make it pass. Exit code 1 means a failed self-test. Every valid input has a result, so there is no exit code 3. Python 3.9 or later, standard library only.

## Input

Two modes, chosen by `mode`. The top-level fields:

| Field | Meaning |
|---|---|
| `mode` | Optional. `expenses` (the default) or `group_order`. |
| `people` | `expenses` only. Distinct names, 2 to 100. |
| `expenses` | `expenses` only. One object per bill, 1 to 2000. |
| `id` | `group_order` only. The name of the order, which sets who gets the leftover cent. |
| `items`, `fees`, `coupons` | `group_order` only. The dishes, the shared fees and the coupons. |
| `paid_by` | `group_order` only, optional. The payer: a name, or an object when several people paid. |
| `rules.settle` | `expenses` only, optional. `min_transfers` (the default) or `greedy`. |
| `audit` | Optional, for `--audit`. `current` is the split the group uses now (see "Checking an existing split"). |

The `examples/` folder holds six complete inputs: `examples/dinner_680.json` (a dinner with a drink that only two people had), `examples/audit_aa.json` (the same dinner audited against equal shares), `examples/trip_five_bills.json` (six people and five bills), `examples/fewest_transfers.json` (two payers and exact amounts), `examples/group_order_takeout.json` (a takeaway order with a delivery fee and tiered coupons) and `examples/group_order_coupon.json` (three people and a tiered coupon, audited against shares by dish price).

**expenses** (the default) is for meals and trips, one object per bill:

```json
{"people": ["A", "B", "C"],
 "expenses": [{
   "id": "dinner-1", "what": "dinner", "paid_by": {"A": 820},
   "items": [{"name": "food", "amount": 480, "everyone": true},
             {"name": "wine", "amount": 160, "among": ["B", "C"]},
             {"name": "kid meal", "amount": 60, "everyone": true, "weights": {"C": 0.5}},
             {"name": "tickets", "amount": 100, "exact": {"A": 60, "B": 40}}],
   "fees": [{"name": "service", "amount": 40, "split": "by_consumption"}],
   "discounts": [{"name": "voucher", "amount": 20, "split": "equal"}]}],
 "rules": {"settle": "min_transfers"}}
```

- Each item says who shares it with exactly one of `everyone: true`, an `among` list (optionally with `weights`, where a missing person counts as 1), or `exact` amounts that add up to the item. Use the boolean `everyone`, never the word "all".
- `paid_by` may name several payers. It must add up to items + fees - discounts.
- A fee or discount is split `by_consumption` (default), `equal` per person, or `exact`. A tip or service charge is a fee. A refund is a discount.
- `id` is the bill's name. It sets which person gets the leftover cent, so keep ids unique and stable.
- Amounts have at most two decimals, one currency.

**group_order** is for one takeaway or online order shared by several people:

```json
{"mode": "group_order", "id": "order-1",
 "items": [{"who": "A", "name": "noodles", "amount": 28, "packaging": 1},
           {"who": "B", "name": "tea", "amount": 6, "packaging": 1}],
 "fees": [{"name": "delivery", "amount": 5, "split": "proportional"}],
 "coupons": [{"name": "spend 30 save 5", "tiers": [[30, 5], [60, 18]], "split": "shapley"},
             {"name": "red packet", "amount": 3, "split": "proportional"}],
 "paid_by": "A"}
```

- `packaging` follows the dish. Fees are shared `proportional` to dish prices (default) or `equal` per person.
- A tiered coupon lists every `[threshold, reduction]` the app shows. The highest tier reached applies once, tiers are not added. Thresholds look at the dish subtotal only.
- A flat coupon such as a platform red packet has `amount` and is shared `proportional` (default) or `equal`. It is not subtracted from anyone's order-alone price.
- `split` of a tiered coupon is `shapley` (default) or `proportional`. Shapley is exact for at most 16 people, beyond that use `proportional`.
- `paid_by` is optional: a name, or an object when several people paid.

## Step 1. Fix the rules before anyone gives numbers

Done when the organizer has posted one rules message and nobody objected.

Bills are public facts, so nobody needs to go first and nothing needs to be sent privately. What must be agreed in advance is how the shared parts are split:

1. Fees and discounts: by what each person ordered (default), equally per person, or exact amounts.
2. Leftover cents: largest remainder, and equal remainders rotate with the bill id, so no one gets the extra cent every time.
3. Settling up: the fewest transfers (exact while at most 16 people have a balance, otherwise the greedy rule and the script says so).
4. For a group order: the full-reduction coupon by Shapley value or in proportion to dish prices, delivery fee and red packet in proportion to dish prices, packaging with the dish. The coupon rule changes who pays what, so decide it before ordering. The group will not vote on the rule after seeing the result.

If AskUserQuestion is available, confirm the choices with it: one sentence restating the situation, the recommended option first. Otherwise ask numbered questions, each with the recommended answer.

Example (Chinese):

> 分账规则（先定再算）：
> 1. 每人只付自己吃喝的部分，服务费和优惠券按各人消费比例分。
> 2. 零头按最大余数法给，并列时按账目编号轮换，不会总落在同一个人头上。
> 3. 转账用最少笔数。
> 4. 外卖拼单的满减按 Shapley 值分，配送费和红包按菜价比例，打包费跟着菜走。
> 5. 结果出来后不再改规则。

## Step 2. Collect and read back

Done when the organizer has confirmed the input table.

- Take amounts from the receipt, the app screenshot or the group chain, not from memory. Ask for what is missing: who paid how much, what each person had, every fee and discount with its amount, and for a group order each person's dishes, the packaging fee per dish, the delivery fee, every coupon tier and the red packet.
- Never assume an item is shared by everyone. Ask who had it.
- Build the JSON, show it back to the organizer as a table (item, amount and who shares it, then fees and discounts, then who paid), and wait for confirmation before running.

## Step 3. Run

Done when the script has exited with code 0.

Run it on the same input three times: `--format md` for the organizer's tables, `--format dm` for one message per person, `--format group` for the group-chat summary. Add `--audit` to compare with the split the group uses now (next section).

## Step 4. Present

Done when every person has their own message and the group has the summary.

1. Give the organizer the md output: the per-person table, the transfers, and the notes. Quote the notes (the lines that start with 提示 or Note) verbatim. They cover zero-yuan items, someone paying for others, a greedy fallback, and a person whose share is negative.
2. Give each person their block from `--format dm`, and ask the organizer to forward each block privately. A block contains only that person's numbers, plus the names of the people they pay or receive from.
3. Post the `--format group` summary. It shows what the bill already shows.
4. For a group order, report the trap check as printed. If it failed, say who would pay less ordering alone. The group decides what to do and the rules stay as agreed.

## Checking an existing split

If the group already splits some way, run with `--audit`. In an `audit` block, `current` is `"aa"` (equal shares of the total, the default for expenses) or an object that gives what each person pays now and adds up to the total, for example `{"audit": {"current": {"A": 170, "B": 170, "C": 170}}}`. For a group order `current` is also `"proportional"` (the default: fees and coupons by dish price). Report, per person and in their own numbers, whether they pay more or less than the rule says and by how much. For a group order also report who pays more than ordering alone. The audit compares and the group decides.

## Edge cases

- A child eats half: `weights`. A guest who left early: leave them out of `among`.
- Someone paid for others, or two people paid one bill: allowed. A note says so.
- A free item with amount 0: allowed, with a note. A person literally named "all" is just a person.
- More than 16 people with a balance: the script settles with the greedy rule and says it may not be the fewest.
- Shapley can give a small order that lifts the group over a threshold a share larger than the order, so that person receives money. The script notes it. If the group dislikes this, choose `proportional` before ordering.
- If someone can reach a coupon tier alone, grouping can waste it and the trap check fails. Say so plainly.

## Guarantees and limits

- Amounts are exact fractions. The total is right to the cent, and every person's share of a bill is within one cent of the exact amount. Each part shown in a breakdown is a whole number of cents and the parts add up to the share.
- With at most 16 people having a balance, the number of transfers is the fewest possible. The total money moved is not minimized.
- The coupon shares add up to the discount. Equal dishes get equal shares. In a group order the trap check is computed, never assumed.
- Not strategy-proof. Dish prices and receipts are taken as facts, so a person could pad an order to cross a threshold.

## When not to use

- Taxi or carpool fares split by who gets out first: ride-split.
- Rent and who gets which room: rent-split.

## Reference

Shapley, L. S. A Value for n-Person Games. In Contributions to the Theory of Games, Volume II, Princeton University Press, 1953, pp. 307-318. doi:10.1515/9781400881970-018.

Shapley, L. S., Shubik, M. A Method for Evaluating the Distribution of Power in a Committee System. American Political Science Review 48(3):787-792, 1954. doi:10.2307/1951053.
