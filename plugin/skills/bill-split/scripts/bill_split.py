"""Split shared bills fairly and settle up with the fewest transfers.

The JSON input (standard input by default) has a "mode" field with two values.

expenses (the default) is for meals and trips. Each expense lists who paid, the items with who
shares each one (everyone, named people, portions or exact amounts), and the fees and discounts
with their own split rule. The script returns what each person owes, the net balances and the
fewest transfers that settle them.

group_order is for one takeaway or online order shared by several people. It has the dishes of
each person with a packaging fee per dish, shared fees such as delivery, tiered full-reduction
coupons (shared by Shapley value or in proportion to dish prices) and flat coupons such as a red
packet. The script also checks whether anybody pays more than ordering alone.

Amounts are exact fractions, rounded once to whole cents with the largest-remainder rule. Ties
rotate with the bill id, so the leftover cent does not always land on the same person. Options:
--format md|dm|group, --json, --audit (compare with the split the group uses now), --lang zh|en,
--demo and --selftest.

Python 3.9 or later, standard library only.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

try:
    import fsq_core as fc
except ModuleNotFoundError:  # python -I, -P and PYTHONSAFEPATH leave the script folder off sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import fsq_core as fc

# ---------------------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------------------

MODES = ("expenses", "group_order")
LEDGER_FIELDS = ("mode", "people", "expenses", "rules", "audit")
ORDER_FIELDS = ("mode", "id", "items", "fees", "coupons", "paid_by", "rules", "audit")
SETTLE_RULES = ("min_transfers", "greedy")
EXPENSE_SPLITS = ("by_consumption", "equal", "exact")
ORDER_FEE_SPLITS = ("proportional", "equal", "by_consumption")  # the last is "proportional"
TIER_SPLITS = ("shapley", "proportional")
# A flat coupon is worth the same to any group that orders, so its Shapley value is an equal
# share. "by_consumption" is "proportional" under the name used for expenses.
FLAT_COUPON_SPLITS = ("proportional", "equal", "shapley", "by_consumption")
# "equal" is accepted as another name of "aa" (equal shares of the total)
EXPENSE_AUDITS = ("aa", "equal")
ORDER_AUDITS = ("proportional", "aa", "equal")

EXACT_LIMIT = 16  # fewest transfers and Shapley shares are exact up to this many people
MAX_PEOPLE = 100
MAX_EXPENSES = 2000
MAX_ROWS = 500  # items per expense or per order
MAX_EXTRAS = 50  # fees, discounts and coupons
MAX_TIERS = 20
MAX_WEIGHT = 1000

Transfer = tuple  # (debtor, creditor, cents)
Note = tuple  # (code, params)


# ---------------------------------------------------------------------------------------
# Text (zh is the default, en mirrors it; the JSON output is language independent)
# ---------------------------------------------------------------------------------------

TEXT: dict[str, dict[str, str]] = {
    "zh": {
        "title_expenses": "分账结果",
        "title_order": "拼单结果",
        "rules_expenses": (
            "规则：每项按各自写明的方式分摊；费用和优惠按各笔账里写的方式分；零头按最大余数法给出，"
            "并列时按账目编号轮换；{settle}。"
        ),
        "rules_order": (
            "规则：打包费跟着菜走{extras}；零头按最大余数法给出，并列时按账目编号轮换；{settle}。"
        ),
        "settle_min": "转账笔数取最少（不超过 16 人有未结余额时精确求解）",
        "settle_greedy": "转账用贪心法，不保证笔数最少",
        "rule_fee_proportional": "{name}按菜价比例分",
        "rule_fee_equal": "{name}按人头平分",
        "rule_coupon_shapley": "「{name}」按 Shapley 值分",
        "rule_coupon_proportional": "「{name}」按菜价比例分",
        "rule_coupon_equal": "「{name}」按人头平分",
        "cap_people": "每人汇总",
        "h_person": "人",
        "h_owed": "应付",
        "h_paid": "已垫付",
        "h_balance": "差额",
        "cap_transfers": "转账：最少 {n} 笔",
        "cap_transfers_greedy": "转账：{n} 笔（贪心法，不保证最少）",
        "h_from": "付款人",
        "h_to": "收款人",
        "h_amount": "金额",
        "even": "所有人都已结清，不需要转账。",
        "balance_hint": "差额为正表示别人要还给他，为负表示他要还给别人。",
        "counts": (
            "转账笔数对比：每笔账各自还给垫付人 {separate} 笔；两人之间先互相抵消 {pairwise} 笔；"
            "「最大欠款人还最大债主」的贪心 {greedy} 笔；最少 {fewest} 笔。"
        ),
        "cap_expense": "第 {i} 笔账：{id}{what}（合计 {total}，{payers} 垫付）",
        "cap_shares": "{id} 分摊明细",
        "h_item": "项目",
        "h_shared": "分摊给",
        "part_items": "项目合计",
        "part_dishes": "菜品",
        "part_packaging": "打包费",
        "everyone": "所有人",
        "leftover": "零头：{id} 里各多出的 1 分给了{names}；余数相同时按账目编号轮换。",
        "tier_explain": (
            "「{name}」按 Shapley 值分：每人分到的优惠，是 TA 在所有凑单顺序里让菜品合计跨过门槛的平均"
            "贡献。"
        ),
        "cap_order": "每人明细",
        "cap_order_paid": "转账（{payer} 垫付）",
        "h_alone": "单点价",
        "h_pay": "应付",
        "trap_ok": "凑单陷阱检查：通过，没有人比自己单点付得更多。",
        "trap_fail": (
            "凑单陷阱检查：没有通过。下面几位在拼单里付的比自己单点还多：{list}。拆开下单更划算。"
        ),
        "trap_person": "{name}（拼单 {pay}，单点 {alone}）",
        "order_total": "整单：{parts}，实付 {total}。",
        "cap_audit_aa": "审计：现在的分法（平均分）与按明细应付的对比",
        "cap_audit_proportional": "审计：现在的分法（按菜价比例）与按规则应付的对比",
        "cap_audit_custom": "审计：现在的分法与按{target}应付的对比",
        "target_items": "明细",
        "target_rule": "规则",
        "h_current": "现在付",
        "h_discount_now": "现在的优惠",
        "h_discount_rule": "按规则的优惠",
        "h_target_items": "按明细应付",
        "h_target_rule": "按规则应付",
        "h_diff": "差额",
        "h_verdict": "结论",
        "more": "多掏 {amount}",
        "less": "少掏 {amount}",
        "same": "一致",
        "audit_summary": (
            "按现在的分法，多掏的人合计多掏 {amount}，别人合计少掏同样多的钱。审计只做比较，要不要"
            "改由大家决定。"
        ),
        "audit_none": "按现在的分法，每个人付的和按{target}应付的一致。",
        "audit_alone": "按现在的分法，{list} 付的比自己单点还多。",
        "dm_hello": "{name}，这是你的账。",
        "dm_totals": "合计应付 {owed}，已垫付 {paid}，差额 {balance}。",
        "dm_expense": "- {id}{what}：应付 {owed}{parts}",
        "dm_parts": "（{parts}）",
        "dm_paid_only": "，没有分摊，只垫付了 {paid}",
        "dm_paid_also": "，另垫付 {paid}",
        "dm_pay": "你转给 {to}：{amount}",
        "dm_receive": "{from_} 转给你：{amount}",
        "dm_even": "你已经结清，不需要转账。",
        "dm_uninvolved": "你没有分摊也没有垫付任何一笔账。",
        "dm_audit_more": "按现在的分法你付 {current}，按{target}应付 {target_amount}，你多掏 {amount}。",
        "dm_audit_less": "按现在的分法你付 {current}，按{target}应付 {target_amount}，你少掏 {amount}。",
        "dm_audit_same": "按现在的分法你付 {current}，按{target}应付 {target_amount}，两者一致。",
        "dm_order": "你的应付：{parts}，合计 {pay}。",
        "dm_order_alone": "你自己单点要付 {alone}。",
        "dm_order_trap": "提醒：拼单里你付的比单点还多，拆开下单对你更划算。",
        "dm_order_payer": "你垫付了整单 {paid}。",
        "g_expenses": "共 {n} 笔账，合计 {total}。",
        "g_owed": "应付：{list}。",
        "g_paid": "垫付：{list}。",
        "g_transfers": "转账（最少 {n} 笔）：",
        "g_transfers_greedy": "转账（{n} 笔，贪心法）：",
        "g_transfer": "- {from_} → {to} {amount}",
        "g_even": "所有人都已结清，不需要转账。",
        "g_audit": "和现在的分法（{label}）相比：{list}。",
        "g_audit_label_aa": "平均分",
        "g_audit_label_proportional": "按菜价比例",
        "g_audit_label_custom": "现有分法",
        "g_order_total": "整单：{parts}，实付 {total}。",
        "g_order_pay": "每人应付：{list}。",
        "g_order_alone": "各自单点：{list}。",
        "g_order_trap_ok": "凑单陷阱检查：通过。",
        "g_order_trap_fail": "凑单陷阱检查：未通过，{list} 拼单比单点付得更多。",
        "g_diff_more": "{name}多掏 {amount}",
        "g_diff_less": "{name}少掏 {amount}",
        "g_diff_same": "{name}一致",
        "not_modeled_expenses": (
            "多币种和汇率：所有金额按同一种货币算。|"
            "转账总金额最少：只保证转账笔数最少，不保证搬动的钱最少。|"
            "税费、小费等当地规则：按填写的金额和分法计算，不另做判断。|"
            "每个人是否同意这套分法：规则要事先定好，结果出来后不再改。"
        ),
        "not_modeled_order": (
            "App 自己的优惠叠加和取整规则：只按填写的门槛、减额和分法计算。|"
            "满减门槛只看菜品合计，不含打包费和配送费。|"
            "红包等固定金额的优惠算这一单独有，单点价不扣它。|"
            "Shapley 值只是一种分法，有人可能不同意：规则要事先定好，结果出来后不再改。|"
            "多币种和转账总金额最少。"
        ),
        "note_zero_item": "提示：{expense} 里的「{item}」是 0 元，对结果没有影响。",
        "note_zero_extra": "提示：{expense} 里的「{name}」是 0 元，对结果没有影响。",
        "note_payer_not_sharing": "提示：{person} 垫付了 {expense}，但没有分摊其中任何一项，是替别人付。",
        "note_negative_share": "提示：{expense} 里 {person} 的应付是 {amount}（负数），因为优惠超过了 TA 的消费。",
        "note_greedy_fallback": (
            "提示：有 {count} 人的余额不为零，超过 {limit} 人，不再精确求最少笔数，转账由贪心法给出，"
            "不保证最少。"
        ),
        "note_greedy_chosen": "提示：按事先定的规则用贪心法转账，不保证笔数最少。",
        "note_zero_order_item": "提示：{person} 的「{item}」是 0 元，对结果没有影响。",
        "note_tier_not_reached": (
            "提示：「{coupon}」没有达到第一档门槛 {threshold}（菜品合计 {subtotal}），所以没有优惠。"
        ),
        "note_negative_payer": (
            "提示：按 Shapley 值，{person} 分到的优惠超过了自己点的金额，实付是 {amount}（负数），"
            "也就是说 TA 是收钱的一方。如果大家不接受，要在下单前把满减改成按菜价比例分。"
        ),
        "note_payer_outside": "提示：垫付的 {person} 没有点菜，只收钱。",
    },
    "en": {
        "title_expenses": "Bill split",
        "title_order": "Group order",
        "rules_expenses": (
            "Rules: each item is shared the way it says; fees and discounts are shared the way each "
            "expense says; leftover cents go by largest remainder and ties rotate with the bill id; "
            "{settle}."
        ),
        "rules_order": (
            "Rules: packaging follows the dish{extras}; leftover cents go by largest remainder "
            "and ties rotate with the bill id; {settle}."
        ),
        "settle_min": "transfers are the fewest possible (exact when at most 16 people have a balance)",
        "settle_greedy": "transfers use the greedy rule and may not be the fewest",
        "rule_fee_proportional": "{name} in proportion to dish prices",
        "rule_fee_equal": "{name} equally per person",
        "rule_coupon_shapley": "'{name}' by Shapley value",
        "rule_coupon_proportional": "'{name}' in proportion to dish prices",
        "rule_coupon_equal": "'{name}' equally per person",
        "cap_people": "Per person",
        "h_person": "Person",
        "h_owed": "Owes",
        "h_paid": "Paid",
        "h_balance": "Balance",
        "cap_transfers": "Transfers: the fewest possible, {n}",
        "cap_transfers_greedy": "Transfers: {n} (greedy, not guaranteed to be the fewest)",
        "h_from": "From",
        "h_to": "To",
        "h_amount": "Amount",
        "even": "Everyone is even, no transfers needed.",
        "balance_hint": "A positive balance means others owe that person; a negative one means they owe others.",
        "counts": (
            "Transfer counts: paying each expense's payer back separately {separate}; netting "
            "pairs of people {pairwise}; the greedy rule 'largest debtor pays largest creditor' "
            "{greedy}; the fewest {fewest}."
        ),
        "cap_expense": "Expense {i}: {id}{what} (total {total}, paid by {payers})",
        "cap_shares": "{id} shares",
        "h_item": "Item",
        "h_shared": "Shared by",
        "part_items": "Items",
        "part_dishes": "Dishes",
        "part_packaging": "Packaging",
        "everyone": "everyone",
        "leftover": "Leftover: in {id} one cent each went to {names}; equal remainders rotate with the bill id.",
        "tier_explain": (
            "'{name}' is shared by Shapley value: each person's share is their average marginal "
            "contribution to lifting the dish subtotal over the threshold, over all orders in "
            "which the group could have been put together."
        ),
        "cap_order": "Per person",
        "cap_order_paid": "Transfers ({payer} paid)",
        "h_alone": "Alone",
        "h_pay": "Pays",
        "trap_ok": "Trap check: passed, nobody pays more than ordering alone.",
        "trap_fail": (
            "Trap check: FAILED. These people pay more in the group order than ordering alone: "
            "{list}. Ordering separately is cheaper."
        ),
        "trap_person": "{name} (group {pay}, alone {alone})",
        "order_total": "Whole order: {parts}, to pay {total}.",
        "cap_audit_aa": "Audit: the current split (equal shares) against the itemised split",
        "cap_audit_proportional": "Audit: the current split (by dish price) against the rule",
        "cap_audit_custom": "Audit: the current split against the {target}",
        "target_items": "itemised split",
        "target_rule": "rule",
        "h_current": "Pays now",
        "h_discount_now": "Discount now",
        "h_discount_rule": "Discount by the rule",
        "h_target_items": "Itemised",
        "h_target_rule": "By the rule",
        "h_diff": "Difference",
        "h_verdict": "Verdict",
        "more": "pays {amount} more",
        "less": "pays {amount} less",
        "same": "same",
        "audit_summary": (
            "Under the current split the people who pay too much pay {amount} more in total, and "
            "the others pay that much less. The audit only compares; the group decides whether "
            "to change."
        ),
        "audit_none": "Under the current split everyone pays what the {target} gives.",
        "audit_alone": "Under the current split {list} pay more than ordering alone.",
        "dm_hello": "{name}, here is your account.",
        "dm_totals": "You owe {owed} in total, you paid {paid}, balance {balance}.",
        "dm_expense": "- {id}{what}: you owe {owed}{parts}",
        "dm_parts": " ({parts})",
        "dm_paid_only": ", you share nothing and paid {paid}",
        "dm_paid_also": ", and you paid {paid}",
        "dm_pay": "You pay {to}: {amount}",
        "dm_receive": "{from_} pays you: {amount}",
        "dm_even": "You are even, no transfer needed.",
        "dm_uninvolved": "You share none of the expenses and paid none of them.",
        "dm_audit_more": (
            "Under the current split you pay {current}, but the {target} gives {target_amount}. "
            "You pay {amount} more than that."
        ),
        "dm_audit_less": (
            "Under the current split you pay {current}, but the {target} gives {target_amount}. "
            "You pay {amount} less than that."
        ),
        "dm_audit_same": (
            "Under the current split you pay {current}, and the {target} gives {target_amount}. "
            "That is the same."
        ),
        "dm_order": "You owe: {parts}, total {pay}.",
        "dm_order_alone": "Ordering alone you would pay {alone}.",
        "dm_order_trap": "Heads up: you pay more here than ordering alone, so ordering separately is cheaper for you.",
        "dm_order_payer": "You paid the whole order, {paid}.",
        "g_expenses": "Expenses: {n}. Total: {total}.",
        "g_owed": "Owes: {list}.",
        "g_paid": "Paid: {list}.",
        "g_transfers": "Transfers (the fewest possible, {n}):",
        "g_transfers_greedy": "Transfers ({n}, greedy):",
        "g_transfer": "- {from_} -> {to} {amount}",
        "g_even": "Everyone is even, no transfers needed.",
        "g_audit": "Compared with the current split ({label}): {list}.",
        "g_audit_label_aa": "equal shares",
        "g_audit_label_proportional": "by dish price",
        "g_audit_label_custom": "as it is now",
        "g_order_total": "Whole order: {parts}, to pay {total}.",
        "g_order_pay": "Each pays: {list}.",
        "g_order_alone": "Ordering alone: {list}.",
        "g_order_trap_ok": "Trap check: passed.",
        "g_order_trap_fail": "Trap check: failed, {list} pay more here than ordering alone.",
        "g_diff_more": "{name} pays {amount} more",
        "g_diff_less": "{name} pays {amount} less",
        "g_diff_same": "{name} same",
        "not_modeled_expenses": (
            "Several currencies and exchange rates: all amounts are in one currency.|"
            "The smallest total amount moved: only the number of transfers is minimized.|"
            "Local tax or tipping rules: the amounts and rules you entered are used as they are.|"
            "Whether everyone agrees with the rules: agree on them first and do not change them "
            "after seeing the result."
        ),
        "not_modeled_order": (
            "The app's own rules for stacking and rounding coupons: only the thresholds, "
            "reductions and split rules you entered are used.|"
            "Coupon thresholds look at the dish subtotal only, not at packaging or delivery.|"
            "A flat coupon such as a red packet belongs to this order only; the alone price does "
            "not subtract it.|"
            "The Shapley value is one way to share a coupon and some people may disagree: agree "
            "on the rule first and do not change it after seeing the result.|"
            "Several currencies and the smallest total amount moved."
        ),
        "note_zero_item": "Note: item '{item}' in {expense} is 0.00 and changes nothing.",
        "note_zero_extra": "Note: '{name}' in {expense} is 0.00 and changes nothing.",
        "note_payer_not_sharing": (
            "Note: {person} paid {expense} but shares none of its items, so they paid for others."
        ),
        "note_negative_share": (
            "Note: {person}'s share of {expense} is {amount} (negative) because the discount is "
            "larger than what they consumed."
        ),
        "note_greedy_fallback": (
            "Note: {count} people have a non-zero balance, more than {limit}, so the fewest "
            "number of transfers is not searched exactly. The list comes from the greedy rule "
            "and may not be the fewest."
        ),
        "note_greedy_chosen": (
            "Note: the agreed rule is the greedy one, so the number of transfers may not be the "
            "fewest."
        ),
        "note_zero_order_item": "Note: {person}'s '{item}' is 0.00 and changes nothing.",
        "note_tier_not_reached": (
            "Note: '{coupon}' did not reach its first threshold {threshold} (dish subtotal "
            "{subtotal}), so it gives no discount."
        ),
        "note_negative_payer": (
            "Note: by Shapley value {person}'s share of the discount is larger than their order, "
            "so they pay {amount} (negative) and receive money. If the group does not accept "
            "that, change the coupon rule to proportional before ordering."
        ),
        "note_payer_outside": "Note: {person} paid but ordered nothing, and only gets money back.",
    },
}


def say(lang: str, key: str, **values: Any) -> str:
    """Fill the text template of this key (see fsq_core.fill_text for the Latin-name spacing)."""
    return fc.fill_text(lang, TEXT[lang][key], **values)


def _names(items: Sequence[str], lang: str) -> str:
    return ("、" if lang == "zh" else ", ").join(items)


def _list(items: Sequence[str], lang: str) -> str:
    return ("，" if lang == "zh" else ", ").join(items)


# ---------------------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------------------


def _path(base: str, key: str) -> str:
    return f"{base}.{key}" if base else key


def _need(obj: dict[str, Any], key: str, base: str) -> Any:
    if key not in obj:
        raise fc.InputError(_path(base, key), "is required")
    return obj[key]


def _amount_text(value: Fraction) -> str:
    return fc.fmt_cents(fc.to_cents(value))


def _ratio_text(value: Fraction) -> str:
    """Exact text of a weight: 2, 0.5 or 1/3."""
    if value.denominator == 1:
        return str(value.numerator)
    rest = value.denominator
    for prime in (2, 5):
        while rest % prime == 0:
            rest //= prime
    if rest != 1:
        return f"{value.numerator}/{value.denominator}"
    places = 1
    while (value * 10**places).denominator != 1:
        places += 1
    digits = str(abs(value.numerator) * 10**places // value.denominator).rjust(places + 1, "0")
    return ("-" if value < 0 else "") + digits[:-places] + "." + digits[-places:]


def _signed(cents: int) -> str:
    text = fc.fmt_cents(abs(cents))
    return ("+" if cents > 0 else "-" if cents < 0 else "") + text


def _cents_dict(values: Mapping[str, int]) -> dict[str, fc.Cents]:
    return {name: fc.Cents(value) for name, value in values.items()}


def _encodable_text(value: Any, base: str, allow_empty: bool = False) -> str:
    """An id, a name or a description: text, and text that can be written out as UTF-8."""
    return fc.encodable(fc.require_text(value, base, allow_empty=allow_empty), base)


def _person_name(value: Any, base: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise fc.InputError(base, "must be a non-empty name without leading or trailing spaces")
    return fc.encodable(value, base)


def _weight(value: Any, base: str) -> Fraction:
    if isinstance(value, float) and math.isfinite(value):
        value = Fraction(repr(value))
    if isinstance(value, bool) or not isinstance(value, (int, Fraction)):
        raise fc.InputError(base, "must be a number")
    weight = Fraction(value)
    if weight <= 0:
        raise fc.InputError(
            base, "must be greater than zero (leave the person out of the item instead)"
        )
    if weight > MAX_WEIGHT:
        raise fc.InputError(base, "is too large")
    return weight


# ---------------------------------------------------------------------------------------
# Parsed input
# ---------------------------------------------------------------------------------------


@dataclass
class ItemSpec:
    """One item of an expense with the exact amount each sharer owes."""

    name: str
    amount: Fraction
    how: str  # "equal", "weights" or "exact"
    sharers: list[str]
    weights: dict[str, Fraction]
    shares: dict[str, Fraction]


@dataclass
class ExtraSpec:
    """A fee (adds to the bill) or a discount (takes off) with its split rule."""

    kind: str  # "fee" or "discount"
    name: str
    amount: Fraction
    split: str
    exact: dict[str, Fraction]


@dataclass
class ExpenseSpec:
    id: str
    what: str
    paid_by: dict[str, Fraction]
    items: list[ItemSpec]
    fees: list[ExtraSpec]
    discounts: list[ExtraSpec]
    notes: list[Note]


@dataclass
class Ledger:
    people: list[str]
    expenses: list[ExpenseSpec]
    settle: str
    audit_current: Any  # None, "aa" or {name: Fraction}


@dataclass
class OrderItem:
    who: str
    name: str
    amount: Fraction
    packaging: Fraction


@dataclass
class OrderFee:
    name: str
    amount: Fraction
    split: str


@dataclass
class OrderCoupon:
    name: str
    tiers: list[tuple[int, int]]  # (threshold, reduction) in cents; empty for a flat coupon
    amount: Fraction  # flat amount; unused for a tiered coupon
    split: str


@dataclass
class OrderSpec:
    id: str
    items: list[OrderItem]
    fees: list[OrderFee]
    coupons: list[OrderCoupon]
    paid_by: dict[str, Fraction] | None
    people: list[str]  # the people who ordered, in order of first appearance
    settle: str
    audit_current: Any  # None, "proportional", "aa" or {name: Fraction}
    notes: list[Note]


# ---------------------------------------------------------------------------------------
# Parsing: expenses
# ---------------------------------------------------------------------------------------


def _split_map(
    raw: Any, base: str, people_set: Sequence[str] | set[str], expected: Fraction, what: str
) -> dict[str, Fraction]:
    """A person-to-amount object that must add up to `expected`."""
    obj = fc.require_object(raw, base)
    if not obj:
        raise fc.InputError(base, "must name at least one person")
    out: dict[str, Fraction] = {}
    for person, value in obj.items():
        where = _path(base, person)
        if person not in people_set:
            raise fc.InputError(where, f"{person!r} is not in people")
        out[person] = fc.money(value, where)
    total = sum(out.values(), Fraction(0))
    if total != expected:
        raise fc.InputError(
            base,
            f"adds up to {_amount_text(total)}, but the {what} amount is {_amount_text(expected)}",
        )
    return out


def _parse_item(raw: Any, base: str, people: list[str], people_set: set[str]) -> ItemSpec:
    obj = fc.require_object(raw, base)
    fc.check_fields(obj, ("name", "amount", "everyone", "among", "weights", "exact"), base)
    name = _encodable_text(_need(obj, "name", base), _path(base, "name"))
    amount = fc.money(_need(obj, "amount", base), _path(base, "amount"))
    if "exact" in obj:
        for other in ("everyone", "among", "weights"):
            if other in obj:
                raise fc.InputError(
                    _path(base, other),
                    'cannot be combined with "exact": exact amounts already say who pays what',
                )
        shares = _split_map(obj["exact"], _path(base, "exact"), people_set, amount, "item")
        return ItemSpec(name, amount, "exact", list(shares), {}, shares)
    if "everyone" in obj and not isinstance(obj["everyone"], bool):
        raise fc.InputError(_path(base, "everyone"), "must be true or false")
    if obj.get("everyone") is True:
        if "among" in obj:
            raise fc.InputError(
                _path(base, "among"), 'give either "everyone": true or "among", not both'
            )
        sharers = list(people)
    elif "among" in obj:
        where = _path(base, "among")
        if isinstance(obj["among"], str):
            raise fc.InputError(
                where, 'must be a list of names; to share with all people use "everyone": true'
            )
        sharers = fc.require_names(obj["among"], where)
        for index, person in enumerate(sharers):
            if person not in people_set:
                raise fc.InputError(f"{where}[{index}]", f"{person!r} is not in people")
    else:
        raise fc.InputError(base, 'needs "everyone": true, an "among" list, or "exact" amounts')
    weights = {person: Fraction(1) for person in sharers}
    if "weights" in obj:
        where = _path(base, "weights")
        for person, value in fc.require_object(obj["weights"], where).items():
            if person not in weights:
                raise fc.InputError(_path(where, person), f"{person!r} does not share this item")
            weights[person] = _weight(value, _path(where, person))
    weight_sum = sum(weights.values(), Fraction(0))
    shares = {person: amount * weights[person] / weight_sum for person in sharers}
    how = "weights" if "weights" in obj else "equal"
    return ItemSpec(name, amount, how, sharers, weights, shares)


def _parse_extra(raw: Any, base: str, kind: str, people_set: set[str]) -> ExtraSpec:
    obj = fc.require_object(raw, base)
    fc.check_fields(obj, ("name", "amount", "split", "exact"), base)
    name = _encodable_text(_need(obj, "name", base), _path(base, "name"))
    amount = fc.money(_need(obj, "amount", base), _path(base, "amount"))
    split = fc.require_choice(
        obj.get("split", "by_consumption"), _path(base, "split"), EXPENSE_SPLITS
    )
    exact: dict[str, Fraction] = {}
    if split == "exact":
        exact = _split_map(
            _need(obj, "exact", base), _path(base, "exact"), people_set, amount, kind
        )
    elif "exact" in obj:
        raise fc.InputError(_path(base, "exact"), 'is only used with "split": "exact"')
    return ExtraSpec(kind, name, amount, split, exact)


def _parse_paid_by(raw: Any, base: str, people_set: set[str]) -> dict[str, Fraction]:
    obj = fc.require_object(raw, base)
    if not obj:
        raise fc.InputError(base, "must name at least one payer")
    paid: dict[str, Fraction] = {}
    for person, value in obj.items():
        where = _path(base, person)
        if person not in people_set:
            raise fc.InputError(where, f"{person!r} is not in people")
        paid[person] = fc.money(value, where, allow_zero=False)
    return paid


def _parse_expense(raw: Any, index: int, people: list[str], people_set: set[str]) -> ExpenseSpec:
    base = f"expenses[{index}]"
    obj = fc.require_object(raw, base)
    fc.check_fields(obj, ("id", "what", "paid_by", "items", "fees", "discounts"), base)
    ident = _encodable_text(obj.get("id", f"expense-{index + 1}"), _path(base, "id"))
    what = (
        _encodable_text(obj["what"], _path(base, "what"), allow_empty=True) if "what" in obj else ""
    )
    paid = _parse_paid_by(_need(obj, "paid_by", base), _path(base, "paid_by"), people_set)
    raw_items = fc.require_list(
        _need(obj, "items", base), _path(base, "items"), min_len=1, max_len=MAX_ROWS
    )
    items = [
        _parse_item(item, f"{base}.items[{j}]", people, people_set)
        for j, item in enumerate(raw_items)
    ]
    extras: dict[str, list[ExtraSpec]] = {}
    for key, kind in (("fees", "fee"), ("discounts", "discount")):
        raw_list = fc.require_list(obj.get(key, []), _path(base, key), max_len=MAX_EXTRAS)
        extras[key] = [
            _parse_extra(extra, f"{base}.{key}[{j}]", kind, people_set)
            for j, extra in enumerate(raw_list)
        ]
    fees, discounts = extras["fees"], extras["discounts"]
    consumption = sum((item.amount for item in items), Fraction(0))
    for key, group in (("fees", fees), ("discounts", discounts)):
        for j, extra in enumerate(group):
            if extra.split == "by_consumption" and consumption == 0 and extra.amount != 0:
                raise fc.InputError(
                    f"{base}.{key}[{j}].split",
                    'by_consumption needs at least one item above zero; use "equal" or "exact"',
                )
    bill = (
        consumption
        + sum((fee.amount for fee in fees), Fraction(0))
        - sum((discount.amount for discount in discounts), Fraction(0))
    )
    if bill < 0:
        raise fc.InputError(
            _path(base, "discounts"), "take off more than the items and fees come to"
        )
    paid_total = sum(paid.values(), Fraction(0))
    if paid_total != bill:
        raise fc.InputError(
            _path(base, "paid_by"),
            f"adds up to {_amount_text(paid_total)}, but items + fees - discounts come to "
            f"{_amount_text(bill)}",
        )
    notes: list[Note] = []
    for item in items:
        if item.amount == 0:
            notes.append(("zero_item", {"expense": ident, "item": item.name}))
    for extra in fees + discounts:
        if extra.amount == 0:
            notes.append(("zero_extra", {"expense": ident, "name": extra.name}))
    sharers = {person for item in items for person in item.sharers}
    for payer in paid:
        if payer not in sharers:
            notes.append(("payer_not_sharing", {"expense": ident, "person": payer}))
    return ExpenseSpec(ident, what, paid, items, fees, discounts, notes)


def _parse_rules(raw: Any) -> str:
    if raw is None:
        return SETTLE_RULES[0]
    obj = fc.require_object(raw, "rules")
    fc.check_fields(obj, ("settle",), "rules")
    return fc.require_choice(obj.get("settle", SETTLE_RULES[0]), "rules.settle", SETTLE_RULES)


def _parse_audit(raw: Any, people_set: set[str], choices: Sequence[str], total: Fraction) -> Any:
    """The audit block: a named baseline, or each person's current amount."""
    if raw is None:
        return None
    obj = fc.require_object(raw, "audit")
    fc.check_fields(obj, ("current",), "audit")
    if "current" not in obj:
        return None
    current = obj["current"]
    if isinstance(current, str):
        chosen = fc.require_choice(current, "audit.current", choices)
        return "aa" if chosen == "equal" else chosen
    if not isinstance(current, dict):
        raise fc.InputError(
            "audit.current",
            "must be "
            + " or ".join(f'"{choice}"' for choice in choices)
            + ", or an object giving what each person pays now",
        )
    return _split_map(current, "audit.current", people_set, total, "total spent")


