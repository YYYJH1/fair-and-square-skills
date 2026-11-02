"""The files that ship with the stuff-split skill: the script source, the examples, the folder.

The script must run on Python 3.9 with the standard library alone, importing it must do nothing,
the examples must say that they are made up, and no public file may hold a machine path, an
address or a credential.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from stuff_split_support import EXAMPLES, GOLDEN, REPO, SCRIPT, SKILL, SKILL_MD

SOURCE = SCRIPT.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)
TESTS_DIR = Path(__file__).resolve().parent
# Things that must never reach a public file: machine paths, e-mail addresses and credential words.
LEAKS = {
    "an absolute path": re.compile(r"(?<![\w./-])/(?:data|home|tmp|Users|var|mnt|root)/\S+"),
    "an e-mail address": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "a credential word": re.compile(r"api[_-]?key|password|secret|token", re.IGNORECASE),
}


def test_the_copy_of_the_shared_core_is_the_real_core():
    copy = (SKILL / "scripts" / "fsq_core.py").read_bytes()
    assert copy == (REPO / "core" / "fsq_core.py").read_bytes()


def test_the_script_parses_with_python_3_9_grammar():
    ast.parse(SOURCE, feature_version=(3, 9))


def test_the_script_imports_only_the_standard_library_and_the_shared_core():
    modules = set()
    for node in ast.walk(TREE):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.add((node.module or "").split(".")[0])
    stdlib = set(getattr(sys, "stdlib_module_names", ())) or {
        "__future__", "argparse", "collections", "dataclasses", "fractions", "itertools", "math",
        "pathlib", "sys", "typing",
    }  # fmt: skip
    assert modules - {"fsq_core"} <= stdlib
    assert "random" not in modules  # the tie order comes from the SHA-256 counter of the core


def test_the_script_starts_with_future_annotations_and_has_no_python_3_10_only_helpers():
    first = next(node for node in TREE.body if not isinstance(node, ast.Expr))
    assert isinstance(first, ast.ImportFrom) and first.module == "__future__"
    for banned in ("bit_count", "pairwise", "strict=True", "removeprefix", "match "):
        assert banned not in SOURCE, banned


def test_the_script_does_not_write_or_reach_out():
    for forbidden in ("subprocess", "socket", "urllib", "open(", "eval(", "exec(", "random."):
        assert forbidden not in SOURCE, forbidden


def test_importing_the_script_does_nothing(tmp_path):
    code = (
        f"import sys; sys.path.insert(0, {str(SCRIPT.parent)!r}); import stuff_split; "
        "print(stuff_split.METHODS)"
    )
    done = subprocess.run(
        [sys.executable, "-I", "-B", "-c", code],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout == "('envy_free', 'knaster', 'max_nash')\n"
    assert list(tmp_path.iterdir()) == []


def test_the_skill_folder_holds_exactly_the_expected_files():
    found = sorted(
        path.relative_to(SKILL).as_posix()
        for path in SKILL.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )
    assert found == [
        "LICENSE",
        "SKILL.md",
        "examples/moving_out_14_items.json",
        "examples/piano_envy_free.json",
        "examples/piano_knaster.json",
        "examples/three_roommates.json",
        "examples/weighted_knaster.json",
        "scripts/fsq_core.py",
        "scripts/stuff_split.py",
    ]


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.json")), ids=lambda path: path.name)
def test_every_example_says_that_it_is_made_up_and_names_its_rule(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["note"].startswith("虚构示例")
    assert data["rules"]["method"] in ("envy_free", "knaster", "max_nash")
    assert path.read_text(encoding="utf-8").endswith("}\n")


def test_the_demo_and_the_piano_in_the_script_are_two_of_the_example_files():
    import stuff_split as ss

    assert json.loads(ss.DEMO_JSON) == json.loads(
        (EXAMPLES / "three_roommates.json").read_text(encoding="utf-8")
    )
    assert json.loads(ss.PIANO_JSON) == json.loads(
        (EXAMPLES / "piano_knaster.json").read_text(encoding="utf-8")
    )


def public_files():
    files = [SKILL_MD, SCRIPT, *sorted(EXAMPLES.glob("*.json"))]
    files += sorted(TESTS_DIR.glob("*.py")) + sorted(GOLDEN.glob("*.txt"))
    return files


@pytest.mark.parametrize("path", public_files(), ids=lambda path: path.name)
def test_public_files_hold_no_machine_path_address_or_credential(path):
    content = path.read_text(encoding="utf-8")
    for what, pattern in LEAKS.items():
        if path.name == Path(__file__).name and what != "a credential word":
            continue  # this file spells the patterns out
        if what == "a credential word" and path.suffix == ".py" and path.parent == TESTS_DIR:
            continue  # test code may use words such as token for something else
        found = pattern.search(content)
        assert found is None, f"{path.name} contains {what}: {found.group(0)!r}"


def test_the_stored_outputs_and_the_examples_are_utf8_text_without_tabs_or_carriage_returns():
    for path in [*sorted(GOLDEN.glob("*.txt")), *sorted(EXAMPLES.glob("*.json")), SKILL_MD]:
        content = path.read_text(encoding="utf-8")
        assert "\r" not in content and content.endswith("\n"), path.name
