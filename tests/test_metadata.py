"""The project metadata agrees in every place that states it: pyproject.toml, the plugin manifest,
the marketplace entry and the README badges. Python 3.9 has no tomllib, so the few fields that are
compared are read with regular expressions."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
PLUGIN = json.loads((ROOT / "plugin/.claude-plugin/plugin.json").read_text(encoding="utf-8"))
MARKETPLACE = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
REPOSITORY = "https://github.com/YYYJH1/fair-and-square-skills"


def array(name: str) -> list[str]:
    found = re.search(rf"^{name} = \[(.*?)^\]", PYPROJECT, flags=re.MULTILINE | re.DOTALL)
    assert found is not None, name
    return re.findall(r'"([^"]+)"', found.group(1))


def urls() -> dict[str, str]:
    table = re.search(r"^\[project\.urls\]\n(.*?)(?=^\[|\Z)", PYPROJECT, re.MULTILINE | re.DOTALL)
    assert table is not None
    return dict(re.findall(r'^(\w+) = "([^"]+)"$', table.group(1), flags=re.MULTILINE))


def test_the_keywords_are_the_ones_of_the_plugin() -> None:
    assert array("keywords") == PLUGIN["keywords"]
    assert MARKETPLACE["plugins"][0]["keywords"] == PLUGIN["keywords"]


def test_the_urls_point_at_the_repository() -> None:
    found = urls()
    assert {"Homepage", "Repository", "Issues", "Documentation", "Changelog"} <= set(found)
    assert found["Homepage"] == found["Repository"] == REPOSITORY
    assert found["Issues"] == f"{REPOSITORY}/issues"
    assert found["Documentation"].startswith(f"{REPOSITORY}/blob/main/docs/")
    assert found["Changelog"] == f"{REPOSITORY}/blob/main/CHANGELOG.md"
    assert PLUGIN["homepage"] == PLUGIN["repository"] == REPOSITORY
    assert MARKETPLACE["plugins"][0]["repository"] == REPOSITORY


def test_the_license_is_the_same_everywhere() -> None:
    assert re.search(r'^license = "MIT"$', PYPROJECT, flags=re.MULTILINE)
    assert PLUGIN["license"] == MARKETPLACE["plugins"][0]["license"] == "MIT"
    assert (ROOT / "LICENSE").read_text(encoding="utf-8").startswith("MIT License")


def test_the_classifiers_name_the_python_versions_of_the_ci_matrix() -> None:
    classifiers = array("classifiers")
    versions = sorted(
        item.rsplit(" :: ", 1)[1]
        for item in classifiers
        if re.fullmatch(r"Programming Language :: Python :: 3\.\d+", item)
    )
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    matrix = re.search(r"python-version: \[(.*?)\]", ci)
    assert matrix is not None
    assert versions == sorted(re.findall(r'"(3\.\d+)"', matrix.group(1)))
    assert 'requires-python = ">=3.9"' in PYPROJECT


def test_the_changelog_has_a_section_for_the_current_version() -> None:
    version = PLUGIN["version"]
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert re.search(
        rf"^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}$", changelog, re.MULTILINE
    )
    assert f"[{version}]: {REPOSITORY}/releases/tag/v{version}" in changelog
