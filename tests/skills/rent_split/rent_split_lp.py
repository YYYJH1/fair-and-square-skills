"""Reference solutions of the rent division by linear programming (scipy is a dev dependency).

The tests compare the script's exact shortest-path solution with these. Amounts are scaled so
that the total rent is 1, which keeps the solver tolerances meaningful for any size of rent.
"""

from __future__ import annotations

from scipy.optimize import linprog

SLACK = 1e-9  # lets a level that was fixed one stage earlier survive solver round-off
TOLERANCE = 1e-7  # a person counts as stuck if they cannot gain more than this


def _scaled(rows: list[list[int]], total: int) -> list[list[float]]:
    return [[x / total for x in row] for row in rows]


def lp_maximin(
    rows: list[list[int]], total: int, room_of: list[int], non_negative: bool
) -> float | None:
    """The largest possible smallest utility among envy-free rents, as a fraction of the total.

    The assignment room_of is fixed (any welfare-maximising one works). Variables are the room
    prices p and the level t; None means that no envy-free prices exist (only possible with
    non_negative, where prices may not go below zero).
    """
    values = _scaled(rows, total)
    n = len(values)
    cost = [0.0] * n + [-1.0]
    a_ub, b_ub = [], []
    for i in range(n):
        own = room_of[i]
        row = [0.0] * (n + 1)
        row[own] = 1.0
        row[n] = 1.0  # t + p_own <= v_i(own)
        a_ub.append(row)
        b_ub.append(values[i][own])
        for j in range(n):
            if j != own:
                row = [0.0] * (n + 1)
                row[own] += 1.0
                row[j] -= 1.0  # p_own - p_j <= v_i(own) - v_i(j)
                a_ub.append(row)
                b_ub.append(values[i][own] - values[i][j])
    bounds = [(0 if non_negative else None, None)] * n + [(None, None)]
    found = linprog(
        cost,
        A_ub=a_ub,
        b_ub=b_ub,
        A_eq=[[1.0] * n + [0.0]],
        b_eq=[1.0],
        bounds=bounds,
        method="highs",
    )
    return -found.fun if found.status == 0 else None


def lp_leximin(rows: list[list[int]], total: int, room_of: list[int]) -> list[float] | None:
    """The leximin-optimal utilities among envy-free splits with no negative rent, or None.

    Solved the textbook way: maximise the smallest utility, find who cannot be raised any
    further, fix them at that level, and repeat for the rest. Variables are the utilities u
    (at most the person's own bid, so that no rent is negative) and the level t.
    """
    values = _scaled(rows, total)
    n = len(values)
    own = [values[i][room_of[i]] for i in range(n)]
    envy_free: list[list[float]] = []  # u_k - u_i <= v_k(room k) - v_i(room k)
    envy_bound: list[float] = []
    for i in range(n):
        for k in range(n):
            if i != k:
                row = [0.0] * (n + 1)
                row[k] += 1.0
                row[i] -= 1.0
                envy_free.append(row)
                envy_bound.append(values[k][room_of[k]] - values[i][room_of[k]])
    bounds = [(None, own[i]) for i in range(n)] + [(None, None)]
    a_eq, b_eq = [[1.0] * n + [0.0]], [sum(own) - 1.0]
    fixed: dict[int, float] = {}
    free = set(range(n))
    while free:
        matrix, bound = [list(row) for row in envy_free], list(envy_bound)
        for j in sorted(free):
            row = [0.0] * (n + 1)
            row[j] = -1.0
            row[n] = 1.0  # t <= u_j
            matrix.append(row)
            bound.append(0.0)
        for j, value in fixed.items():
            row = [0.0] * (n + 1)
            row[j] = -1.0  # u_j >= its fixed level
            matrix.append(row)
            bound.append(-value + SLACK)
        first = linprog(
            [0.0] * n + [-1.0],
            A_ub=matrix,
            b_ub=bound,
            A_eq=a_eq,
            b_eq=b_eq,
            bounds=bounds,
            method="highs",
        )
        if first.status != 0:
            return None
        level = -first.fun
        stuck = []
        for i in sorted(free):
            matrix, bound = [list(row) for row in envy_free], list(envy_bound)
            for j in [*sorted(free), *fixed]:
                row = [0.0] * (n + 1)
                row[j] = -1.0  # u_j >= the current level of j
                matrix.append(row)
                bound.append(-(level if j in free else fixed[j]) + SLACK)
            objective = [0.0] * (n + 1)
            objective[i] = -1.0
            best = linprog(
                objective,
                A_ub=matrix,
                b_ub=bound,
                A_eq=a_eq,
                b_eq=b_eq,
                bounds=bounds,
                method="highs",
            )
            if best.status == 0 and -best.fun <= level + TOLERANCE:
                stuck.append(i)
        if not stuck:
            stuck = [min(free)]
        for i in stuck:
            fixed[i] = level
            free.discard(i)
    return [fixed[i] for i in range(n)]
