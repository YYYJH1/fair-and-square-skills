"""Envy-free rent division from private bids, exact to the cent.

Each roommate prices every room privately so that the prices add up to the total rent. The
script gives the rooms to the people who bid most overall, then sets the rents so that nobody
would rather live in another room at that room's rent. All arithmetic uses exact fractions,
and the rents are rounded to whole cents only at the end.

Input is one JSON object on standard input (or --input FILE)::

    {"total_rent": 8000,
     "rooms": ["Main", "South", "North", "Study"],
     "bids": {"Ann": [3000, 2200, 1600, 1200], "Bob": [...], ...},
     "rules": {"negative_rent": "spliddit", "random_source": "optional public text"},
     "audit": {"assignment": {"Ann": "Study", ...}, "rent": {"Ann": 2000, ...}}}

Only the standard library and the shared fsq_core module are used. Nothing is written to disk.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

try:
    import fsq_core as fc
except ModuleNotFoundError:  # python -I, -P and PYTHONSAFEPATH leave the script folder off sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import fsq_core as fc

NEGATIVE_RENT_RULES = ("spliddit", "allow", "forbid")
MAX_PEOPLE = 20
TOP_LEVEL_FIELDS = ("total_rent", "rooms", "bids", "rules", "audit")
RULE_FIELDS = ("negative_rent", "random_source")
AUDIT_FIELDS = ("assignment", "rent")
TIE_RULE_NAME = "rent_split_assignment_v1"

APPLIED_NON_NEGATIVE = "non_negative"
APPLIED_ALLOWED = "negative_allowed"
APPLIED_FALLBACK = "negative_allowed_after_no_non_negative_solution"

fmt = fc.fmt_cents


# ---------------------------------------------------------------------------------------
# Exact solver. All amounts are Fractions of one unit (callers pass cents).
# ---------------------------------------------------------------------------------------


def welfare_max_assignment(values: Sequence[Sequence[Fraction]]) -> list[int]:
    """Room of each person in an assignment with the largest total value (Hungarian method)."""
    n = len(values)
    cost = [[-Fraction(value) for value in row] for row in values]
    pot_row = [Fraction(0)] * (n + 1)
    pot_col = [Fraction(0)] * (n + 1)
    owner = [0] * (n + 1)  # owner[c] is the 1-based row matched to column c, 0 if none
    way = [0] * (n + 1)
    for row in range(1, n + 1):
        owner[0] = row
        col0 = 0
        slack: list[Fraction | None] = [None] * (n + 1)
        seen = [False] * (n + 1)
        while True:
            seen[col0] = True
            row0 = owner[col0]
            delta: Fraction | None = None
            col1 = 0
            for col in range(1, n + 1):
                if seen[col]:
                    continue
                reduced = cost[row0 - 1][col - 1] - pot_row[row0] - pot_col[col]
                current = slack[col]
                if current is None or reduced < current:
                    slack[col] = current = reduced
                    way[col] = col0
                if delta is None or current < delta:
                    delta, col1 = current, col
            for col in range(n + 1):
                if seen[col]:
                    pot_row[owner[col]] += delta
                    pot_col[col] -= delta
                else:
                    slack[col] -= delta
            col0 = col1
            if owner[col0] == 0:
                break
        while col0:
            previous = way[col0]
            owner[col0] = owner[previous]
            col0 = previous
    room_of = [0] * n
    for col in range(1, n + 1):
        room_of[owner[col] - 1] = col - 1
    return room_of


def shortest_paths(
    values: Sequence[Sequence[Fraction]], room_of: Sequence[int]
) -> list[list[Fraction]]:
    """All-pairs shortest paths on the envy graph of a welfare-maximising assignment.

    The edge from person i to person k weighs v_k(room of k) - v_i(room of k). A utility
    vector u is envy-free at some rents exactly when u_k - u_i <= dist[i][k] for all i, k.
    """
    n = len(values)
    dist = [
        [
            Fraction(0) if i == k else Fraction(values[k][room_of[k]] - values[i][room_of[k]])
            for k in range(n)
        ]
        for i in range(n)
    ]
    for mid in range(n):
        for i in range(n):
            for k in range(n):
                dist[i][k] = min(dist[i][k], dist[i][mid] + dist[mid][k])
    if any(dist[i][i] < 0 for i in range(n)):
        raise ValueError("the assignment does not maximise the total value")
    return dist


def maximin_utilities(dist: Sequence[Sequence[Fraction]], budget: Fraction) -> list[Fraction]:
    """The unique envy-free utilities that leave the worst-off person as well off as possible.

    budget is the total value of the assignment minus the total rent. Rents may be negative.
    """
    n = len(dist)
    lows = [-min(row) for row in dist]
    level = (Fraction(budget) - sum(lows, Fraction(0))) / n
    return [level + low for low in lows]


def _largest_shift(
    offsets: Sequence[Fraction], floors: Sequence[Fraction | None], budget: Fraction
) -> Fraction:
    """Largest x with sum_k max(x + offsets[k], floors[k]) <= budget (None means no floor)."""
    n = len(offsets)

    def total(x: Fraction) -> Fraction:
        return sum(
            (
                x + offsets[k] if floors[k] is None or x + offsets[k] >= floors[k] else floors[k]
                for k in range(n)
            ),
            Fraction(0),
        )

    points = sorted({floors[k] - offsets[k] for k in range(n) if floors[k] is not None})
    unbounded = sum(1 for floor in floors if floor is None)
    if not points:
        return (budget - sum(offsets, Fraction(0))) / n
    if total(points[0]) > budget:
        if not unbounded:
            raise ValueError("the budget is below the sum of the floors")
        return points[0] - (total(points[0]) - budget) / unbounded
    best = points[0]
    for point in points:
        if total(point) > budget:
            break
        best = point
    active = sum(1 for k in range(n) if floors[k] is None or floors[k] - offsets[k] <= best)
    return best + (budget - total(best)) / active


def nonneg_leximin_utilities(
    dist: Sequence[Sequence[Fraction]], own: Sequence[Fraction], budget: Fraction
) -> list[Fraction] | None:
    """Envy-free utilities with no negative rent that are leximin optimal, or None.

    own[i] is the value person i puts on the room they get, so a rent is non-negative exactly
    when the utility is at most own[i]. The result is unique. None means that no envy-free
    split without a negative rent exists. The derivation is in docs/THEORY.md.
    """
    n = len(dist)
    budget = Fraction(budget)
    cap = [min(own[i] + dist[i][k] for i in range(n)) for k in range(n)]
    if sum(cap, Fraction(0)) < budget:
        return None
    fixed: dict[int, Fraction] = {}
    free = set(range(n))
    while free:
        slack = [max(-dist[i][j] for j in free) for i in range(n)]
        floors = [max((fixed[j] - dist[i][j] for j in fixed), default=None) for i in range(n)]
        level = min(min(cap[i] - slack[i] for i in range(n)), _largest_shift(slack, floors, budget))
        base = [
            level + slack[k] if floors[k] is None else max(level + slack[k], floors[k])
            for k in range(n)
        ]
        stuck = []
        for i in sorted(free):
            offsets = [level - dist[k][i] for k in range(n)]
            room = min(
                min(cap[k] - offsets[k] for k in range(n)), _largest_shift(offsets, base, budget)
            )
            if room <= 0:
                stuck.append(i)
        if not stuck:
            raise RuntimeError("leximin: nobody is stuck at the current level (internal error)")
        for i in stuck:
            fixed[i] = level
            free.discard(i)
    return [fixed[i] for i in range(n)]


@dataclass
class ExactSolution:
    """The exact answer, before ties between assignments are resolved and before rounding."""

    room_of: list[int]  # one welfare-maximising assignment
    utilities: list[Fraction]
    rents: list[Fraction]  # per room
    applied: str


def verify_exact(
    values: Sequence[Sequence[Fraction]],
    total: Fraction,
    room_of: Sequence[int],
    rents: Sequence[Fraction],
    non_negative: bool,
) -> None:
    """Raise AssertionError unless the rents are exactly envy-free and add up to the total."""
    n = len(values)
    if sum(rents, Fraction(0)) != total:
        raise AssertionError("the rents do not add up to the total rent")
    if non_negative and any(rent < 0 for rent in rents):
        raise AssertionError("a rent is negative in a solution without negative rents")
    for i in range(n):
        mine = values[i][room_of[i]] - rents[room_of[i]]
        if any(values[i][k] - rents[k] > mine for k in range(n)):
            raise AssertionError(f"person {i} envies another room")


def solve_exact(values: Sequence[Sequence[Fraction]], total: Fraction, rule: str) -> ExactSolution:
    """Solve the rent division exactly. Raises fc.NoSolution under the rule forbid.

    values[i][k] is what person i bids for room k, and each row should add up to total.
    """
    matrix = [[Fraction(x) for x in row] for row in values]
    n = len(matrix)
    room_of = welfare_max_assignment(matrix)
    own = [matrix[i][room_of[i]] for i in range(n)]
    dist = shortest_paths(matrix, room_of)
    budget = sum(own, Fraction(0)) - Fraction(total)
    utilities = None
    applied = APPLIED_ALLOWED
    if rule in ("spliddit", "forbid"):
        utilities = nonneg_leximin_utilities(dist, own, budget)
        if utilities is not None:
            applied = APPLIED_NON_NEGATIVE
        elif rule == "forbid":
            raise fc.NoSolution(
                "under the rule forbid there is no split in which nobody envies anyone and "
                "nobody is paid to live, so everybody should bid again. "
                "按事先约定的 forbid 规则，没有一种分法能让人人不羡慕、同时没有人倒贴，请全体重新报价。"
            )
        else:
            applied = APPLIED_FALLBACK
    if utilities is None:
        utilities = maximin_utilities(dist, budget)
    rents = [Fraction(0)] * n
    for i in range(n):
        rents[room_of[i]] = own[i] - utilities[i]
    verify_exact(matrix, Fraction(total), room_of, rents, applied == APPLIED_NON_NEGATIVE)
    return ExactSolution(room_of, utilities, rents, applied)


# ---------------------------------------------------------------------------------------
# Ties between equally good assignments
# ---------------------------------------------------------------------------------------


def tight_rooms(
    values: Sequence[Sequence[Fraction]], rents: Sequence[Fraction], utilities: Sequence[Fraction]
) -> list[list[int]]:
    """For each person, the rooms that are exactly as good as the best one at these rents."""
    n = len(values)
    return [[k for k in range(n) if values[i][k] - rents[k] == utilities[i]] for i in range(n)]


def _can_match(tight: Sequence[Sequence[int]], people: Sequence[int], rooms: set[int]) -> bool:
    """True if the given people can all get distinct rooms from `rooms` along tight edges."""
    holder: dict[int, int] = {}

    def place(person: int, visited: set[int]) -> bool:
        for room in tight[person]:
            if room in rooms and room not in visited:
                visited.add(room)
                if room not in holder or place(holder[room], visited):
                    holder[room] = person
                    return True
        return False

    return all(place(person, set()) for person in people)


def choose_assignment(
    tight: Sequence[Sequence[int]],
    people: Sequence[str],
    rooms: Sequence[str],
    stream: fc.SeedStream | None,
) -> tuple[list[int], bool]:
    """Pick one assignment that uses only tight rooms. Returns (room of each person, was_tie).

    People are handled one at a time. Without a stream they go in the order of their names
    and each takes the first suitable room by name. With a stream (public randomness) the
    order is a seeded shuffle and each choice among the suitable rooms is a seeded draw.
    A room is suitable if everybody still waiting can be given some room afterwards.
    was_tie is True when more than one assignment was possible.
    """
    n = len(people)
    index = {name: i for i, name in enumerate(people)}
    names = fc.shuffle(list(people), stream) if stream is not None else sorted(people)
    order = [index[name] for name in names]
    free = set(range(n))
    room_of = [-1] * n
    was_tie = False
    for position, person in enumerate(order):
        waiting = order[position + 1 :]
        options = [
            room
            for room in sorted(tight[person], key=lambda k: rooms[k])
            if room in free and _can_match(tight, waiting, free - {room})
        ]
        if not options:
            raise RuntimeError("no assignment fits the tight rooms (internal error)")
        was_tie = was_tie or len(options) > 1
        if stream is not None and len(options) > 1:
            chosen = options[stream.below(len(options))]
        else:
            chosen = options[0]
        room_of[person] = chosen
        free.discard(chosen)
    return room_of, was_tie


# ---------------------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------------------


@dataclass
class Audit:
    """A split the group uses today: the room of each person and what each person pays."""

    rooms: dict[str, str]
    rents: dict[str, int]  # cents


@dataclass
class Problem:
    """A validated input. Amounts are integer cents, bids exactly as the people gave them."""

    total: int
    rooms: list[str]
    people: list[str]
    bids: list[list[int]]  # bids[person][room]
    rule: str
    random_source: str | None = None
    audit: Audit | None = None


def _required(obj: dict[str, Any], key: str, where: str = "") -> Any:
    if key not in obj:
        raise fc.InputError(f"{where}{key}", "is required")
    return obj[key]


def _read_audit(value: Any, people: list[str], rooms: list[str], total: int) -> Audit:
    obj = fc.require_object(value, "audit")
    fc.check_fields(obj, AUDIT_FIELDS, "audit")
    placed = fc.require_object(_required(obj, "assignment", "audit."), "audit.assignment")
    paid = fc.require_object(_required(obj, "rent", "audit."), "audit.rent")
    for label, mapping in (("assignment", placed), ("rent", paid)):
        for name in people:
            if name not in mapping:
                raise fc.InputError(f"audit.{label}.{name}", "is missing; list every person")
        for name in mapping:
            if name not in people:
                raise fc.InputError(f"audit.{label}.{name}", "is not a person listed in bids")
    for name in people:
        if placed[name] not in rooms:
            raise fc.InputError(f"audit.assignment.{name}", f"{placed[name]!r} is not a room")
    if sorted(placed[name] for name in people) != sorted(rooms):
        raise fc.InputError("audit.assignment", "must give every room to exactly one person")
    rents = {
        name: fc.to_cents(fc.money(paid[name], f"audit.rent.{name}", allow_negative=True))
        for name in people
    }
    if sum(rents.values()) != total:
        raise fc.InputError(
            "audit.rent",
            f"the current rents add up to {fmt(sum(rents.values()))}, "
            f"but total_rent is {fmt(total)}",
        )
    return Audit({name: placed[name] for name in people}, rents)


def read_problem(data: Any, partial: bool = False) -> Problem:
    """Validate a parsed input object. partial=True is for --commit and --verify-commit.

    A partial input may hold any number of people and needs no rules block.
    """
    obj = fc.require_object(data, "input")
    fc.check_fields(obj, TOP_LEVEL_FIELDS, "")
    total = fc.to_cents(fc.money(_required(obj, "total_rent"), "total_rent", allow_zero=False))
    rooms = fc.require_names(_required(obj, "rooms"), "rooms", min_len=2, max_len=MAX_PEOPLE)
    bid_obj = fc.require_object(_required(obj, "bids"), "bids")
    people = list(bid_obj)
    if not people:
        raise fc.InputError("bids", "must name at least one person")
    for name in people:
        if not name or name != name.strip():
            raise fc.InputError(
                "bids", f"the name {name!r} must be non-empty without leading or trailing spaces"
            )
    for index, room in enumerate(rooms):
        fc.encodable(room, f"rooms[{index}]")
    for name in people:
        fc.encodable(name, f"bids.{name}")
    if not partial and len(people) != len(rooms):
        raise fc.InputError(
            "bids",
            f"{len(people)} people but {len(rooms)} rooms: rent-split needs exactly one room "
            "per person (a couple who share a room bid together as one person)",
        )
    bids = []
    for name in people:
        row = fc.require_list(bid_obj[name], f"bids.{name}")
        if len(row) != len(rooms):
            raise fc.InputError(
                f"bids.{name}",
                f"needs {len(rooms)} bids, one per room in the order of rooms, got {len(row)}",
            )
        bids.append([fc.to_cents(fc.money(x, f"bids.{name}[{k}]")) for k, x in enumerate(row)])
    rule, source = "spliddit", None
    if "rules" in obj or not partial:
        rules = fc.require_object(obj.get("rules", {}), "rules")
        fc.check_fields(rules, RULE_FIELDS, "rules")
        if "negative_rent" not in rules:
            raise fc.InputError(
                "rules.negative_rent",
                "is required: the group agrees on spliddit, allow or forbid before anyone bids",
            )
        rule = fc.require_choice(rules["negative_rent"], "rules.negative_rent", NEGATIVE_RENT_RULES)
        if "random_source" in rules:
            source = fc.require_text(rules["random_source"], "rules.random_source")
    audit = None
    if "audit" in obj and not partial:
        audit = _read_audit(obj["audit"], people, rooms, total)
    return Problem(total, rooms, people, bids, rule, source, audit)


# ---------------------------------------------------------------------------------------
# Computation
# ---------------------------------------------------------------------------------------


@dataclass
class Outcome:
    """Everything computed from a Problem. Amounts without a unit are integer cents."""

    problem: Problem
    room_of: list[int]  # room index of each person
    rents: list[int]  # rounded rent of each room
    shown: list[list[int]]  # bids as shown to people: the given bids plus a whole-cent shift
    shift_exact: list[Fraction]  # exact per-room shift of each person's bids, in cents
    values: list[list[int]]  # shown bid minus rent, for each person and room
    surplus: list[int]  # the value of the person's own room
    max_envy: int
    applied: str
    was_tie: bool
    seed_hex: str | None
    exact_rents: list[Fraction]  # in cents, before rounding


def compute(problem: Problem) -> Outcome:
    """Solve a validated problem: exact solution, tie-breaking, rounding, self-check."""
    n = len(problem.people)
    rooms = problem.rooms
    shift_exact = [Fraction(problem.total - sum(row), n) for row in problem.bids]
    used = [[Fraction(x) + shift_exact[i] for x in row] for i, row in enumerate(problem.bids)]
    exact = solve_exact(used, Fraction(problem.total), problem.rule)
    tight = tight_rooms(used, exact.rents, exact.utilities)
    stream = None
    seed_hex = None
    if problem.random_source is not None:
        seed = fc.make_seed(TIE_RULE_NAME, problem.people, n, problem.random_source)
        seed_hex = seed.hex()
        stream = fc.SeedStream(seed)
    room_of, was_tie = choose_assignment(tight, problem.people, rooms, stream)
    verify_exact(
        used, Fraction(problem.total), room_of, exact.rents, exact.applied == APPLIED_NON_NEGATIVE
    )

    whole_shift = [fc.round_half_up(s) for s in shift_exact]
    shown = [[x + whole_shift[i] for x in row] for i, row in enumerate(problem.bids)]
    assignment = {problem.people[i]: rooms[room_of[i]] for i in range(n)}
    bids_map = {
        problem.people[i]: {rooms[k]: Fraction(shown[i][k], 100) for k in range(n)}
        for i in range(n)
    }
    prices = {rooms[k]: exact.rents[k] / 100 for k in range(n)}
    key = "rent-split|" + fc.canonical_json(
        {"people": sorted(problem.people), "rooms": sorted(rooms), "total": problem.total}
    )
    by_room = fc.round_min_envy(prices, problem.total, bids_map, assignment, key)
    rents = [by_room[room] for room in rooms]
    values = [[shown[i][k] - rents[k] for k in range(n)] for i in range(n)]
    surplus = [values[i][room_of[i]] for i in range(n)]
    max_envy = max(max(values[i]) - surplus[i] for i in range(n))
    if sum(rents) != problem.total or max_envy > 1:
        raise AssertionError("rounding left the total off or an envy above one cent")
    return Outcome(
        problem=problem,
        room_of=room_of,
        rents=rents,
        shown=shown,
        shift_exact=shift_exact,
        values=values,
        surplus=surplus,
        max_envy=max_envy,
        applied=exact.applied,
        was_tie=was_tie,
        seed_hex=seed_hex,
        exact_rents=exact.rents,
    )


# ---------------------------------------------------------------------------------------
# Texts (zh is the default, en says the same)
# ---------------------------------------------------------------------------------------

TEXT: dict[str, dict[str, Any]] = {
    "zh": {
        "sep": "、",
        "end": "。",
        "rule_spliddit": "先在没人倒贴的无嫉妒分法里找，找不到再允许倒贴（spliddit）",
        "rule_allow": "允许倒贴，住最差的房间可以倒收钱（allow）",
        "rule_forbid": "不许倒贴，找不到就全体重报（forbid）",
        "nm_strategy": "防策略：没有任何无嫉妒分租方法能防策略。",
        "nm_rooms": (
            "房间数和人数不等，以及两人合住但不是情侣的情形（情侣先商量出一组联合报价，当作一个人）。"
        ),
        "nm_budget": "有人最多只能付多少的预算上限。",
        "cell_paid": "{amount}（倒收）",
        "cert_gain": "按你报的价，{room}比你心里价位便宜 {amount}",
        "cert_zero": "按你报的价，{room}的房租正好等于你心里的价位",
        "cert_loss": "按你报的价，{room}比你心里价位贵 {amount}",
        "cert_envied": (
            "{head}。取整到分后，{envied}比这间多划算 {amount}，"
            "这是取整造成的误差（精确值下换哪间都不会更划算）"
        ),
        "cert_plain": "{head}，换哪间都不会更划算",
        "cert_ties": "；{ties}对你来说一样划算（{compare}），打平不算吃亏",
        "cmp_gain": "也便宜 {amount}",
        "cmp_zero": "也正好等于你的报价",
        "cmp_loss": "也贵 {amount}",
        "within_ok": "你付的不超过你自己给这间房的报价。",
        "within_over": (
            "你付的比你自己给这间房的报价多 {amount}，这是取整到分造成的（精确值下不超过报价）。"
        ),
        "shift_note": (
            "你报的价加起来是 {bid_sum}，比总租金 {total} {side} {gap}。"
            "脚本把你每间房的报价统一{detail}，不是按比例缩放，各房间之间的差额没变，"
            "所以你的比较结果不受影响。下面用的是调整后的报价。请确认，或者重报。"
        ),
        "side_less": "少",
        "side_more": "多",
        "detail_add": "加了 {amount}",
        "detail_sub": "减了 {amount}",
        "detail_exact": "（精确值是 {exact}，显示时取整到分）",
        "a_caption": "现在的分法体检",
        "a_hdr_opt": ["人", "现在住", "现在房租", "按自己的报价", "按规则该付", "现在每月"],
        "a_hdr_bad": [
            "人",
            "现在住",
            "现在房租",
            "按自己的报价",
            "规则建议住",
            "规则房租",
            "现在的好处",
            "规则下的好处",
        ],
        "ec_none": "不羡慕任何人",
        "ec_some": "羡慕{rooms} {amount}",
        "ev_none": "不羡慕任何人",
        "ev_some": "羡慕{rooms} {amount}",
        "dc_more": "多掏 {amount}",
        "dc_less": "少掏 {amount}",
        "dc_same": "和规则一致",
        "dv_more": "多掏 {amount}",
        "dv_less": "少掏 {amount}",
        "dv_same": "和规则一致",
        "a_bullet_opt": (
            "- {name} 住{now}：按自己的报价{envy}；按规则该付 {rule_rent}，现在每月{delta}"
        ),
        "a_group_opt": "{name} 住{now}：现在每月 {rent_now}，按规则该付 {rule_rent}（{delta}）",
        "a_bullet_bad": (
            "- {name} 现在住{now}（每月 {rent_now}）：按自己的报价{envy}；"
            "按规则建议住{new}，每月 {rule_rent}"
        ),
        "a_group_bad": "{name}：现在住{now}，每月 {rent_now}；建议住{new}，每月 {rule_rent}",
        "a_dm_head": "现在的分法体检：",
        "a_dm_now": "你现在住 {now}，每月付 {rent_now}。",
        "a_dm_envy": "按你报的价，现在的分法下你{envy}。",
        "a_dm_rule": "按规则，{now}每月该付 {rule_rent}，你现在每月{delta}。",
        "a_dm_envy_bad": (
            "按你报的价，现在的分法下你{envy}；你现在的好处（报价 - 房租）是 {gain_now}。"
        ),
        "a_dm_rule_bad": (
            "现在的住法不是总报价最高的住法，房租无论怎么定都做不到人人不羡慕。"
            "按规则建议你住 {new}，每月付 {rule_rent}，"
            "按你报的价好处是 {gain_rule}。"
        ),
        "a_verdict_opt": "现在的住法是总报价最高的住法（报价之和 {best}），问题只在房租怎么定。",
        "a_verdict_bad": (
            "现在的住法不是总报价最高的住法：这样住的报价之和是 {now}，低于最优住法的 {best}。"
            "这种住法下房租无论怎么定，都做不到人人不羡慕（Svensson 1983），所以先建议换房。"
        ),
        "a_group_head_opt": "现在的分法体检：住法没问题（总报价最高），差别只在房租怎么定。",
        "a_group_head_bad": (
            "现在的分法体检：现在的住法不是总报价最高的住法，"
            "房租无论怎么定都做不到人人不羡慕，建议换房。"
        ),
        "a_note": "{verdict}审计只做比较，不替大家决定改不改。\n\n{bullets}",
        "title": "分房租结果（总租金 {total}）",
        "t_hdr_assign": ["人", "房间", "每月房租", "对这间房的报价", "赚到（报价 - 房租）"],
        "t_cap_assign": "谁住哪间、付多少",
        "t_adjusted": "（调整后）",
        "t_total": "合计",
        "t_hdr_person": "人",
        "t_cap_envy": "羡慕表（报价 - 房租，带 * 的是本人房间，数越大越划算）",
        "t_rent_row": "房租",
        "n_rule": "规则（事先定好，结果出来后不再改）：{rule}。",
        "n_fallback": (
            "本次结果：找不到没人倒贴的无嫉妒分法，按规则改用允许倒贴的分法。"
            "倒收房租的房间：{rooms}。"
        ),
        "n_negative": "本次结果：有房间倒收房租：{rooms}。",
        "n_no_negative": "本次结果：没有人倒贴。",
        "n_envy_zero": (
            "取整到分后，没有人羡慕任何人（最大羡慕 0.00）。"
            "每间房租只向下或向上取到分，总额恰好等于总租金。"
        ),
        "n_envy_some": (
            "取整到分后，最大羡慕是 {amount}：精确值下没有羡慕，这是取整造成的，最多差 0.01。"
            "每间房租只向下或向上取到分，总额恰好等于总租金。"
        ),
        "n_tie_seed": (
            "有几种总报价相同的住法，已用规则里的公开随机源打破。"
            "种子（SHA-256）：{seed}。算法见 fsq_core 的 SEED_SPEC。"
        ),
        "n_seed_unused": "规则里给了公开随机源，但这次没有并列的住法，用不上。",
        "n_tie_names": (
            "有几种总报价相同的住法（房租和每人的好处都一样），没有提供公开随机源，"
            "按姓名排序打破。想要不偏向名字靠前的人，下次在规则消息里写一个公开随机源。"
        ),
        "n_shift": "{name}：{note}",
        "n_one_liners": "每人一句话（只发给本人，不要贴到群里）：",
        "n_one_liner": "- {name}：{text}",
        "n_audit_ignored": "输入里有 audit 块，这次没有加 --audit，所以没有做审计。",
        "dm_head": "{name}，这是只给你的分房租结果，别人看不到你的报价。",
        "dm_rule_split": "按规则的分法：",
        "dm_room_pay": "你住 {room}，每月付 {amount}。",
        "dm_room_paid": "你住 {room}，每月倒收 {amount}。",
        "dm_bid": "你给这间房的报价是 {bid}，赚到 {gain}。",
        "dm_table_head": "你的核对表（你的报价 - 房租，带 * 的是你住的房间，数越大越划算）：",
        "dm_table_row": "  {room}：{bid} - {rent} = {value}{star}",
        "g_room_pay": "{name} 住 {room}，每月付 {amount}",
        "g_room_paid": "{name} 住 {room}，每月倒收 {amount}",
        "g_total": "合计 {sum}，等于总租金 {total}。",
        "g_fallback": "没有找到没人倒贴的无嫉妒分法，按规则改用允许倒贴的分法。",
        "g_guarantee": (
            "保证：按各人私下报的价，没有人想和别人换房间（取整到分后最多差 {amount}）。"
            "每个人会收到一条只含自己数字的私信，可以自己核对。"
        ),
        "s_title": "储物间的例子：同一组报价，两种负房租规则",
        "s_hdr": ["人", "allow（允许倒贴）", "spliddit 和 forbid（不倒贴）"],
        "s_cell": "{room}，付 {rent}，赚 {gain}",
        "s_note": (
            "同一组报价，两种规则的结果都无嫉妒（取整到分后最大羡慕都是 {worst}）。"
            "看完结果再表决的话，甲乙会选第二列，所以规则必须在收报价之前定好。"
        ),
        "c_lines": [
            "承诺码（现在就发到群里）：{digest}",
            "盐（自己保管，收齐别人的报价后和下面的原文一起公开）：{nonce}",
            "承诺的原文（自己保管，先不要公开）：{payload}",
            "",
            "核对：公开盐和原文后，任何人用 --verify-commit 加上承诺码、盐和完整输入核对。",
            "也可以手算：承诺码 = SHA-256(fsq-commit-v1 + 换行 + 盐 + 换行 + 原文)。",
            "",
        ],
        "v_ok": "核对通过：{person} 的报价和盐与承诺码一致。",
        "v_bad": "核对失败：{person} 的报价或盐与承诺码不一致，不要采用这份输入。",
    },
    "en": {
        "sep": ", ",
        "end": ".",
        "rule_spliddit": (
            "first look for an envy-free split in which nobody is paid to live in a room, "
            "and allow that only if none exists (spliddit)"
        ),
        "rule_allow": (
            "paying someone to live in a room is allowed, so the person in the least wanted "
            "room may receive money (allow)"
        ),
        "rule_forbid": (
            "nobody may be paid to live in a room, and if no such split exists everybody "
            "bids again (forbid)"
        ),
        "nm_strategy": "Strategy-proofness: no envy-free rent division method is strategy-proof.",
        "nm_rooms": (
            "Different numbers of rooms and people, and two people who share a room without "
            "being a couple (a couple first agrees on one joint set of bids and counts as one "
            "person)."
        ),
        "nm_budget": "A budget limit on the most a person can pay.",
        "cell_paid": "{amount} (paid to live there)",
        "cert_gain": "By your bids, {room} is {amount} cheaper than the price you had in mind",
        "cert_zero": "By your bids, the rent of {room} is exactly the price you had in mind",
        "cert_loss": (
            "By your bids, {room} is {amount} more expensive than the price you had in mind"
        ),
        "cert_envied": (
            "{head}. After rounding to the cent, {envied} would be {amount} better for you "
            "than this room. That is a rounding error (at the exact values no other room is "
            "a better deal)"
        ),
        "cert_plain": "{head}, and no other room is a better deal",
        "cert_ties": (
            ". {ties} would be exactly as good a deal for you ({compare}), and a tie is not a loss"
        ),
        "cmp_gain": "also {amount} cheaper than your price",
        "cmp_zero": "also exactly your price",
        "cmp_loss": "also {amount} more expensive than your price",
        "within_ok": "You pay no more than your own bid for this room.",
        "within_over": (
            "You pay {amount} more than your own bid for this room. That comes from rounding "
            "to the cent (at the exact values it is not above the bid)."
        ),
        "shift_note": (
            "Your bids add up to {bid_sum}, which is {gap} {side} the total rent of {total}. "
            "The script moved each of your room bids by the same amount, {detail}, and did not "
            "scale them in proportion. The differences between rooms stay the same, so your "
            "comparison is not affected. The numbers below use the adjusted bids. Please "
            "confirm them or bid again."
        ),
        "side_less": "less than",
        "side_more": "more than",
        "detail_add": "adding {amount}",
        "detail_sub": "subtracting {amount}",
        "detail_exact": " (the exact value is {exact}, rounded to the cent for display)",
        "a_caption": "Check of the current split",
        "a_hdr_opt": [
            "Person",
            "Lives in now",
            "Rent now",
            "Envies, by own bids",
            "Rent by the rule",
            "Now, compared with the rule",
        ],
        "a_hdr_bad": [
            "Person",
            "Lives in now",
            "Rent now",
            "Envies, by own bids",
            "Room by the rule",
            "Rent by the rule",
            "Gain now",
            "Gain by the rule",
        ],
        "ec_none": "nobody",
        "ec_some": "{rooms} by {amount}",
        "ev_none": "envy nobody",
        "ev_some": "envy {rooms} by {amount}",
        "dc_more": "{amount} more",
        "dc_less": "{amount} less",
        "dc_same": "same as the rule",
        "dv_more": "pay {amount} more than that",
        "dv_less": "pay {amount} less than that",
        "dv_same": "pay exactly that",
        "a_bullet_opt": (
            "- {name} lives in {now}: by their own bids they {envy}; the rent by the rule is "
            "{rule_rent}, and they now {delta}"
        ),
        "a_group_opt": (
            "{name} lives in {now}: pays {rent_now} a month now, the rent by the rule is "
            "{rule_rent} ({delta})"
        ),
        "a_bullet_bad": (
            "- {name} lives in {now} now ({rent_now} a month): by their own bids they {envy}; "
            "the rule suggests {new} at {rule_rent} a month"
        ),
        "a_group_bad": (
            "{name}: lives in {now} now at {rent_now} a month; the rule suggests {new} at "
            "{rule_rent} a month"
        ),
        "a_dm_head": "Check of the current split:",
        "a_dm_now": "You live in {now} now and pay {rent_now} a month.",
        "a_dm_envy": "By your bids, under the current split you {envy}.",
        "a_dm_rule": "By the rule, {now} costs {rule_rent} a month, and you now {delta}.",
        "a_dm_envy_bad": (
            "By your bids, under the current split you {envy}. Your gain now (bid - rent) "
            "is {gain_now}."
        ),
        "a_dm_rule_bad": (
            "The current rooms are not the ones with the highest total of bids, so no choice "
            "of rents can make everybody envy-free. The rule suggests that you live in {new} "
            "and pay {rule_rent} a month, which gives you a gain of {gain_rule} by your bids."
        ),
        "a_verdict_opt": (
            "The current rooms are the ones with the highest total of bids ({best}), so the "
            "only question is how the rents are set."
        ),
        "a_verdict_bad": (
            "The current rooms are not the ones with the highest total of bids: they add up to "
            "{now}, below the best total of {best}. With these rooms no choice of rents can "
            "make everybody envy-free (Svensson 1983), so the first advice is to change rooms."
        ),
        "a_group_head_opt": (
            "Check of the current split: the rooms are fine (highest total of bids), and only "
            "the rents differ."
        ),
        "a_group_head_bad": (
            "Check of the current split: the current rooms are not the ones with the highest "
            "total of bids, so no choice of rents can make everybody envy-free. A change of "
            "rooms is suggested."
        ),
        "a_note": (
            "{verdict} The audit only compares. The group decides whether to change anything."
            "\n\n{bullets}"
        ),
        "title": "Rent split result (total rent {total})",
        "t_hdr_assign": [
            "Person",
            "Room",
            "Rent per month",
            "Bid for this room",
            "Gain (bid - rent)",
        ],
        "t_cap_assign": "Who lives where and pays what",
        "t_adjusted": " (adjusted)",
        "t_total": "Total",
        "t_hdr_person": "Person",
        "t_cap_envy": (
            "Envy table (bid - rent, the room marked * is the person's own, a larger number is "
            "a better deal)"
        ),
        "t_rent_row": "Rent",
        "n_rule": "Rule (fixed in advance, not changed after the result): {rule}.",
        "n_fallback": (
            "This result: no envy-free split without a negative rent exists, so the rule fell "
            "back to the split that allows it. Rooms where the person is paid to live: {rooms}."
        ),
        "n_negative": "This result: some rooms have a negative rent and the person living there is paid: {rooms}.",
        "n_no_negative": "This result: nobody is paid to live in a room.",
        "n_envy_zero": (
            "After rounding to the cent, nobody envies anybody (largest envy 0.00). Each rent is "
            "rounded only down or up to the cent, and the total is exactly the total rent."
        ),
        "n_envy_some": (
            "After rounding to the cent, the largest envy is {amount}. There is no envy at the "
            "exact values, so this is caused by rounding and is at most 0.01. Each rent is "
            "rounded only down or up to the cent, and the total is exactly the total rent."
        ),
        "n_tie_seed": (
            "Several assignments have the same total of bids, and the public random source in "
            "the rules broke the tie. Seed (SHA-256): {seed}. The algorithm is SEED_SPEC in "
            "fsq_core."
        ),
        "n_seed_unused": (
            "The rules name a public random source, but no assignments tie this time, so it "
            "was not needed."
        ),
        "n_tie_names": (
            "Several assignments have the same total of bids (the rents and everybody's gain "
            "are the same), and no public random source was given, so the tie was broken by "
            "sorting the names. To avoid favoring names that sort first, put a public random "
            "source in the rules message next time."
        ),
        "n_shift": "{name}: {note}",
        "n_one_liners": "One line per person (send it to that person only, not to the group):",
        "n_one_liner": "- {name}: {text}",
        "n_audit_ignored": (
            "The input has an audit block, but --audit was not given, so no audit was done."
        ),
        "dm_head": "{name}, this is your own rent result. Nobody else can see your bids.",
        "dm_rule_split": "The split by the rule:",
        "dm_room_pay": "You live in {room} and pay {amount} a month.",
        "dm_room_paid": "You live in {room} and are paid {amount} a month.",
        "dm_bid": "Your bid for this room is {bid}, so you gain {gain}.",
        "dm_table_head": (
            "Your check table (your bid - rent, the room marked * is the one you live in, a "
            "larger number is a better deal):"
        ),
        "dm_table_row": "  {room}: {bid} - {rent} = {value}{star}",
        "g_room_pay": "{name} lives in {room} and pays {amount} a month",
        "g_room_paid": "{name} lives in {room} and is paid {amount} a month",
        "g_total": "Total {sum}, equal to the total rent of {total}.",
        "g_fallback": (
            "No envy-free split without a negative rent exists, so the rule fell back to the "
            "split that allows it."
        ),
        "g_guarantee": (
            "Guarantee: judged by the bids each person gave in private, nobody wants to swap "
            "rooms with anybody (after rounding to the cent the difference is at most "
            "{amount}). Everybody gets a private message with only their own numbers, so each "
            "person can check it."
        ),
        "s_title": "The storage room example: the same bids under two negative-rent rules",
        "s_hdr": [
            "Person",
            "allow (paying someone is allowed)",
            "spliddit and forbid (nobody is paid)",
        ],
        "s_cell": "{room}, pays {rent}, gains {gain}",
        "s_note": (
            "With the same bids, both rules give a split without envy (after rounding to the "
            "cent the largest envy is {worst} in both). If the group voted after seeing the "
            "results, 甲 and 乙 would choose the second column, so the rule must be fixed "
            "before the bids are collected."
        ),
        "c_lines": [
            "Commitment code (post it in the group now): {digest}",
            (
                "Nonce (keep it to yourself, and publish it with the text below once everybody "
                "else's bids are in): {nonce}"
            ),
            "Committed text (keep it to yourself and do not show it yet): {payload}",
            "",
            (
                "To check: once the nonce and the text are public, anyone can run "
                "--verify-commit with the commitment code, the nonce and the full input."
            ),
            (
                "It can also be checked by hand: commitment code = SHA-256(fsq-commit-v1 + "
                "newline + nonce + newline + text)."
            ),
            "",
        ],
        "v_ok": "Check passed: the bids of {person} and the nonce match the commitment code.",
        "v_bad": (
            "Check failed: the bids of {person} or the nonce do not match the commitment code. "
            "Do not use this input."
        ),
    },
}


def say(lang: str, key: str, **values: Any) -> str:
    """Fill the text template of this key (see fsq_core.fill_text for the Latin-name spacing)."""
    return fc.fill_text(lang, TEXT[lang][key], **values)


def joined(lang: str, items: Iterable[str]) -> str:
    """Names joined with the separator of the language."""
    return TEXT[lang]["sep"].join(items)


def not_modeled(lang: str = "zh") -> list[str]:
    """What the result does not cover, one sentence each."""
    text = TEXT[lang]
    return [text[key] for key in ("nm_strategy", "nm_rooms", "nm_budget")]


def rent_cell(rent: int, lang: str = "zh") -> str:
    """A rent for a table cell; a negative rent is marked as money received."""
    return say(lang, "cell_paid", amount=fmt(rent)) if rent < 0 else fmt(rent)


def _compare_phrase(surplus: int, lang: str) -> str:
    if surplus > 0:
        return say(lang, "cmp_gain", amount=fmt(surplus))
    if surplus == 0:
        return say(lang, "cmp_zero")
    return say(lang, "cmp_loss", amount=fmt(-surplus))


def certificate_line(
    room: str,
    surplus: int,
    ties: Sequence[str],
    envied: Sequence[str],
    envy: int,
    lang: str = "zh",
) -> str:
    """The one-sentence certificate of a person, in the person's own numbers.

    surplus is the person's bid for their room minus its rent. ties are the other rooms with
    exactly the same value for the person. envied are rooms that look better by `envy` cents
    only because of rounding (never more than one cent).
    """
    if surplus > 0:
        head = say(lang, "cert_gain", room=room, amount=fmt(surplus))
    elif surplus == 0:
        head = say(lang, "cert_zero", room=room)
    else:
        head = say(lang, "cert_loss", room=room, amount=fmt(-surplus))
    if envied:
        text = say(lang, "cert_envied", head=head, envied=joined(lang, envied), amount=fmt(envy))
    else:
        text = say(lang, "cert_plain", head=head)
    if ties:
        text += say(
            lang, "cert_ties", ties=joined(lang, ties), compare=_compare_phrase(surplus, lang)
        )
    return text + TEXT[lang]["end"]


def within_bid_line(rent: int, bid: int, lang: str = "zh") -> str:
    """The sentence that the person pays no more than their own bid for the room."""
    if rent <= bid:
        return say(lang, "within_ok")
    return say(lang, "within_over", amount=fmt(rent - bid))


def exact_text(amount_cents: Fraction) -> str:
    """An amount given in cents, as a decimal in units ('-25.00') or a fraction ('-1/3')."""
    if amount_cents.denominator == 1:
        return fmt(int(amount_cents))
    units = amount_cents / 100
    return f"{units.numerator}/{units.denominator}"


def shift_note(outcome: Outcome, i: int, lang: str = "zh") -> str:
    """What happened to person i's bids when they did not add up to the total rent."""
    p = outcome.problem
    exact = outcome.shift_exact[i]
    whole = fc.round_half_up(exact)
    bid_sum = sum(p.bids[i])
    gap = p.total - bid_sum
    side = say(lang, "side_less" if gap > 0 else "side_more")
    detail = say(lang, "detail_add" if exact > 0 else "detail_sub", amount=fmt(abs(whole)))
    if exact.denominator != 1:
        detail += say(lang, "detail_exact", exact=exact_text(abs(exact)))
    return say(
        lang,
        "shift_note",
        bid_sum=fmt(bid_sum),
        total=fmt(p.total),
        side=side,
        gap=fmt(abs(gap)),
        detail=detail,
    )


