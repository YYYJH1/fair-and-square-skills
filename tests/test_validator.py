"""Unit tests for tools/validate_plugin.py, run against throw-away fixture trees."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import textwrap
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
VALIDATOR_PATH = ROOT / "tools" / "validate_plugin.py"

MARKETPLACE = ".claude-plugin/marketplace.json"
CLAUDE_MANIFEST = "plugin/.claude-plugin/plugin.json"
SKILLS = "plugin/skills"

DESCRIPTION = "Use whenever people need to settle something fairly. Not for unrelated things."


def load_validator() -> ModuleType:
    """Import tools/validate_plugin.py by path (tools/ is not a package)."""
    spec = importlib.util.spec_from_file_location("validate_plugin", VALIDATOR_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


vp = load_validator()


# --------------------------------------------------------------------------------------
# Fixture tree helpers
# --------------------------------------------------------------------------------------


def write(path: Path, text: str) -> Path:
    """Write a UTF-8 text file, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_json(path: Path, data: object) -> None:
    """Write a JSON file."""
    write(path, json.dumps(data, indent=2) + "\n")


def edit_json(path: Path, change: Callable[[Any], object]) -> None:
    """Load a JSON file, apply ``change`` to the parsed data and save it again."""
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    write_json(path, data)


def skill_md(
    name: str = "demo-skill", description: str = DESCRIPTION, extra: str = "", body: str = ""
) -> str:
    """Return the text of a valid SKILL.md. ``extra`` is more frontmatter, one line per field."""
    return f"---\nname: {name}\ndescription: {description}\n{extra}---\n\n# {name}\n\n{body}\n"


def add_skill(root: Path, name: str = "demo-skill", **fields: str) -> Path:
    """Create a skill directory with a SKILL.md, one script and one example."""
    directory = root / SKILLS / name
    write(directory / "SKILL.md", skill_md(name=name, **fields))
    write(directory / "scripts" / "demo.py", "print('demo')\n")
    write(directory / "examples" / "input.json", "{}\n")
    return directory


def build_repo(root: Path, skills: tuple[str, ...] = ("demo-skill",)) -> Path:
    """Create a repository tree that passes every check."""
    entry = {"name": "fair-and-square", "source": "./plugin", "description": "Test."}
    write_json(
        root / MARKETPLACE,
        {"name": "fair-and-square", "owner": {"name": "Tester"}, "plugins": [entry]},
    )
    manifest = {"name": "fair-and-square", "version": "0.0.1", "description": "Test."}
    write_json(root / CLAUDE_MANIFEST, manifest)
    (root / SKILLS).mkdir(parents=True, exist_ok=True)
    for name in skills:
        add_skill(root, name)
    return root


def rule_ids(root: Path) -> list[str]:
    """Return the rule ids of every problem found under ``root``, sorted."""
    return sorted(problem.rule for problem in vp.validate(root))


