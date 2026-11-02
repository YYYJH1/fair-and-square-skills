"""Money parsing, JSON input and cent formatting."""

from __future__ import annotations

import io
from fractions import Fraction

import fsq_core as core
import pytest
from hypothesis import given
from hypothesis import strategies as st

MAX_CENTS = 100 * 10**12  # money() accepts amounts up to 10**12


class TestMoney:
    def test_string_and_json_number_agree(self):
        from_string = core.money("0.29", "amount")
        from_json = core.money(core.parse_input("0.29"), "amount")
        assert from_string == from_json == Fraction(29, 100)
        assert core.to_cents(from_string) == 29

    def test_float_is_read_as_its_shortest_decimal(self):
        # Fraction(0.29) * 100 is 28.999999999999996 in binary floating point
        assert core.to_cents(core.money(0.29, "amount")) == 29

    @pytest.mark.parametrize(
        ("value", "cents"),
        [
            (12, 1200),
            ("12", 1200),
            ("12.3", 1230),
            ("12.34", 1234),
            ("  7.05 ", 705),
            ("+3.50", 350),
            ("12.340", 1234),
            ("0", 0),
            ("-0.00", 0),
            (Fraction(5, 2), 250),
            (Fraction(3000), 300000),
        ],
    )
    def test_accepts_whole_cents(self, value, cents):
        assert core.to_cents(core.money(value, "amount")) == cents

    @pytest.mark.parametrize(
        "value", ["0.295", "1.005", "12.345", Fraction(1, 3), Fraction(1, 200), 0.295]
    )
    def test_rejects_sub_cent_precision(self, value):
        with pytest.raises(core.InputError) as caught:
            core.money(value, "bids.阿明[2]")
        assert caught.value.field == "bids.阿明[2]"
        assert "decimal" in caught.value.message

    @pytest.mark.parametrize("value", [True, False])
    def test_rejects_booleans(self, value):
        with pytest.raises(core.InputError) as caught:
            core.money(value, "paid")
        assert caught.value.field == "paid"

    @pytest.mark.parametrize(
        "value",
        [
            float("nan"),
            float("inf"),
            float("-inf"),
            "nan",
            "NaN",
            "inf",
            "-inf",
            "+Infinity",
        ],
    )
    def test_rejects_nan_and_infinity(self, value):
        with pytest.raises(core.InputError, match="NaN and infinity"):
            core.money(value, "paid", allow_negative=True)

    @pytest.mark.parametrize(
        "value",
        [
            None,
            [],
            {},
            "",
            " ",
            "abc",
            "1,050.00",
            "1e3",
            "$5",
            "5%",
            "1_000",
            "1/2",
            "٣",
            "1.",
            ".5",
        ],
    )
    def test_rejects_things_that_are_not_decimal_amounts(self, value):
        with pytest.raises(core.InputError):
            core.money(value, "paid")

    def test_negative_and_zero_flags(self):
        for value in (-1, "-0.01", Fraction(-1, 100)):
            with pytest.raises(core.InputError, match="negative"):
                core.money(value, "paid")
            assert core.money(value, "rent", allow_negative=True) < 0
        with pytest.raises(core.InputError, match="greater than zero"):
            core.money(0, "total", allow_zero=False)
        assert core.money(0, "total") == 0

    def test_rejects_absurd_amounts(self):
        assert core.money(10**12, "x") == 10**12
        with pytest.raises(core.InputError, match="too large"):
            core.money(10**12 + 1, "x")

    @given(st.integers(-MAX_CENTS, MAX_CENTS))
    def test_roundtrip_through_text(self, cents):
        text = core.fmt_cents(cents, thousands=False)
        assert core.to_cents(core.money(text, "x", allow_negative=True)) == cents
        with_commas = core.fmt_cents(cents)
        assert with_commas.replace(",", "") == text

    @given(st.integers(-MAX_CENTS, MAX_CENTS))
    def test_whole_cent_fractions_roundtrip(self, cents):
        amount = Fraction(cents, 100)
        assert core.to_cents(amount) == cents
        assert core.money(amount, "x", allow_negative=True) == amount


class TestCentsMarker:
    def test_cents_are_never_read_as_currency_units(self):
        # Cents(95000) is 950.00; read as units it would be 95000.00, a 100-fold error
        with pytest.raises(TypeError, match="already in cents"):
            core.money(core.Cents(95000), "x")
        with pytest.raises(TypeError, match="already in cents"):
            core.to_cents(core.Cents(95000))

    def test_cents_still_format_and_print(self):
        assert core.fmt_cents(core.Cents(95000)) == "950.00"
        assert core.cents_str(core.Cents(-5)) == "-0.05"
        assert repr(core.Cents(7)) == "Cents(7)"
        assert core.Cents(7) + 1 == 8 and type(core.Cents(7) + 1) is int