def tie_and_envy(outcome: Outcome, i: int) -> tuple[list[int], list[int], int]:
    """Rooms that tie with person i's own, rooms that look better, and the largest gap."""
    row, own = outcome.values[i], outcome.room_of[i]
    mine = row[own]
    others = [k for k in range(len(row)) if k != own]
    ties = [k for k in others if row[k] == mine]
    envied = [k for k in others if row[k] > mine]
    return ties, envied, max((row[k] - mine for k in envied), default=0)


def person_certificate(outcome: Outcome, i: int, lang: str = "zh") -> tuple[str, str]:
    """The one-sentence certificate of person i and the 'not above your bid' sentence."""
    p = outcome.problem
    own = outcome.room_of[i]
    ties, envied, envy = tie_and_envy(outcome, i)
    line = certificate_line(
        p.rooms[own],
        outcome.surplus[i],
        [p.rooms[k] for k in ties],
        [p.rooms[k] for k in envied],
        envy,
        lang,
    )
    return line, within_bid_line(outcome.rents[own], outcome.shown[i][own], lang)


# ---------------------------------------------------------------------------------------
# Audit of a split the group already uses
# ---------------------------------------------------------------------------------------


@dataclass
class AuditPerson:
    """One person under the current split and under the rule's split."""

    room_now: int
    rent_now: int
    surplus_now: int
    envy: int  # largest envy at the current split, 0 if none
    envied: list[int]  # the rooms with that envy
    rule_room: int  # the person's room under the rule (the current room if it is optimal)
    rule_rent: int
    surplus_rule: int
    delta: int  # current rent minus the rule's rent for the current room


