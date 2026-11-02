"""docs/THEORY.md: one section per skill with the same parts, every guarantee tied to tests that
exist, every reference with its DOI, and prose that follows the rules of the repository."""

from __future__ import annotations

import re

import pytest
import theory_doc as doc

TEXT = doc.theory_text()
SHARED_PARTS = ("Exact amounts and cents", "Public randomness", "Commitments", "Input files")
OVERCLAIMS = [
    "nobody can cheat",
    "cannot be rigged",
    "tamper-proof",
    "impossible to cheat",
    "everybody envy-free",
    "perfectly fair",
    "absolutely fair",
    "谁也做不了手脚",
    "绝对公平",
    "完全公平",
]
LEAKS = doc.LEAKS


class TestStructure:
    def test_the_second_level_headings_are_in_the_documented_order(self):
        assert doc.headings(TEXT, 2) == [
            "How to read the sections",
            "Shared mechanisms",
            *doc.SKILLS,
            "References",
        ]

    def test_the_shared_mechanisms_have_their_parts(self):
        assert doc.headings(doc.section("Shared mechanisms"), 3) == [
            *SHARED_PARTS,
            "Limits that hold for every skill",
        ]

    @pytest.mark.parametrize("skill", doc.SKILLS)
    def test_every_skill_section_has_the_same_three_parts(self, skill):
        assert doc.headings(doc.section(skill), 3) == list(doc.SKILL_PARTS)

    @pytest.mark.parametrize("skill", doc.SKILLS)
    def test_guarantees_are_numbered_from_one_without_gaps(self, skill):
        items = doc.guarantees(doc.subsection(skill, "Guarantees"))
        numbers = [int(re.match(r"(\d+)\.", item).group(1)) for item in items]
        assert numbers == list(range(1, len(items) + 1))
        assert len(items) >= 7

    @pytest.mark.parametrize("skill", doc.SKILLS)
    def test_every_guarantee_names_the_tests_that_check_it(self, skill):
        for item in doc.guarantees(doc.subsection(skill, "Guarantees")):
            assert doc.cited(item), f"{skill}: no test is named for: {item[:70]}"

    @pytest.mark.parametrize("part", SHARED_PARTS)
    def test_every_shared_guarantee_names_the_tests_that_check_it(self, part):
        text = doc.subsection("Shared mechanisms", part)
        items = doc.guarantees(text)
        assert items
        for item in items:
            assert doc.cited(item), f"{part}: no test is named for: {item[:70]}"

    def test_the_skill_sections_open_with_the_folder_that_holds_their_tests(self):
        for skill in doc.SKILLS:
            folder = "tests/skills/" + skill.replace("-", "_") + "/"
            opening = doc.section(skill).split("### Guarantees")[0]
            assert folder in opening, skill


class TestCitedTests:
    def test_every_named_test_exists(self):
        assert doc.missing_tests(TEXT) == []

    def test_test_file_names_are_unique_so_that_file_and_function_are_enough(self):
        duplicated = {
            name: paths for name, paths in doc.file_paths_of_tests().items() if len(paths) > 1
        }
        assert duplicated == {}

    def test_no_test_is_named_without_its_file(self):
        assert doc.BARE_TEST_NAME.findall(TEXT) == []

    @pytest.mark.parametrize("skill", doc.SKILLS)
    def test_a_skill_section_names_only_its_own_tests_and_those_of_the_core(self, skill):
        own = "tests/skills/" + skill.replace("-", "_") + "/"
        paths = doc.file_paths_of_tests()
        for ref in doc.cited(doc.section(skill)):
            (path,) = paths[ref.file]
            where = path.relative_to(doc.REPO).as_posix()
            assert where.startswith((own, "tests/core/")), f"{skill} names {ref.shown()}"

    @pytest.mark.parametrize(
        ("skill", "least"),
        [
            ("rent-split", 35),
            ("bill-split", 40),
            ("ride-split", 25),
            ("group-vote", 40),
            ("chore-split", 90),
            ("slot-lottery", 135),
            ("gift-exchange", 85),
            ("stuff-split", 70),
        ],
    )
    def test_each_skill_names_many_distinct_tests(self, skill, least):
        assert len({ref.shown() for ref in doc.cited(doc.section(skill))}) >= least

    def test_the_shared_mechanisms_name_core_tests_only(self):
        paths = doc.file_paths_of_tests()
        for ref in doc.cited(doc.section("Shared mechanisms")):
            (path,) = paths[ref.file]
            assert path.parent.name == "core", ref.shown()


class TestReferences:
    REFERENCES = doc.section("References")

    def entries(self):
        return [
            line
            for line in self.REFERENCES.splitlines()
            if line.startswith("- ") and "doi:" in line
        ]

    def test_every_reference_carries_a_doi_in_the_form_doi_colon_10_dot(self):
        entries = self.entries()
        assert len(entries) == 31
        for entry in entries:
            assert len(doc.doi_list(entry)) == 1, entry

    def test_no_doi_is_listed_twice(self):
        dois = [d.lower() for d in doc.doi_list(self.REFERENCES)]
        assert len(dois) == len(set(dois))

    def test_the_entries_are_in_alphabetical_order(self):
        names = [entry[2:].split(",")[0] for entry in self.entries()]
        assert names == sorted(names, key=lambda name: name.lower().replace("ğ", "g"))

    def test_every_reference_is_cited_in_the_text_before_the_list(self):
        body = TEXT.split("## References")[0]
        for entry in self.entries():
            surname = entry[2:].split(",")[0]
            year = re.search(r"\b(?:19|20)\d{2}\b", entry.split("doi:")[0])
            assert year is not None, entry
            assert re.search(rf"{surname}[^\n]{{0,80}}{year.group(0)}", body), entry[:60]

    def test_every_dois_pattern_is_plausible(self):
        for doi in doc.doi_list(self.REFERENCES):
            assert re.fullmatch(r"10\.\d{4,9}/[A-Za-z0-9._()/;:-]+", doi.replace(";", "")), doi

    def test_every_work_the_notes_name_is_in_the_list(self):
        notes = self.REFERENCES.split("Notes on the references")[1]
        named = re.findall(
            r"((?:von )?[A-Z][\w-]*)(?: and [A-Z][\w-]*| et al\.)? \(((?:19|20)\d{2})\)", notes
        )
        assert len(named) >= 12
        for surname, year in named:
            assert any(
                entry.startswith(f"- {surname},") and year in entry.split("doi:")[0]
                for entry in self.entries()
            ), f"{surname} ({year}) is named in the notes and missing from the list"


class TestStyle:
    def test_the_prose_has_no_semicolons_or_dashes(self):
        text = doc.prose(TEXT)
        for mark in (";", "—", "–", "‒", " -- "):
            assert mark not in text, repr(mark)

    def test_no_overclaims(self):
        lowered = TEXT.lower()
        assert [claim for claim in OVERCLAIMS if claim.lower() in lowered] == []

    def test_no_machine_paths_or_addresses_anywhere(self):
        for what in ("an absolute path", "an e-mail address"):
            assert LEAKS[what].search(TEXT) is None, what

    def test_no_credential_words_in_the_prose(self):
        assert LEAKS["a credential word"].search(doc.prose(TEXT)) is None

    def test_the_file_is_plain_text(self):
        assert "\t" not in TEXT and "\r" not in TEXT
        assert TEXT.endswith("\n") and not TEXT.endswith("\n\n")
        assert not [line for line in TEXT.splitlines() if line != line.rstrip()]
