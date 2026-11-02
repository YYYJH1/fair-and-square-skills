"""The eight SKILL.md files follow one template, so that an agent finds the same thing in the same
place in every skill, and a rule that is stated in one is stated in all.

What the template fixes: the frontmatter description (its length and its three parts), the
headings, the language tag of every fenced block, the sentences on options and exit codes, the
list of example files, the table of input fields, the Reference section, and wording that the
repository does not use (the word manipulation-proof, a promise tied to "this version", semicolons).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "plugin" / "skills"
SKILLS = sorted(path.name for path in SKILLS_DIR.iterdir() if path.is_dir())
DESCRIPTION_LIMIT = 850  # the specification allows 1024, and a limit this close breaks on an edit
EXIT_CODE_2 = "Exit code 2 means invalid input and the message names the field"


def text_of(skill: str) -> str:
    return (SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8")


def description_of(skill: str) -> str:
    found = re.search(r"^description: (.*)$", text_of(skill), flags=re.MULTILINE)
    assert found is not None
    return found.group(1)


def prose_of(skill: str) -> str:
    """The text without fenced blocks and without inline code."""
    kept, inside = [], False
    for line in text_of(skill).split("\n---\n", 1)[1].splitlines():
        if line.lstrip().startswith("```"):
            inside = not inside
        elif not inside:
            kept.append(line)
    return re.sub(r"`[^`]*`", "", "\n".join(kept))


def test_there_are_eight_skills() -> None:
    assert len(SKILLS) == 8


@pytest.mark.parametrize("skill", SKILLS)
class TestDescription:
    def test_it_is_far_from_the_limit_of_1024_characters(self, skill):
        assert len(description_of(skill)) <= DESCRIPTION_LIMIT

    def test_it_has_the_same_three_parts_in_the_same_order(self, skill):
        description = description_of(skill)
        assert description.startswith("Use whenever ")
        assert ", even if nobody asks for an algorithm." in description
        triggers = description.index(" Typical requests include ")
        refusal = description.index(" Not for ")
        assert triggers < refusal
        assert description.endswith(".")

    def test_the_chinese_triggers_sit_in_the_list_of_typical_requests(self, skill):
        description = description_of(skill)
        first_chinese = re.search(r"[一-鿿]", description)
        assert first_chinese is not None
        assert description.index(" Typical requests include ") < first_chinese.start()
        assert first_chinese.start() < description.index(" Not for ")
        assert "。" not in description, "a Chinese full stop in an English sentence"

    def test_it_is_one_plain_line_of_yaml(self, skill):
        description = description_of(skill)
        assert ": " not in description and " #" not in description
        assert "<" not in description and ">" not in description


@pytest.mark.parametrize("skill", SKILLS)
class TestStructure:
    def test_the_headings_every_skill_has(self, skill):
        headings = re.findall(r"^## (.*)$", text_of(skill), flags=re.MULTILINE)
        for needed in ("The script", "Guarantees and limits", "When not to use", "Reference"):
            assert needed in headings, needed
        steps = [heading for heading in headings if heading.startswith("Step ")]
        assert [step[:6] for step in steps] == ["Step 1", "Step 2", "Step 3", "Step 4"]

    def test_the_reference_heading_is_singular_and_comes_last(self, skill):
        headings = re.findall(r"^## (.*)$", text_of(skill), flags=re.MULTILINE)
        assert headings[-1] == "Reference"
        assert "References" not in headings

    def test_a_check_of_an_existing_split_has_the_same_heading_everywhere(self, skill):
        headings = re.findall(r"^## (.*)$", text_of(skill), flags=re.MULTILINE)
        assert "Checking a split already made" not in headings
        if skill in ("rent-split", "bill-split", "ride-split"):
            assert "Checking an existing split" in headings

    def test_every_fenced_block_names_its_language(self, skill):
        inside = False
        for number, line in enumerate(text_of(skill).splitlines(), start=1):
            stripped = line.strip()
            if not stripped.startswith("```"):
                continue
            if not inside:
                assert re.fullmatch(r"```(bash|json|python)", stripped), f"line {number}"
            inside = not inside
        assert not inside

    def test_the_input_fields_have_a_table(self, skill):
        assert "| Field | Meaning |" in text_of(skill)


@pytest.mark.parametrize("skill", SKILLS)
class TestOptionsAndExitCodes:
    def test_the_options_sentence_is_the_same_everywhere(self, skill):
        assert "Options are listed by `--help`." in text_of(skill)
        assert "All flags are listed" not in text_of(skill)

    def test_demo_and_selftest_are_both_described(self, skill):
        body = text_of(skill)
        assert "`--demo`" in body and "`--selftest`" in body

    def test_the_exit_codes_are_all_stated(self, skill):
        body = text_of(skill)
        assert EXIT_CODE_2 in body
        assert "Exit code 1 means" in body
        assert "Exit code 3 means" in body or "there is no exit code 3" in body

    def test_python_and_the_standard_library_are_stated_once(self, skill):
        assert text_of(skill).count("Python 3.9 or later, standard library only.") == 1


@pytest.mark.parametrize("skill", SKILLS)
class TestExamples:
    def test_one_sentence_lists_every_example_file(self, skill):
        body = text_of(skill)
        assert "The `examples/` folder holds " in body
        sentence = body.split("The `examples/` folder holds ")[1].split("\n\n")[0]
        listed = set(re.findall(r"examples/([A-Za-z0-9_.-]+\.json)", sentence))
        actual = {path.name for path in (SKILLS_DIR / skill / "examples").glob("*")}
        assert listed == actual


@pytest.mark.parametrize("skill", SKILLS)
class TestWording:
    def test_nothing_is_promised_for_a_version(self, skill):
        body = text_of(skill).lower()
        for phrase in ("this version", "in this release", "not yet supported"):
            assert phrase not in body, phrase

    def test_one_word_for_one_property(self, skill):
        assert "manipulation-proof" not in text_of(skill).lower()

    def test_no_semicolons_or_dashes_in_the_prose(self, skill):
        prose = prose_of(skill)
        # The Chinese lines in quotation marks are what the script prints.
        prose = re.sub(r'"[^"\n]*[一-鿿][^"\n]*"', "", prose)
        for mark in (";", "；", "—", "–"):
            assert mark not in prose, mark

    def test_the_reference_entries_end_with_a_full_stop_or_a_link(self, skill):
        reference = text_of(skill).split("\n## Reference\n", 1)[1]
        entries = [block.strip() for block in reference.split("\n\n") if block.strip()]
        assert entries
        for entry in entries:
            assert entry.endswith(".") or entry.split()[-1].startswith("http"), entry[-60:]
            assert "doi:" in entry or entry.split()[-1].startswith("http"), entry[:60]