@dataclass
class AuditReport:
    """The audit: is the current assignment welfare-maximising, and who gains or loses."""

    optimal: bool
    welfare_now: int
    welfare_best: int
    people: list[AuditPerson]


def audit_split(outcome: Outcome) -> AuditReport:
    """Compare the current split with the rule's split, in each person's own numbers."""
    p = outcome.problem
    audit = p.audit
    if audit is None:
        raise fc.InputError("audit", "is required with --audit: the current rooms and rents")
    n = len(p.people)
    room_index = {room: k for k, room in enumerate(p.rooms)}
    now = [room_index[audit.rooms[name]] for name in p.people]
    rent_of_room = [0] * n
    for i, name in enumerate(p.people):
        rent_of_room[now[i]] = audit.rents[name]
    welfare_now = sum(outcome.shown[i][now[i]] for i in range(n))
    welfare_best = sum(outcome.shown[i][outcome.room_of[i]] for i in range(n))
    optimal = welfare_now == welfare_best
    people = []
    for i, name in enumerate(p.people):
        here = outcome.shown[i][now[i]] - audit.rents[name]
        gaps = {k: outcome.shown[i][k] - rent_of_room[k] - here for k in range(n) if k != now[i]}
        envy = max(max(gaps.values()), 0)
        envied = [k for k, gap in gaps.items() if envy > 0 and gap == envy]
        room = now[i] if optimal else outcome.room_of[i]
        people.append(
            AuditPerson(
                room_now=now[i],
                rent_now=audit.rents[name],
                surplus_now=here,
                envy=envy,
                envied=envied,
                rule_room=room,
                rule_rent=outcome.rents[room],
                surplus_rule=outcome.shown[i][room] - outcome.rents[room],
                delta=audit.rents[name] - outcome.rents[now[i]],
            )
        )
    return AuditReport(optimal, welfare_now, welfare_best, people)


