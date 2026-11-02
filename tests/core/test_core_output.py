"""The result envelope and its md, dm, group and json writers."""

from __future__ import annotations

import json
from fractions import Fraction

import fsq_core as core
import pytest
from hypothesis import given
from hypothesis import strategies as st

ENVELOPE_KEYS = ["certificate", "inputs_echo", "not_modeled", "reproduce", "result"]


def sample_result() -> core.Result:
    return core.Result(
        title="分房租",
        inputs_echo={
            "total_rent": core.Cents(800000),
            "people": ["阿明", "小红"],
            "rule": "spliddit",
        },
        result={
            "rent": {"阿明": core.Cents(95000), "小红": core.Cents(-106666)},
            "rule_applied": "不倒贴",
            "count": 2,
            "exact": True,
        },
        certificate={
            "one_liner": {"阿明": "按你报的价，换哪间都不会更划算"},
            "max_envy": core.Cents(0),
        },
        not_modeled=["不防策略", "不含预算上限"],
        reproduce="python3 scripts/rent_split.py --input - --format md",
        tables=[
            core.Table(
                header=["人", "房租"],
                rows=[["阿明", "950.00"], ["小红|备注", "-1,066.66"]],
                caption="分配",
            )
        ],
        notes=["以上金额由脚本算出。"],
        person_lines={"阿明": ["你付 950.00", "换哪间都不会更划算"], "小红": ["你付 -1,066.66"]},
        group_lines=["本月房租已分好，各人私信查收。"],
    )


class TestJsonable:
    def test_cents_become_two_decimal_strings(self):
        out = core.jsonable(
            {"a": core.Cents(95000), "b": [core.Cents(-106666), core.Cents(5), core.Cents(0)]}
        )
        assert out == {"a": "950.00", "b": ["-1066.66", "0.05", "0.00"]}

    def test_plain_values_pass_through(self):
        value = {"n": 3, "flag": True, "none": None, "text": "阿明", "list": (1, 2)}
        assert core.jsonable(value) == {
            "n": 3,
            "flag": True,
            "none": None,
            "text": "阿明",
            "list": [1, 2],
        }
        assert core.jsonable(value)["flag"] is True
        assert type(core.jsonable(core.jsonable(3))) is int

    @pytest.mark.parametrize("bad", [Fraction(1, 2), 1.5, {1, 2}, b"x", object()])
    def test_unsafe_numbers_and_types_are_refused(self, bad):
        with pytest.raises(TypeError, match=r"\$\.result\.rent"):
            core.jsonable({"result": {"rent": bad}})

    def test_non_text_keys_are_refused(self):
        with pytest.raises(TypeError, match="not text"):
            core.jsonable({1: "a"})

    def test_a_bare_cent_count_is_not_confused_with_money(self):
        assert core.jsonable({"people": 4}) == {"people": 4}
        assert core.jsonable({"rent": core.Cents(400)}) == {"rent": "4.00"}


class TestJson:
    def test_envelope_has_exactly_the_five_keys(self):
        assert sorted(core.envelope(sample_result())) == ENVELOPE_KEYS
        assert sorted(json.loads(core.render_json(core.Result()))) == ENVELOPE_KEYS

    def test_amounts_are_strings_with_two_decimals(self):
        data = json.loads(core.render_json(sample_result()))
        assert data["result"]["rent"] == {"阿明": "950.00", "小红": "-1066.66"}
        assert data["inputs_echo"]["total_rent"] == "8000.00"
        assert data["certificate"]["max_envy"] == "0.00"
        assert data["result"]["count"] == 2 and data["result"]["exact"] is True

    def test_keys_are_sorted_at_every_level(self):
        def check(pairs):
            keys = [key for key, _ in pairs]
            assert keys == sorted(keys)
            return dict(pairs)

        json.loads(core.render_json(sample_result()), object_pairs_hook=check)

    def test_text_is_not_escaped_and_ends_with_one_newline(self):
        text = core.render_json(sample_result())
        assert "阿明" in text and "\\u" not in text
        assert text.endswith("}\n") and not text.endswith("\n\n")

    def test_same_input_same_bytes(self):
        assert core.render_json(sample_result()) == core.render_json(sample_result())

    def test_fractions_in_the_result_are_a_programming_error(self):
        result = core.Result(result={"rent": Fraction(95000, 100)})
        with pytest.raises(TypeError):
            core.render_json(result)


