"""The text checks that several skills share: encodable text, known fields, one-line notes,
names and source texts, the self-check helper, and filling Chinese templates with Latin names."""

from __future__ import annotations

import fsq_core as core
import pytest
from hypothesis import given
from hypothesis import strategies as st

LONE = core.parse_input('"\\ud800"')  # a lone surrogate, which cannot be written as UTF-8
SURROGATE_MESSAGE = "contains an invalid character (unpaired surrogate)"


class TestEncodable:
    @pytest.mark.parametrize("text", ["", "abc", "阿明", "Coco 小红", "emoji 🎉"])
    def test_encodable_text_is_returned_unchanged(self, text):
        assert core.encodable(text, "name") == text

    def test_a_lone_surrogate_is_an_input_error_naming_the_field(self):
        with pytest.raises(core.InputError) as caught:
            core.encodable("a" + LONE, "people[2]")
        assert caught.value.field == "people[2]"
        assert caught.value.message == SURROGATE_MESSAGE

    @given(st.text())
    def test_every_str_without_surrogates_passes(self, text):
        assert core.encodable(text, "x") == text


class TestCheckFields:
    def test_known_fields_pass(self):
        core.check_fields({"a": 1, "b": 2}, ("a", "b", "c"), "rules")
        core.check_fields({}, ("a",), "rules")

    def test_an_unknown_top_level_field_is_named_without_a_prefix(self):
        with pytest.raises(core.InputError) as caught:
            core.check_fields({"a": 1, "zzz": 2}, ("a", "b"), "")
        assert caught.value.field == "zzz"
        assert caught.value.message == "is not a known field; allowed: a, b"

    def test_an_unknown_nested_field_is_named_with_its_path(self):
        with pytest.raises(core.InputError) as caught:
            core.check_fields({"deadline": 1, "typo": 2}, ("deadline",), "rules")
        assert caught.value.field == "rules.typo"

    def test_the_first_unknown_field_in_input_order_is_reported(self):
        with pytest.raises(core.InputError) as caught:
            core.check_fields({"x": 1, "y": 2}, ("a",), "top")
        assert caught.value.field == "top.x"

    def test_non_text_keys_are_reported_through_str(self):
        with pytest.raises(core.InputError) as caught:
            core.check_fields({1: "x"}, ("a",), "")
        assert caught.value.field == "1"


class TestOneLine:
    def test_the_text_is_trimmed(self):
        assert core.one_line("  before Friday noon \n", "rules.deadline") == "before Friday noon"

    def test_the_limit_is_in_characters_after_trimming(self):
        assert core.one_line(" " + "x" * core.MAX_NOTE_CHARS + " ", "f") == "x" * 300
        with pytest.raises(core.InputError, match="at most 300 characters") as caught:
            core.one_line("x" * 301, "rules.deadline")
        assert caught.value.field == "rules.deadline"

    def test_the_limit_can_be_changed(self):
        assert core.one_line("abcd", "f", max_chars=4) == "abcd"
        with pytest.raises(core.InputError, match="at most 3 characters"):
            core.one_line("abcd", "f", max_chars=3)

    @pytest.mark.parametrize("text", ["a\nb", "a\rb", "a\r\nb"])
    def test_more_than_one_line_is_refused(self, text):
        with pytest.raises(core.InputError, match="single line"):
            core.one_line(text, "f")

    @pytest.mark.parametrize("value", [None, 5, ["x"], True])
    def test_it_must_be_text(self, value):
        with pytest.raises(core.InputError, match="must be text"):
            core.one_line(value, "f")

    @pytest.mark.parametrize("value", ["", "   ", "\n"])
    def test_it_must_not_be_blank(self, value):
        with pytest.raises(core.InputError, match="must not be empty"):
            core.one_line(value, "f")

    def test_a_lone_surrogate_is_refused(self):
        with pytest.raises(core.InputError) as caught:
            core.one_line("x" + LONE, "f")
        assert caught.value.message == SURROGATE_MESSAGE


class TestRequireEncodableNames:
    def test_names_come_back_as_a_list_in_input_order(self):
        assert core.require_encodable_names(["小红", "Coco"], "people") == ["小红", "Coco"]

    def test_the_rules_of_require_names_still_apply(self):
        with pytest.raises(core.InputError, match="duplicate") as caught:
            core.require_encodable_names(["a", "a"], "people", 2)
        assert caught.value.field == "people[1]"
        with pytest.raises(core.InputError, match="at least 2"):
            core.require_encodable_names(["a"], "people", 2)
        with pytest.raises(core.InputError, match="at most 2"):
            core.require_encodable_names(["a", "b", "c"], "people", 1, 2)
        with pytest.raises(core.InputError, match="must be a list"):
            core.require_encodable_names("ab", "people")

    def test_a_name_with_a_lone_surrogate_is_refused_with_its_position(self):
        with pytest.raises(core.InputError) as caught:
            core.require_encodable_names(["a", "b" + LONE], "slot_names")
        assert caught.value.field == "slot_names[1]"
        assert caught.value.message == SURROGATE_MESSAGE