def _delta_text(delta: int, lang: str, verb: bool = False) -> str:
    """How far the current rent is from the rule's: a table cell, or a verb phrase (verb=True)."""
    kind = "more" if delta > 0 else "less" if delta < 0 else "same"
    return say(lang, ("dv_" if verb else "dc_") + kind, amount=fmt(abs(delta)))


def _envy_text(rooms: Sequence[str], person: AuditPerson, lang: str, verb: bool = False) -> str:
    """Who the person envies at the current split: a table cell, or a verb phrase (verb=True)."""
    prefix = "ev_" if verb else "ec_"
    if person.envy <= 0:
        return say(lang, prefix + "none")
    envied = joined(lang, [rooms[k] for k in person.envied])
    return say(lang, prefix + "some", rooms=envied, amount=fmt(person.envy))


@dataclass
class AuditView:
    """The audit as it appears in each output: a table, notes, messages and JSON."""

    table: fc.Table
    note: str
    group: list[str]
    private: dict[str, list[str]]
    payload: dict[str, Any]


def audit_view(outcome: Outcome, report: AuditReport, lang: str = "zh") -> AuditView:
    """Write the audit report for the organizer, each person and the group."""
    text = TEXT[lang]
    p = outcome.problem
    rooms = p.rooms
    rows: list[list[str]] = []
    bullets: list[str] = []
    group: list[str] = []
    private: dict[str, list[str]] = {}
    per_person: dict[str, Any] = {}
    for i, name in enumerate(p.people):
        a = report.people[i]
        per_person[name] = {
            "room_now": rooms[a.room_now],
            "rent_now_cents": fc.Cents(a.rent_now),
            "surplus_now_cents": fc.Cents(a.surplus_now),
            "envy_cents": fc.Cents(a.envy),
            "envied_rooms": [rooms[k] for k in a.envied],
            "rule_room": rooms[a.rule_room],
            "rule_rent_cents": fc.Cents(a.rule_rent),
            "surplus_rule_cents": fc.Cents(a.surplus_rule),
            "delta_cents": fc.Cents(a.delta) if report.optimal else None,
        }
        envy = _envy_text(rooms, a, lang)
        envy_verb = _envy_text(rooms, a, lang, verb=True)
        now = f"{rooms[a.room_now]}"
        shown = {
            "name": name,
            "now": now,
            "rent_now": fmt(a.rent_now),
            "rule_rent": fmt(a.rule_rent),
        }
        if report.optimal:
            delta = _delta_text(a.delta, lang)
            delta_verb = _delta_text(a.delta, lang, verb=True)
            rows.append([name, now, fmt(a.rent_now), envy, fmt(a.rule_rent), delta])
            bullets.append(say(lang, "a_bullet_opt", envy=envy_verb, delta=delta_verb, **shown))
            group.append(say(lang, "a_group_opt", delta=delta, **shown))
            mine = [
                say(lang, "a_dm_now", **shown),
                say(lang, "a_dm_envy", envy=envy_verb),
                say(lang, "a_dm_rule", delta=delta_verb, **shown),
            ]
        else:
            new = rooms[a.rule_room]
            rows.append(
                [
                    name,
                    now,
                    fmt(a.rent_now),
                    envy,
                    new,
                    fmt(a.rule_rent),
                    fmt(a.surplus_now),
                    fmt(a.surplus_rule),
                ]
            )
            bullets.append(say(lang, "a_bullet_bad", envy=envy_verb, new=new, **shown))
            group.append(say(lang, "a_group_bad", new=new, **shown))
            mine = [
                say(lang, "a_dm_now", **shown),
                say(lang, "a_dm_envy_bad", envy=envy_verb, gain_now=fmt(a.surplus_now)),
                say(lang, "a_dm_rule_bad", new=new, gain_rule=fmt(a.surplus_rule), **shown),
            ]
        private[name] = [text["a_dm_head"], *mine]
    if report.optimal:
        header = list(text["a_hdr_opt"])
        verdict = say(lang, "a_verdict_opt", best=fmt(report.welfare_best))
        group_head = text["a_group_head_opt"]
    else:
        header = list(text["a_hdr_bad"])
        verdict = say(
            lang, "a_verdict_bad", now=fmt(report.welfare_now), best=fmt(report.welfare_best)
        )
        group_head = text["a_group_head_bad"]
    json_part = {
        "assignment_is_optimal": report.optimal,
        "bids_total_now_cents": fc.Cents(report.welfare_now),
        "bids_total_best_cents": fc.Cents(report.welfare_best),
        "per_person": per_person,
    }
    return AuditView(
        table=fc.Table(header, rows, text["a_caption"]),
        note=say(lang, "a_note", verdict=verdict, bullets="\n".join(bullets)),
        group=[group_head, *group],
        private=private,
        payload=json_part,
    )


