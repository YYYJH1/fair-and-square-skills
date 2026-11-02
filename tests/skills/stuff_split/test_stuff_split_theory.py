"""What only the stuff-split section of docs/THEORY.md says.

The structure of the section, the tests it names, its prose and its references in general are
checked for every skill by tests/test_theory.py. This file adds the limits that the section has to
spell out and the four references that only stuff-split cites.
"""

from __future__ import annotations

import re

import theory_doc as doc

SKILL = "stuff-split"
SECTION = doc.section(SKILL)
NEW_DOIS = {
    "10.1017/cbo9780511598975": "Brams",
    "10.1086/664613": "Budish",
    "10.1145/3355902": "Caragiannis",
    "10.1145/988772.988792": "Lipton",
}


def entries():
    """The reference entries that name stuff-split."""
    return [
        line
        for line in doc.section("References").splitlines()
        if line.startswith("- ") and "doi:" in line and "stuff-split" in line.split("doi:")[1]
    ]


def test_the_not_guaranteed_part_cites_the_examples_that_show_each_limit():
    part = doc.subsection(SKILL, "Not guaranteed")
    for needed in (
        "Strategy-proofness",
        "Freedom from envy under knaster",
        "Freedom from all envy under max_nash",
        "An equal share of the surplus under envy_free",
        "Efficiency of the turns",
        "Scale when somebody cannot get anything",
        "Equal chances in a tie",
        "Anything outside the model",
        "Size limits",
    ):
        assert needed in part, needed
    assert len(doc.cited(part)) >= 10


def test_the_four_references_of_the_section_are_listed_once_each_with_one_doi():
    found = entries()
    dois = [doc.doi_list(entry) for entry in found]
    assert all(len(one) == 1 for one in dois)
    listed = [one[0].lower() for one in dois]
    for doi, surname in NEW_DOIS.items():
        assert listed.count(doi) == 1, doi
        (entry,) = [e for e in found if doi in e.lower()]
        assert entry[2:].startswith(surname), entry[:60]


def test_the_notes_say_what_each_reference_is_cited_for():
    notes = doc.section("References").split("Notes on the references")[1]
    for needed in (
        "CrossRef",
        "Brams and Taylor (1996) is cited for the Knaster procedure of sealed bids",
        "Lipton et al. (2004) for the notion of envy up to one item",
        "Budish (2011) for its name",
        "Caragiannis et al. (2019) is cited for the maximum Nash welfare rule",
    ):
        assert needed in notes, needed


def test_every_reference_of_the_section_is_cited_in_its_text_with_its_year():
    for entry in entries():
        surname = entry[2:].split(",")[0]
        year = re.search(r"\b(?:19|20)\d{2}\b", entry.split("doi:")[0])
        assert year is not None, entry
        assert re.search(rf"{surname}[^\n]{{0,80}}{year.group(0)}", SECTION), entry[:60]