def parse_ledger(data: dict[str, Any]) -> Ledger:
    """Validate an expenses input; every error names the field."""
    fc.check_fields(data, LEDGER_FIELDS, "")
    people = fc.require_encodable_names(
        _need(data, "people", ""), "people", min_len=2, max_len=MAX_PEOPLE
    )
    people_set = set(people)
    raw_expenses = fc.require_list(
        _need(data, "expenses", ""), "expenses", min_len=1, max_len=MAX_EXPENSES
    )
    expenses = [
        _parse_expense(raw, index, people, people_set) for index, raw in enumerate(raw_expenses)
    ]
    seen: set[str] = set()
    for index, expense in enumerate(expenses):
        if expense.id in seen:
            raise fc.InputError(f"expenses[{index}].id", f"duplicate id {expense.id!r}")
        seen.add(expense.id)
    total = sum((sum(e.paid_by.values(), Fraction(0)) for e in expenses), Fraction(0))
    audit = _parse_audit(data.get("audit"), people_set, EXPENSE_AUDITS, total)
    return Ledger(people, expenses, _parse_rules(data.get("rules")), audit)


# ---------------------------------------------------------------------------------------
# Parsing: group orders
# ---------------------------------------------------------------------------------------


def _parse_tiers(raw: Any, base: str) -> list[tuple[int, int]]:
    tiers = fc.require_list(raw, base, min_len=1, max_len=MAX_TIERS)
    out: list[tuple[int, int]] = []
    for index, pair in enumerate(tiers):
        where = f"{base}[{index}]"
        pair = fc.require_list(pair, where, min_len=2, max_len=2)
        threshold = fc.money(pair[0], f"{where}[0]", allow_zero=False)
        reduction = fc.money(pair[1], f"{where}[1]", allow_zero=False)
        if reduction > threshold:
            raise fc.InputError(f"{where}[1]", "the reduction cannot be more than the threshold")
        out.append((fc.to_cents(threshold), fc.to_cents(reduction)))
    return out