# ---------------------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------------------


def _bid_tables(outcome: Outcome, lang: str = "zh") -> list[fc.Table]:
    text = TEXT[lang]
    p = outcome.problem
    n = len(p.people)
    rows = []
    for i, name in enumerate(p.people):
        own = outcome.room_of[i]
        adjusted = text["t_adjusted"] if outcome.shift_exact[i] != 0 else ""
        bid = fmt(outcome.shown[i][own]) + adjusted
        rows.append(
            [name, p.rooms[own], rent_cell(outcome.rents[own], lang), bid, fmt(outcome.surplus[i])]
        )
    rows.append([text["t_total"], "", fmt(sum(outcome.rents)), "", ""])
    assignment = fc.Table(list(text["t_hdr_assign"]), rows, text["t_cap_assign"])
    envy_rows = []
    for i, name in enumerate(p.people):
        cells = [
            fmt(outcome.values[i][k]) + ("*" if k == outcome.room_of[i] else "") for k in range(n)
        ]
        envy_rows.append([name, *cells])
    envy_rows.append([text["t_rent_row"], *[rent_cell(r, lang) for r in outcome.rents]])
    envy = fc.Table([text["t_hdr_person"], *p.rooms], envy_rows, text["t_cap_envy"])
    return [assignment, envy]