def problems_for(root: Path, rule: str) -> list[Any]:
    """Return only the problems reported under one rule."""
    return [problem for problem in vp.validate(root) if problem.rule == rule]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A valid repository with one skill called demo-skill."""
    return build_repo(tmp_path)


# --------------------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------------------


def test_valid_tree_passes(repo: Path) -> None:
    assert vp.validate(repo) == []


def test_empty_skills_directory_is_valid(tmp_path: Path) -> None:
    root = build_repo(tmp_path, skills=())
    write(root / SKILLS / ".gitkeep", "")
    assert vp.validate(root) == []


def test_missing_skills_directory_is_reported(tmp_path: Path) -> None:
    root = build_repo(tmp_path, skills=())
    (root / SKILLS).rmdir()
    assert rule_ids(root) == ["layout"]


def test_skill_directory_without_skill_md_is_reported(repo: Path) -> None:
    (repo / SKILLS / "demo-skill" / "SKILL.md").unlink()
    assert rule_ids(repo) == ["skill-file"]


# --------------------------------------------------------------------------------------
# SKILL.md frontmatter fields
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    [
        "when_to_use",
        "argument-hint",
        "disable-model-invocation",
        "user-invocable",
        "model",
        "context",
        "version",
    ],
)
def test_fields_outside_the_open_spec_are_rejected(repo: Path, field: str) -> None:
    add_skill(repo, "demo-skill", extra=f"{field}: something\n")
    found = problems_for(repo, "frontmatter-fields")
    assert len(found) == 1
    assert field in found[0].message


def test_every_spec_field_is_accepted(repo: Path) -> None:
    extra = (
        "license: MIT\n"
        "compatibility: Python 3.9 or later, standard library only\n"
        "metadata:\n"
        "  author: someone\n"
        "  version: '1'\n"
        "allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/demo.py *)\n"
    )
    add_skill(repo, "demo-skill", extra=extra)
    assert vp.validate(repo) == []


# --------------------------------------------------------------------------------------
# name
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["Rent-Split", "rent_split", "-rent", "rent-", "rent--split", "rent split", "rent.split"],
)
def test_names_must_be_lowercase_letters_digits_and_single_hyphens(
    tmp_path: Path, name: str
) -> None:
    root = build_repo(tmp_path, skills=())
    add_skill(root, name)
    found = rule_ids(root)
    assert "name-format" in found
    assert "name-directory" not in found


def test_name_length_limit_is_64(tmp_path: Path) -> None:
    root = build_repo(tmp_path, skills=())
    add_skill(root, "a" * 64)
    assert vp.validate(root) == []
    add_skill(root, "b" * 65)
    found = problems_for(root, "name-format")
    assert len(found) == 1
    assert "65 characters" in found[0].message


def test_name_must_match_its_directory(tmp_path: Path) -> None:
    root = build_repo(tmp_path, skills=())
    directory = add_skill(root, "right-name")
    write(directory / "SKILL.md", skill_md(name="other-name"))
    assert rule_ids(root) == ["name-directory"]


@pytest.mark.parametrize("name", ["claude-helper", "my-claude", "anthropic-tools", "anthropic"])
def test_reserved_words_are_rejected_in_names(tmp_path: Path, name: str) -> None:
    root = build_repo(tmp_path, skills=())
    add_skill(root, name)
    assert rule_ids(root) == ["name-reserved"]


def test_missing_name_is_reported(repo: Path) -> None:
    write(repo / SKILLS / "demo-skill" / "SKILL.md", f"---\ndescription: {DESCRIPTION}\n---\n")
    assert rule_ids(repo) == ["name"]


# --------------------------------------------------------------------------------------
# description
# --------------------------------------------------------------------------------------


def test_description_length_limit_is_1024(tmp_path: Path) -> None:
    root = build_repo(tmp_path, skills=())
    add_skill(root, "exact-limit", description="a" * 1024)
    add_skill(root, "over-limit", description="a" * 1025)
    found = problems_for(root, "description-length")
    assert len(found) == 1
    assert "over-limit" in found[0].path
    assert "1025" in found[0].message


def test_folded_description_is_measured_after_folding(repo: Path) -> None:
    lines = textwrap.wrap("word " * 250, 60)
    folded = "".join(f"  {line}\n" for line in lines)
    text = f"---\nname: demo-skill\ndescription: >-\n{folded}---\n"
    write(repo / SKILLS / "demo-skill" / "SKILL.md", text)
    assert rule_ids(repo) == ["description-length"]


@pytest.mark.parametrize("bracket", ["<", ">"])
def test_angle_brackets_are_rejected_in_descriptions(repo: Path, bracket: str) -> None:
    add_skill(repo, "demo-skill", description=f"Use it when a {bracket} b.")
    assert rule_ids(repo) == ["description-brackets"]


def test_missing_and_empty_descriptions_are_reported(repo: Path) -> None:
    skill = repo / SKILLS / "demo-skill" / "SKILL.md"
    write(skill, "---\nname: demo-skill\n---\n")
    assert rule_ids(repo) == ["description"]
    write(skill, "---\nname: demo-skill\ndescription:\n---\n")
    assert rule_ids(repo) == ["description"]


# --------------------------------------------------------------------------------------
# Frontmatter syntax
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "fragment"),
    [
        ("no frontmatter here\n", "missing or unclosed"),
        ("---\nname: demo-skill\ndescription: x\n", "missing or unclosed"),
        ("---\nname: demo-skill\nname: again\ndescription: x\n---\n", "duplicate key"),
        ("---\nname: demo-skill\ndescription: Use it: now\n---\n", "contains ': '"),
        ('---\nname: demo-skill\ndescription: "never closed\n---\n', "never closed"),
        ("---\nname: demo-skill\ndescription: *starred*\n---\n", "starts with"),
        ("---\n  name: indented\n---\n", "unexpected indentation"),
    ],
)
def test_frontmatter_syntax_errors_are_reported(repo: Path, content: str, fragment: str) -> None:
    write(repo / SKILLS / "demo-skill" / "SKILL.md", content)
    found = vp.validate(repo)
    assert [problem.rule for problem in found] == ["frontmatter"]
    assert fragment in found[0].message


def test_quoted_values_may_contain_colons(repo: Path) -> None:
    add_skill(repo, "demo-skill", description='"Use it: now, or later."')
    assert vp.validate(repo) == []


def test_crlf_line_endings_and_a_byte_order_mark_are_accepted(repo: Path) -> None:
    text = chr(0xFEFF) + skill_md().replace("\n", "\r\n")
    (repo / SKILLS / "demo-skill" / "SKILL.md").write_bytes(text.encode("utf-8"))
    assert vp.validate(repo) == []


def test_frontmatter_parser_reads_block_scalars_lists_and_mappings() -> None:
    block = (
        "name: demo\n"
        "description: |\n  line one\n  line two\n"
        "summary: >-\n  first\n  second\n\n  third\n"
        'allowed-tools:\n  - Read\n  - "Bash(ls)"\n'
        "metadata:\n  a: b\n"
    )
    parsed = vp.parse_frontmatter(block)
    assert parsed["description"] == "line one\nline two\n"
    assert parsed["summary"] == "first second\nthird"
    assert parsed["allowed-tools"] == ["Read", "Bash(ls)"]
    assert parsed["metadata"] == {"a": "b"}


# --------------------------------------------------------------------------------------
# Files referenced from SKILL.md
# --------------------------------------------------------------------------------------


def test_missing_referenced_files_are_reported(repo: Path) -> None:
    body = (
        "Run `python3 ${CLAUDE_SKILL_DIR}/scripts/missing.py`, "
        "read examples/nothing.json and references/theory.md.\n"
    )
    add_skill(repo, "demo-skill", body=body)
    messages = [problem.message for problem in problems_for(repo, "reference")]
    assert len(messages) == 3
    assert any("scripts/missing.py" in message for message in messages)
    assert any("examples/nothing.json" in message for message in messages)
    assert any("references/theory.md" in message for message in messages)


def test_existing_referenced_files_pass(repo: Path) -> None:
    body = "Use ${CLAUDE_SKILL_DIR}/scripts/demo.py and ./examples/input.json, see scripts/.\n"
    add_skill(repo, "demo-skill", body=body)
    assert vp.validate(repo) == []


def test_references_in_frontmatter_are_checked_too(repo: Path) -> None:
    extra = "allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/gone.py *)\n"
    add_skill(repo, "demo-skill", extra=extra)
    found = problems_for(repo, "reference")
    assert len(found) == 1
    assert "scripts/gone.py" in found[0].message


def test_placeholders_and_foreign_paths_are_not_references(repo: Path) -> None:
    body = (
        "Patterns scripts/<name>.py and scripts/*.py, "
        "the sibling ../rent-split/scripts/x.py and ../scripts/y.py, "
        "an install at ~/.claude/skills/demo-skill/scripts/run.py, "
        "a link https://example.com/scripts/a.py.\n"
    )
    add_skill(repo, "demo-skill", body=body)
    assert vp.validate(repo) == []


def test_find_references_reports_line_numbers() -> None:
    text = "intro\nuse scripts/a.py\n\nand examples/b.json.\nrepeat scripts/a.py\n"
    assert vp.find_references(text) == [(2, "scripts/a.py"), (4, "examples/b.json")]


def test_references_written_next_to_chinese_text_are_found() -> None:
    text = "运行scripts/rent_split.py和examples/input.json。\n"
    assert vp.find_references(text) == [(1, "scripts/rent_split.py"), (1, "examples/input.json")]


# --------------------------------------------------------------------------------------
# Plugin manifests
# --------------------------------------------------------------------------------------


def test_missing_manifest_is_reported(repo: Path) -> None:
    (repo / CLAUDE_MANIFEST).unlink()
    found = problems_for(repo, "manifest-missing")
    assert [problem.path for problem in found] == [CLAUDE_MANIFEST]


@pytest.mark.parametrize("content", ["{not json", "[1, 2]", ""])
def test_manifest_that_is_not_a_json_object_is_reported(repo: Path, content: str) -> None:
    write(repo / CLAUDE_MANIFEST, content)
    assert rule_ids(repo) == ["manifest-json"]


def test_plugin_manifest_requires_name_and_version(repo: Path) -> None:
    edit_json(repo / CLAUDE_MANIFEST, lambda data: data.pop("version"))
    assert "manifest-version" in rule_ids(repo)
    edit_json(repo / CLAUDE_MANIFEST, lambda data: data.pop("name"))
    assert "manifest-name" in rule_ids(repo)


# --------------------------------------------------------------------------------------
# One version in three places
# --------------------------------------------------------------------------------------


def add_versions(
    root: Path, pyproject: str = "0.0.1", core: str = "0.0.1", theory: str = "0.0.1"
) -> None:
    """Put a pyproject.toml, a core/fsq_core.py and a docs/THEORY.md with these versions in."""
    write(
        root / "pyproject.toml",
        f'[build-system]\nversion = "9.9.9"\n\n[project]\nname = "x"\nversion = "{pyproject}"\n'
        '\n[tool.other]\nversion = "8.8.8"\n',
    )
    write(root / "core" / "fsq_core.py", f'"""Core."""\n\nCORE_VERSION = "{core}"\n')
    write(root / "core" / "MANIFEST.txt", "# nothing is shared in this tree\n")
    write(root / "docs" / "THEORY.md", f"# Theory notes\n\nVersion: {theory}\n")


def test_the_same_version_in_the_three_places_passes(repo: Path) -> None:
    add_versions(repo)
    assert vp.validate(repo) == []


@pytest.mark.parametrize(
    ("pyproject", "core", "theory", "named"),
    [
        ("0.0.2", "0.0.1", "0.0.1", "pyproject.toml"),
        ("0.0.1", "0.0.2", "0.0.1", "core/fsq_core.py"),
        ("0.0.1", "0.0.1", "0.0.2", "docs/THEORY.md"),
    ],
)
def test_a_version_that_differs_is_reported(
    repo: Path, pyproject: str, core: str, theory: str, named: str
) -> None:
    add_versions(repo, pyproject, core, theory)
    found = problems_for(repo, "version-sync")
    assert len(found) == 1
    assert "0.0.1" in found[0].message and "0.0.2" in found[0].message
    assert named in found[0].message


def test_a_theory_file_without_a_version_line_is_reported(repo: Path) -> None:
    add_versions(repo)
    write(repo / "docs" / "THEORY.md", "# Theory notes\n\nStatus: draft\n")
    found = problems_for(repo, "version-sync")
    assert len(found) == 1 and "(no Version line)" in found[0].message


def test_only_the_project_table_of_the_pyproject_counts(repo: Path) -> None:
    add_versions(repo)
    write(repo / "pyproject.toml", '[tool.other]\nversion = "0.0.1"\n\n[project]\nname = "x"\n')
    found = problems_for(repo, "version-sync")
    assert len(found) == 1 and "(no version)" in found[0].message


def test_a_missing_version_or_a_missing_file_is_not_a_difference(repo: Path) -> None:
    add_versions(repo)
    (repo / "pyproject.toml").unlink()
    assert vp.validate(repo) == []


# --------------------------------------------------------------------------------------
# License copies
# --------------------------------------------------------------------------------------


def test_license_copies_are_not_required_without_a_root_license(repo: Path) -> None:
    assert vp.validate(repo) == []


def test_identical_license_copies_pass(tmp_path: Path) -> None:
    root = build_repo(tmp_path, skills=("first-skill", "second-skill"))
    write(root / "LICENSE", "MIT License\n")
    for name in ("first-skill", "second-skill"):
        write(root / SKILLS / name / "LICENSE", "MIT License\n")
    assert vp.validate(root) == []


def test_a_missing_or_changed_license_copy_is_reported(tmp_path: Path) -> None:
    root = build_repo(tmp_path, skills=("first-skill", "second-skill"))
    write(root / "LICENSE", "MIT License\n")
    write(root / SKILLS / "second-skill" / "LICENSE", "MIT License (edited)\n")
    missing = problems_for(root, "license-missing")
    assert [problem.path for problem in missing] == [f"{SKILLS}/first-skill/LICENSE"]
    drift = problems_for(root, "license-drift")
    assert [problem.path for problem in drift] == [f"{SKILLS}/second-skill/LICENSE"]


# --------------------------------------------------------------------------------------
# Marketplace
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"), [("skills", ["./plugin/skills/demo-skill"]), ("version", "0.0.1")]
)
def test_marketplace_entry_must_not_list_skills_or_a_version(
    repo: Path, field: str, value: object
) -> None:
    edit_json(repo / MARKETPLACE, lambda data: data["plugins"][0].update({field: value}))
    found = problems_for(repo, "marketplace-entry")
    assert len(found) == 1
    assert f"`{field}`" in found[0].message


@pytest.mark.parametrize("source", ["./", "."])
def test_marketplace_source_must_not_be_the_repository_root(repo: Path, source: str) -> None:
    edit_json(repo / MARKETPLACE, lambda data: data["plugins"][0].update({"source": source}))
    found = problems_for(repo, "marketplace-source")
    assert len(found) == 1
    assert "repository root" in found[0].message


def test_marketplace_source_must_contain_a_plugin_manifest(repo: Path) -> None:
    edit_json(repo / MARKETPLACE, lambda data: data["plugins"][0].update({"source": "./nowhere"}))
    assert rule_ids(repo) == ["marketplace-source"]


def test_marketplace_entry_name_must_match_the_plugin(repo: Path) -> None:
    edit_json(repo / MARKETPLACE, lambda data: data["plugins"][0].update({"name": "other"}))
    assert rule_ids(repo) == ["marketplace-source"]


@pytest.mark.parametrize("plugins", [[], "not a list", ["not an object"]])
def test_marketplace_plugins_must_be_a_list_of_objects(repo: Path, plugins: object) -> None:
    edit_json(repo / MARKETPLACE, lambda data: data.update({"plugins": plugins}))
    assert "marketplace-entry" in rule_ids(repo)


def test_marketplace_source_must_be_a_string(repo: Path) -> None:
    edit_json(repo / MARKETPLACE, lambda data: data["plugins"][0].update({"source": {"a": 1}}))
    assert rule_ids(repo) == ["marketplace-source"]


def test_missing_marketplace_is_reported(repo: Path) -> None:
    (repo / MARKETPLACE).unlink()
    found = problems_for(repo, "manifest-missing")
    assert [problem.path for problem in found] == [MARKETPLACE]


# --------------------------------------------------------------------------------------
# Shared core copies
# --------------------------------------------------------------------------------------


def add_core(root: Path, files: dict[str, str], manifest: str | None) -> Path:
    """Create core/ with the given files and, when ``manifest`` is not None, a MANIFEST.txt."""
    core = root / "core"
    core.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        write(core / name, text)
    if manifest is not None:
        write(core / "MANIFEST.txt", manifest)
    return core


def copy_core(root: Path, skill: str, name: str, text: str) -> Path:
    """Put a copy of a core file into a skill's scripts/ folder."""
    return write(root / SKILLS / skill / "scripts" / name, text)