def tier_reduction_function(tiers: Sequence[tuple[int, int]]):
    """Return f(total_cents): the largest reduction whose threshold the total reaches, else 0."""
    ordered = sorted(tiers)
    thresholds = [threshold for threshold, _ in ordered]
    best: list[int] = []
    running = 0
    for _, reduction in ordered:
        running = max(running, reduction)
        best.append(running)

    def reduction_at(total_cents: int) -> int:
        reached = bisect_right(thresholds, total_cents)
        return best[reached - 1] if reached else 0

    return reduction_at


def _parse_order_item(raw: Any, base: str) -> OrderItem:
    obj = fc.require_object(raw, base)
    fc.check_fields(obj, ("who", "name", "amount", "packaging"), base)
    who = _person_name(_need(obj, "who", base), _path(base, "who"))
    name = _encodable_text(_need(obj, "name", base), _path(base, "name"))
    amount = fc.money(_need(obj, "amount", base), _path(base, "amount"))
    packaging = fc.money(obj.get("packaging", 0), _path(base, "packaging"))
    return OrderItem(who, name, amount, packaging)


def _parse_order_fee(raw: Any, base: str) -> OrderFee:
    obj = fc.require_object(raw, base)
    fc.check_fields(obj, ("name", "amount", "split"), base)
    name = _encodable_text(_need(obj, "name", base), _path(base, "name"))
    amount = fc.money(_need(obj, "amount", base), _path(base, "amount"))
    split = fc.require_choice(
        obj.get("split", "proportional"), _path(base, "split"), ORDER_FEE_SPLITS
    )
    return OrderFee(name, amount, "proportional" if split == "by_consumption" else split)


def _parse_order_coupon(raw: Any, base: str) -> OrderCoupon:
    obj = fc.require_object(raw, base)
    fc.check_fields(obj, ("name", "tiers", "amount", "split"), base)
    name = _encodable_text(_need(obj, "name", base), _path(base, "name"))
    if ("tiers" in obj) == ("amount" in obj):
        raise fc.InputError(
            base, 'needs either "tiers" (full-reduction thresholds) or "amount" (a flat coupon)'
        )
    if "tiers" in obj:
        tiers = _parse_tiers(obj["tiers"], _path(base, "tiers"))
        split = fc.require_choice(obj.get("split", "shapley"), _path(base, "split"), TIER_SPLITS)
        return OrderCoupon(name, tiers, Fraction(0), split)
    amount = fc.money(obj["amount"], _path(base, "amount"))
    split = fc.require_choice(
        obj.get("split", "proportional"), _path(base, "split"), FLAT_COUPON_SPLITS
    )
    return OrderCoupon(name, [], amount, "proportional" if split == "by_consumption" else split)