def _rule_line(outcome: Outcome, lang: str) -> str:
    """The agreed rule for negative rents, as the first line of the notes and the group card."""
    return say(lang, "n_rule", rule=TEXT[lang]["rule_" + outcome.problem.rule])


def _notes(outcome: Outcome, lang: str = "zh") -> list[str]:
    p = outcome.problem
    notes = [_rule_line(outcome, lang)]
    negative = joined(lang, [p.rooms[k] for k, r in enumerate(outcome.rents) if r < 0])
    if outcome.applied == APPLIED_FALLBACK:
        notes.append(say(lang, "n_fallback", rooms=negative))
    elif negative:
        notes.append(say(lang, "n_negative", rooms=negative))
    else:
        notes.append(say(lang, "n_no_negative"))
    if outcome.max_envy == 0:
        notes.append(say(lang, "n_envy_zero"))
    else:
        notes.append(say(lang, "n_envy_some", amount=fmt(outcome.max_envy)))
    if outcome.seed_hex is not None and outcome.was_tie:
        notes.append(say(lang, "n_tie_seed", seed=outcome.seed_hex))
    elif outcome.seed_hex is not None:
        notes.append(say(lang, "n_seed_unused"))
    elif outcome.was_tie:
        notes.append(say(lang, "n_tie_names"))
    for i, name in enumerate(p.people):
        if outcome.shift_exact[i] != 0:
            notes.append(say(lang, "n_shift", name=name, note=shift_note(outcome, i, lang)))
    return notes


def _person_lines(
    outcome: Outcome, i: int, audit_lines: Sequence[str] = (), lang: str = "zh"
) -> list[str]:
    """The private message of person i: only their own numbers and the public rents."""
    text = TEXT[lang]
    p = outcome.problem
    name, own = p.people[i], outcome.room_of[i]
    line, within = person_certificate(outcome, i, lang)
    lines = [say(lang, "dm_head", name=name)]
    if audit_lines:
        lines += [*audit_lines, text["dm_rule_split"]]
    rent = outcome.rents[own]
    lines += [
        say(
            lang,
            "dm_room_paid" if rent < 0 else "dm_room_pay",
            room=p.rooms[own],
            amount=fmt(abs(rent)),
        ),
        say(lang, "dm_bid", bid=fmt(outcome.shown[i][own]), gain=fmt(outcome.surplus[i])),
    ]
    if outcome.shift_exact[i] != 0:
        lines.append(shift_note(outcome, i, lang))
    lines += [line, within, text["dm_table_head"]]
    for k, room in enumerate(p.rooms):
        rent = outcome.rents[k]
        rent_text = f"({fmt(rent)})" if rent < 0 else fmt(rent)
        star = " *" if k == own else ""
        lines.append(
            say(
                lang,
                "dm_table_row",
                room=room,
                bid=fmt(outcome.shown[i][k]),
                rent=rent_text,
                value=fmt(outcome.values[i][k]),
                star=star,
            )
        )
    return lines


