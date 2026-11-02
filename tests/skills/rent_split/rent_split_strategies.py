"""Hypothesis strategies for the rent-split tests."""

from __future__ import annotations

from fractions import Fraction
from typing import Any

from hypothesis import HealthCheck, settings
from hypothesis import strategies as st

SETTINGS = settings(
    max_examples=120,
    deadline=None,
    derandomize=True,
    database=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)


@st.composite
def bid_matrices(
    draw: Any, min_people: int = 2, max_people: int = 6
) -> tuple[list[list[int]], int]:
    """(rows, total) in cents: each row is a split of total into one bid per room.

    The amounts are multiples of a random unit, which makes ties common when the unit is large
    compared to the total. A row sometimes copies an earlier row, which gives equal tastes.
    """
    n = draw(st.integers(min_people, max_people))
    unit = draw(st.sampled_from([1, 3, 100, 2500, 123457]))
    units = draw(st.integers(1, 60))
    rows: list[list[int]] = []
    for i in range(n):
        if i and draw(st.integers(0, 4)) == 0:
            rows.append(list(rows[draw(st.integers(0, i - 1))]))
            continue
        cuts = sorted(draw(st.lists(st.integers(0, units), min_size=n - 1, max_size=n - 1)))
        parts = [b - a for a, b in zip([0, *cuts], [*cuts, units])]
        rows.append([part * unit for part in parts])
    return rows, units * unit


@st.composite
def loose_bid_matrices(
    draw: Any, min_people: int = 2, max_people: int = 5
) -> tuple[list[list[int]], int]:
    """(rows, total) in cents where the rows need not add up to the total."""
    n = draw(st.integers(min_people, max_people))
    total = draw(st.integers(1, 500_000))
    rows = [draw(st.lists(st.integers(0, 400_000), min_size=n, max_size=n)) for _ in range(n)]
    return rows, total


@st.composite
def permutations_of(draw: Any, n: int) -> list[int]:
    return draw(st.permutations(list(range(n))))


def json_values() -> st.SearchStrategy[Any]:
    """Arbitrary JSON-like values as the script's reader could produce them."""
    leaves = st.one_of(
        st.none(),
        st.booleans(),
        st.integers(-10_000, 10_000_000),
        st.fractions(max_denominator=1000),
        st.text(max_size=8),
        st.sampled_from(["spliddit", "allow", "forbid", "12.34", "-1", "nan", "0.001"]),
    )
    return st.recursive(
        leaves,
        lambda children: st.one_of(
            st.lists(children, max_size=5),
            st.dictionaries(st.text(max_size=6), children, max_size=5),
        ),
        max_leaves=12,
    )


def as_fraction_rows(rows: list[list[int]]) -> list[list[Fraction]]:
    return [[Fraction(x) for x in row] for row in rows]