def _order_bill(
    items: list[OrderItem], fees: list[OrderFee], coupons: list[OrderCoupon]
) -> tuple[Fraction, Fraction]:
    """Return (dish subtotal, amount to pay) of an order, in currency units."""
    subtotal = sum((item.amount for item in items), Fraction(0))
    reduction = Fraction(0)
    for coupon in coupons:
        if coupon.tiers:
            reduction += Fraction(tier_reduction_function(coupon.tiers)(fc.to_cents(subtotal)), 100)
        else:
            reduction += coupon.amount
    total = (
        subtotal
        + sum((item.packaging for item in items), Fraction(0))
        + sum((fee.amount for fee in fees), Fraction(0))
        - reduction
    )
    return subtotal, total


def parse_order(data: dict[str, Any]) -> OrderSpec:
    """Validate a group_order input; every error names the field."""
    fc.check_fields(data, ORDER_FIELDS, "")
    ident = _encodable_text(data.get("id", "group-order"), "id")
    raw_items = fc.require_list(_need(data, "items", ""), "items", min_len=1, max_len=MAX_ROWS)
    items = [_parse_order_item(raw, f"items[{j}]") for j, raw in enumerate(raw_items)]
    fees = [
        _parse_order_fee(raw, f"fees[{j}]")
        for j, raw in enumerate(fc.require_list(data.get("fees", []), "fees", max_len=MAX_EXTRAS))
    ]
    coupons = [
        _parse_order_coupon(raw, f"coupons[{j}]")
        for j, raw in enumerate(
            fc.require_list(data.get("coupons", []), "coupons", max_len=MAX_EXTRAS)
        )
    ]
    buyers: list[str] = []
    for item in items:
        if item.who not in buyers:
            buyers.append(item.who)
    if len(buyers) > MAX_PEOPLE:
        raise fc.InputError("items", f"at most {MAX_PEOPLE} people can share one order")
    subtotal, total = _order_bill(items, fees, coupons)
    for j, fee in enumerate(fees):
        if fee.split == "proportional" and subtotal == 0 and fee.amount != 0:
            raise fc.InputError(
                f"fees[{j}].split",
                'all dishes are 0.00, so there is nothing to be proportional to; use "equal"',
            )
    for j, coupon in enumerate(coupons):
        where = f"coupons[{j}].split"
        if coupon.tiers and coupon.split == "shapley" and len(buyers) > EXACT_LIMIT:
            raise fc.InputError(
                where,
                f'"shapley" is exact for at most {EXACT_LIMIT} people; use "proportional" for '
                f"{len(buyers)} people",
            )
        if (
            not coupon.tiers
            and coupon.split == "proportional"
            and subtotal == 0
            and coupon.amount != 0
        ):
            raise fc.InputError(
                where, 'all dishes are 0.00, so there is nothing to be proportional to; use "equal"'
            )
    if total < 0:
        raise fc.InputError("coupons", "take off more than the order costs")
    paid_by: dict[str, Fraction] | None = None
    if "paid_by" in data:
        raw_paid = data["paid_by"]
        if isinstance(raw_paid, str):
            if total == 0:
                raise fc.InputError("paid_by", "the order costs nothing, so nobody paid")
            paid_by = {_person_name(raw_paid, "paid_by"): total}
        else:
            obj = fc.require_object(raw_paid, "paid_by")
            if not obj:
                raise fc.InputError("paid_by", "must name at least one payer")
            paid_by = {}
            for person, value in obj.items():
                paid_by[_person_name(person, f"paid_by.{person}")] = fc.money(
                    value, f"paid_by.{person}", allow_zero=False
                )
            paid_total = sum(paid_by.values(), Fraction(0))
            if paid_total != total:
                raise fc.InputError(
                    "paid_by",
                    f"adds up to {_amount_text(paid_total)}, but the order comes to {_amount_text(total)}",
                )
    everyone = set(buyers) | set(paid_by or {})
    audit = _parse_audit(data.get("audit"), everyone, ORDER_AUDITS, total)
    notes: list[Note] = []
    for item in items:
        if item.amount == 0:
            notes.append(("zero_order_item", {"person": item.who, "item": item.name}))
    for payer in paid_by or {}:
        if payer not in buyers:
            notes.append(("payer_outside", {"person": payer}))
    return OrderSpec(
        ident, items, fees, coupons, paid_by, buyers, _parse_rules(data.get("rules")), audit, notes
    )


# ---------------------------------------------------------------------------------------
# Rounding in layers
# ---------------------------------------------------------------------------------------


def round_layers(
    parts: Sequence[tuple[str, str, Mapping[str, Fraction]]], key: str
) -> tuple[dict[str, int], list[dict[str, int]], dict[str, Fraction]]:
    """Round running totals so that the parts add up and the last total is rounded once.

    `parts` are (kind, name, signed exact amount per person) layers in the order they are shown.
    The running total after each layer is rounded to cents by the largest-remainder rule with
    `key` as the tie-break rotation. The result is (final cents per person, the change in cents
    that each layer contributed, the exact final total). The final cents are exactly the single
    rounding of the exact total, so the layers never move a person's total.
    """
    population = sorted({person for _, _, amounts in parts for person in amounts})
    running = {person: Fraction(0) for person in population}
    previous = {person: 0 for person in population}
    deltas: list[dict[str, int]] = []
    for _, _, amounts in parts:
        for person, value in amounts.items():
            running[person] += value
        total = sum(running.values(), Fraction(0)) * 100
        if total.denominator != 1:
            raise ValueError("a layer does not add up to a whole number of cents")
        rounded = fc.round_shares(dict(running), int(total), key)
        deltas.append({person: rounded[person] - previous[person] for person in population})
        previous = rounded
    return previous, deltas, running


def leftover_of(final: Mapping[str, int], exact: Mapping[str, Fraction]) -> list[str]:
    """People whose rounded amount is one cent above the floor of their exact amount."""
    return sorted(person for person in final if final[person] > math.floor(exact[person] * 100))


# ---------------------------------------------------------------------------------------
# Settling up: fewest transfers by subset DP, greedy beyond that
# ---------------------------------------------------------------------------------------


def _zero_sum_order(values: Sequence[int]) -> tuple[list[int], int]:
    """Indices of `values` in an order with as many zero-sum prefixes as possible.

    The values must add up to zero. Returns (order, number of zero-sum prefixes). Cutting the
    order at every zero-sum prefix splits the values into the largest possible number of
    zero-sum groups. Dynamic programming over subsets, O(2^k * k) for k values.
    """
    count = len(values)
    size = 1 << count
    sums = [0] * size
    for mask in range(1, size):
        low = mask & -mask
        sums[mask] = sums[mask ^ low] + values[low.bit_length() - 1]
    best = [0] * size
    for mask in range(1, size):
        top = 0
        rest = mask
        while rest:
            low = rest & -rest
            top = max(top, best[mask ^ low])
            rest ^= low
        best[mask] = top + (1 if sums[mask] == 0 else 0)
    order: list[int] = []
    mask = size - 1
    while mask:
        want = best[mask] - (1 if sums[mask] == 0 else 0)
        rest = mask
        while rest:
            low = rest & -rest
            if best[mask ^ low] == want:
                break
            rest ^= low
        order.append(low.bit_length() - 1)
        mask ^= low
    order.reverse()
    return order, best[size - 1]


def zero_sum_groups(values: Sequence[int]) -> list[list[int]]:
    """Split the indices of `values` (non-zero, adding up to zero) into the most zero-sum groups."""
    if sum(values) != 0:
        raise ValueError("values must add up to zero")
    order, _ = _zero_sum_order(values)
    groups: list[list[int]] = []
    current: list[int] = []
    running = 0
    for index in order:
        current.append(index)
        running += values[index]
        if running == 0:
            groups.append(current)
            current, running = [], 0
    return groups


def greedy_transfers(net: Mapping[str, int]) -> list[Transfer]:
    """Repeatedly let the largest debtor pay the largest creditor (ties by name)."""
    balance = {name: value for name, value in net.items() if value}
    if sum(balance.values()) != 0:
        raise ValueError("balances must add up to zero")
    plan: list[Transfer] = []
    while balance:
        creditor = min((n for n in balance if balance[n] > 0), key=lambda n: (-balance[n], n))
        debtor = min((n for n in balance if balance[n] < 0), key=lambda n: (balance[n], n))
        amount = min(balance[creditor], -balance[debtor])
        plan.append((debtor, creditor, amount))
        for name, change in ((creditor, -amount), (debtor, amount)):
            balance[name] += change
            if balance[name] == 0:
                del balance[name]
    return sorted(plan)


def fewest_transfers(net: Mapping[str, int]) -> list[Transfer]:
    """A settlement with the fewest transfers (exact, at most EXACT_LIMIT non-zero balances).

    The fewest number of transfers is the number of people with a balance minus the largest
    number of groups the balances can be split into so that each group adds up to zero. Each
    group of m people is settled by m - 1 transfers, matching the largest debtor with the
    largest creditor. The result is deterministic and does not depend on the order of `net`.
    """
    names = sorted(name for name, value in net.items() if value)
    if len(names) > EXACT_LIMIT:
        raise ValueError(f"at most {EXACT_LIMIT} people can be searched exactly")
    values = [net[name] for name in names]
    plan: list[Transfer] = []
    for group in zero_sum_groups(values):
        plan.extend(greedy_transfers({names[i]: values[i] for i in group}))
    return sorted(plan)


@dataclass
class Settlement:
    transfers: list[Transfer]
    exact_minimum: bool
    method: str  # "subset_dp" or "greedy"
    balances: int  # people with a non-zero balance


def settle(net: Mapping[str, int], rule: str) -> Settlement:
    """Settle net balances (cents, adding up to zero) by the agreed rule."""
    if sum(net.values()) != 0:
        raise ValueError("balances must add up to zero")
    nonzero = sum(1 for value in net.values() if value)
    if rule == "min_transfers" and nonzero <= EXACT_LIMIT:
        return Settlement(fewest_transfers(net), True, "subset_dp", nonzero)
    return Settlement(greedy_transfers(net), False, "greedy", nonzero)


# ---------------------------------------------------------------------------------------
# Shapley value of a tiered coupon
# ---------------------------------------------------------------------------------------


def shapley_tier_shares(
    dishes: Mapping[str, int], tiers: Sequence[tuple[int, int]]
) -> dict[str, Fraction]:
    """Exact Shapley value (in cents) of the coupon game of a group order.

    The players are the people, `dishes` holds each person's dish total in cents, and the
    worth of a group S of people is the reduction that the tiers give for the dish total of S.
    The shares add up to the reduction of the whole order. Exact for at most EXACT_LIMIT people
    (all 2^n groups are enumerated).
    """
    names = sorted(dishes)
    count = len(names)
    if count > EXACT_LIMIT:
        raise ValueError(f"at most {EXACT_LIMIT} people are supported")
    reduction_at = tier_reduction_function(tiers)
    size = 1 << count
    totals = [0] * size
    worth = [0] * size
    for mask in range(1, size):
        low = mask & -mask
        totals[mask] = totals[mask ^ low] + dishes[names[low.bit_length() - 1]]
        worth[mask] = reduction_at(totals[mask])
    return dict(zip(names, fc.shapley_values(count, worth)))


# ---------------------------------------------------------------------------------------
# Computing: expenses
# ---------------------------------------------------------------------------------------


@dataclass
class ExpenseCalc:
    spec: ExpenseSpec
    total_cents: int
    paid_cents: dict[str, int]
    owed_cents: dict[str, int]  # the people who share the expense
    layers: list[tuple[str, str]]  # (kind, name) of each layer
    layer_cents: list[dict[str, int]]
    leftover_to: list[str]
    notes: list[Note]