def _group_lines(outcome: Outcome, lang: str = "zh") -> list[str]:
    p = outcome.problem
    lines = [_rule_line(outcome, lang)]
    for i, name in enumerate(p.people):
        own = outcome.room_of[i]
        rent = outcome.rents[own]
        lines.append(
            say(
                lang,
                "g_room_paid" if rent < 0 else "g_room_pay",
                name=name,
                room=p.rooms[own],
                amount=fmt(abs(rent)),
            )
        )
    lines.append(say(lang, "g_total", sum=fmt(sum(outcome.rents)), total=fmt(p.total)))
    if outcome.applied == APPLIED_FALLBACK:
        lines.append(say(lang, "g_fallback"))
    lines.append(say(lang, "g_guarantee", amount=fmt(outcome.max_envy)))
    return lines


def _reproduce(audit: bool, lang: str = "zh") -> str:
    """The command of a run on standard input, for callers that give no command of their own."""
    flag = (" --audit" if audit else "") + (f" --lang {lang}" if lang != "zh" else "")
    return f"python3 scripts/rent_split.py --input - --format md{flag}"


def reproduce_command(args: argparse.Namespace) -> str:
    """The command line of this run, with every option that changes the output."""
    parts = ["python3", "scripts/rent_split.py"]
    parts += ["--demo"] if args.demo else ["--input", "-"]
    parts += ["--json"] if args.json else ["--format", args.format]
    if args.audit:
        parts.append("--audit")
    if args.lang != "zh":
        parts += ["--lang", args.lang]
    return " ".join(parts)