class TestMarkdown:
    def test_layout(self):
        text = core.render_md(sample_result())
        assert text.startswith("# 分房租\n\n## 分配\n\n| 人 | 房租 |\n| --- | --- |\n")
        assert "| 阿明 | 950.00 |" in text
        assert "| 小红\\|备注 | -1,066.66 |" in text  # a pipe inside a cell is escaped
        assert "以上金额由脚本算出。" in text
        assert "## 本结果不包含\n\n- 不防策略\n- 不含预算上限\n" in text
        assert (
            "## 复算命令\n\n```\npython3 scripts/rent_split.py --input - --format md\n```\n" in text
        )
        assert text.endswith("```\n")

    def test_english_labels(self):
        text = core.render_md(sample_result(), lang="en")
        assert "## Not modeled" in text and "## Reproduce" in text

    def test_empty_result_is_a_single_newline_free_of_noise(self):
        assert core.render_md(core.Result()) == "\n"

    def test_markdown_holds_nothing_of_the_dm_or_group_sections(self):
        text = core.render_md(sample_result())
        assert "各人私信查收" not in text and "你付" not in text

    def test_ragged_rows_are_refused(self):
        result = core.Result(tables=[core.Table(["a", "b"], [["only one"]])])
        with pytest.raises(ValueError, match="cells"):
            core.render_md(result)

    def test_unknown_language(self):
        with pytest.raises(ValueError, match="lang"):
            core.render_md(sample_result(), lang="fr")


class TestDirectMessages:
    def test_one_message_per_person_in_listing_order(self):
        messages = core.render_dm_messages(sample_result())
        assert list(messages) == ["阿明", "小红"]
        assert messages["阿明"] == "你付 950.00\n换哪间都不会更划算"
        assert messages["小红"] == "你付 -1,066.66"

    def test_each_message_holds_only_that_persons_numbers(self):
        messages = core.render_dm_messages(sample_result())
        assert "1,066.66" not in messages["阿明"]
        assert "950.00" not in messages["小红"]

    def test_text_has_a_note_for_the_organizer_and_a_header_per_person(self):
        text = core.render_dm(sample_result())
        assert text.startswith(
            "（给组织者：下面每一段只私发给对应的人，不要贴到群里。）\n\n--- 发给 阿明 ---\n你付 950.00"
        )
        assert "\n\n--- 发给 小红 ---\n你付 -1,066.66\n" in text
        assert text.endswith("\n") and not text.endswith("\n\n")
        english = core.render_dm(sample_result(), lang="en")
        assert "--- To 小红 ---" in english and "send each block below privately" in english

    def test_names_with_braces_do_not_break_the_template(self):
        result = core.Result(person_lines={"{person}": ["x"], "a}b": ["y"]})
        text = core.render_dm(result)
        assert "--- 发给 {person} ---" in text and "--- 发给 a}b ---" in text

    def test_no_messages_is_a_programming_error(self):
        with pytest.raises(ValueError, match="per-person"):
            core.render_dm(core.Result())


class TestGroup:
    def test_only_the_title_and_group_lines(self):
        assert core.render_group(sample_result()) == "分房租\n本月房租已分好，各人私信查收。\n"

    def test_nothing_private_can_leak_from_other_sections(self):
        text = core.render_group(sample_result())
        for private in ("950.00", "1,066.66", "1066.66", "换哪间", "spliddit", "不防策略"):
            assert private not in text

    @given(
        st.lists(st.text(alphabet="0123456789.,", min_size=3, max_size=9), min_size=1, max_size=6),
        st.lists(st.text(alphabet="abcdefg", min_size=1, max_size=6), min_size=1, max_size=4),
    )
    def test_group_text_never_contains_private_cells_or_lines(self, secrets_found, names):
        secrets_found = [f"#{s}#" for s in secrets_found]
        result = core.Result(
            title="T",
            tables=[core.Table(["h"], [[s] for s in secrets_found])],
            notes=secrets_found,
            person_lines={name: secrets_found for name in names},
            certificate={"private": secrets_found},
            group_lines=["public line"],
        )
        text = core.render_group(result)
        assert text == "T\npublic line\n"
        assert not any(secret in text for secret in secrets_found)

    def test_empty_summary_is_a_programming_error(self):
        with pytest.raises(ValueError, match="group"):
            core.render_group(core.Result())


class TestRenderDispatch:
    @pytest.mark.parametrize("fmt", ["md", "dm", "group"])
    def test_same_input_same_bytes(self, fmt):
        assert core.render(sample_result(), fmt) == core.render(sample_result(), fmt)

    def test_choice_of_writer(self):
        result = sample_result()
        assert core.render(result, "md") == core.render_md(result)
        assert core.render(result, "dm") == core.render_dm(result)
        assert core.render(result, "group") == core.render_group(result)
        assert core.render(result, "group", as_json=True) == core.render_json(result)
        assert core.render(result, "md", lang="en") == core.render_md(result, "en")

    def test_unknown_format(self):
        with pytest.raises(ValueError, match="fmt"):
            core.render(sample_result(), "html")