@dataclass
class AuditCalc:
    label: str  # "aa", "proportional" or "custom"
    current: dict[str, int]
    target: dict[str, int]
    delta: dict[str, int]  # current minus target: positive means the person pays more now
    over_alone: list[str]  # people who pay more now than ordering alone (group orders)
    current_discount: dict[str, int] | None = None  # coupon share now (proportional baseline)
    target_discount: dict[str, int] | None = None


@dataclass
class LedgerCalc:
    ledger: Ledger
    expenses: list[ExpenseCalc]
    total_cents: int
    owed: dict[str, int]
    paid: dict[str, int]
    net: dict[str, int]
    settlement: Settlement
    counts: dict[str, int | None]
    notes: list[Note]
    audit: AuditCalc | None


def _extra_shares(
    extra: ExtraSpec, consumption: Mapping[str, Fraction], sharers: Sequence[str]
) -> dict[str, Fraction]:
    if extra.split == "exact":
        return dict(extra.exact)
    if extra.amount == 0:
        return {person: Fraction(0) for person in sharers}
    if extra.split == "equal":
        return {person: extra.amount / len(sharers) for person in sharers}
    total = sum(consumption.values(), Fraction(0))
    return {person: extra.amount * consumption[person] / total for person in sharers}


def split_expense(spec: ExpenseSpec) -> ExpenseCalc:
    """Split one expense: exact shares by layer, then the layered cent rounding."""
    consumption: dict[str, Fraction] = {}
    for item in spec.items:
        for person, value in item.shares.items():
            consumption[person] = consumption.get(person, Fraction(0)) + value
    sharers = sorted(consumption)
    layers: list[tuple[str, str, dict[str, Fraction]]] = [("items", "", dict(consumption))]
    for extra in spec.fees:
        layers.append(("fee", extra.name, _extra_shares(extra, consumption, sharers)))
    for extra in spec.discounts:
        shares = _extra_shares(extra, consumption, sharers)
        layers.append(
            ("discount", extra.name, {person: -value for person, value in shares.items()})
        )
    final, deltas, exact = round_layers(layers, spec.id)
    paid = {person: fc.to_cents(value) for person, value in spec.paid_by.items()}
    total = sum(paid.values())
    if sum(final.values()) != total:
        raise AssertionError("shares do not add up to the amount paid")
    notes = list(spec.notes)
    for person in sorted(final):
        if final[person] < 0:
            notes.append(
                (
                    "negative_share",
                    {"expense": spec.id, "person": person, "amount": fc.Cents(final[person])},
                )
            )
    return ExpenseCalc(
        spec,
        total,
        paid,
        final,
        [(kind, name) for kind, name, _ in layers],
        deltas,
        leftover_of(final, exact),
        notes,
    )


def transfer_counts(
    expenses: Sequence[ExpenseCalc], net: Mapping[str, int]
) -> dict[str, int | None]:
    """Transfers needed by four ways of settling, for an honest comparison.

    separate: every person pays every payer back for each expense, merged per pair of people.
    pairwise: the same after netting each pair of people against each other.
    greedy: the largest debtor pays the largest creditor. fewest: exact, or None above the limit.
    """
    debts: dict[tuple[str, str], Fraction] = {}
    for calc in expenses:
        for payer, paid in calc.paid_cents.items():
            for person, owed in calc.owed_cents.items():
                if person == payer or owed == 0:
                    continue
                amount = Fraction(owed * paid, calc.total_cents)
                pair = (person, payer) if amount > 0 else (payer, person)
                debts[pair] = debts.get(pair, Fraction(0)) + abs(amount)
    nets: dict[tuple[str, str], Fraction] = {}
    for (debtor, creditor), amount in debts.items():
        low, high = sorted((debtor, creditor))
        nets[(low, high)] = nets.get((low, high), Fraction(0)) + (
            amount if debtor == low else -amount
        )
    nonzero = sum(1 for value in net.values() if value)
    return {
        "separate": len(debts),
        "pairwise": sum(1 for value in nets.values() if value),
        "greedy": len(greedy_transfers(net)),
        "fewest": len(fewest_transfers(net)) if nonzero <= EXACT_LIMIT else None,
    }


def compute_ledger(ledger: Ledger, audit: bool) -> LedgerCalc:
    """All numbers of an expenses input."""
    calcs = [split_expense(spec) for spec in ledger.expenses]
    owed = {person: 0 for person in ledger.people}
    paid = {person: 0 for person in ledger.people}
    for calc in calcs:
        for person, cents in calc.owed_cents.items():
            owed[person] += cents
        for person, cents in calc.paid_cents.items():
            paid[person] += cents
    net = {person: paid[person] - owed[person] for person in ledger.people}
    settlement = settle(net, ledger.settle)
    notes: list[Note] = [note for calc in calcs for note in calc.notes]
    if ledger.settle == "greedy":
        notes.append(("greedy_chosen", {}))
    elif not settlement.exact_minimum:
        notes.append(("greedy_fallback", {"count": settlement.balances, "limit": EXACT_LIMIT}))
    total = sum(calc.total_cents for calc in calcs)
    audit_calc = None
    if audit:
        current_spec = ledger.audit_current if ledger.audit_current is not None else "aa"
        label, current = _current_split(current_spec, ledger.people, total, "aa")
        delta = {person: current[person] - owed[person] for person in ledger.people}
        audit_calc = AuditCalc(label, current, dict(owed), delta, [])
    return LedgerCalc(
        ledger,
        calcs,
        total,
        owed,
        paid,
        net,
        settlement,
        transfer_counts(calcs, net),
        notes,
        audit_calc,
    )


def _current_split(
    spec: Any, people: Sequence[str], total_cents: int, key: str
) -> tuple[str, dict[str, int]]:
    """Cents each person pays under the split the group uses now ("aa" or explicit amounts)."""
    if spec == "aa":
        each = {person: Fraction(total_cents, 100 * len(people)) for person in people}
        return "aa", fc.round_shares(each, total_cents, key)
    current = {person: 0 for person in people}
    for person, value in spec.items():
        current[person] = fc.to_cents(value)
    return "custom", current


# ---------------------------------------------------------------------------------------
# Computing: group orders
# ---------------------------------------------------------------------------------------


@dataclass
class OrderCalc:
    spec: OrderSpec
    people: list[str]  # the people who ordered
    subtotal_cents: int
    total_cents: int
    layers: list[tuple[str, str]]
    layer_cents: list[dict[str, int]]
    pay: dict[str, int]
    alone: dict[str, int]
    discount: dict[str, int]  # discount each person receives from all coupons, positive
    reductions: dict[str, int]  # cents each coupon takes off the whole order
    shapley: dict[str, dict[str, Fraction]]  # coupon name -> exact share in currency units
    leftover_to: list[str]
    over_alone: list[str]
    negative_payers: list[str]
    paid: dict[str, int]
    net: dict[str, int]
    settlement: Settlement
    notes: list[Note]
    audit: AuditCalc | None


def _order_layers(
    spec: OrderSpec, mode: str
) -> tuple[
    list[tuple[str, str, dict[str, Fraction]]], dict[str, dict[str, Fraction]], dict[str, int]
]:
    """Exact layers of an order. mode "rule" follows the order's own split rules and
    "proportional" shares every fee and coupon in proportion to dish prices."""
    people = spec.people
    dish = {person: Fraction(0) for person in people}
    pack = {person: Fraction(0) for person in people}
    for item in spec.items:
        dish[item.who] += item.amount
        pack[item.who] += item.packaging
    subtotal = sum(dish.values(), Fraction(0))
    layers: list[tuple[str, str, dict[str, Fraction]]] = [("dishes", "", dict(dish))]
    if any(pack.values()):
        layers.append(("packaging", "", dict(pack)))

    def share(amount: Fraction, split: str) -> dict[str, Fraction]:
        if amount == 0:
            return {person: Fraction(0) for person in people}
        if split in ("equal", "shapley") or subtotal == 0:
            return {person: amount / len(people) for person in people}
        return {person: amount * dish[person] / subtotal for person in people}

    for fee in spec.fees:
        layers.append(
            ("fee", fee.name, share(fee.amount, fee.split if mode == "rule" else "proportional"))
        )
    shapley: dict[str, dict[str, Fraction]] = {}
    reductions: dict[str, int] = {}
    cents = {person: fc.to_cents(dish[person]) for person in people}
    for coupon in spec.coupons:
        if coupon.tiers:
            reduction = tier_reduction_function(coupon.tiers)(fc.to_cents(subtotal))
            reductions[coupon.name] = reduction
            if coupon.split == "shapley" and mode == "rule":
                exact = shapley_tier_shares(cents, coupon.tiers)
                shapley[coupon.name] = {person: value / 100 for person, value in exact.items()}
                shares = shapley[coupon.name]
            else:
                shares = share(Fraction(reduction, 100), "proportional")
        else:
            reductions[coupon.name] = fc.to_cents(coupon.amount)
            shares = share(coupon.amount, coupon.split if mode == "rule" else "proportional")
        layers.append(("coupon", coupon.name, {person: -value for person, value in shares.items()}))
    return layers, shapley, reductions


def compute_order(spec: OrderSpec, audit: bool) -> OrderCalc:
    """All numbers of a group order."""
    people = spec.people
    layers, shapley, reductions = _order_layers(spec, "rule")
    final, deltas, exact = round_layers(layers, spec.id)
    dish = {person: Fraction(0) for person in people}
    pack = {person: Fraction(0) for person in people}
    for item in spec.items:
        dish[item.who] += item.amount
        pack[item.who] += item.packaging
    subtotal_cents = fc.to_cents(sum(dish.values(), Fraction(0)))
    total_cents = sum(final.values())
    tier_functions = [
        tier_reduction_function(coupon.tiers) for coupon in spec.coupons if coupon.tiers
    ]
    fee_cents = sum(fc.to_cents(fee.amount) for fee in spec.fees)
    alone = {
        person: fc.to_cents(dish[person])
        + fc.to_cents(pack[person])
        + fee_cents
        - sum(reduction_at(fc.to_cents(dish[person])) for reduction_at in tier_functions)
        for person in people
    }
    discount = {person: 0 for person in people}
    for index, (kind, _name, _amounts) in enumerate(layers):
        if kind == "coupon":
            for person in people:
                discount[person] -= deltas[index][person]
    over_alone = [person for person in people if final[person] > alone[person]]
    negative = [person for person in people if final[person] < 0]
    paid: dict[str, int] = {}
    if spec.paid_by:
        paid = {person: fc.to_cents(value) for person, value in spec.paid_by.items()}
    everyone = list(people) + [person for person in paid if person not in people]
    pay_all = {person: final.get(person, 0) for person in everyone}
    net = {person: paid.get(person, 0) - pay_all[person] for person in everyone}
    settlement = settle(net, spec.settle) if spec.paid_by else Settlement([], True, "subset_dp", 0)
    notes: list[Note] = list(spec.notes)
    for coupon in spec.coupons:
        if coupon.tiers and reductions[coupon.name] == 0:
            first = min(threshold for threshold, _ in coupon.tiers)
            notes.append(
                (
                    "tier_not_reached",
                    {
                        "coupon": coupon.name,
                        "threshold": fc.Cents(first),
                        "subtotal": fc.Cents(subtotal_cents),
                    },
                )
            )
    for person in negative:
        notes.append(("negative_payer", {"person": person, "amount": fc.Cents(final[person])}))
    if spec.paid_by and spec.settle == "greedy":
        notes.append(("greedy_chosen", {}))
    elif spec.paid_by and not settlement.exact_minimum:
        notes.append(("greedy_fallback", {"count": settlement.balances, "limit": EXACT_LIMIT}))
    audit_calc = None
    if audit:
        audit_calc = _audit_order(spec, final, alone, discount, total_cents)
    return OrderCalc(
        spec,
        people,
        subtotal_cents,
        total_cents,
        [(kind, name) for kind, name, _ in layers],
        deltas,
        final,
        alone,
        discount,
        reductions,
        shapley,
        leftover_of(final, exact),
        over_alone,
        negative,
        paid,
        net,
        settlement,
        notes,
        audit_calc,
    )