def _json_parts(
    outcome: Outcome, lang: str = "zh"
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    p = outcome.problem
    n = len(p.people)
    echo: dict[str, Any] = {
        "total_rent": fc.Cents(p.total),
        "rooms": list(p.rooms),
        "bids": {
            name: {p.rooms[k]: fc.Cents(p.bids[i][k]) for k in range(n)}
            for i, name in enumerate(p.people)
        },
        "rules": {"negative_rent": p.rule},
    }
    if p.random_source is not None:
        echo["rules"]["random_source"] = p.random_source
    shifted = {
        name: {
            "bids_sum_cents": fc.Cents(sum(p.bids[i])),
            "exact_shift_per_room": exact_text(outcome.shift_exact[i]),
            "shown_shift_per_room_cents": fc.Cents(fc.round_half_up(outcome.shift_exact[i])),
        }
        for i, name in enumerate(p.people)
        if outcome.shift_exact[i] != 0
    }
    if outcome.was_tie:
        method = "random_source" if outcome.seed_hex is not None else "sorted_names"
    else:
        method = "not_needed"
    result: dict[str, Any] = {
        "assignment": {name: p.rooms[outcome.room_of[i]] for i, name in enumerate(p.people)},
        "rent_cents": {room: fc.Cents(outcome.rents[k]) for k, room in enumerate(p.rooms)},
        "surplus_cents": {name: fc.Cents(outcome.surplus[i]) for i, name in enumerate(p.people)},
        "rule": p.rule,
        "rule_applied": outcome.applied,
        "has_negative_rent": any(r < 0 for r in outcome.rents),
        "max_envy_cents": fc.Cents(outcome.max_envy),
        "shifted": shifted,
        "tie_break": {"was_tie": outcome.was_tie, "method": method, "seed_hex": outcome.seed_hex},
    }
    certificate: dict[str, Any] = {
        "envy_table": {
            name: {p.rooms[k]: fc.Cents(outcome.values[i][k]) for k in range(n)}
            for i, name in enumerate(p.people)
        },
        "one_liner": {
            name: person_certificate(outcome, i, lang)[0] for i, name in enumerate(p.people)
        },
        "ties": {
            name: [p.rooms[k] for k in tie_and_envy(outcome, i)[0]]
            for i, name in enumerate(p.people)
        },
        "rent_within_own_bid": {
            name: outcome.rents[outcome.room_of[i]] <= outcome.shown[i][outcome.room_of[i]]
            for i, name in enumerate(p.people)
        },
    }
    return echo, result, certificate


def build_result(
    outcome: Outcome,
    report: AuditReport | None = None,
    ignored_audit: bool = False,
    lang: str = "zh",
    reproduce: str | None = None,
) -> fc.Result:
    """Turn an Outcome (and an optional audit) into the Result the core writes out."""
    if lang not in TEXT:
        raise ValueError(f"lang must be one of {', '.join(TEXT)}")
    p = outcome.problem
    echo, result, certificate = _json_parts(outcome, lang)
    view = audit_view(outcome, report, lang) if report is not None else None
    if view is not None and p.audit is not None:
        echo["audit"] = {
            "assignment": dict(p.audit.rooms),
            "rent": {name: fc.Cents(cents) for name, cents in p.audit.rents.items()},
        }
        result["audit"] = view.payload
    out = fc.Result(
        title=say(lang, "title", total=fmt(p.total)),
        inputs_echo=echo,
        result=result,
        certificate=certificate,
        not_modeled=not_modeled(lang),
        reproduce=reproduce if reproduce is not None else _reproduce(view is not None, lang),
    )
    out.tables = _bid_tables(outcome, lang)
    out.notes = _notes(outcome, lang)
    lines = [
        say(lang, "n_one_liner", name=name, text=person_certificate(outcome, i, lang)[0])
        for i, name in enumerate(p.people)
    ]
    out.notes.append(say(lang, "n_one_liners") + "\n\n" + "\n".join(lines))
    if ignored_audit:
        out.notes.append(say(lang, "n_audit_ignored"))
    out.group_lines = _group_lines(outcome, lang)
    for i, name in enumerate(p.people):
        audit_lines = view.private[name] if view is not None else ()
        out.person_lines[name] = _person_lines(outcome, i, audit_lines, lang)
    if view is not None:
        out.tables.insert(0, view.table)
        out.notes.insert(0, view.note)
        out.group_lines = [*view.group, "", *out.group_lines]
    return out


def analyse(
    data: Any, want_audit: bool = False, lang: str = "zh", reproduce: str | None = None
) -> fc.Result:
    """Validate parsed input, solve it and build the Result (the whole pipeline)."""
    problem = read_problem(data)
    if want_audit and problem.audit is None:
        raise fc.InputError("audit", "is required with --audit: the current rooms and rents")
    outcome = compute(problem)
    report = audit_split(outcome) if want_audit else None
    return build_result(
        outcome,
        report,
        ignored_audit=problem.audit is not None and not want_audit,
        lang=lang,
        reproduce=reproduce,
    )


# ---------------------------------------------------------------------------------------
# Commitments (the organizer goes first)
# ---------------------------------------------------------------------------------------


def commit_payload(problem: Problem, person: str | None) -> dict[str, Any]:
    """What a commitment covers: the person, the total rent and their bid for each room.

    The bids are keyed by room name, so the order of rooms in the input does not matter.
    """
    if person is None:
        if len(problem.people) != 1:
            raise fc.InputError("--person", "is required when bids holds more than one person")
        person = problem.people[0]
    if person not in problem.people:
        raise fc.InputError("--person", f"{person!r} is not a person listed in bids")
    row = problem.bids[problem.people.index(person)]
    return {
        "person": person,
        "total_rent": Fraction(problem.total, 100),
        "bids": {room: Fraction(row[k], 100) for k, room in enumerate(problem.rooms)},
    }


def run_commit(args: argparse.Namespace) -> int:
    """--commit: print the commitment code, the nonce and the committed text."""
    payload = commit_payload(read_problem(fc.read_object(args), partial=True), args.person)
    commitment = fc.commit(payload, args.nonce)
    if args.json:
        record = {"digest": commitment.digest, "nonce": commitment.nonce, "payload": payload}
        sys.stdout.write(fc.canonical_json(record) + "\n")
        return 0
    lines = [
        fc.fill_text(
            args.lang,
            line,
            digest=commitment.digest,
            nonce=commitment.nonce,
            payload=fc.canonical_json(payload),
        )
        for line in TEXT[args.lang]["c_lines"]
    ]
    sys.stdout.write("\n".join(lines))
    return 0


def run_verify(args: argparse.Namespace) -> int:
    """--verify-commit: check the revealed bids against a published commitment code."""
    if args.nonce is None:
        raise fc.InputError("--nonce", "is required with --verify-commit")
    payload = commit_payload(read_problem(fc.read_object(args), partial=True), args.person)
    matched = fc.verify_commit(args.verify_commit, payload, args.nonce)
    if args.json:
        sys.stdout.write(fc.canonical_json({"match": matched, "person": payload["person"]}) + "\n")
    else:
        key = "v_ok" if matched else "v_bad"
        sys.stdout.write(say(args.lang, key, person=payload["person"]) + "\n")
    return 0 if matched else 1


# ---------------------------------------------------------------------------------------
# Demo and self-test
# ---------------------------------------------------------------------------------------

DEMO_JSON = """{
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
}"""

STORAGE_JSON = """{
  "total_rent": 6000,
  "rooms": ["大主卧", "朝南卧", "储物间改的小间"],
  "bids": {"甲": [4800, 1000, 200], "乙": [1000, 4800, 200], "丙": [2900, 2900, 200]},
  "rules": {"negative_rent": "spliddit"}
}"""


def storage_comparison(lang: str = "zh") -> fc.Result:
    """The three-person example under allow and under spliddit, side by side."""
    text = TEXT[lang]
    base = fc.parse_input(STORAGE_JSON)
    outcomes = {
        rule: compute(read_problem({**base, "rules": {"negative_rent": rule}}))
        for rule in ("allow", "spliddit")
    }
    rows = []
    for i, name in enumerate(outcomes["allow"].problem.people):
        cells = [name]
        for outcome in outcomes.values():
            own = outcome.room_of[i]
            room = outcome.problem.rooms[own]
            cells.append(
                say(
                    lang,
                    "s_cell",
                    room=room,
                    rent=fmt(outcome.rents[own]),
                    gain=fmt(outcome.surplus[i]),
                )
            )
        rows.append(cells)
    table = fc.Table(list(text["s_hdr"]), rows)
    worst = fmt(max(outcome.max_envy for outcome in outcomes.values()))
    note = say(lang, "s_note", worst=worst)
    return fc.Result(title=text["s_title"], tables=[table], notes=[note])


def run_demo(args: argparse.Namespace) -> int:
    """--demo: the four-roommate example with an audit; md output adds the storage room."""
    result = analyse(
        fc.read_object(args, DEMO_JSON),
        want_audit=True,
        lang=args.lang,
        reproduce=reproduce_command(args),
    )
    if args.json or args.format != "md":
        fc.emit(result, args, lang=args.lang)
        return 0
    sys.stdout.write(
        fc.render_md(result, args.lang)
        + "\n"
        + fc.render_md(storage_comparison(args.lang), args.lang)
    )
    return 0


# A split in which nobody can be given a room for free of negative rent: nobody values the first
# room at anything, so whoever lives there must be paid.
NO_NON_NEGATIVE_BIDS = [[0, 2, 0, 4], [0, 3, 3, 0], [0, 1, 0, 5], [0, 0, 5, 1]]
NO_NON_NEGATIVE_TOTAL = 6


def selftest_checks() -> list[tuple[str, Callable[[], None]]]:
    """Named checks of the rent logic for --selftest (the core adds its own)."""

    def paid(outcome: Outcome) -> list[int]:
        return [outcome.rents[outcome.room_of[i]] for i in range(len(outcome.room_of))]

    def four() -> None:
        outcome = compute(read_problem(fc.parse_input(DEMO_JSON)))
        fc.expect(paid(outcome) == [95000, 225000, 315000, 165000], f"rents {paid(outcome)}")
        fc.expect(outcome.surplus == [25000, 25000, 25000, 35000], f"surplus {outcome.surplus}")
        fc.expect(outcome.max_envy == 0, "envy")

    def storage() -> None:
        base = fc.parse_input(STORAGE_JSON)
        got = {}
        for rule in NEGATIVE_RENT_RULES:
            got[rule] = paid(compute(read_problem({**base, "rules": {"negative_rent": rule}})))
        fc.expect(got["allow"] == [353333, 353333, -106666], f"allow {got['allow']}")
        fc.expect(got["spliddit"] == [300000, 300000, 0], f"spliddit {got['spliddit']}")
        fc.expect(got["forbid"] == got["spliddit"], "forbid equals spliddit when it is feasible")

    def pseudo_random() -> None:
        stream = fc.SeedStream(fc.make_seed("rent_split_selftest", ["cases"], 1, "selftest"))
        for _ in range(25):
            n = 2 + stream.below(4)
            total = 100 * (50 + stream.below(500))
            rows = []
            for _person in range(n):
                cuts = sorted(stream.below(total + 1) for _ in range(n - 1))
                rows.append([b - a for a, b in zip([0, *cuts], [*cuts, total])])
            for rule in ("allow", "spliddit"):
                solve_exact(rows, Fraction(total), rule)  # raises if not exactly envy-free

    def forbid() -> None:
        rows = [[Fraction(x) for x in row] for row in NO_NON_NEGATIVE_BIDS]
        total = Fraction(NO_NON_NEGATIVE_TOTAL)
        fc.expect(
            solve_exact(rows, total, "spliddit").applied == APPLIED_FALLBACK,
            "spliddit should fall back to allowing negative rent",
        )
        fc.expect(min(solve_exact(rows, total, "allow").rents) < 0, "allow should pay someone")
        try:
            solve_exact(rows, total, "forbid")
        except fc.NoSolution:
            return
        raise AssertionError("forbid should have no solution here")

    def shifting() -> None:
        plain = compute(read_problem(fc.parse_input(DEMO_JSON)))
        moved = fc.parse_input(DEMO_JSON)
        moved["bids"]["阿明"] = [x + 77 for x in moved["bids"]["阿明"]]
        fc.expect(compute(read_problem(moved)).rents == plain.rents, "a shift changed the rents")

    def ties() -> None:
        flat = {"total_rent": 900, "rooms": ["b", "a", "c"], "rules": {"negative_rent": "allow"}}
        flat["bids"] = {"y": [300, 300, 300], "x": [300, 300, 300], "z": [300, 300, 300]}
        result = analyse(flat).result
        fc.expect(sorted(result["rent_cents"].values()) == [30000] * 3, "equal rents")
        fc.expect(
            result["assignment"] == {"x": "a", "y": "b", "z": "c"}, "names pick rooms in order"
        )
        fc.expect(result["tie_break"]["method"] == "sorted_names", "tie-break method")

    def audit() -> None:
        text = fc.render_md(analyse(fc.parse_input(DEMO_JSON), want_audit=True))
        fc.expect("多掏 1,050.00" in text, "audit of the equal split")
        moved = fc.parse_input(DEMO_JSON)
        moved["audit"]["assignment"] = {
            "阿明": "主卧带卫",
            "小红": "南次卧",
            "大刘": "北次卧",
            "Coco": "小书房",
        }
        text = fc.render_md(analyse(moved, want_audit=True))
        fc.expect("不是总报价最高" in text, "audit of a wrong assignment")

    def commitment() -> None:
        payload = commit_payload(read_problem(fc.parse_input(DEMO_JSON), partial=True), "阿明")
        digest, nonce = fc.commit(payload)
        fc.expect(fc.verify_commit(digest, payload, nonce), "commitment round trip")
        payload["bids"]["小书房"] += 1
        fc.expect(not fc.verify_commit(digest, payload, nonce), "a changed bid must not verify")

    return [
        ("rent: four roommates", four),
        ("rent: storage room under the three rules", storage),
        ("rent: exact envy-freeness on pseudo-random bids", pseudo_random),
        ("rent: forbid has no solution where spliddit falls back", forbid),
        ("rent: shifting one person's bids changes nothing", shifting),
        ("rent: ties are broken by name without a random source", ties),
        ("rent: audit of an equal split and of a wrong assignment", audit),
        ("rent: commitment by person", commitment),
    ]


# ---------------------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rent_split.py",
        description=(
            "Envy-free rent division from private bids, exact to the cent. Reads one JSON "
            "object (total_rent, rooms, bids, rules and an optional audit block) from standard "
            "input or --input FILE and prints tables, private messages or a group summary, in "
            "Chinese by default or in English with --lang en. Bids that do not add up to the "
            "total rent are shifted, never scaled."
        ),
        epilog=fc.exit_codes_epilog(
            one="a commitment did not match (--verify-commit) or a self-test failed",
            three="the agreed rule has no solution for these bids",
        )
        + " A commitment is SHA-256 of fsq-commit-v1, newline, nonce, newline and the "
        "canonical JSON of the payload printed by --commit.",
    )
    fc.standard_args(parser)
    parser.add_argument(
        "--audit",
        action="store_true",
        help="also compare the split in the input's audit block with the rule's split",
    )
    fc.add_lang_option(parser, "JSON keys and names do not change")
    parser.add_argument(
        "--commit",
        action="store_true",
        help="print a commitment to one person's bids (the organizer goes first) and exit",
    )
    parser.add_argument(
        "--verify-commit",
        metavar="DIGEST",
        help="check the revealed bids in the input against a published commitment code",
    )
    parser.add_argument(
        "--person",
        metavar="NAME",
        help="whose bids to commit to or verify when the input lists several people",
    )
    parser.add_argument(
        "--nonce",
        metavar="HEX",
        help="--verify-commit: the 32 hex characters revealed with the bids. "
        "--commit: use this instead of a fresh random one (for tests only)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    fc.exclusive_modes(args, "--demo", "--selftest", "--commit", "--verify-commit")
    if (args.person is not None or args.nonce is not None) and not (
        args.commit or args.verify_commit is not None
    ):
        raise fc.InputError(
            "options", "--person and --nonce belong to --commit and --verify-commit"
        )
    if args.selftest:
        return fc.run_selftest(selftest_checks())
    if args.demo:
        return run_demo(args)
    if args.commit:
        return run_commit(args)
    if args.verify_commit is not None:
        return run_verify(args)
    fc.emit(
        analyse(
            fc.read_object(args),
            want_audit=args.audit,
            lang=args.lang,
            reproduce=reproduce_command(args),
        ),
        args,
        lang=args.lang,
    )
    return 0


if __name__ == "__main__":
    fc.run_cli(main)