class TestToCents:
    def test_exact_values_only(self):
        assert core.to_cents(Fraction(29, 100)) == 29
        assert core.to_cents(3) == 300
        with pytest.raises(ValueError, match="whole number of cents"):
            core.to_cents(Fraction(1, 3))
        with pytest.raises(ValueError):
            core.to_cents(Fraction(1, 200))

    @pytest.mark.parametrize("value", [0.29, True, "1.00", None])
    def test_rejects_non_exact_types(self, value):
        with pytest.raises(TypeError):
            core.to_cents(value)


class TestFormat:
    @pytest.mark.parametrize(
        ("cents", "text"),
        [
            (105000, "1,050.00"),
            (-106666, "-1,066.66"),
            (0, "0.00"),
            (5, "0.05"),
            (-5, "-0.05"),
            (99, "0.99"),
            (100, "1.00"),
            (123456789, "1,234,567.89"),
            (-100000000, "-1,000,000.00"),
        ],
    )
    def test_with_thousands(self, cents, text):
        assert core.fmt_cents(cents) == text

    def test_without_thousands(self):
        assert core.fmt_cents(123456789, thousands=False) == "1234567.89"
        assert core.cents_str(-106666) == "-1066.66"

    @pytest.mark.parametrize("value", [True, 1.5, Fraction(1), "5", None])
    def test_requires_int(self, value):
        with pytest.raises(TypeError):
            core.fmt_cents(value)


class TestParseInput:
    def test_decimals_are_exact_and_integers_stay_ints(self):
        data = core.parse_input('{"a": 0.29, "b": 1e2, "c": 3, "d": -0.5, "e": 12.340}')
        assert data["a"] == Fraction(29, 100) and isinstance(data["a"], Fraction)
        assert data["b"] == 100 and isinstance(data["b"], Fraction)
        assert data["c"] == 3 and type(data["c"]) is int
        assert data["d"] == Fraction(-1, 2)
        assert core.to_cents(data["e"]) == 1234

    def test_the_binary_float_trap_is_avoided(self):
        # json.loads would give 0.29, and int(0.29 * 100) is 28
        assert core.to_cents(core.money(core.parse_input("0.29"), "x")) == 29

    def test_load_input_reads_a_stream(self):
        assert core.load_input(io.StringIO('{"total": 8000.50}')) == {"total": Fraction(16001, 2)}

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "{",
            "[1, 2",
            "NaN",
            "Infinity",
            "-Infinity",
            '{"a": NaN}',
            '{"a": 1, "a": 2}',
            "1e999999999",
            "1.5e-999999999",
            "[" * 100000,
            '"\\ud800"x',
        ],
    )
    def test_bad_json_is_an_input_error(self, text):
        with pytest.raises(core.InputError) as caught:
            core.parse_input(text)
        assert caught.value.field == "input"

    def test_oversized_input_is_refused(self):
        with pytest.raises(core.InputError, match="too large"):
            core.parse_input(" " * (core.MAX_INPUT_CHARS + 1))


class TestValidators:
    def test_require_object_and_list(self):
        assert core.require_object({"a": 1}, "f") == {"a": 1}
        with pytest.raises(core.InputError, match="JSON object"):
            core.require_object([], "f")
        assert core.require_list([1], "f", min_len=1, max_len=2) == [1]
        for bad, message in (([], "at least 1"), ([1, 2, 3], "at most 2"), ("x", "list")):
            with pytest.raises(core.InputError, match=message):
                core.require_list(bad, "f", min_len=1, max_len=2)

    def test_require_text(self):
        assert core.require_text("a", "f") == "a"
        for bad in ("", "  ", 3, None):
            with pytest.raises(core.InputError):
                core.require_text(bad, "f")
        assert core.require_text("", "f", allow_empty=True) == ""

    def test_require_int(self):
        assert core.require_int(3, "n", minimum=1, maximum=5) == 3
        assert core.require_int(Fraction(3), "n") == 3  # written as 3.0 in JSON
        for bad in (True, 2.5, Fraction(5, 2), "3", None):
            with pytest.raises(core.InputError, match="whole number"):
                core.require_int(bad, "n")
        with pytest.raises(core.InputError, match="at least"):
            core.require_int(0, "n", minimum=1)
        with pytest.raises(core.InputError, match="at most"):
            core.require_int(9, "n", maximum=5)

    def test_require_names(self):
        assert core.require_names(["阿明", "小红"], "people", min_len=2) == ["阿明", "小红"]
        with pytest.raises(core.InputError) as caught:
            core.require_names(["阿明", "阿明"], "people")
        assert caught.value.field == "people[1]" and "duplicate" in caught.value.message
        for bad in ([""], [" 阿明"], ["阿明 "], [3], [None]):
            with pytest.raises(core.InputError):
                core.require_names(bad, "people")
        with pytest.raises(core.InputError, match="at least 2"):
            core.require_names(["a"], "people", min_len=2)

    def test_require_choice(self):
        assert core.require_choice("allow", "rule", ("allow", "forbid")) == "allow"
        with pytest.raises(core.InputError, match="allow, forbid"):
            core.require_choice("x", "rule", ("allow", "forbid"))
        with pytest.raises(core.InputError):
            core.require_choice(1, "rule", ("allow", "forbid"))