def test_core_check_is_skipped_without_a_core_directory(repo: Path) -> None:
    copy_core(repo, "demo-skill", "helper.py", "anything\n")
    assert vp.validate(repo) == []


def test_identical_core_copies_pass(repo: Path) -> None:
    add_core(repo, {"a.py": "A = 1\n", "b.py": "B = 2\n"}, "a.py\nb.py\n")
    copy_core(repo, "demo-skill", "a.py", "A = 1\n")
    copy_core(repo, "demo-skill", "b.py", "B = 2\n")
    assert vp.validate(repo) == []


def test_a_drifted_core_copy_is_reported(repo: Path) -> None:
    add_core(repo, {"a.py": "A = 1\n"}, "a.py\n")
    copy_core(repo, "demo-skill", "a.py", "A = 2\n")
    found = problems_for(repo, "core-drift")
    assert [problem.path for problem in found] == [f"{SKILLS}/demo-skill/scripts/a.py"]
    assert "core/a.py" in found[0].message


def test_every_skill_is_checked_for_drift(tmp_path: Path) -> None:
    root = build_repo(tmp_path, skills=("first-skill", "second-skill"))
    add_core(root, {"a.py": "A = 1\n"}, "a.py\n")
    copy_core(root, "first-skill", "a.py", "A = 1\n")
    copy_core(root, "second-skill", "a.py", "A = 1  # edited\n")
    found = problems_for(root, "core-drift")
    assert len(found) == 1
    assert "second-skill" in found[0].path