def _audit_order(
    spec: OrderSpec,
    pay: Mapping[str, int],
    alone: Mapping[str, int],
    discount: Mapping[str, int],
    total_cents: int,
) -> AuditCalc:
    people = spec.people
    current_spec = spec.audit_current if spec.audit_current is not None else "proportional"
    current_discount = None
    if current_spec == "proportional":
        layers, _, _ = _order_layers(spec, "proportional")
        current, deltas, _ = round_layers(layers, spec.id)
        label = "proportional"
        current_discount = {
            person: -sum(
                deltas[index][person]
                for index, (kind, _name, _amounts) in enumerate(layers)
                if kind == "coupon"
            )
            for person in people
        }
    elif current_spec == "aa":
        label, current = _current_split("aa", people, total_cents, spec.id)
    else:
        label, current = _current_split(
            current_spec, sorted(set(people) | set(current_spec)), total_cents, spec.id
        )
    delta = {person: current.get(person, 0) - pay.get(person, 0) for person in current}
    over = [person for person in people if current.get(person, 0) > alone[person]]
    return AuditCalc(label, dict(current), dict(pay), delta, over, current_discount, discount)


# ---------------------------------------------------------------------------------------
# Results: shared pieces
# ---------------------------------------------------------------------------------------


def _note_json(note: Note) -> dict[str, Any]:
    code, params = note
    return {"code": code, **params}


def _note_text(note: Note, lang: str) -> str:
    code, params = note
    values = {
        key: (fc.fmt_cents(int(value)) if isinstance(value, fc.Cents) else value)
        for key, value in params.items()
    }
    return say(lang, "note_" + code, **values)


def _layer_label(kind: str, name: str, lang: str) -> str:
    if kind == "items":
        return say(lang, "part_items")
    if kind == "dishes":
        return say(lang, "part_dishes")
    if kind == "packaging":
        return say(lang, "part_packaging")
    return name


def _verdict(delta: int, lang: str) -> str:
    """Words for current minus target: positive means the person pays more now."""
    if delta > 0:
        return say(lang, "more", amount=fc.fmt_cents(delta))
    if delta < 0:
        return say(lang, "less", amount=fc.fmt_cents(-delta))
    return say(lang, "same")


def _transfer_rows(transfers: Sequence[Transfer]) -> list[list[str]]:
    return [[debtor, creditor, fc.fmt_cents(cents)] for debtor, creditor, cents in transfers]


def _transfers_json(transfers: Sequence[Transfer]) -> list[dict[str, Any]]:
    return [
        {"from": debtor, "to": creditor, "cents": fc.Cents(cents)}
        for debtor, creditor, cents in transfers
    ]


def _transfer_table(settlement: Settlement, lang: str, caption: str | None = None) -> fc.Table:
    count = len(settlement.transfers)
    if caption is None:
        key = "cap_transfers" if settlement.exact_minimum else "cap_transfers_greedy"
        caption = say(lang, key, n=count)
    return fc.Table(
        [say(lang, "h_from"), say(lang, "h_to"), say(lang, "h_amount")],
        _transfer_rows(settlement.transfers),
        caption,
    )


def _transfer_group_lines(settlement: Settlement, lang: str) -> list[str]:
    if not settlement.transfers:
        return [say(lang, "g_even")]
    key = "g_transfers" if settlement.exact_minimum else "g_transfers_greedy"
    lines = [say(lang, key, n=len(settlement.transfers))]
    for debtor, creditor, cents in settlement.transfers:
        lines.append(say(lang, "g_transfer", from_=debtor, to=creditor, amount=fc.fmt_cents(cents)))
    return lines


def _transfer_dm_lines(person: str, settlement: Settlement, lang: str) -> list[str]:
    lines = []
    for debtor, creditor, cents in settlement.transfers:
        if debtor == person:
            lines.append(say(lang, "dm_pay", to=creditor, amount=fc.fmt_cents(cents)))
        elif creditor == person:
            lines.append(say(lang, "dm_receive", from_=debtor, amount=fc.fmt_cents(cents)))
    return lines or [say(lang, "dm_even")]


def _audit_json(audit: AuditCalc) -> dict[str, Any]:
    per_person: dict[str, Any] = {}
    for person in sorted(audit.delta):
        entry: dict[str, Any] = {
            "current_cents": fc.Cents(audit.current.get(person, 0)),
            "target_cents": fc.Cents(audit.target.get(person, 0)),
            "delta_cents": fc.Cents(audit.delta[person]),
        }
        if audit.current_discount is not None and audit.target_discount is not None:
            entry["current_discount"] = fc.Cents(audit.current_discount.get(person, 0))
            entry["target_discount"] = fc.Cents(audit.target_discount.get(person, 0))
        per_person[person] = entry
    return {
        "baseline": audit.label,
        "per_person": per_person,
        "pays_more_now": sorted(person for person, value in audit.delta.items() if value > 0),
        "pays_less_now": sorted(person for person, value in audit.delta.items() if value < 0),
        "pays_more_than_alone_now": sorted(audit.over_alone),
    }


def _audit_table_and_note(
    audit: AuditCalc, people: Sequence[str], lang: str, target_key: str
) -> tuple[fc.Table, str]:
    if audit.label == "custom":
        target = say(lang, "target_items" if target_key == "h_target_items" else "target_rule")
        caption = say(lang, "cap_audit_custom", target=target)
    else:
        caption = say(lang, "cap_audit_" + audit.label)
    target_name = say(lang, "target_items" if target_key == "h_target_items" else "target_rule")
    with_discount = audit.current_discount is not None and audit.target_discount is not None
    header = [say(lang, "h_person")]
    if with_discount:
        header += [say(lang, "h_discount_now"), say(lang, "h_discount_rule")]
    header += [
        say(lang, "h_current"),
        say(lang, target_key),
        say(lang, "h_diff"),
        say(lang, "h_verdict"),
    ]
    rows = []
    for person in people:
        row = [person]
        if with_discount:
            row += [
                fc.fmt_cents(audit.current_discount.get(person, 0)),
                fc.fmt_cents(audit.target_discount.get(person, 0)),
            ]
        row += [
            fc.fmt_cents(audit.current.get(person, 0)),
            fc.fmt_cents(audit.target.get(person, 0)),
            _signed(audit.delta[person]),
            _verdict(audit.delta[person], lang),
        ]
        rows.append(row)
    table = fc.Table(header, rows, caption)
    over = [value for value in audit.delta.values() if value > 0]
    if over:
        note = say(lang, "audit_summary", amount=fc.fmt_cents(sum(over)))
    else:
        note = say(lang, "audit_none", target=target_name)
    return table, note


def _audit_dm_line(audit: AuditCalc, person: str, target_key: str, lang: str) -> str:
    delta = audit.delta[person]
    kind = "more" if delta > 0 else "less" if delta < 0 else "same"
    return say(
        lang,
        "dm_audit_" + kind,
        current=fc.fmt_cents(audit.current.get(person, 0)),
        target=say(lang, target_key),
        target_amount=fc.fmt_cents(audit.target.get(person, 0)),
        amount=fc.fmt_cents(abs(delta)),
    )


def _audit_group_line(audit: AuditCalc, people: Sequence[str], lang: str) -> str:
    parts = []
    for person in people:
        delta = audit.delta[person]
        if delta > 0:
            parts.append(say(lang, "g_diff_more", name=person, amount=fc.fmt_cents(delta)))
        elif delta < 0:
            parts.append(say(lang, "g_diff_less", name=person, amount=fc.fmt_cents(-delta)))
        else:
            parts.append(say(lang, "g_diff_same", name=person))
    return say(
        lang,
        "g_audit",
        label=say(lang, "g_audit_label_" + audit.label),
        list=_list(parts, lang),
    )


def _not_modeled(key: str, lang: str) -> list[str]:
    return TEXT[lang][key].split("|")


def _reproduce(audit: bool, lang: str) -> str:
    """The command of a run on standard input, for callers that give no command of their own."""
    command = "python3 scripts/bill_split.py --input - --format md"
    if audit:
        command += " --audit"
    if lang != "zh":
        command += f" --lang {lang}"
    return command


def reproduce_command(args: argparse.Namespace) -> str:
    """The command line of this run, with every option that changes the output."""
    parts = ["python3", "scripts/bill_split.py"]
    parts += ["--demo"] if args.demo else ["--input", "-"]
    parts += ["--json"] if args.json else ["--format", args.format]
    if args.audit:
        parts.append("--audit")
    if args.lang != "zh":
        parts += ["--lang", args.lang]
    return " ".join(parts)


# ---------------------------------------------------------------------------------------
# Results: expenses
# ---------------------------------------------------------------------------------------


def _shared_text(item: ItemSpec, people: Sequence[str], lang: str) -> str:
    if item.how == "exact":
        return _list([f"{p} {_amount_text(v)}" for p, v in item.shares.items()], lang)
    if item.how == "equal" and set(item.sharers) == set(people):
        return say(lang, "everyone")
    labels = [
        person if item.weights[person] == 1 else f"{person}×{_ratio_text(item.weights[person])}"
        for person in item.sharers
    ]
    return _list(labels, lang)


def _echo_item(item: ItemSpec) -> dict[str, Any]:
    echo: dict[str, Any] = {
        "name": item.name,
        "amount": fc.Cents(fc.to_cents(item.amount)),
        "split": item.how,
        "shared_by": list(item.sharers),
    }
    if item.how == "weights":
        echo["weights"] = {p: _ratio_text(w) for p, w in item.weights.items()}
    if item.how == "exact":
        echo["exact"] = {p: fc.Cents(fc.to_cents(v)) for p, v in item.shares.items()}
    return echo


def _echo_extra(extra: ExtraSpec) -> dict[str, Any]:
    echo: dict[str, Any] = {
        "name": extra.name,
        "amount": fc.Cents(fc.to_cents(extra.amount)),
        "split": extra.split,
    }
    if extra.split == "exact":
        echo["exact"] = {p: fc.Cents(fc.to_cents(v)) for p, v in extra.exact.items()}
    return echo


def _echo_audit(current: Any) -> dict[str, Any]:
    if isinstance(current, str):
        return {"current": current}
    return {"current": {p: fc.Cents(fc.to_cents(v)) for p, v in current.items()}}


def _echo_ledger(ledger: Ledger) -> dict[str, Any]:
    echo: dict[str, Any] = {
        "mode": "expenses",
        "people": list(ledger.people),
        "rules": {"settle": ledger.settle},
        "expenses": [
            {
                "id": spec.id,
                "what": spec.what,
                "paid_by": {p: fc.Cents(fc.to_cents(v)) for p, v in spec.paid_by.items()},
                "items": [_echo_item(item) for item in spec.items],
                "fees": [_echo_extra(extra) for extra in spec.fees],
                "discounts": [_echo_extra(extra) for extra in spec.discounts],
            }
            for spec in ledger.expenses
        ],
    }
    if ledger.audit_current is not None:
        echo["audit"] = _echo_audit(ledger.audit_current)
    return echo


def _expense_parts_json(calc: ExpenseCalc) -> list[dict[str, Any]]:
    return [
        {"kind": kind, "name": name, "cents": _cents_dict(calc.layer_cents[index])}
        for index, (kind, name) in enumerate(calc.layers)
    ]


def _expense_dm_line(person: str, calc: ExpenseCalc, lang: str) -> str | None:
    owed = calc.owed_cents.get(person)
    paid = calc.paid_cents.get(person, 0)
    if owed is None and not paid:
        return None
    what = f" {calc.spec.what}" if calc.spec.what else ""
    parts = []
    if owed is not None:
        for index, (kind, name) in enumerate(calc.layers):
            cents = calc.layer_cents[index].get(person, 0)
            if cents:
                parts.append(f"{_layer_label(kind, name, lang)} {fc.fmt_cents(cents)}")
    text = say(
        lang,
        "dm_expense",
        id=calc.spec.id,
        what=what,
        owed=fc.fmt_cents(owed or 0),
        parts=say(lang, "dm_parts", parts=_list(parts, lang)) if parts else "",
    )
    if paid and owed is None:
        text += say(lang, "dm_paid_only", paid=fc.fmt_cents(paid))
    elif paid:
        text += say(lang, "dm_paid_also", paid=fc.fmt_cents(paid))
    return text


def _ledger_rules_line(ledger: Ledger, lang: str) -> str:
    settle_text = say(lang, "settle_min" if ledger.settle == "min_transfers" else "settle_greedy")
    return say(lang, "rules_expenses", settle=settle_text)