class TestRequireSourceText:
    def test_the_text_is_kept_exactly_as_given(self):
        text = "  （虚构示例）03 11 19  \t"
        assert core.require_source_text(text, "random_source") == text

    def test_the_limit_is_in_characters(self):
        assert core.require_source_text("x" * core.MAX_SOURCE_CHARS, "s") == "x" * 10_000
        with pytest.raises(core.InputError, match="at most 10000 characters") as caught:
            core.require_source_text("x" * 10_001, "rules.random_source")
        assert caught.value.field == "rules.random_source"

    def test_the_limit_can_be_changed(self):
        with pytest.raises(core.InputError, match="at most 5 characters"):
            core.require_source_text("abcdef", "s", max_chars=5)

    @pytest.mark.parametrize("value", [None, 20261108, ["x"]])
    def test_it_must_be_text(self, value):
        with pytest.raises(core.InputError, match="must be text"):
            core.require_source_text(value, "s")

    @pytest.mark.parametrize("value", ["", "   ", "\n\t"])
    def test_it_must_not_be_blank(self, value):
        with pytest.raises(core.InputError, match="must not be empty"):
            core.require_source_text(value, "s")

    def test_a_lone_surrogate_is_refused(self):
        with pytest.raises(core.InputError) as caught:
            core.require_source_text("src" + LONE, "random_source")
        assert caught.value.message == SURROGATE_MESSAGE


class TestExpect:
    def test_a_true_condition_passes_silently(self):
        assert core.expect(1 + 1 == 2, "arithmetic") is None

    def test_a_false_condition_raises_with_the_message(self):
        with pytest.raises(AssertionError, match="the sum was 3"):
            core.expect(1 + 1 == 3, "the sum was 3")

    def test_the_self_test_runner_reports_it_as_a_failed_check(self, capsys):
        def broken() -> None:
            core.expect(False, "no good")

        assert core.run_selftest([("broken", broken)], include_core=False) == 1
        assert "FAIL broken: AssertionError: no good" in capsys.readouterr().out


class TestFillText:
    @pytest.mark.parametrize(
        ("template", "values", "expected"),
        [
            ("{name}赢了", {"name": "Coco"}, "Coco 赢了"),
            ("赢家是{name}", {"name": "Coco"}, "赢家是 Coco"),
            ("把{a}给{b}", {"a": "Amy", "b": "Bob"}, "把 Amy 给 Bob"),
            ("第{n}周", {"n": 3}, "第 3 周"),
            ("{name}赢了", {"name": "小红"}, "小红赢了"),
            ("「{name}」赢了", {"name": "Coco"}, "「Coco」赢了"),
            ("{name}：赢了", {"name": "Coco"}, "Coco：赢了"),
            ("赢家 {name} 来了", {"name": "Coco"}, "赢家 Coco 来了"),
            ("{name}赢了", {"name": "Zoë"}, "Zoë赢了"),
            ("{name}赢了", {"name": "Coco_"}, "Coco_赢了"),
            ("{name}赢了", {"name": "小红 Coco"}, "小红 Coco 赢了"),
            ("{name}赢了", {"name": ""}, "赢了"),
            ("每{n}天", {"n": "2.5"}, "每 2.5 天"),
        ],
    )
    def test_chinese_gets_a_space_where_an_ascii_value_touches_a_chinese_character(
        self, template, values, expected
    ):
        assert core.fill_text("zh", template, **values) == expected

    def test_english_is_filled_exactly_like_str_format(self):
        template = "{name}赢了 {n}"
        assert core.fill_text("en", template, name="Coco", n=3) == template.format(name="Coco", n=3)

    def test_the_value_itself_is_never_changed(self):
        text = core.fill_text("zh", "{a}和{b}", a="Amy", b="Bob")
        assert "Amy" in text and "Bob" in text

    def test_a_missing_value_is_a_key_error_as_with_str_format(self):
        with pytest.raises(KeyError):
            core.fill_text("zh", "{name}赢了")

    @given(
        st.text(alphabet="ABCabc12", min_size=1, max_size=6),
        st.text(alphabet="赢了周天", min_size=1, max_size=4),
        st.text(alphabet="赢了周天", min_size=0, max_size=4),
    )
    def test_removing_the_spaces_gives_the_plain_result(self, value, left, right):
        template = left + "{name}" + right
        filled = core.fill_text("zh", template, name=value)
        assert filled.replace(" ", "") == template.format(name=value)
        assert filled.startswith(left + " ") and value in filled