def test_a_line_ending_difference_counts_as_drift(repo: Path) -> None:
    add_core(repo, {"a.py": "A = 1\n"}, "a.py\n")
    copy_core(repo, "demo-skill", "a.py", "A = 1\r\n")
    assert rule_ids(repo) == ["core-drift"]


def test_only_files_in_the_manifest_are_compared(repo: Path) -> None:
    add_core(repo, {"a.py": "A = 1\n", "extra.py": "E = 1\n"}, "a.py\n")
    copy_core(repo, "demo-skill", "a.py", "A = 1\n")
    copy_core(repo, "demo-skill", "extra.py", "E = 2\n")
    assert vp.validate(repo) == []


def test_a_missing_core_copy_is_reported(repo: Path) -> None:
    add_core(repo, {"a.py": "A = 1\n", "b.py": "B = 2\n"}, "a.py\nb.py\n")
    copy_core(repo, "demo-skill", "a.py", "A = 1\n")
    found = problems_for(repo, "core-missing")
    assert [problem.path for problem in found] == [f"{SKILLS}/demo-skill/scripts/b.py"]
    assert "core/b.py" in found[0].message
    assert rule_ids(repo) == ["core-missing"]


def test_a_skill_without_a_scripts_folder_is_skipped(repo: Path) -> None:
    add_core(repo, {"a.py": "A = 1\n"}, "a.py\n")
    shutil.rmtree(repo / SKILLS / "demo-skill" / "scripts")
    assert vp.validate(repo) == []


