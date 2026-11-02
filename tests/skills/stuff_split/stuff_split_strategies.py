"""Hypothesis strategies for the stuff-split tests."""

from __future__ import annotations

from typing import Any

from hypothesis import HealthCheck, settings
from hypothesis import strategies as st

SETTINGS = settings(
    max_examples=120,
    deadline=None,
    derandomize=True,
    database=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.data_too_large,
        HealthCheck.filter_too_much,
    ],
)

# The guarantees that rest on a search over every allocation get more examples.
HEAVY = settings(SETTINGS, max_examples=300)


@st.composite
def value_matrices(
    draw: Any, min_people: int = 2, max_people: int = 4, max_items: int = 5, zeros: bool = True
) -> list[list[int]]:
    """Values in cents: one row per person, one column per item.

    The values are multiples of a random unit and come from a small range, which makes ties
    common. A row sometimes copies an earlier row, which gives equal tastes.
    """
    n = draw(st.integers(min_people, max_people))
    m = draw(st.integers(1, max_items))
    unit = draw(st.sampled_from([1, 5, 100, 2500, 333]))
    low = 0 if zeros else 1
    rows: list[list[int]] = []
    for i in range(n):
        if i and draw(st.integers(0, 4)) == 0:
            rows.append(list(rows[draw(st.integers(0, i - 1))]))
            continue
        rows.append([draw(st.integers(low, 6)) * unit for _ in range(m)])
    return rows


@st.composite
def small_matrices(draw: Any) -> list[list[int]]:
    """Matrices small enough for a search over all allocations in every example."""
    return draw(value_matrices(min_people=2, max_people=4, max_items=5))


@st.composite
def weight_lists(draw: Any, n: int) -> list[int]:
    return [draw(st.integers(1, 5)) for _ in range(n)]
