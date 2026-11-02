"""Shared core of the fair-and-square skills (standard library only, Python 3.9+).

Every skill script imports this one module. It provides exact money parsing and cent
rounding, the text checks that several skills share, the exact Shapley value, the seed
mapping for lotteries driven by a public randomness source, hash commitments for the
organizer-goes-first rule, and the common output envelope with its md, dm, group and json
writers.

The canonical source is core/fsq_core.py. tools/sync_core.py copies it byte for byte into
every skill's scripts/ directory, so each skill folder also works on its own.

The core never writes a file. Its one change to the file system is deleting the --input file
after it has been read, and only when --delete-input is given (see read_input).

Conventions. Amounts are exact Fractions in currency units. money() validates a user amount,
to_cents() and fmt_cents() convert to and from integer cents, and Cents marks an integer
number of cents in a Result so that render_json prints it as "950.00". Bad user input raises
InputError(field, message), exit code 2. A rule that has no answer raises NoSolution, exit
code 3. Any other exception is a bug and propagates.

A skill script is shaped like this::

    def main():
        args = standard_args(argparse.ArgumentParser(description="...")).parse_args()
        exclusive_modes(args, "--demo", "--selftest")
        if args.selftest:
            return run_selftest(my_checks)
        data = read_object(args, DEMO_JSON)
        ...  # validate with require_* and money(), compute, build a Result
        emit(result, args)
        return 0

    run_cli(main)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import secrets
import stat
import sys
import textwrap
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from fractions import Fraction
from itertools import combinations
from pathlib import Path
from typing import (
    Any,
    Callable,
    NamedTuple,
    NoReturn,
)

CORE_VERSION = "0.2.0"

EXIT_OK = 0
EXIT_INPUT = 2  # invalid input; the message names the field
EXIT_NO_SOLUTION = 3  # the agreed rule has no solution for these numbers

MAX_MONEY = Fraction(10**12)  # largest absolute amount money() accepts
MAX_INPUT_CHARS = 2_000_000
MAX_NOTE_CHARS = 300  # one_line(): a short note such as a deadline or a source description
MAX_SOURCE_CHARS = 10_000  # require_source_text(): the public random source, kept verbatim
MAX_SHAPLEY_PLAYERS = 20  # shapley_values() visits all 2**n groups
EXACT_SEARCH_MAX_ITEMS = 8  # round_min_envy searches exhaustively up to this many items


# ---------------------------------------------------------------------------------------
# Errors and exit codes
# ---------------------------------------------------------------------------------------


class InputError(Exception):
    """Invalid user input. The CLI prints the field name and exits with code 2."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(f"{field}: {message}")
        self.field = field
        self.message = message


class NoSolution(Exception):
    """The agreed rule has no solution for these numbers. The CLI exits with code 3."""


def _use_utf8() -> None:
    """Switch the standard streams to UTF-8 so Chinese names survive any locale."""
    for stream, errors in (
        (sys.stdin, "strict"),
        (sys.stdout, "strict"),
        (sys.stderr, "backslashreplace"),
    ):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors=errors)
        except (ValueError, OSError):
            pass


def run_cli(main: Callable[..., int | None], argv: Sequence[str] | None = None) -> NoReturn:
    """Call main() (or main(argv)), report InputError and NoSolution on stderr, then exit.

    Exit codes: 0 for success or the int main returns, 2 for invalid input, 3 when the
    agreed rule has no solution. Any other exception is a bug and propagates.
    """
    _use_utf8()
    try:
        code = main() if argv is None else main(list(argv))
    except InputError as err:
        print(f'error: invalid input, field "{err.field}": {err.message}', file=sys.stderr)
        sys.exit(EXIT_INPUT)
    except NoSolution as err:
        print(f"no solution: {err}", file=sys.stderr)
        sys.exit(EXIT_NO_SOLUTION)
    sys.exit(EXIT_OK if code is None else code)


def _utf8(text: str, field: str = "input") -> bytes:
    """Encode text as UTF-8, turning an unpaired surrogate into an InputError."""
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError as err:
        raise InputError(field, "contains an invalid character (unpaired surrogate)") from err


# ---------------------------------------------------------------------------------------
# Canonical JSON and input parsing
# ---------------------------------------------------------------------------------------