def test_a_manifest_entry_without_a_core_file_is_reported(repo: Path) -> None:
    add_core(repo, {"a.py": "A = 1\n"}, "a.py\nghost.py\n")
    found = problems_for(repo, "core-manifest")
    assert len(found) == 1
    assert "ghost.py" in found[0].message


def test_without_a_manifest_every_core_py_file_is_compared(repo: Path) -> None:
    add_core(repo, {"a.py": "A = 1\n", "notes.txt": "n\n"}, None)
    copy_core(repo, "demo-skill", "a.py", "A = 9\n")
    copy_core(repo, "demo-skill", "notes.txt", "different\n")
    assert rule_ids(repo) == ["core-drift"]


def test_manifest_syntax_variants(tmp_path: Path) -> None:
    digest = "a" * 64
    manifest = (
        "# a comment\n"
        "\n"
        "./one.py\n"
        "core/two.py\n"
        f"{digest}  three.py\n"
        f"four.py  {digest}\n"
        "five.py  # trailing comment\n"
        f"{digest} *six.py\n"
        "one.py\n"
    )
    core = add_core(tmp_path, {}, manifest)
    expected = ["one.py", "two.py", "three.py", "four.py", "five.py", "six.py"]
    assert vp.read_core_names(core) == expected


# --------------------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------------------


def test_main_reports_ok_and_exits_zero(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert vp.main(["--root", str(repo)]) == 0
    assert capsys.readouterr().out.startswith("OK: 1 skill(s) checked")


def test_main_prints_every_problem_and_exits_one(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    add_skill(repo, "demo-skill", description="<bad>", extra="model: x\n")
    assert vp.main(["--root", str(repo)]) == 1
    lines = capsys.readouterr().out.splitlines()
    assert any(line.startswith("[description-brackets] ") for line in lines)
    assert any(line.startswith("[frontmatter-fields] ") for line in lines)
    assert lines[-1] == "FAILED: 2 problem(s), 1 skill(s) checked"


def test_script_runs_as_a_program(repo: Path) -> None:
    command = [sys.executable, str(VALIDATOR_PATH), "--root", str(repo)]
    ok = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    write(repo / SKILLS / "demo-skill" / "SKILL.md", "no frontmatter\n")
    bad = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
    assert bad.returncode == 1
    assert "[frontmatter]" in bad.stdout


def test_repository_itself_is_valid() -> None:
    problems = vp.validate(ROOT)
    assert not problems, "\n".join(problem.format() for problem in problems)
