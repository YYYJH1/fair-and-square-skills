"""Helpers for the tests that read docs/THEORY.md: its sections, the tests it names and its
references. The module name has no test prefix on purpose, so that pytest does not collect it."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import NamedTuple

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"
THEORY = REPO / "docs" / "THEORY.md"

SKILLS = (
    "rent-split",
    "bill-split",
    "ride-split",
    "group-vote",
    "chore-split",
    "slot-lottery",
    "gift-exchange",
    "stuff-split",
)
SKILL_PARTS = ("Guarantees", "Not guaranteed", "Method")

# What a public file must not hold: a machine path, an e-mail address (or a word that names a
# credential, which only counts outside code).
LEAKS = {
    "an absolute path": re.compile(r"(?<![\w./-])/(?:data|home|tmp|Users|var|mnt|root)/\S+"),
    "an e-mail address": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "a credential word": re.compile(r"api[_-]?key|password|secret|token", re.IGNORECASE),
}

# `test_file.py::function` or `test_file.py::Class::function`
REFERENCE = re.compile(
    r"`(test_[A-Za-z0-9_]+\.py)::(?:([A-Za-z_][A-Za-z0-9_]*)::)?(test_[A-Za-z0-9_]+)`"
)
BARE_TEST_NAME = re.compile(r"`test_[A-Za-z0-9_]+`")
DOI = re.compile(r"doi:(10\.\d{4,9}/\S+)")


class Cited(NamedTuple):
    """A test named in THEORY.md."""

    file: str
    cls: str | None
    function: str

    def shown(self) -> str:
        middle = f"{self.cls}::" if self.cls else ""
        return f"{self.file}::{middle}{self.function}"


def theory_text() -> str:
    return THEORY.read_text(encoding="utf-8")


def section(title: str, text: str | None = None) -> str:
    """The text of the second-level section `## title`, up to the next second-level heading."""
    body = theory_text() if text is None else text
    found = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", body, re.MULTILINE | re.DOTALL)
    if found is None:
        raise LookupError(f"THEORY.md has no section '## {title}'")
    return f"## {title}\n" + found.group(1)


def subsection(title: str, heading: str, text: str | None = None) -> str:
    """The text of `### heading` inside the section `## title`."""
    body = section(title, text)
    found = re.search(
        rf"^### {re.escape(heading)}\n(.*?)(?=^### |\Z)", body, re.MULTILINE | re.DOTALL
    )
    if found is None:
        raise LookupError(f"section '{title}' has no part '### {heading}'")
    return found.group(1)


def headings(markdown: str, level: int) -> list[str]:
    return re.findall(rf"^{'#' * level} (.+)$", markdown, re.MULTILINE)


def guarantees(markdown: str) -> list[str]:
    """The numbered items of a markdown text, each with its continuation lines."""
    items: list[str] = []
    for line in markdown.splitlines():
        if re.match(r"^\d+\. ", line):
            items.append(line)
        elif items and (line.startswith("   ") or not line.strip()):
            items[-1] += "\n" + line
        elif items and line.strip() and not line.startswith(("-", "|")):
            break
    return items


def prose(markdown: str) -> str:
    """The sentences of a markdown text: no code blocks, inline code, tables or block quotes."""
    out = re.sub(r"```.*?```", "", markdown, flags=re.DOTALL)
    out = re.sub(r"`[^`]*`", "", out)
    out = re.sub(r"^\|.*$", "", out, flags=re.MULTILINE)
    return re.sub(r"^\s*>.*$", "", out, flags=re.MULTILINE)


def cited(markdown: str) -> list[Cited]:
    """Every test named as file::function or file::Class::function, in text order."""
    return [Cited(f, c or None, fn) for f, c, fn in REFERENCE.findall(markdown)]


def file_paths_of_tests() -> dict[str, list[Path]]:
    """Every test file name under tests/ with the paths that carry it."""
    found: dict[str, list[Path]] = {}
    for path in sorted(TESTS.rglob("test_*.py")):
        if "__pycache__" not in path.parts:
            found.setdefault(path.name, []).append(path)
    return found


def defined_in(path: Path, cls: str | None, function: str) -> bool:
    """True when the file defines that test function, at module level or inside the class."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if cls is None and isinstance(node, ast.FunctionDef) and node.name == function:
            return True
        if cls is not None and isinstance(node, ast.ClassDef) and node.name == cls:
            return any(
                isinstance(sub, ast.FunctionDef) and sub.name == function for sub in node.body
            )
    return False


def missing_tests(markdown: str) -> list[str]:
    """The tests named in the text that do not exist (or whose file name is not unique)."""
    paths = file_paths_of_tests()
    missing = []
    for ref in cited(markdown):
        files = paths.get(ref.file, [])
        if len(files) != 1 or not defined_in(files[0], ref.cls, ref.function):
            missing.append(ref.shown())
    return missing


def doi_list(markdown: str) -> list[str]:
    return DOI.findall(markdown)