def _decimal_text(value: Fraction) -> str | None:
    """Exact plain-decimal text of value (no exponent), or None if it does not terminate."""
    den = value.denominator
    rest, twos, fives = den, 0, 0
    while rest % 2 == 0:
        rest //= 2
        twos += 1
    while rest % 5 == 0:
        rest //= 5
        fives += 1
    if rest != 1:
        return None
    places = max(twos, fives)
    digits = str(abs(value.numerator) * 10**places // den).rjust(places + 1, "0")
    split = len(digits) - places
    text = digits[:split] + ("." + digits[split:] if places else "")
    return ("-" if value < 0 else "") + text


def canonical_json(obj: Any) -> str:
    """Canonical JSON text: sorted keys, no whitespace, non-ASCII characters kept as is.

    For str, int, bool, None, lists and dicts the result equals
    json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False). A Fraction is
    written as an exact plain decimal (3000, 12.5, 0.29), so 3000 and 3000.00 agree.
    Floats and Fractions that do not terminate as decimals raise TypeError.
    """
    out: list[str] = []
    _canon(obj, out, "$")
    return "".join(out)


def _canon(obj: Any, out: list[str], path: str) -> None:
    if obj is None:
        out.append("null")
    elif obj is True:
        out.append("true")
    elif obj is False:
        out.append("false")
    elif isinstance(obj, str):
        out.append(json.dumps(obj, ensure_ascii=False))
    elif isinstance(obj, int):
        out.append(str(int(obj)))
    elif isinstance(obj, Fraction):
        text = _decimal_text(obj)
        if text is None:
            raise TypeError(f"{obj} at {path} has no finite decimal form")
        out.append(text)
    elif isinstance(obj, (list, tuple)):
        out.append("[")
        for index, item in enumerate(obj):
            if index:
                out.append(",")
            _canon(item, out, f"{path}[{index}]")
        out.append("]")
    elif isinstance(obj, dict):
        for key in obj:
            if not isinstance(key, str):
                raise TypeError(f"object key {key!r} at {path} is not text")
        out.append("{")
        for index, key in enumerate(sorted(obj)):
            if index:
                out.append(",")
            out.append(json.dumps(key, ensure_ascii=False))
            out.append(":")
            _canon(obj[key], out, f"{path}.{key}")
        out.append("}")
    else:
        raise TypeError(f"cannot write {type(obj).__name__} at {path} as canonical JSON")


def _parse_float(text: str) -> Fraction:
    """JSON number with a fraction or exponent -> exact Fraction (no binary floats)."""
    exponent = text.lower().partition("e")[2]
    if exponent and abs(int(exponent)) > 30:
        raise ValueError(f"exponent too large in {text}")
    if len(text) > 100:
        raise ValueError("number has too many digits")
    return Fraction(text)


def _reject_constant(name: str) -> Any:
    raise ValueError(f"{name} is not allowed")


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate key {key!r}")
        out[key] = value
    return out


def parse_input(text: str) -> Any:
    """Parse JSON text exactly: decimals become Fractions, integers stay ints.

    NaN, Infinity and duplicate object keys are rejected with an InputError.
    """
    if len(text) > MAX_INPUT_CHARS:
        raise InputError("input", "input is too large")
    try:
        return json.loads(
            text,
            parse_float=_parse_float,
            parse_int=int,
            parse_constant=_reject_constant,
            object_pairs_hook=_unique_keys,
        )
    except (ValueError, RecursionError) as err:
        raise InputError("input", f"not valid JSON: {err}") from err


def load_input(stream: Any) -> Any:
    """Read all of a text stream and parse it with parse_input."""
    return parse_input(stream.read(MAX_INPUT_CHARS + 1))


def require_object(value: Any, field: str) -> dict[str, Any]:
    """Return value if it is a JSON object, else raise InputError naming field."""
    if not isinstance(value, dict):
        raise InputError(field, "must be a JSON object")
    return value


def require_list(value: Any, field: str, min_len: int = 0, max_len: int | None = None) -> list[Any]:
    """Return value if it is a list with a length in range, else raise InputError."""
    if not isinstance(value, list):
        raise InputError(field, "must be a list")
    if len(value) < min_len:
        raise InputError(field, f"must have at least {min_len} item(s)")
    if max_len is not None and len(value) > max_len:
        raise InputError(field, f"must have at most {max_len} item(s)")
    return value


def require_text(value: Any, field: str, allow_empty: bool = False) -> str:
    """Return value if it is text (non-blank unless allow_empty), else raise InputError."""
    if not isinstance(value, str):
        raise InputError(field, "must be text")
    if not allow_empty and not value.strip():
        raise InputError(field, "must not be empty")
    return value


def require_int(
    value: Any, field: str, minimum: int | None = None, maximum: int | None = None
) -> int:
    """Return value as an int (3 and 3.0 are accepted, true and 2.5 are not)."""
    if isinstance(value, Fraction) and value.denominator == 1:
        value = value.numerator
    if isinstance(value, bool) or not isinstance(value, int):
        raise InputError(field, "must be a whole number")
    if minimum is not None and value < minimum:
        raise InputError(field, f"must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise InputError(field, f"must be at most {maximum}")
    return int(value)


def require_names(
    value: Any, field: str, min_len: int = 1, max_len: int | None = None
) -> list[str]:
    """Return a list of distinct, non-empty names without leading or trailing spaces."""
    items = require_list(value, field, min_len, max_len)
    seen: set[str] = set()
    for index, name in enumerate(items):
        where = f"{field}[{index}]"
        if not isinstance(name, str) or not name or name != name.strip():
            raise InputError(where, "must be a non-empty name without leading or trailing spaces")
        if name in seen:
            raise InputError(where, f"duplicate name {name!r}")
        seen.add(name)
    return list(items)


def require_choice(value: Any, field: str, options: Sequence[str]) -> str:
    """Return value if it is one of options, else raise InputError listing them."""
    if not isinstance(value, str) or value not in options:
        raise InputError(field, "must be one of: " + ", ".join(options))
    return value


def encodable(text: str, where: str) -> str:
    """Return text, or refuse an unpaired surrogate (it cannot be hashed) naming the field."""
    _utf8(text, where)
    return text


def check_fields(obj: Mapping[str, Any], allowed: Sequence[str], where: str) -> None:
    """Refuse a field that is not in allowed, so a misspelled option cannot go unnoticed.

    where is the path of obj ("" for the top level); the error names where.key.
    """
    for key in obj:
        if key not in allowed:
            name = f"{where}.{key}" if where else str(key)
            raise InputError(name, "is not a known field; allowed: " + ", ".join(allowed))


def one_line(value: Any, where: str, max_chars: int = MAX_NOTE_CHARS) -> str:
    """A short note such as a deadline: one line of encodable text, trimmed, not too long."""
    text = require_text(value, where).strip()
    if len(text) > max_chars:
        raise InputError(where, f"is too long (at most {max_chars} characters)")
    if "\n" in text or "\r" in text:
        raise InputError(where, "must be a single line")
    return encodable(text, where)


def require_encodable_names(
    value: Any, field: str, min_len: int = 1, max_len: int | None = None
) -> list[str]:
    """require_names, and every name must be encodable (names are hashed into seeds)."""
    names = require_names(value, field, min_len, max_len)
    for index, name in enumerate(names):
        encodable(name, f"{field}[{index}]")
    return names


def require_source_text(value: Any, field: str, max_chars: int = MAX_SOURCE_CHARS) -> str:
    """The public random source: non-blank, encodable text, kept exactly as given."""
    text = require_text(value, field)
    if len(text) > max_chars:
        raise InputError(field, f"is too long (at most {max_chars} characters)")
    return encodable(text, field)


# ---------------------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------------------

_NOT_NUMBERS = {"nan", "inf", "infinity"}


def _show(value: Any) -> str:
    """Readable form of a rejected amount for error messages."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Fraction):
        return _decimal_text(value) or f"{value.numerator}/{value.denominator}"
    return str(value)


def _no_cents(value: Any, what: str) -> None:
    """Refuse a Cents value where currency units are expected (it would be 100 times too big)."""
    if isinstance(value, Cents):
        raise TypeError(f"{what} is Cents, which is already in cents; pass currency units")


def _as_fraction(value: Any, field: str) -> Fraction:
    _no_cents(value, field)
    if isinstance(value, bool):
        raise InputError(field, "must be an amount, not true or false")
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, Fraction):
        return value
    if isinstance(value, float):
        # Only reached when the caller did not use load_input. repr() is the shortest decimal
        # that round-trips, so 0.29 means 29 cents rather than 0.28999999999999998.
        if not math.isfinite(value):
            raise InputError(field, "NaN and infinity are not amounts")
        return Fraction(repr(value))
    if isinstance(value, str):
        text = value.strip()
        if text.lower().lstrip("+-") in _NOT_NUMBERS:
            raise InputError(field, "NaN and infinity are not amounts")
        if re.fullmatch(r"[+-]?[0-9]+(?:\.[0-9]+)?", text) is None:
            raise InputError(field, f"{value!r} is not a decimal amount such as 12.34")
        return Fraction(text)
    raise InputError(field, f"must be a number or a decimal string, not {type(value).__name__}")


def money(
    value: Any, field: str, *, allow_negative: bool = False, allow_zero: bool = True
) -> Fraction:
    """Validate an amount and return it as an exact Fraction of the currency unit.

    Accepts an int, a Fraction (what load_input produces for decimals), a finite float, or a
    decimal string like "12.34" (no thousands separators). The amount must be a whole number
    of cents: 0.295 is rejected, 12.340 is accepted. Booleans, NaN and infinity are rejected,
    negatives unless allow_negative, zero if allow_zero is False, and anything above 10**12.
    """
    amount = _as_fraction(value, field)
    if (amount * 100).denominator != 1:
        raise InputError(
            field, f"{_show(value)} has more than two decimal places (amounts are whole cents)"
        )
    if amount < 0 and not allow_negative:
        raise InputError(field, "must not be negative")
    if amount == 0 and not allow_zero:
        raise InputError(field, "must be greater than zero")
    if abs(amount) > MAX_MONEY:
        raise InputError(field, "is too large")
    return amount


def to_cents(amount: Any) -> int:
    """Exact cents of an amount that is already a whole number of cents, else ValueError."""
    _no_cents(amount, "amount")
    if isinstance(amount, (bool, float)) or not isinstance(amount, (int, Fraction)):
        raise TypeError(f"amount must be an int or Fraction, not {type(amount).__name__}")
    cents = Fraction(amount) * 100
    if cents.denominator != 1:
        raise ValueError(f"{amount} is not a whole number of cents")
    return cents.numerator


def fmt_cents(cents: int, thousands: bool = True) -> str:
    """Format integer cents as '1,050.00' or '-1,066.66' ('1050.00' without thousands)."""
    if isinstance(cents, bool) or not isinstance(cents, int):
        raise TypeError(f"cents must be an int, not {type(cents).__name__}")
    whole, part = divmod(abs(int(cents)), 100)
    digits = f"{whole:,}" if thousands else str(whole)
    return f"{'-' if cents < 0 else ''}{digits}.{part:02d}"


def cents_str(cents: int) -> str:
    """Cents as a plain two-decimal string without thousands separators ('1050.00')."""
    return fmt_cents(cents, thousands=False)


class Cents(int):
    """Integer cents marked as money: render_json prints it as a string such as "950.00"."""

    __slots__ = ()

    def __repr__(self) -> str:
        return f"Cents({int(self)})"


# ---------------------------------------------------------------------------------------
# Rounding to cents
# ---------------------------------------------------------------------------------------


def round_half_up(value: int | Fraction) -> int:
    """The nearest integer to an exact value, halves going up (5/2 gives 3, -5/2 gives -2)."""
    if isinstance(value, bool) or not isinstance(value, (int, Fraction)):
        raise TypeError(f"value must be an int or Fraction, not {type(value).__name__}")
    return math.floor(Fraction(value) + Fraction(1, 2))


def fnv1a32(text: str) -> int:
    """32-bit FNV-1a hash of the UTF-8 bytes of text."""
    value = 0x811C9DC5
    for byte in _utf8(text, "key"):
        value = ((value ^ byte) * 0x01000193) & 0xFFFFFFFF
    return value


def _priority(raw: Mapping[str, Fraction], key: str) -> list[str]:
    """Names in largest-remainder order, exact ties rotated by the FNV-1a hash of key.

    Names are sorted first, the rotation starts at index fnv1a32(key) % n, so the order
    does not depend on how the caller built the mapping.
    """
    names = sorted(raw)
    start = fnv1a32(key) % len(names)
    turn = {name: (index - start) % len(names) for index, name in enumerate(names)}
    return sorted(names, key=lambda name: (-(raw[name] - math.floor(raw[name])), turn[name]))


def _cent_values(values: Mapping[str, Any], total_cents: int, what: str) -> dict[str, Fraction]:
    """Exact cents per name; the values must add up to total_cents exactly."""
    if isinstance(total_cents, bool) or not isinstance(total_cents, int):
        raise TypeError("total_cents must be an int")
    raw: dict[str, Fraction] = {}
    for name, value in values.items():
        _no_cents(value, f"{what}[{name!r}]")
        if isinstance(value, (bool, float)) or not isinstance(value, (int, Fraction)):
            raise TypeError(
                f"{what}[{name!r}] must be an int or Fraction, not {type(value).__name__}"
            )
        raw[name] = Fraction(value) * 100
    got = sum(raw.values(), Fraction(0))
    if got != total_cents:
        raise ValueError(f"{what} add up to {got} cents, expected {total_cents}")
    return raw


def round_shares(shares: Mapping[str, Fraction], total_cents: int, key: str) -> dict[str, int]:
    """Round exact shares (in currency units) to integer cents that add up to total_cents.

    Largest remainder: everyone gets the floor of their share in cents, and the leftover
    cents go to the largest fractional remainders. Exact ties are broken by a rotation of the
    names, sorted by code point, starting at fnv1a32(key) % n. Use a different key for each
    entry (a bill id), so the leftover cent does not always land on the same person. The
    result depends only on the shares, the total and the key, never on input order.
    The shares must add up to total_cents exactly, else ValueError.
    """
    raw = _cent_values(shares, total_cents, "shares")
    if not raw:
        return {}
    cents = {name: math.floor(value) for name, value in raw.items()}
    leftover = total_cents - sum(cents.values())
    for name in _priority(raw, key)[:leftover]:
        cents[name] += 1
    return {name: cents[name] for name in sorted(cents)}


def apportion(total_cents: int, weights: Mapping[str, Fraction], key: str) -> dict[str, int]:
    """Split total_cents in proportion to non-negative weights, rounded by round_shares."""
    if any(isinstance(w, (bool, float)) for w in weights.values()):
        raise TypeError("weights must be ints or Fractions")
    weight_sum = sum((Fraction(w) for w in weights.values()), Fraction(0))
    if weight_sum <= 0 or any(w < 0 for w in weights.values()):
        raise ValueError("weights must be non-negative and not all zero")
    shares = {
        name: Fraction(total_cents, 100) * Fraction(weight) / weight_sum
        for name, weight in weights.items()
    }
    return round_shares(shares, total_cents, key)


def _check_assignment(
    bids: Mapping[str, Mapping[str, Fraction]],
    assignment: Mapping[str, str],
    items: Sequence[str],
) -> None:
    if set(bids) != set(assignment):
        raise ValueError("bids and assignment must cover the same people")
    for person, item in assignment.items():
        if item not in items:
            raise ValueError(f"{person} is assigned to unknown item {item!r}")
        missing = [name for name in items if name not in bids[person]]
        if missing:
            raise ValueError(f"{person} has no bid for {missing[0]!r}")


def surplus_table_cents(
    bids: Mapping[str, Mapping[str, Fraction]], price_cents: Mapping[str, int]
) -> dict[str, dict[str, int]]:
    """For each person and item: bid minus price, in cents (the envy table of a rent split)."""
    return {
        person: {item: to_cents(row[item]) - price_cents[item] for item in price_cents}
        for person, row in bids.items()
    }


def max_envy_cents(
    bids: Mapping[str, Mapping[str, Fraction]],
    assignment: Mapping[str, str],
    price_cents: Mapping[str, int],
) -> int:
    """Largest envy in cents: how much more any person would gain from some other item."""
    _check_assignment(bids, assignment, sorted(price_cents))
    worst = 0
    for person, row in surplus_table_cents(bids, price_cents).items():
        worst = max(worst, max(row.values()) - row[assignment[person]])
    return worst


def _envy_scorer(
    bids: Mapping[str, Mapping[str, Fraction]],
    assignment: Mapping[str, str],
    items: Sequence[str],
    lower: Mapping[str, int],
) -> Callable[[set[str]], int]:
    """Return score(up): the max envy in cents when the items in `up` are rounded up."""
    rows = [
        ({item: to_cents(bids[person][item]) for item in items}, assignment[person])
        for person in sorted(assignment)
    ]

    def score(up: set[str]) -> int:
        worst = 0
        for bid, own in rows:
            gain = max(bid[item] - lower[item] - (1 if item in up else 0) for item in items)
            own_gain = bid[own] - lower[own] - (1 if own in up else 0)
            worst = max(worst, gain - own_gain)
        return worst

    return score


def _swap_search(
    fractional: Sequence[str], leftover: int, score: Callable[[set[str]], int]
) -> set[str]:
    """Hill climbing by single swaps from the largest-remainder choice (not exact)."""
    chosen = set(fractional[:leftover])
    best = score(chosen)
    improved = True
    while improved and best > 0:
        improved = False
        for out_item in [item for item in fractional if item in chosen]:
            for in_item in [item for item in fractional if item not in chosen]:
                trial = (chosen - {out_item}) | {in_item}
                trial_score = score(trial)
                if trial_score < best:
                    chosen, best, improved = trial, trial_score, True
                    break
            if improved:
                break
    return chosen


def round_min_envy(
    prices: Mapping[str, Fraction],
    total_cents: int,
    bids: Mapping[str, Mapping[str, Fraction]],
    assignment: Mapping[str, str],
    key: str,
) -> dict[str, int]:
    """Round exact prices (currency units) to cents so that the largest envy is smallest.

    For rent-like problems: prices maps each item (room) to its exact price, bids[person][item]
    is what the person would pay for the item (whole cents), assignment maps each person to
    the item they get. Every item is rounded down or up to a cent and the total is exactly
    total_cents. Among all such roundings the one with the smallest maximum envy wins (the
    envy of a person is the most they would gain by switching to another item at the rounded
    prices). Ties go to the rounding that is closest to largest remainder, with remainder
    ties rotated by fnv1a32(key) as in round_shares.

    The search is exact (exhaustive) for up to 8 items, EXACT_SEARCH_MAX_ITEMS. With more
    items it starts from largest remainder and improves by single swaps, which is never
    worse than largest remainder but not guaranteed optimal. Returns cents per item.
    """
    raw = _cent_values(prices, total_cents, "prices")
    items = sorted(raw)
    _check_assignment(bids, assignment, items)
    if not items:
        return {}
    lower = {item: math.floor(raw[item]) for item in items}
    leftover = total_cents - sum(lower.values())
    fractional = [item for item in _priority(raw, key) if raw[item] != lower[item]]
    up: set[str] = set()
    score = _envy_scorer(bids, assignment, items, lower)  # also checks that bids are whole cents
    if leftover > 0:
        if len(items) <= EXACT_SEARCH_MAX_ITEMS:
            rank = {item: index for index, item in enumerate(fractional)}
            best: tuple[int, tuple[int, ...]] | None = None
            for choice in combinations(fractional, leftover):
                candidate = (score(set(choice)), tuple(rank[item] for item in choice))
                if best is None or candidate < best:
                    best, up = candidate, set(choice)
        else:
            up = _swap_search(fractional, leftover, score)
    return {item: lower[item] + (1 if item in up else 0) for item in items}


# ---------------------------------------------------------------------------------------
# Cooperative games
# ---------------------------------------------------------------------------------------


def shapley_values(n: int, worth: Sequence[int | Fraction]) -> list[Fraction]:
    """Exact Shapley value of a game with players 0 to n-1, from the worth of every group.

    worth[mask] is the worth of the group whose members are the set bits of mask, for every
    mask from 0 to 2**n - 1; worth[0] is the empty group. The value of player i is the
    average, over all orders in which the players can join, of the worth that i adds:
    the sum over all groups S without i of |S|! (n - |S| - 1)! / n! * (worth[S + i] - worth[S]).
    Worths must be ints or Fractions, so that nothing is rounded on the way. The values add up
    to worth[2**n - 1] - worth[0]. At most MAX_SHAPLEY_PLAYERS players are supported.
    """
    if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= MAX_SHAPLEY_PLAYERS:
        raise ValueError(f"n must be an int between 0 and {MAX_SHAPLEY_PLAYERS}")
    size = 1 << n
    if len(worth) != size:
        raise ValueError(f"worth needs one entry for each of the {size} groups, got {len(worth)}")
    for value in worth:
        if isinstance(value, bool) or not isinstance(value, (int, Fraction)):
            raise TypeError(f"worth entries must be ints or Fractions, not {type(value).__name__}")
    members = [0] * size
    for mask in range(1, size):
        members[mask] = members[mask & (mask - 1)] + 1
    weight = [math.factorial(k) * math.factorial(n - k - 1) for k in range(n)]
    scaled: list[int | Fraction] = [0] * n
    for mask in range(size - 1):
        gain_weight = weight[members[mask]]
        base = worth[mask]
        for index in range(n):
            bit = 1 << index
            if not mask & bit:
                gain = worth[mask | bit] - base
                if gain:
                    scaled[index] += gain_weight * gain
    denominator = math.factorial(n)
    if sum(scaled) != denominator * (worth[size - 1] - worth[0]):
        raise AssertionError("Shapley shares do not add up to the worth of the whole group")
    return [Fraction(share) / denominator for share in scaled]


# ---------------------------------------------------------------------------------------
# Seed mapping (public randomness -> reproducible draws)
# ---------------------------------------------------------------------------------------

SEED_SPEC = (
    "seed = SHA-256 of the canonical JSON (sorted keys, no spaces, UTF-8) of "
    '{"n_slots": N, "participants": names sorted by code point, "rule": RULE, '
    '"source": SOURCE TEXT}. '
    "Draw number c = first 8 bytes, big-endian, of SHA-256(seed + c as 8 big-endian bytes). "
    "A uniform integer in [0, n) takes x mod n if x < 2^64 - (2^64 mod n), otherwise the next "
    "draw is used. The order is Fisher-Yates over the code-point-sorted names, i from n-1 "
    "down to 1, swapping position i with a uniform integer in [0, i]."
)


def seed_preimage(
    rule_name: str, participants: Sequence[str], n_slots: int, source_text: str
) -> str:
    """The exact text whose SHA-256 is the seed: the canonical JSON of the four inputs.

    The preimage is the canonical JSON of {"n_slots", "participants" (sorted by code point),
    "rule", "source"}. Canonical JSON quotes and escapes every string and fixes the key order,
    so two different inputs can never produce the same preimage (the property a length prefix
    would give). The source text is used verbatim, with no trimming or normalisation.
    Raises ValueError for a blank rule or source, duplicate or non-text participants, or a
    negative slot count: validate user input first (require_names and friends).
    """
    if not isinstance(rule_name, str) or not rule_name:
        raise ValueError("rule_name must be non-empty text")
    if not isinstance(source_text, str) or not source_text.strip():
        raise ValueError("source_text must be non-empty text")
    if isinstance(n_slots, bool) or not isinstance(n_slots, int) or n_slots < 0:
        raise ValueError("n_slots must be a non-negative int")
    if not all(isinstance(name, str) for name in participants):
        raise ValueError("participants must be text")
    if len(set(participants)) != len(participants):
        raise ValueError("participants must be distinct")
    return canonical_json(
        {
            "rule": rule_name,
            "participants": sorted(participants),
            "n_slots": n_slots,
            "source": source_text,
        }
    )


def make_seed(rule_name: str, participants: Sequence[str], n_slots: int, source_text: str) -> bytes:
    """32-byte seed from the rule name, participants, slot count and public randomness text.

    The seed is the SHA-256 of seed_preimage(...), which also lists what is refused.
    """
    preimage = seed_preimage(rule_name, participants, n_slots, source_text)
    return hashlib.sha256(_utf8(preimage, "random_source")).digest()


class SeedStream:
    """Uniform integers from a SHA-256 counter, with rejection sampling.

    Only hashlib and integer arithmetic are used (never the random module), so the same seed
    gives the same numbers on every Python version and platform.
    """

    def __init__(self, seed: bytes) -> None:
        if not isinstance(seed, (bytes, bytearray)) or len(seed) != 32:
            raise ValueError("seed must be 32 bytes (see make_seed)")
        self._seed = bytes(seed)
        self.counter = 0

    @classmethod
    def from_hex(cls, seed_hex: str) -> SeedStream:
        """Build a stream from the 64-character hex form of a seed."""
        return cls(bytes.fromhex(seed_hex))

    def next_u64(self) -> int:
        """Next unsigned 64-bit number of the stream."""
        block = hashlib.sha256(self._seed + self.counter.to_bytes(8, "big")).digest()
        self.counter += 1
        return int.from_bytes(block[:8], "big")

    def below(self, n: int) -> int:
        """Uniform integer in [0, n) by rejection sampling (1 <= n <= 2**64)."""
        if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= 1 << 64:
            raise ValueError("n must be an int between 1 and 2**64")
        limit = (1 << 64) - ((1 << 64) % n)
        while True:
            x = self.next_u64()
            if x < limit:
                return x % n


def shuffle(items: Sequence[Any], stream: SeedStream) -> list[Any]:
    """A uniformly random order of items, as a new list.

    The items are sorted first (code point order for text) and then permuted by Fisher-Yates
    from the end, so the result depends only on the set of items and the seed, not on the
    order the caller listed them in.
    """
    out = sorted(items)
    for i in range(len(out) - 1, 0, -1):
        j = stream.below(i + 1)
        out[i], out[j] = out[j], out[i]
    return out


def sample(items: Sequence[Any], k: int, stream: SeedStream) -> list[Any]:
    """The first k items of shuffle(items, stream)."""
    if isinstance(k, bool) or not isinstance(k, int) or not 0 <= k <= len(items):
        raise ValueError(f"cannot draw {k!r} items from {len(items)}")
    return shuffle(items, stream)[:k]


def draw_order(
    rule_name: str, participants: Sequence[str], n_slots: int, source_text: str
) -> list[str]:
    """Full lottery order: the first n_slots names win, the rest are the waiting list."""
    return shuffle(
        participants, SeedStream(make_seed(rule_name, participants, n_slots, source_text))
    )


class SeededOrder(NamedTuple):
    """A drawn order with what anyone needs to recompute it: the seed and its preimage."""

    order: list[str]
    seed_hex: str
    preimage: str


def seeded_order(
    rule_name: str, participants: Sequence[str], n_slots: int, source_text: str
) -> SeededOrder:
    """draw_order, together with the hex form of the seed and the text hashed into it."""
    seed = make_seed(rule_name, participants, n_slots, source_text)
    return SeededOrder(
        shuffle(participants, SeedStream(seed)),
        seed.hex(),
        seed_preimage(rule_name, participants, n_slots, source_text),
    )


# ---------------------------------------------------------------------------------------
# Commitments (organizer goes first)
# ---------------------------------------------------------------------------------------

COMMIT_TAG = "fsq-commit-v1"


class Commitment(NamedTuple):
    """A commitment: publish the digest now, keep the nonce and payload until the reveal."""

    digest: str
    nonce: str


def new_nonce() -> str:
    """Fresh random 128-bit nonce as 32 lowercase hex characters (from secrets)."""
    return secrets.token_hex(16)


def _check_nonce(nonce: Any) -> str:
    if not isinstance(nonce, str) or re.fullmatch(r"[0-9a-f]{32}", nonce) is None:
        raise InputError("nonce", "must be 32 lowercase hex characters (128 bits)")
    return nonce


def _commit_digest(payload: Any, nonce: str) -> str:
    body = canonical_json(parse_input(payload) if isinstance(payload, str) else payload)
    return hashlib.sha256(_utf8(f"{COMMIT_TAG}\n{nonce}\n{body}")).hexdigest()


def commit(payload: Any, nonce: str | None = None) -> Commitment:
    """Commit to a payload without revealing it.

    The digest is SHA-256 of the text COMMIT_TAG, newline, nonce, newline and the canonical
    JSON of the payload. The payload is either a JSON-compatible object or a str holding
    JSON text (re-canonicalised, so spacing and 3000 versus 3000.00 do not matter). A str is
    always read as JSON text, so to commit a bare string wrap it in a list. Without a nonce, a
    fresh random 128-bit one is generated with secrets: keep it with the payload.
    """
    chosen = new_nonce() if nonce is None else _check_nonce(nonce)
    return Commitment(_commit_digest(payload, chosen), chosen)


def verify_commit(digest: str, payload: Any, nonce: str) -> bool:
    """True if the revealed payload and nonce match the published digest."""
    if not isinstance(digest, str) or not digest.isascii():
        raise InputError("digest", "must be a hex string")
    return secrets.compare_digest(
        _commit_digest(payload, _check_nonce(nonce)), digest.strip().lower()
    )


# ---------------------------------------------------------------------------------------
# Output envelope and writers
# ---------------------------------------------------------------------------------------

FORMATS = ("md", "dm", "group")
LANGS = ("zh", "en")

_LABELS: dict[str, dict[str, str]] = {
    "zh": {
        "not_modeled": "本结果不包含",
        "reproduce": "复算命令",
        "dm_intro": "（给组织者：下面每一段只私发给对应的人，不要贴到群里。）",
        "dm_to": "发给 {person}",
    },
    "en": {
        "not_modeled": "Not modeled",
        "reproduce": "Reproduce",
        "dm_intro": (
            "(For the organizer: send each block below privately to the person named. "
            "Do not post it in the group.)"
        ),
        "dm_to": "To {person}",
    },
}


@dataclass
class Table:
    """A table for the organizer: a header row and rows of already formatted cells."""

    header: list[str]
    rows: list[list[str]]
    caption: str = ""


@dataclass
class Result:
    """What a skill returns. The writers turn it into md, dm, group or json output.

    inputs_echo, result, certificate, not_modeled and reproduce are the JSON envelope; wrap
    every amount in Cents. tables and notes feed the md output, person_lines (person to
    lines, holding only that person's numbers) feeds dm, and group_lines (no private bids)
    feeds group. The skill decides the content; the writers only lay it out.
    """

    title: str = ""
    inputs_echo: dict[str, Any] = dataclass_field(default_factory=dict)
    result: dict[str, Any] = dataclass_field(default_factory=dict)
    certificate: dict[str, Any] = dataclass_field(default_factory=dict)
    not_modeled: list[str] = dataclass_field(default_factory=list)
    reproduce: str = ""
    tables: list[Table] = dataclass_field(default_factory=list)
    notes: list[str] = dataclass_field(default_factory=list)
    person_lines: dict[str, list[str]] = dataclass_field(default_factory=dict)
    group_lines: list[str] = dataclass_field(default_factory=list)


def jsonable(obj: Any, path: str = "$") -> Any:
    """Convert a structure to plain JSON types: Cents become strings like "950.00".

    Fractions, floats, sets and non-text keys raise TypeError, so an amount can never reach
    the output as a float or as a bare number of cents by accident.
    """
    if obj is None or isinstance(obj, (bool, str)):
        return obj
    if isinstance(obj, Cents):
        return cents_str(int(obj))
    if isinstance(obj, int):
        return int(obj)
    if isinstance(obj, dict):
        for key in obj:
            if not isinstance(key, str):
                raise TypeError(f"object key {key!r} at {path} is not text")
        return {key: jsonable(value, f"{path}.{key}") for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(value, f"{path}[{index}]") for index, value in enumerate(obj)]
    raise TypeError(
        f"cannot write {type(obj).__name__} at {path}: wrap amounts in Cents and turn other "
        "numbers into text"
    )


def envelope(result: Result) -> dict[str, Any]:
    """The JSON envelope: exactly inputs_echo, result, certificate, not_modeled, reproduce."""
    return jsonable(
        {
            "inputs_echo": result.inputs_echo,
            "result": result.result,
            "certificate": result.certificate,
            "not_modeled": list(result.not_modeled),
            "reproduce": result.reproduce,
        }
    )


def render_json(result: Result) -> str:
    """The envelope as JSON text: sorted keys, two-space indent, UTF-8 characters kept."""
    return json.dumps(envelope(result), sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def _labels(lang: str) -> dict[str, str]:
    if lang not in _LABELS:
        raise ValueError(f"lang must be one of {', '.join(LANGS)}")
    return _LABELS[lang]


_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_IDEOGRAPH = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def fill_text(lang: str, template: str, **values: Any) -> str:
    """Fill a str.format template with values, as template.format(**values) does.

    In Chinese (lang "zh"), a value that begins or ends with an ASCII letter or digit, such as
    the name Coco, gets a space where the template puts it right next to a Chinese character.
    The value itself is never changed, and other languages are filled as they are.
    """
    if lang == "zh":
        pieces = []
        last = 0
        for match in _PLACEHOLDER.finditer(template):
            value = str(values.get(match.group(1), ""))
            before = template[match.start() - 1] if match.start() else " "
            after = template[match.end()] if match.end() < len(template) else " "
            pieces.append(template[last : match.start()])
            if value and value[0].isascii() and value[0].isalnum() and _IDEOGRAPH.match(before):
                pieces.append(" ")
            pieces.append(match.group(0))
            if value and value[-1].isascii() and value[-1].isalnum() and _IDEOGRAPH.match(after):
                pieces.append(" ")
            last = match.end()
        pieces.append(template[last:])
        template = "".join(pieces)
    return template.format(**values)


def _cell(text: Any) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def render_md(result: Result, lang: str = "zh") -> str:
    """Markdown for the organizer: title, tables, notes, what is not modeled, how to rerun."""
    labels = _labels(lang)
    lines: list[str] = []
    if result.title:
        lines += [f"# {result.title}", ""]
    for table in result.tables:
        if table.caption:
            lines += [f"## {table.caption}", ""]
        lines.append("| " + " | ".join(_cell(cell) for cell in table.header) + " |")
        lines.append("| " + " | ".join("---" for _ in table.header) + " |")
        for row in table.rows:
            if len(row) != len(table.header):
                raise ValueError(f"table row has {len(row)} cells, header has {len(table.header)}")
            lines.append("| " + " | ".join(_cell(cell) for cell in row) + " |")
        lines.append("")
    for note in result.notes:
        lines += [note, ""]
    if result.not_modeled:
        lines += [f"## {labels['not_modeled']}", ""]
        lines += [f"- {item}" for item in result.not_modeled] + [""]
    if result.reproduce:
        lines += [f"## {labels['reproduce']}", "", "```", result.reproduce, "```", ""]
    return "\n".join(lines).rstrip("\n") + "\n"


def render_dm_messages(result: Result) -> dict[str, str]:
    """One message per person, in the order of result.person_lines."""
    if not result.person_lines:
        raise ValueError("this result has no per-person messages")
    return {person: "\n".join(lines) for person, lines in result.person_lines.items()}


def render_dm(result: Result, lang: str = "zh") -> str:
    """Private messages: a note for the organizer, then one block per person."""
    labels = _labels(lang)
    blocks = [labels["dm_intro"]]
    for person, text in render_dm_messages(result).items():
        header = labels["dm_to"].format(person=person)
        blocks.append(f"--- {header} ---\n{text}")
    return "\n\n".join(blocks) + "\n"


def render_group(result: Result) -> str:
    """Group-chat summary: the title and result.group_lines, nothing else."""
    if not result.group_lines:
        raise ValueError("this result has no group summary")
    lines = ([result.title] if result.title else []) + list(result.group_lines)
    return "\n".join(lines) + "\n"


def render(result: Result, fmt: str = "md", as_json: bool = False, lang: str = "zh") -> str:
    """Render a Result as JSON (as_json) or as one of the text formats md, dm, group."""
    if as_json:
        return render_json(result)
    if fmt == "md":
        return render_md(result, lang)
    if fmt == "dm":
        return render_dm(result, lang)
    if fmt == "group":
        return render_group(result)
    raise ValueError(f"fmt must be one of {', '.join(FORMATS)}")


# ---------------------------------------------------------------------------------------
# Command-line helpers
# ---------------------------------------------------------------------------------------


def standard_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Add the options every skill script shares.

    They are --input, --delete-input, --format, --json, --demo and --selftest.
    """
    parser.add_argument(
        "--input",
        default="-",
        metavar="FILE",
        help="JSON input file, or - for standard input (default)",
    )
    parser.add_argument(
        "--delete-input",
        action="store_true",
        help="delete the --input FILE as soon as it has been read, even if the input is then "
        "rejected. Needs --input FILE, not standard input. A file that cannot be read is "
        "left alone",
    )
    parser.add_argument(
        "--format",
        choices=FORMATS,
        default="md",
        help="text output: md (tables for the organizer), dm (one private message per "
        "person), group (summary for the group chat without private numbers)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the JSON envelope instead (sorted keys, amounts as two-decimal strings)",
    )
    parser.add_argument("--demo", action="store_true", help="run on the built-in fictional example")
    parser.add_argument(
        "--selftest", action="store_true", help="run the built-in self-checks and exit"
    )
    return parser


def exit_codes_epilog(one: str = "a failed self-test", three: str | None = None) -> str:
    """The sentence on exit codes that ends the --help text of every skill script.

    one names what exit code 1 means in this script, and three what exit code 3 means. A script
    that never exits with 3 leaves three out, and the sentence then says that 3 is not used. The
    text is wrapped at 78 columns, so it also reads well under a help formatter that does not wrap.
    """
    if three is None:
        text = (
            f"Exit code 0 means success, 1 {one} and 2 invalid input (the message names the "
            "field). Every valid input has a result, so exit code 3 is not used."
        )
    else:
        text = (
            f"Exit code 0 means success, 1 {one}, 2 invalid input (the message names the field) "
            f"and 3 {three}."
        )
    return textwrap.fill(text, width=78, break_long_words=False, break_on_hyphens=False)


def exclusive_modes(args: argparse.Namespace, *flags: str) -> None:
    """Refuse two of these mode flags in one run, for example "--demo" and "--selftest".

    A flag counts as given when its value is true, or is any text for an option that takes a
    value. The message names every flag in flags, in the order given.
    """
    given = 0
    for flag in flags:
        value = getattr(args, flag.lstrip("-").replace("-", "_"), None)
        given += value is not None and value is not False
    if given > 1:
        names = ", ".join(flags[:-1]) + f" and {flags[-1]}"
        raise InputError("options", f"choose at most one of {names}")


def add_lang_option(parser: argparse.ArgumentParser, unchanged: str) -> argparse.ArgumentParser:
    """Add --lang (zh or en, default zh) to a parser, for skills that write text in both.

    unchanged finishes the help text and names what the language does not touch, for
    example "JSON keys and names do not change". Call it where the option should appear in
    --help: it is not part of standard_args because not every skill has two languages.
    """
    parser.add_argument(
        "--lang",
        choices=LANGS,
        default="zh",
        help=f"language of the text output (default zh); {unchanged}",
    )
    return parser


def _require_plain_file(path: str) -> None:
    """Refuse a link, a directory or a device: --delete-input deletes regular files only.

    Deleting a link would leave the file it points to on disk. A path that is missing or cannot
    be examined passes, because the read that follows reports it.
    """
    try:
        mode = Path(path).lstat().st_mode
    except OSError:
        return
    if not stat.S_ISREG(mode):
        raise InputError(
            "--delete-input", f"{path} is not a regular file, so nothing was read or deleted"
        )


def _delete_input_file(path: str) -> None:
    """Delete the --input file that has just been read. The only place the core deletes a file."""
    try:
        Path(path).unlink(missing_ok=True)
    except OSError as err:
        raise InputError(
            "--delete-input", f"read {path} but could not delete it: {err.strerror or err}"
        ) from err


def read_input(args: argparse.Namespace, demo: Any = None) -> Any:
    """The parsed input of this run: the demo data, the --input file, or standard input.

    demo may be JSON text (parsed like real input) or a ready object.

    With --delete-input the --input file is deleted as soon as it has been read, before its text
    is parsed as JSON. It is therefore gone whether the input is then accepted or rejected, and
    also when its bytes are not valid UTF-8. Nothing is deleted when the file cannot be read.
    Standard input, a link, a directory and a device are refused with an InputError, and so is a
    file that was read but cannot be deleted. The demo reads no file.
    """
    if getattr(args, "demo", False):
        if demo is None:
            raise InputError("--demo", "this skill has no built-in example")
        return parse_input(demo) if isinstance(demo, str) else demo
    path = getattr(args, "input", "-")
    delete = bool(getattr(args, "delete_input", False))
    if path == "-":
        if delete:
            raise InputError(
                "--delete-input", "needs --input FILE (standard input leaves no file to delete)"
            )
        stream = sys.stdin
        if stream is None or stream.isatty():
            raise InputError("input", "no JSON on standard input: pipe it in or pass --input FILE")
        return load_input(stream)
    if delete:
        _require_plain_file(path)
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except OSError as err:
        raise InputError("input", f"cannot read {path}: {err.strerror or err}") from err
    except UnicodeDecodeError as err:
        if delete:
            _delete_input_file(path)
        raise InputError("input", f"{path} is not valid UTF-8") from err
    if delete:
        _delete_input_file(path)
    return parse_input(text)


def read_object(args: argparse.Namespace, demo: Any = None) -> dict[str, Any]:
    """read_input, required to be a JSON object. Invalid UTF-8 on stdin is an input error."""
    try:
        return require_object(read_input(args, demo), "input")
    except UnicodeDecodeError as err:
        raise InputError("input", "is not valid UTF-8") from err


def emit(result: Result, args: argparse.Namespace, stream: Any = None, lang: str = "zh") -> None:
    """Write the result in the format chosen by --json / --format to stream (default stdout)."""
    text = render(result, getattr(args, "format", "md"), bool(getattr(args, "json", False)), lang)
    (sys.stdout if stream is None else stream).write(text)


# ---------------------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------------------

_GOLDEN_PEOPLE = ["阿明", "小红", "大刘", "Coco", "老王", "Yuki", "小周", "Mia"]
_GOLDEN_SOURCE = "（虚构示例）2026-11-08 某公开开奖号码 03 11 19 24 33 + 02 07"
_GOLDEN_SEED_PREFIX = "15b9c53a44270857eb442863"
_GOLDEN_ORDER = ["Yuki", "小周", "大刘", "Coco", "小红", "阿明", "Mia", "老王"]


def expect(condition: bool, message: str) -> None:
    """A self-check: raise AssertionError(message) unless condition holds."""
    if not condition:
        raise AssertionError(message)


def _expect_input_error(call: Callable[[], Any], what: str) -> None:
    try:
        call()
    except InputError:
        return
    raise AssertionError(f"{what} was accepted")


def core_selftest_checks() -> list[tuple[str, Callable[[], None]]]:
    """Named checks of this module, including the recorded seed-mapping golden values."""

    def check_money() -> None:
        expect(money("0.29", "x") == Fraction(29, 100), "string 0.29")
        expect(to_cents(money(parse_input("0.29"), "x")) == 29, "JSON 0.29")
        for bad in ("0.295", True, "nan", -1):
            _expect_input_error(lambda bad=bad: money(bad, "x"), f"money({bad!r})")

    def check_format() -> None:
        expect(fmt_cents(105000) == "1,050.00", "1,050.00")
        expect(fmt_cents(-106666) == "-1,066.66", "-1,066.66")

    def check_rotation() -> None:
        counts = {"A": 0, "B": 0, "C": 0}
        for number in range(1, 31):
            third = {name: Fraction(100, 3) for name in counts}
            cents = round_shares(third, 10000, f"expense-{number}")
            expect(sum(cents.values()) == 10000, "total")
            for name, value in cents.items():
                counts[name] += value == 3334
        expect(sorted(counts.values()) == [10, 10, 10], f"leftover cents {counts}")

    def check_min_envy() -> None:
        rooms = ["big", "south", "closet"]
        bids = {
            "p1": dict(zip(rooms, map(Fraction, (4800, 1000, 200)))),
            "p2": dict(zip(rooms, map(Fraction, (1000, 4800, 200)))),
            "p3": dict(zip(rooms, map(Fraction, (2900, 2900, 200)))),
        }
        assignment = {"p1": "big", "p2": "south", "p3": "closet"}
        prices = {
            "big": Fraction(10600, 3),
            "south": Fraction(10600, 3),
            "closet": Fraction(-3200, 3),
        }
        cents = round_min_envy(prices, 600000, bids, assignment, "rent")
        expect(sum(cents.values()) == 600000, "total")
        expect(max_envy_cents(bids, assignment, cents) == 0, "envy")

    def check_seed() -> None:
        seed = make_seed("uniform_lottery_v1", _GOLDEN_PEOPLE, 3, _GOLDEN_SOURCE)
        expect(seed.hex().startswith(_GOLDEN_SEED_PREFIX), "seed " + seed.hex()[:24])
        expect(shuffle(_GOLDEN_PEOPLE, SeedStream(seed)) == _GOLDEN_ORDER, "order")

    def check_commit() -> None:
        digest, nonce = commit({"bids": [Fraction(3000), 2200]})
        expect(verify_commit(digest, '{"bids": [3000.00, 2200]}', nonce), "round trip")
        expect(not verify_commit(digest, {"bids": [3000, 2201]}, nonce), "tampered payload")

    def check_canonical() -> None:
        sample_value = {"b": [1, "x", None, True], "a": {"z": "你好", "y": []}}
        expected = json.dumps(
            sample_value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        expect(canonical_json(sample_value) == expected, "canonical JSON")

    return [
        ("money", check_money),
        ("fmt_cents", check_format),
        ("round_shares rotation", check_rotation),
        ("round_min_envy", check_min_envy),
        ("seed golden", check_seed),
        ("commit round trip", check_commit),
        ("canonical json", check_canonical),
    ]


def run_selftest(
    checks: Sequence[tuple[str, Callable[[], None]]] = (), include_core: bool = True
) -> int:
    """Run the core checks (unless include_core is False) and the given (name, check) pairs.

    A check passes if it returns and fails if it raises. Prints one line per check and a
    summary, and returns 0 if all passed, else 1. A skill's --selftest returns this value.
    """
    every = (core_selftest_checks() if include_core else []) + list(checks)
    failed = 0
    for name, check in every:
        try:
            check()
        except Exception as err:  # noqa: BLE001 - any failure of a check is reported, not raised
            failed += 1
            print(f"FAIL {name}: {type(err).__name__}: {err}")
        else:
            print(f"ok   {name}")
    print(
        f"selftest: {len(every) - failed} passed, {failed} failed "
        f"(fsq_core {CORE_VERSION}, Python {sys.version.split()[0]})"
    )
    return 1 if failed else 0
