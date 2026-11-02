"""The files that ship with the skill: SKILL.md, the examples, the script source, and its section of
docs/THEORY.md.

SKILL.md is part of the product, so its rules are tested like code: its frontmatter, its length,
and above all that every command in it runs.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import theory_doc as doc
from rent_split_support import EXAMPLES, GOLDEN, REPO, SCRIPT, SKILL, SKILL_MD


def load_validator():
    spec = importlib.util.spec_from_file_location(
        "validate_plugin_for_rent_split", REPO / "tools" / "validate_plugin.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


vp = load_validator()
TEXT = SKILL_MD.read_text(encoding="utf-8")
COMMAND_START = "python3 ${CLAUDE_SKILL_DIR}/scripts/rent_split.py"


def frontmatter():
    parts = vp.split_frontmatter(TEXT)
    assert parts is not None
    return vp.parse_frontmatter(parts[0])


def bash_blocks():
    return re.findall(r"^```bash\n(.*?)^```$", TEXT, re.MULTILINE | re.DOTALL)


def first_heredoc_input():
    """The JSON of the first heredoc in SKILL.md, the input of the main example."""
    block = next(b for b in bash_blocks() if "<<'EOF'" in b)
    return block.partition("<<'EOF'\n")[2].rsplit("\nEOF", 1)[0]


# --------------------------------------------------------------------------------------
# SKILL.md
# --------------------------------------------------------------------------------------


def test_the_repository_validator_accepts_the_skill():
    assert vp.check_skill(SKILL, REPO) == []


def test_the_copy_of_the_shared_core_is_the_real_core():
    copy = (SKILL / "scripts" / "fsq_core.py").read_bytes()
    assert copy == (REPO / "core" / "fsq_core.py").read_bytes()


def test_frontmatter_uses_only_fields_of_the_open_specification():
    fields = frontmatter()
    assert set(fields) == {"name", "description", "license", "allowed-tools"}
    assert fields["name"] == "rent-split" == SKILL.name
    assert fields["license"] == "MIT"
    assert fields["allowed-tools"] == f"Bash({COMMAND_START} *)"


def test_the_description_triggers_in_english_and_chinese_and_points_to_the_neighbours():
    description = frontmatter()["description"]
    assert len(description) <= 1024
    assert "<" not in description
    assert ">" not in description
    for phrase in ("roommates", "rent split", "bill-split", "slot-lottery", "分房租", "公平吗"):
        assert phrase in description, phrase
    assert description.startswith("Use whenever")


def test_the_body_is_in_english_and_short():
    assert len(TEXT.splitlines()) < 500
    body = TEXT.split("---", 2)[2]
    prose = re.sub(r"```.*?```", "", body, flags=re.DOTALL)
    prose = re.sub(r"^>.*$", "", prose, flags=re.MULTILINE)  # the Chinese rules message
    chinese = "".join(re.findall(r"[一-鿿]+", prose))
    letters = re.findall(r"[A-Za-z]+", prose)
    # Only one quoted certificate line and a few words such as 倒收 are Chinese.
    assert len(chinese) < 100, len(chinese)
    assert len(letters) > 600


def test_the_script_is_called_through_the_skill_dir_variable_with_a_fallback_sentence():
    assert "${CLAUDE_SKILL_DIR}/scripts/rent_split.py" in TEXT
    assert "If that variable was not replaced, the script is in the `scripts/` folder" in TEXT


def test_each_step_says_when_it_is_done():
    for heading in ("Step 1", "Step 2", "Step 3", "Step 4"):
        section = re.search(rf"^## {heading}.*?(?=^## |\Z)", TEXT, re.MULTILINE | re.DOTALL)
        assert section is not None, heading
        assert "Done when" in section.group(0), heading


def test_the_required_sections_are_present():
    headings = re.findall(r"^## (.*)$", TEXT, re.MULTILINE)
    for wanted in (
        "The script",
        "The organizer goes first",
        "Checking an existing split",
        "Guarantees and limits",
        "When not to use",
        "Reference",
    ):
        assert wanted in headings, wanted
    assert "Step 3. Run" in " ".join(headings)


def test_the_text_states_the_three_runs_the_exit_codes_and_the_ban_on_doing_arithmetic():
    for phrase in (
        "--format md",
        "--format dm",
        "--format group",
        "Exit code 2",
        "Exit code 3",
        "Exit code 1",
        "Do not compute, estimate or adjust",
        "never scales",
    ):
        assert phrase in TEXT, phrase


def test_there_are_runnable_blocks_and_each_starts_with_the_allowed_command():
    blocks = bash_blocks()
    assert len(blocks) >= 5
    for block in blocks:
        assert block.startswith(COMMAND_START), block.splitlines()[0]


@pytest.mark.parametrize("index", range(len(bash_blocks())))
def test_every_command_in_skill_md_runs(index, tmp_path):
    block = bash_blocks()[index]
    if "--delete-input" in block:
        # The command for Claude Code names a file that the agent writes first. Write the
        # documented input there. The script deletes it again, so the folder ends up empty.
        path = tmp_path / "input.json"
        path.write_text(first_heredoc_input(), encoding="utf-8")
        block = block.replace("<input-file>", str(path))
    command = block.replace("python3 ", f"{sys.executable} -B ", 1)
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    env["CLAUDE_SKILL_DIR"] = str(SKILL)
    done = subprocess.run(
        ["bash", "-c", command],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, f"{block}\n{done.stdout}\n{done.stderr}"
    assert done.stdout.strip()
    assert list(tmp_path.iterdir()) == []  # nothing is written next to the user's files


def test_the_verify_example_in_skill_md_belongs_to_the_commit_example():
    blocks = bash_blocks()
    commit = next(b for b in blocks if "--commit" in b)
    verify = next(b for b in blocks if "--verify-commit" in b)
    assert '"阿明": [3000, 2200, 1600, 1200]' in commit
    assert '"阿明": [3000, 2200, 1600, 1200]' in verify


def test_the_chinese_certificate_example_in_skill_md_is_what_the_script_prints():
    done = subprocess.run(
        [sys.executable, "-B", str(SCRIPT), "--input", str(EXAMPLES / "four_roommates.json")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    quoted = re.search(r"“?(按你报的价，南次卧[^”\"]*打平不算吃亏。)", TEXT)
    assert quoted is not None
    assert quoted.group(1) in done.stdout


# --------------------------------------------------------------------------------------
# The script source
# --------------------------------------------------------------------------------------

SOURCE = SCRIPT.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


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
        "__future__", "argparse", "collections", "dataclasses", "fractions", "math", "pathlib", "sys",
        "typing",
    }  # fmt: skip
    assert modules - {"fsq_core"} <= stdlib
    assert "random" not in modules  # the draws come from the SHA-256 counter of the core


def test_the_script_starts_with_future_annotations_and_has_no_python_3_10_only_helpers():
    first = next(node for node in TREE.body if not isinstance(node, ast.Expr))
    assert isinstance(first, ast.ImportFrom) and first.module == "__future__"
    for banned in ("bit_count", "pairwise", "strict=True", "removeprefix"):
        assert banned not in SOURCE, banned


def test_importing_the_script_does_nothing(tmp_path):
    code = (
        f"import sys; sys.path.insert(0, {str(SCRIPT.parent)!r}); import rent_split; "
        "print(rent_split.NEGATIVE_RENT_RULES)"
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
    assert done.stdout == "('spliddit', 'allow', 'forbid')\n"
    assert list(tmp_path.iterdir()) == []


# --------------------------------------------------------------------------------------
# What ships
# --------------------------------------------------------------------------------------


def test_the_skill_folder_holds_exactly_the_expected_files():
    found = sorted(
        path.relative_to(SKILL).as_posix()
        for path in SKILL.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )
    assert found == [
        "LICENSE",
        "SKILL.md",
        "examples/audit_equal_split.json",
        "examples/four_roommates.json",
        "examples/storage_room.json",
        "scripts/fsq_core.py",
        "scripts/rent_split.py",
    ]


def public_files():
    files = [SKILL_MD, SCRIPT, doc.THEORY, *sorted(EXAMPLES.glob("*.json"))]
    files += sorted(Path(__file__).resolve().parent.glob("*.py"))
    files += sorted(GOLDEN.glob("*.txt"))
    return files


@pytest.mark.parametrize("path", public_files(), ids=lambda path: path.name)
def test_public_files_hold_no_machine_path_or_address(path):
    text = path.read_text(encoding="utf-8")
    for what in ("an absolute path", "an e-mail address"):
        found = doc.LEAKS[what].search(text)
        assert found is None, f"{path.name} contains {what}: {found.group(0)!r}"


# --------------------------------------------------------------------------------------
# The skill's section of docs/THEORY.md
# --------------------------------------------------------------------------------------


def test_the_theory_section_has_the_parts_and_cites_the_references_of_the_skill():
    text = doc.section("rent-split")
    assert text.startswith("## rent-split\n")
    assert doc.headings(text, 3) == ["Guarantees", "Not guaranteed", "Method"]
    references = doc.section("References")
    for doi in ("10.1145/3131361", "10.1145/2728732.2728738", "10.2307/1912044"):
        assert f"doi:{doi}" in references, doi
    for author in ("Gal, Mash, Procaccia and Zick", "Goldman and Procaccia", "Svensson"):
        assert author in text, author
    assert ";" not in text
    assert "—" not in text


def test_every_test_the_theory_section_cites_exists():
    text = doc.section("rent-split")
    assert len({ref.shown() for ref in doc.cited(text)}) >= 30
    assert doc.missing_tests(text) == []
    assert "scipy.optimize.linprog" in text


def test_the_theory_section_holds_no_machine_paths_or_credentials():
    text = doc.section("rent-split")
    for what in ("an absolute path", "an e-mail address"):
        assert doc.LEAKS[what].search(text) is None, what