def build_ledger_result(
    calc: LedgerCalc, lang: str, audit: bool, reproduce: str | None = None
) -> fc.Result:
    """Turn the numbers of an expenses input into a Result (md, dm, group and json)."""
    ledger = calc.ledger
    people = ledger.people
    fmt = fc.fmt_cents
    settlement = calc.settlement
    result = fc.Result(
        title=say(lang, "title_expenses"),
        inputs_echo=_echo_ledger(ledger),
        reproduce=reproduce if reproduce is not None else _reproduce(audit, lang),
        not_modeled=_not_modeled("not_modeled_expenses", lang),
    )

    # JSON
    result.result = {
        "mode": "expenses",
        "total_cents": fc.Cents(calc.total_cents),
        "owed_cents": _cents_dict(calc.owed),
        "paid_cents": _cents_dict(calc.paid),
        "net_cents": _cents_dict(calc.net),
        "transfers": _transfers_json(settlement.transfers),
        "exact_minimum": settlement.exact_minimum,
        "settle_method": settlement.method,
        "transfer_counts": dict(calc.counts),
        "notes": [_note_json(note) for note in calc.notes],
    }
    result.certificate = {
        "expenses": {
            ec.spec.id: {
                "what": ec.spec.what,
                "total_cents": fc.Cents(ec.total_cents),
                "paid_cents": _cents_dict(ec.paid_cents),
                "owed_cents": _cents_dict(ec.owed_cents),
                "parts": _expense_parts_json(ec),
                "leftover_cents": fc.Cents(len(ec.leftover_to)),
                "leftover_to": list(ec.leftover_to),
            }
            for ec in calc.expenses
        }
    }
    if calc.audit is not None:
        result.result["audit"] = _audit_json(calc.audit)

    # md
    result.tables.append(
        fc.Table(
            [
                say(lang, "h_person"),
                say(lang, "h_owed"),
                say(lang, "h_paid"),
                say(lang, "h_balance"),
            ],
            [[p, fmt(calc.owed[p]), fmt(calc.paid[p]), _signed(calc.net[p])] for p in people],
            say(lang, "cap_people"),
        )
    )
    result.tables.append(_transfer_table(settlement, lang))
    if calc.audit is not None:
        table, note = _audit_table_and_note(calc.audit, people, lang, "h_target_items")
        result.tables.append(table)
        result.notes.append(note)
    for index, ec in enumerate(calc.expenses, start=1):
        spec = ec.spec
        what = f" {spec.what}" if spec.what else ""
        payers = _list([f"{p} {fmt(c)}" for p, c in sorted(ec.paid_cents.items())], lang)
        result.tables.append(
            fc.Table(
                [say(lang, "h_item"), say(lang, "h_amount"), say(lang, "h_shared")],
                [
                    [item.name, _amount_text(item.amount), _shared_text(item, people, lang)]
                    for item in spec.items
                ],
                say(
                    lang,
                    "cap_expense",
                    i=index,
                    id=spec.id,
                    what=what,
                    total=fmt(ec.total_cents),
                    payers=payers,
                ),
            )
        )
        sharers = sorted(ec.owed_cents, key=lambda p: (people.index(p), p))
        header = [say(lang, "h_person")]
        header += [_layer_label(kind, name, lang) for kind, name in ec.layers]
        header += [say(lang, "h_owed"), say(lang, "h_paid")]
        rows = []
        for person in sharers + [p for p in people if p in ec.paid_cents and p not in sharers]:
            row = [person]
            for index_layer in range(len(ec.layers)):
                row.append(fmt(ec.layer_cents[index_layer].get(person, 0)))
            row += [fmt(ec.owed_cents.get(person, 0)), fmt(ec.paid_cents.get(person, 0))]
            rows.append(row)
        result.tables.append(fc.Table(header, rows, say(lang, "cap_shares", id=spec.id)))
    result.notes.insert(0, _ledger_rules_line(ledger, lang))
    if not settlement.transfers:
        result.notes.append(say(lang, "even"))
    result.notes.append(say(lang, "balance_hint"))
    counts = calc.counts
    if counts["fewest"] is not None and (
        counts["separate"] != counts["fewest"] or counts["greedy"] != counts["fewest"]
    ):
        result.notes.append(say(lang, "counts", **counts))
    for ec in calc.expenses:
        if ec.leftover_to:
            result.notes.append(
                say(
                    lang,
                    "leftover",
                    id=ec.spec.id,
                    names=_names(ec.leftover_to, lang),
                )
            )
    result.notes.extend(_note_text(note, lang) for note in calc.notes)

    # dm
    for person in people:
        lines = [
            say(lang, "dm_hello", name=person),
            say(
                lang,
                "dm_totals",
                owed=fmt(calc.owed[person]),
                paid=fmt(calc.paid[person]),
                balance=_signed(calc.net[person]),
            ),
        ]
        expense_lines = [_expense_dm_line(person, ec, lang) for ec in calc.expenses]
        involved = [line for line in expense_lines if line]
        lines += involved or [say(lang, "dm_uninvolved")]
        lines += _transfer_dm_lines(person, settlement, lang)
        if calc.audit is not None:
            lines.append(_audit_dm_line(calc.audit, person, "target_items", lang))
        result.person_lines[person] = lines

    # group
    result.group_lines = [
        say(lang, "g_expenses", n=len(calc.expenses), total=fmt(calc.total_cents)),
        say(
            lang,
            "g_owed",
            list=_list([f"{p} {fmt(calc.owed[p])}" for p in people], lang),
        ),
        say(
            lang,
            "g_paid",
            list=_list([f"{p} {fmt(calc.paid[p])}" for p in people if calc.paid[p]], lang),
        ),
    ]
    result.group_lines += _transfer_group_lines(settlement, lang)
    if calc.audit is not None:
        result.group_lines.append(_audit_group_line(calc.audit, people, lang))
    return result


# ---------------------------------------------------------------------------------------
# Results: group orders
# ---------------------------------------------------------------------------------------


def _echo_order(spec: OrderSpec) -> dict[str, Any]:
    def money_of(value: Fraction) -> fc.Cents:
        return fc.Cents(fc.to_cents(value))

    coupons = []
    for coupon in spec.coupons:
        echo: dict[str, Any] = {"name": coupon.name, "split": coupon.split}
        if coupon.tiers:
            echo["tiers"] = [[fc.Cents(t), fc.Cents(r)] for t, r in coupon.tiers]
        else:
            echo["amount"] = money_of(coupon.amount)
        coupons.append(echo)
    order_echo: dict[str, Any] = {
        "mode": "group_order",
        "id": spec.id,
        "items": [
            {
                "who": item.who,
                "name": item.name,
                "amount": money_of(item.amount),
                "packaging": money_of(item.packaging),
            }
            for item in spec.items
        ],
        "fees": [
            {"name": fee.name, "amount": money_of(fee.amount), "split": fee.split}
            for fee in spec.fees
        ],
        "coupons": coupons,
        "paid_by": (
            None if spec.paid_by is None else {p: money_of(v) for p, v in spec.paid_by.items()}
        ),
        "rules": {"settle": spec.settle},
    }
    if spec.audit_current is not None:
        order_echo["audit"] = _echo_audit(spec.audit_current)
    return order_echo


def _order_rules_line(spec: OrderSpec, lang: str) -> str:
    snippets = []
    for fee in spec.fees:
        snippets.append(say(lang, "rule_fee_" + fee.split, name=fee.name))
    for coupon in spec.coupons:
        snippets.append(say(lang, "rule_coupon_" + coupon.split, name=coupon.name))
    separator = "；" if lang == "zh" else "; "
    extras = "".join(separator + snippet for snippet in snippets)
    settle_text = say(lang, "settle_min" if spec.settle == "min_transfers" else "settle_greedy")
    return say(lang, "rules_order", extras=extras, settle=settle_text)


def _order_layer_totals(calc: OrderCalc, lang: str) -> list[str]:
    parts = []
    for index, (kind, name) in enumerate(calc.layers):
        total = sum(calc.layer_cents[index].values())
        parts.append(f"{_layer_label(kind, name, lang)} {fc.fmt_cents(total)}")
    return parts


def _order_dm_parts(person: str, calc: OrderCalc, lang: str) -> str:
    parts = []
    for index, (kind, name) in enumerate(calc.layers):
        cents = calc.layer_cents[index].get(person, 0)
        if cents:
            parts.append(f"{_layer_label(kind, name, lang)} {fc.fmt_cents(cents)}")
    return _list(parts, lang)


def build_order_result(
    calc: OrderCalc, lang: str, audit: bool, reproduce: str | None = None
) -> fc.Result:
    """Turn the numbers of a group order into a Result (md, dm, group and json)."""
    spec = calc.spec
    people = calc.people
    fmt = fc.fmt_cents
    trap_ok = not calc.over_alone
    result = fc.Result(
        title=say(lang, "title_order"),
        inputs_echo=_echo_order(spec),
        reproduce=reproduce if reproduce is not None else _reproduce(audit, lang),
        not_modeled=_not_modeled("not_modeled_order", lang),
    )

    # JSON
    result.result = {
        "mode": "group_order",
        "total_cents": fc.Cents(calc.total_cents),
        "subtotal_cents": fc.Cents(calc.subtotal_cents),
        "pay_cents": _cents_dict(calc.pay),
        "alone_cents": _cents_dict(calc.alone),
        "coupon_share": _cents_dict(calc.discount),
        "coupon_reductions": _cents_dict(calc.reductions),
        "trap_check": trap_ok,
        "pays_more_than_alone": sorted(calc.over_alone),
        "notes": [_note_json(note) for note in calc.notes],
    }
    if spec.paid_by:
        result.result.update(
            {
                "paid_cents": _cents_dict(calc.paid),
                "net_cents": _cents_dict(calc.net),
                "transfers": _transfers_json(calc.settlement.transfers),
                "exact_minimum": calc.settlement.exact_minimum,
                "settle_method": calc.settlement.method,
            }
        )
    if calc.audit is not None:
        result.result["audit"] = _audit_json(calc.audit)
    result.certificate = {
        "order_id": spec.id,
        "parts": [
            {"kind": kind, "name": name, "cents": _cents_dict(calc.layer_cents[index])}
            for index, (kind, name) in enumerate(calc.layers)
        ],
        "shapley": {
            coupon: {person: _ratio_text(value) for person, value in shares.items()}
            for coupon, shares in calc.shapley.items()
        },
        "leftover_cents": fc.Cents(len(calc.leftover_to)),
        "leftover_to": list(calc.leftover_to),
    }

    # md
    header = [say(lang, "h_person")]
    header += [_layer_label(kind, name, lang) for kind, name in calc.layers]
    header += [say(lang, "h_pay"), say(lang, "h_alone")]
    rows = []
    for person in people:
        row = [person] + [fmt(deltas.get(person, 0)) for deltas in calc.layer_cents]
        row += [fmt(calc.pay[person]), fmt(calc.alone[person])]
        rows.append(row)
    result.tables.append(fc.Table(header, rows, say(lang, "cap_order")))
    if spec.paid_by:
        payers = _names(sorted(spec.paid_by), lang)
        result.tables.append(
            _transfer_table(calc.settlement, lang, say(lang, "cap_order_paid", payer=payers))
        )
    if calc.audit is not None:
        table, note = _audit_table_and_note(calc.audit, people, lang, "h_target_rule")
        result.tables.append(table)
        result.notes.append(note)
        if calc.audit.over_alone:
            result.notes.append(say(lang, "audit_alone", list=_names(calc.audit.over_alone, lang)))
    result.notes.insert(0, _order_rules_line(spec, lang))
    if spec.paid_by and not calc.settlement.transfers:
        result.notes.append(say(lang, "even"))
    result.notes.append(
        say(
            lang,
            "order_total",
            parts=_list(_order_layer_totals(calc, lang), lang),
            total=fmt(calc.total_cents),
        )
    )
    if trap_ok:
        result.notes.append(say(lang, "trap_ok"))
    else:
        listed = _names(
            [
                say(lang, "trap_person", name=p, pay=fmt(calc.pay[p]), alone=fmt(calc.alone[p]))
                for p in calc.over_alone
            ],
            lang,
        )
        result.notes.append(say(lang, "trap_fail", list=listed))
    for coupon in spec.coupons:
        if coupon.tiers and coupon.split == "shapley":
            result.notes.append(say(lang, "tier_explain", name=coupon.name))
    if calc.leftover_to:
        result.notes.append(
            say(
                lang,
                "leftover",
                id=spec.id,
                names=_names(calc.leftover_to, lang),
            )
        )
    result.notes.extend(_note_text(note, lang) for note in calc.notes)

    # dm
    for person in people + [p for p in calc.paid if p not in people]:
        lines = [say(lang, "dm_hello", name=person)]
        if person in calc.pay:
            lines.append(
                say(
                    lang,
                    "dm_order",
                    parts=_order_dm_parts(person, calc, lang),
                    pay=fmt(calc.pay[person]),
                )
            )
            lines.append(say(lang, "dm_order_alone", alone=fmt(calc.alone[person])))
            if person in calc.over_alone:
                lines.append(say(lang, "dm_order_trap"))
        if person in calc.paid:
            lines.append(say(lang, "dm_order_payer", paid=fmt(calc.paid[person])))
        if spec.paid_by:
            lines += _transfer_dm_lines(person, calc.settlement, lang)
        if calc.audit is not None and person in calc.audit.delta:
            lines.append(_audit_dm_line(calc.audit, person, "target_rule", lang))
        result.person_lines[person] = lines

    # group
    result.group_lines = [
        say(
            lang,
            "g_order_total",
            parts=_list(_order_layer_totals(calc, lang), lang),
            total=fmt(calc.total_cents),
        ),
        say(lang, "g_order_pay", list=_list([f"{p} {fmt(calc.pay[p])}" for p in people], lang)),
        say(lang, "g_order_alone", list=_list([f"{p} {fmt(calc.alone[p])}" for p in people], lang)),
        say(lang, "g_order_trap_ok")
        if trap_ok
        else say(lang, "g_order_trap_fail", list=_names(calc.over_alone, lang)),
    ]
    if spec.paid_by:
        result.group_lines += _transfer_group_lines(calc.settlement, lang)
    if calc.audit is not None:
        result.group_lines.append(_audit_group_line(calc.audit, people, lang))
    return result


# ---------------------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------------------


def compute(
    data: Any, audit: bool = False, lang: str = "zh", reproduce: str | None = None
) -> fc.Result:
    """Validate a parsed input and compute its Result (the function behind the command line).

    reproduce is the command line to print in the Reproduce section. Without it the section
    shows the command that reads the same JSON from standard input.
    """
    if lang not in fc.LANGS:
        raise ValueError(f"lang must be one of {', '.join(fc.LANGS)}")
    obj = fc.require_object(data, "input")
    mode = fc.require_choice(obj.get("mode", "expenses"), "mode", MODES)
    if mode == "expenses":
        return build_ledger_result(compute_ledger(parse_ledger(obj), audit), lang, audit, reproduce)
    return build_order_result(compute_order(parse_order(obj), audit), lang, audit, reproduce)


# ---------------------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------------------

DEMO_AUDIT_AA = """
{
  "mode": "expenses",
  "people": ["阿明", "小红", "大刘", "Coco"],
  "expenses": [
    {
      "id": "dinner-1",
      "what": "聚餐",
      "paid_by": {"阿明": 680},
      "items": [
        {"name": "菜", "amount": 480, "everyone": true},
        {"name": "酒", "amount": 160, "among": ["大刘", "Coco"]}
      ],
      "fees": [{"name": "服务费", "amount": 40, "split": "by_consumption"}],
      "discounts": []
    }
  ],
  "rules": {"settle": "min_transfers"},
  "audit": {"current": "aa"}
}
"""

DEMO_TRIP = """
{
  "mode": "expenses",
  "people": ["阿明", "小红", "大刘", "Coco", "老王", "Yuki"],
  "expenses": [
    {"id": "trip-1", "what": "民宿", "paid_by": {"阿明": 1200},
     "items": [{"name": "两晚住宿", "amount": 1200, "everyone": true}]},
    {"id": "trip-2", "what": "包车", "paid_by": {"小红": 600},
     "items": [{"name": "一日包车", "amount": 600,
                "among": ["阿明", "小红", "大刘", "Coco"]}]},
    {"id": "trip-3", "what": "晚饭", "paid_by": {"大刘": 360},
     "items": [{"name": "烧烤", "amount": 360, "among": ["大刘", "Coco", "老王"]}]},
    {"id": "trip-4", "what": "门票", "paid_by": {"Coco": 300},
     "items": [{"name": "景区门票", "amount": 300, "everyone": true}]},
    {"id": "trip-5", "what": "咖啡", "paid_by": {"老王": 180},
     "items": [{"name": "咖啡", "amount": 180, "among": ["阿明", "老王"]}]}
  ],
  "rules": {"settle": "min_transfers"}
}
"""

DEMO_COUPON = """
{
  "mode": "group_order",
  "id": "coupon-1",
  "items": [
    {"who": "甲", "name": "烤鱼套餐", "amount": 150},
    {"who": "乙", "name": "火锅双人餐", "amount": 140},
    {"who": "丙", "name": "奶茶", "amount": 20}
  ],
  "coupons": [{"name": "满300减60", "tiers": [[300, 60]], "split": "shapley"}],
  "paid_by": "甲",
  "audit": {"current": "proportional"}
}
"""

# name, input text, show the audit
DEMOS = (
    ("audit_aa", DEMO_AUDIT_AA, True),
    ("trip_five_bills", DEMO_TRIP, False),
    ("group_order_coupon", DEMO_COUPON, True),
)


def run_demo(args: argparse.Namespace) -> int:
    command = reproduce_command(args)
    results = [
        (name, compute(fc.parse_input(text), audit=audit, lang=args.lang, reproduce=command))
        for name, text, audit in DEMOS
    ]
    if args.json:
        envelopes = {name: fc.envelope(result) for name, result in results}
        sys.stdout.write(json.dumps(envelopes, sort_keys=True, ensure_ascii=False, indent=2) + "\n")
        return 0
    blocks = []
    for number, (name, result) in enumerate(results, start=1):
        text = fc.render(result, args.format, False, args.lang)
        blocks.append(f"=== demo {number}/{len(results)}: {name} ===\n\n{text}")
    sys.stdout.write("\n".join(blocks))
    return 0


# ---------------------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------------------


def _brute_force_groups(values: Sequence[int]) -> int:
    """Largest number of zero-sum groups, by recursion over subsets (independent of the DP)."""
    count = len(values)
    sums = [0] * (1 << count)
    for mask in range(1, 1 << count):
        low = mask & -mask
        sums[mask] = sums[mask ^ low] + values[low.bit_length() - 1]
    memo = {0: 0}

    def best(mask: int) -> int:
        if mask in memo:
            return memo[mask]
        low = mask & -mask
        top = 0
        sub = mask
        while sub:
            if sub & low and sums[sub] == 0:
                top = max(top, 1 + best(mask ^ sub))
            sub = (sub - 1) & mask
        memo[mask] = top
        return top

    return best((1 << count) - 1)


def selftest_checks() -> list[tuple[str, Any]]:
    def dinner() -> None:
        calc = compute_ledger(parse_ledger(fc.parse_input(DEMO_AUDIT_AA)), True)
        owed = {p: fc.fmt_cents(c) for p, c in calc.owed.items()}
        fc.expect(
            owed == {"阿明": "127.50", "小红": "127.50", "大刘": "212.50", "Coco": "212.50"},
            f"owed {owed}",
        )
        fc.expect(calc.audit is not None and calc.audit.delta["阿明"] == 4250, "audit")
        fc.expect(len(calc.settlement.transfers) == 3, "transfers")

    def trip() -> None:
        calc = compute_ledger(parse_ledger(fc.parse_input(DEMO_TRIP)), False)
        fc.expect(
            calc.counts == {"separate": 16, "pairwise": 11, "greedy": 5, "fewest": 5},
            f"counts {calc.counts}",
        )
        fc.expect(calc.net["阿明"] == 71000 and calc.net["老王"] == -28000, "net balances")

    def greedy_trap() -> None:
        net = {"甲": 7000, "乙": 5000, "丙": -5000, "丁": -4000, "戊": -3000}
        fc.expect(len(greedy_transfers(net)) == 4, "greedy count")
        plan = fewest_transfers(net)
        fc.expect(
            plan == [("丁", "甲", 4000), ("丙", "乙", 5000), ("戊", "甲", 3000)], f"plan {plan}"
        )

    def coupon() -> None:
        calc = compute_order(parse_order(fc.parse_input(DEMO_COUPON)), True)
        fc.expect([calc.pay[p] for p in "甲乙丙"] == [13000, 12000, 0], f"pay {calc.pay}")
        fc.expect(calc.audit is not None, "audit")
        fc.expect([calc.audit.current[p] for p in "甲乙丙"] == [12097, 11290, 1613], "proportional")

    def takeout() -> None:
        data = fc.parse_input(
            '{"mode": "group_order", "id": "waimai-1",'
            ' "items": [{"who": "阿明", "name": "黄焖鸡", "amount": 28, "packaging": 1},'
            ' {"who": "小红", "name": "麻辣烫", "amount": 28, "packaging": 1},'
            ' {"who": "Coco", "name": "柠檬水", "amount": 6, "packaging": 1}],'
            ' "fees": [{"name": "配送费", "amount": 5}],'
            ' "coupons": [{"name": "满减", "tiers": [[40, 10], [60, 18]]},'
            ' {"name": "红包", "amount": 3}]}'
        )
        calc = compute_order(parse_order(data), False)
        fc.expect(
            [calc.pay[p] for p in ("阿明", "小红", "Coco")] == [2224, 2223, 453],
            f"pay {calc.pay}",
        )
        fc.expect(calc.total_cents == 4900 and not calc.over_alone, "total and trap check")

    def dp_against_brute_force() -> None:
        state = 12345
        for _ in range(60):
            state = (state * 1103515245 + 12345) % (2**31)
            count = 2 + state % 6
            values = []
            for _ in range(count - 1):
                state = (state * 1103515245 + 12345) % (2**31)
                values.append((state >> 8) % 7 - 3)
            values.append(-sum(values))
            nonzero = [v for v in values if v]
            groups = _brute_force_groups(nonzero)
            net = {f"p{i}": v for i, v in enumerate(nonzero)}
            fc.expect(len(fewest_transfers(net)) == len(nonzero) - groups, f"dp {nonzero}")

    def rotation() -> None:
        counts = {"A": 0, "B": 0, "C": 0}
        for number in range(1, 31):
            shares = {name: Fraction(100, 3) for name in counts}
            cents = fc.round_shares(shares, 10000, f"expense-{number}")
            for name, value in cents.items():
                counts[name] += value == 3334
        fc.expect(sorted(counts.values()) == [10, 10, 10], f"rotation {counts}")

    def decimals() -> None:
        data = fc.parse_input(
            '{"people": ["a", "b"], "expenses": [{"paid_by": {"a": 0.29},'
            ' "items": [{"name": "x", "amount": 0.29, "everyone": true}]}]}'
        )
        calc = compute_ledger(parse_ledger(data), False)
        fc.expect(calc.total_cents == 29 and sum(calc.owed.values()) == 29, "0.29 is 29 cents")

    return [
        ("dinner 680 and the AA audit", dinner),
        ("trip: 16, 11, 5, 5 transfers", trip),
        ("greedy needs 4, the fewest is 3", greedy_trap),
        ("coupon: Shapley and proportional", coupon),
        ("takeout: 22.24, 22.23, 4.53", takeout),
        ("fewest transfers against brute force", dp_against_brute_force),
        ("leftover cent rotates over 30 bills", rotation),
        ("decimal amounts are exact", decimals),
    ]


# ---------------------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bill_split.py",
        description=__doc__,
        epilog=fc.exit_codes_epilog(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    fc.standard_args(parser)
    parser.add_argument(
        "--audit",
        action="store_true",
        help="also compare with the split the group uses now (input field audit.current; "
        "equal shares for expenses, dish-price proportional for group orders by default)",
    )
    fc.add_lang_option(parser, "the JSON output has no prose")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    fc.exclusive_modes(args, "--demo", "--selftest")
    if args.selftest:
        return fc.run_selftest(selftest_checks())
    if args.demo:
        return run_demo(args)
    data = fc.read_object(args)
    result = compute(data, audit=args.audit, lang=args.lang, reproduce=reproduce_command(args))
    fc.emit(result, args, lang=args.lang)
    return 0


if __name__ == "__main__":
    fc.run_cli(main)
