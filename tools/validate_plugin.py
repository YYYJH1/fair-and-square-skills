"""Check the plugin layout, manifest, SKILL.md files and shared copies.

Standard library only, Python 3.9 or later::

    python tools/validate_plugin.py [--root PATH]

Every problem is printed as ``[rule] path: message``. The exit status is 0 when nothing is
wrong, 1 when at least one problem was found and 2 for command-line errors.

Rules: layout, skill-file, frontmatter, frontmatter-fields, name, name-format,
name-directory, name-reserved, description, description-length, description-brackets,
reference, manifest-missing, manifest-json, manifest-name, manifest-version, version-sync,
marketplace-entry, marketplace-source, core-manifest, core-missing, core-drift,
license-missing, license-drift.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, NamedTuple

# Frontmatter fields defined by the open Agent Skills specification. Anything else is rejected
# so the same SKILL.md also loads in tools that are stricter than Claude Code.
SPEC_FIELDS = ("name", "description", "license", "compatibility", "metadata", "allowed-tools")
NAME_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
NAME_MAX_LENGTH = 64
DESCRIPTION_MAX_LENGTH = 1024
RESERVED_NAME_WORDS = ("claude", "anthropic")

MARKETPLACE_PATH = ".claude-plugin/marketplace.json"
CLAUDE_MANIFEST_PATH = "plugin/.claude-plugin/plugin.json"
PYPROJECT_PATH = "pyproject.toml"
CORE_VERSION_PATH = "core/fsq_core.py"
THEORY_PATH = "docs/THEORY.md"
LICENSE_NAME = "LICENSE"
SKILLS_PATH = "plugin/skills"
CORE_PATH = "core"
CORE_MANIFEST_NAME = "MANIFEST.txt"

# U+FEFF, the byte order mark some editors put in front of a UTF-8 file.
BOM = chr(0xFEFF)


class Problem(NamedTuple):
    """One validation failure."""

    rule: str
    path: str
    message: str

    def format(self) -> str:
        """Return the one-line report form."""
        return f"[{self.rule}] {self.path}: {self.message}"


class FrontmatterError(ValueError):
    """Raised when the YAML frontmatter of a SKILL.md cannot be read."""


# --------------------------------------------------------------------------------------
# Frontmatter: a small YAML subset, enough for SKILL.md headers without third-party code.
# --------------------------------------------------------------------------------------

_KEY_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_.-]*)[ \t]*:(?:[ \t]+(.*))?$")
_BLOCK_HEADER = re.compile(r"^([|>])([+-]?)([1-9]?)([+-]?)[ \t]*(?:#.*)?$")
_COMMENT = re.compile(r"(?:^|[ \t])#.*$")
_COLON_SPACE = re.compile(r":(?:[ \t]|$)")
_PLAIN_FORBIDDEN_START = "@`%&*!|>,]}"


def split_frontmatter(text: str) -> tuple[str, str] | None:
    """Split a SKILL.md into (frontmatter, body), or return None without a closed block."""
    lines = text.lstrip(BOM).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not lines or lines[0].rstrip() != "---":
        return None
    for index in range(1, len(lines)):
        if lines[index].rstrip() == "---":
            return "\n".join(lines[1:index]), "\n".join(lines[index + 1 :])
    return None


def parse_frontmatter(block: str) -> dict[str, Any]:
    """Parse the YAML subset used in SKILL.md frontmatter.

    Values are strings, lists of strings or dicts. Plain, quoted, folded and literal scalars
    are understood. A plain scalar that contains ``: `` or starts with an indicator character
    is rejected because strict YAML parsers refuse it. Quote the value instead.
    """
    lines = block.split("\n")
    result: dict[str, Any] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            index += 1
            continue
        if line[0] in " \t":
            raise FrontmatterError(f"line {index + 1}: unexpected indentation")
        match = _KEY_LINE.match(line)
        if match is None:
            raise FrontmatterError(f"line {index + 1}: expected 'key: value', got {line.strip()!r}")
        key = match.group(1)
        inline = (match.group(2) or "").strip()
        if key in result:
            raise FrontmatterError(f"line {index + 1}: duplicate key '{key}'")
        end = index + 1
        continuation: list[str] = []
        while end < len(lines) and (not lines[end].strip() or lines[end][0] in " \t"):
            continuation.append(lines[end])
            end += 1
        result[key] = _read_value(key, inline, continuation)
        index = end
    return result


def _read_value(key: str, inline: str, continuation: list[str]) -> Any:
    """Interpret one top-level value from its first line and indented continuation lines."""
    body = list(continuation)
    while body and not body[-1].strip():
        body.pop()
    header = _BLOCK_HEADER.match(inline)
    if header is not None:
        return _block_scalar(header.group(1), header.group(2) + header.group(4), body)
    if not inline:
        return _nested_value(key, body)
    if inline[0] in "\"'":
        return _quoted_scalar(key, inline, body)
    if inline[0] in "[{":
        return " ".join([inline] + [line.strip() for line in body if line.strip()])
    return _plain_scalar(key, [inline, *body])


def _plain_scalar(key: str, lines: list[str]) -> str:
    """Fold a plain (unquoted) scalar and refuse text that strict YAML would reject."""
    parts = [_COMMENT.sub("", line).strip() for line in lines]
    value = " ".join(part for part in parts if part)
    if value and value[0] in _PLAIN_FORBIDDEN_START:
        raise FrontmatterError(
            f"'{key}': unquoted text starts with {value[0]!r}, which strict YAML parsers "
            "reject; wrap the whole value in quotes"
        )
    if _COLON_SPACE.search(value):
        raise FrontmatterError(
            f"'{key}': unquoted text contains ': ' or ends with ':', which strict YAML parsers "
            "reject; wrap the whole value in quotes"
        )
    return value


def _quoted_scalar(key: str, inline: str, body: list[str]) -> str:
    """Read a single- or double-quoted scalar that may continue on following lines."""
    quote = inline[0]
    text = " ".join([inline[1:]] + [line.strip() for line in body if line.strip()])
    chars: list[str] = []
    rest: str | None = None
    position = 0
    while position < len(text):
        char = text[position]
        if quote == '"' and char == "\\":
            chars.append(text[position : position + 2])
            position += 2
            continue
        if char == quote:
            if quote == "'" and text[position + 1 : position + 2] == "'":
                chars.append("'")
                position += 2
                continue
            rest = text[position + 1 :]
            break
        chars.append(char)
        position += 1
    if rest is None:
        raise FrontmatterError(f"'{key}': the opening quote ({quote}) is never closed")
    if rest.strip() and not rest.strip().startswith("#"):
        raise FrontmatterError(f"'{key}': unexpected text after the closing quote")
    raw = "".join(chars)
    if quote == "'":
        return raw
    try:
        return str(json.loads('"' + raw + '"', strict=False))
    except ValueError:
        return raw


def _block_scalar(style: str, chomp: str, lines: list[str]) -> str:
    """Read a literal (|) or folded (>) block scalar."""
    indents = [len(line) - len(line.lstrip(" ")) for line in lines if line.strip()]
    if not indents:
        return ""
    base = min(indents)
    body = [line[base:] if line.strip() else "" for line in lines]
    if style == "|":
        text = "\n".join(body)
    else:
        pieces: list[str] = []
        blanks = 0
        for line in body:
            if not line:
                blanks += 1
                continue
            if pieces:
                pieces.append("\n" * blanks if blanks else " ")
            pieces.append(line)
            blanks = 0
        text = "".join(pieces)
    return text if "-" in chomp else text + "\n"


def _nested_value(key: str, body: list[str]) -> Any:
    """Read a value that starts on the next line: a mapping, a list or a plain scalar."""
    content = [line for line in body if line.strip() and not line.lstrip().startswith("#")]
    if not content:
        return ""
    indent = min(len(line) - len(line.lstrip(" \t")) for line in content)
    dedented = [line[indent:] if line.strip() else "" for line in body]
    first = next(line for line in dedented if line.strip() and not line.lstrip().startswith("#"))
    if first.startswith("-") and (len(first) == 1 or first[1] in " \t"):
        items: list[str] = []
        for line in dedented:
            if line.startswith("-"):
                item = line[1:].strip()
                quoted = bool(item) and item[0] in "\"'"
                items.append(_quoted_scalar(key, item, []) if quoted else item)
        return items
    if _KEY_LINE.match(first):
        return parse_frontmatter("\n".join(dedented))
    return _plain_scalar(key, dedented)


# --------------------------------------------------------------------------------------
# SKILL.md checks
# --------------------------------------------------------------------------------------

# A reference starts at the beginning of a token, or right after ${CLAUDE_SKILL_DIR}/ or ./
# (but not ../, which points outside the skill folder). Only ASCII counts as part of a path,
# so a path written right next to Chinese text is still found and delimited.
_REFERENCE = re.compile(
    r"(?:(?<=\$\{CLAUDE_SKILL_DIR\}/)|(?<=(?<!\.)\./)|(?<![A-Za-z0-9_./${}~-]))"
    r"((?:scripts|examples|references)/[A-Za-z0-9_./-]*)"
)
_PLACEHOLDER_NEXT = "*<{[$%?"


def find_references(text: str) -> list[tuple[int, str]]:
    """Return (line number, path) for every scripts/, examples/ or references/ mention.

    Mentions followed by a glob or placeholder character, such as ``scripts/<name>.py``, are
    skipped because they do not name a single file.
    """
    found: list[tuple[int, str]] = []
    seen = set()
    for match in _REFERENCE.finditer(text):
        following = text[match.end() : match.end() + 1]
        if following and following in _PLACEHOLDER_NEXT:
            continue
        reference = match.group(1).rstrip(".")
        if reference in seen:
            continue
        seen.add(reference)
        found.append((text.count("\n", 0, match.start()) + 1, reference))
    return found


def check_name(name: str, directory: str, path: str) -> list[Problem]:
    """Check one skill name against the specification and its directory."""
    problems: list[Problem] = []
    if len(name) > NAME_MAX_LENGTH:
        problems.append(
            Problem("name-format", path, f"name has {len(name)} characters, the limit is 64")
        )
    if NAME_PATTERN.fullmatch(name) is None:
        problems.append(
            Problem(
                "name-format",
                path,
                f"name {name!r} must be lowercase letters, digits and single hyphens, "
                "without a leading or trailing hyphen",
            )
        )
    if name != directory:
        problems.append(
            Problem("name-directory", path, f"name {name!r} must equal its directory {directory!r}")
        )
    lowered = name.lower()
    for word in RESERVED_NAME_WORDS:
        if word in lowered:
            problems.append(Problem("name-reserved", path, f"name must not contain {word!r}"))
    return problems


def check_description(description: str, path: str) -> list[Problem]:
    """Check the description length and forbidden characters."""
    problems: list[Problem] = []
    text = description.strip()
    if not text:
        problems.append(Problem("description", path, "description must not be empty"))
    if len(text) > DESCRIPTION_MAX_LENGTH:
        problems.append(
            Problem(
                "description-length",
                path,
                f"description has {len(text)} characters, the limit is {DESCRIPTION_MAX_LENGTH}",
            )
        )
    found = [char for char in "<>" if char in text]
    if found:
        problems.append(
            Problem(
                "description-brackets",
                path,
                "description must not contain angle brackets: " + " ".join(found),
            )
        )
    return problems


def check_skill(skill_dir: Path, root: Path) -> list[Problem]:
    """Validate one skill directory: SKILL.md frontmatter and the files it points to."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return [Problem("skill-file", _rel(skill_dir, root), "directory has no SKILL.md")]
    path = _rel(skill_md, root)
    try:
        text = skill_md.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return [Problem("skill-file", path, "file is not valid UTF-8")]
    text = text.lstrip(BOM).replace("\r\n", "\n").replace("\r", "\n")
    parts = split_frontmatter(text)
    if parts is None:
        return [Problem("frontmatter", path, "missing or unclosed frontmatter (a --- block)")]
    try:
        fields = parse_frontmatter(parts[0])
    except FrontmatterError as error:
        return [Problem("frontmatter", path, str(error))]

    problems: list[Problem] = []
    unknown = sorted(set(fields) - set(SPEC_FIELDS))
    if unknown:
        problems.append(
            Problem(
                "frontmatter-fields",
                path,
                "fields outside the Agent Skills specification: "
                + ", ".join(unknown)
                + " (allowed: "
                + ", ".join(SPEC_FIELDS)
                + ")",
            )
        )
    name = fields.get("name")
    if isinstance(name, str) and name:
        problems.extend(check_name(name, skill_dir.name, path))
    else:
        problems.append(Problem("name", path, "name is required and must be non-empty text"))
    description = fields.get("description")
    if isinstance(description, str):
        problems.extend(check_description(description, path))
    else:
        problems.append(
            Problem("description", path, "description is required and must be non-empty text")
        )
    for line, reference in find_references(text):
        target = skill_dir / reference
        exists = target.is_dir() if reference.endswith("/") else target.exists()
        if not exists:
            problems.append(
                Problem(
                    "reference",
                    path,
                    f"line {line}: `{reference}` does not exist inside {skill_dir.name}/",
                )
            )
    return problems


def list_skill_dirs(root: Path) -> list[Path]:
    """Return the skill directories under plugin/skills, sorted by name."""
    skills = root / SKILLS_PATH
    if not skills.is_dir():
        return []
    return sorted(
        entry for entry in skills.iterdir() if entry.is_dir() and not entry.name.startswith(".")
    )


# --------------------------------------------------------------------------------------
# Manifest checks
# --------------------------------------------------------------------------------------


def _rel(path: Path, root: Path) -> str:
    """Return ``path`` relative to ``root`` with forward slashes when possible."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _load_json(root: Path, rel: str) -> tuple[dict[str, Any] | None, list[Problem]]:
    """Read a JSON object, reporting a missing file or a syntax error as a problem."""
    path = root / rel
    if not path.is_file():
        return None, [Problem("manifest-missing", rel, "file does not exist")]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return None, [Problem("manifest-json", rel, f"cannot read JSON: {error}")]
    if not isinstance(data, dict):
        return None, [Problem("manifest-json", rel, "top level must be a JSON object")]
    return data, []


def _is_text(value: Any) -> bool:
    """Return True for a non-empty string."""
    return isinstance(value, str) and bool(value.strip())


def check_manifests(root: Path) -> list[Problem]:
    """Check that the plugin manifest names the plugin and carries a version."""
    claude, problems = _load_json(root, CLAUDE_MANIFEST_PATH)
    if claude is None:
        return problems
    if not _is_text(claude.get("name")):
        problems.append(Problem("manifest-name", CLAUDE_MANIFEST_PATH, "name is required"))
    if not _is_text(claude.get("version")):
        problems.append(
            Problem(
                "manifest-version",
                CLAUDE_MANIFEST_PATH,
                "version is required, because users receive an update only when it changes",
            )
        )
    return problems


_PROJECT_TABLE = re.compile(r"^\[project\][ \t]*\n(.*?)(?=^\[|\Z)", re.MULTILINE | re.DOTALL)
_PYPROJECT_VERSION = re.compile(r'^version[ \t]*=[ \t]*"([^"]+)"', re.MULTILINE)
_CORE_VERSION = re.compile(r'^CORE_VERSION[ \t]*=[ \t]*"([^"]+)"', re.MULTILINE)
_THEORY_VERSION = re.compile(r"^Version: (\S+)[ \t]*$", re.MULTILINE)


def check_versions(root: Path) -> list[Problem]:
    """The version in plugin.json, pyproject.toml, core/fsq_core.py and docs/THEORY.md agree.

    A file that does not exist is skipped, so a tree without a pyproject.toml, a core or a
    THEORY.md is not reported here.
    """
    found: dict[str, str] = {}
    claude, _ = _load_json(root, CLAUDE_MANIFEST_PATH)
    if claude is not None and _is_text(claude.get("version")):
        found[CLAUDE_MANIFEST_PATH] = claude["version"].strip()
    pyproject = root / PYPROJECT_PATH
    if pyproject.is_file():
        table = _PROJECT_TABLE.search(pyproject.read_text(encoding="utf-8"))
        match = _PYPROJECT_VERSION.search(table.group(1)) if table else None
        found[PYPROJECT_PATH] = match.group(1) if match else "(no version)"
    core = root / CORE_VERSION_PATH
    if core.is_file():
        match = _CORE_VERSION.search(core.read_text(encoding="utf-8"))
        found[CORE_VERSION_PATH] = match.group(1) if match else "(no CORE_VERSION)"
    theory = root / THEORY_PATH
    if theory.is_file():
        match = _THEORY_VERSION.search(theory.read_text(encoding="utf-8"))
        found[THEORY_PATH] = match.group(1) if match else "(no Version line)"
    if len(set(found.values())) <= 1:
        return []
    shown = ", ".join(f"{path} {version}" for path, version in found.items())
    return [Problem("version-sync", CLAUDE_MANIFEST_PATH, f"the versions differ: {shown}")]


def check_marketplace(root: Path) -> list[Problem]:
    """Check the marketplace file: no skills or version in entries, source is the plugin dir."""
    data, problems = _load_json(root, MARKETPLACE_PATH)
    if data is None:
        return problems
    plugins = data.get("plugins")
    if not isinstance(plugins, list) or not plugins:
        return [
            *problems,
            Problem("marketplace-entry", MARKETPLACE_PATH, "plugins must be a non-empty list"),
        ]
    claude, _ = _load_json(root, CLAUDE_MANIFEST_PATH)
    for index, entry in enumerate(plugins):
        label = f"plugins[{index}]"
        if not isinstance(entry, dict):
            problems.append(
                Problem("marketplace-entry", MARKETPLACE_PATH, f"{label} is not an object")
            )
            continue
        label += f" ({entry.get('name')})"
        if "skills" in entry:
            problems.append(
                Problem(
                    "marketplace-entry",
                    MARKETPLACE_PATH,
                    f"{label} must not have a `skills` field: it would replace the default "
                    "skills/ scan with the listed paths",
                )
            )
        if "version" in entry:
            problems.append(
                Problem(
                    "marketplace-entry",
                    MARKETPLACE_PATH,
                    f"{label} must not have a `version` field: the version is set in "
                    f"{CLAUDE_MANIFEST_PATH}",
                )
            )
        problems.extend(_check_marketplace_source(root, entry, label, claude))
    return problems


def _check_marketplace_source(
    root: Path, entry: dict[str, Any], label: str, claude: dict[str, Any] | None
) -> list[Problem]:
    """A local source must be a plugin subdirectory, not the repository root."""
    source = entry.get("source")
    if not isinstance(source, str):
        return [
            Problem(
                "marketplace-source",
                MARKETPLACE_PATH,
                f"{label} needs a local path `source` such as ./plugin",
            )
        ]
    if not source.startswith("."):
        return []
    target = (root / source).resolve()
    if target == root.resolve():
        return [
            Problem(
                "marketplace-source",
                MARKETPLACE_PATH,
                f"{label} source {source!r} is the repository root; use the plugin subdirectory "
                "so tests and docs stay out of users' plugin caches",
            )
        ]
    manifest = target / ".claude-plugin" / "plugin.json"
    if not manifest.is_file():
        return [
            Problem(
                "marketplace-source",
                MARKETPLACE_PATH,
                f"{label} source {source!r} has no .claude-plugin/plugin.json",
            )
        ]
    if claude is not None and claude.get("name") != entry.get("name"):
        return [
            Problem(
                "marketplace-source",
                MARKETPLACE_PATH,
                f"{label} name differs from the plugin name {claude.get('name')!r}",
            )
        ]
    return []


# --------------------------------------------------------------------------------------
# Shared-core copies
# --------------------------------------------------------------------------------------

_DIGEST = re.compile(r"(?:[A-Za-z0-9_-]+:)?[0-9a-fA-F]{32,}")


def read_core_names(core_dir: Path) -> list[str]:
    """Return the core file names listed in core/MANIFEST.txt, or every core/*.py without one.

    A manifest line may be a bare name or a name next to a hex checksum in either order, and
    ``#`` starts a comment. A leading ``core/``, ``./`` or ``*`` on a name is ignored.
    """
    manifest = core_dir / CORE_MANIFEST_NAME
    if not manifest.is_file():
        return sorted(path.name for path in core_dir.glob("*.py"))
    names: list[str] = []
    for raw in manifest.read_text(encoding="utf-8").splitlines():
        tokens = [_strip_core_prefix(token.lstrip("*")) for token in raw.split("#", 1)[0].split()]
        candidates = [token for token in tokens if token and not _DIGEST.fullmatch(token)]
        if candidates and candidates[0] not in names:
            names.append(candidates[0])
    return names


def _strip_core_prefix(token: str) -> str:
    """Drop a leading ``./`` and ``core/`` from a manifest entry."""
    return token.removeprefix("./").removeprefix("core/")


def check_core_copies(root: Path) -> list[Problem]:
    """Compare each skill's copies of the shared core files with the canonical ones.

    Every skill that has a scripts/ folder must hold a byte-identical copy of every listed
    core file, the same rule that ``tools/sync_core.py --check`` applies. Skills without a
    scripts/ folder are skipped.
    """
    core_dir = root / CORE_PATH
    if not core_dir.is_dir():
        return []
    problems: list[Problem] = []
    manifest_rel = f"{CORE_PATH}/{CORE_MANIFEST_NAME}"
    canonical: dict[str, bytes] = {}
    for name in read_core_names(core_dir):
        source = core_dir / name
        if source.is_file():
            canonical[name] = source.read_bytes()
        else:
            problems.append(
                Problem(
                    "core-manifest",
                    manifest_rel,
                    f"{name} is listed but {CORE_PATH}/{name} is missing",
                )
            )
    for skill_dir in list_skill_dirs(root):
        scripts = skill_dir / "scripts"
        if not scripts.is_dir():
            continue
        for name, expected in canonical.items():
            copy = scripts / name
            if not copy.is_file():
                problems.append(
                    Problem(
                        "core-missing",
                        _rel(copy, root),
                        f"copy of {CORE_PATH}/{name} is missing; run tools/sync_core.py",
                    )
                )
            elif copy.read_bytes() != expected:
                problems.append(
                    Problem(
                        "core-drift",
                        _rel(copy, root),
                        f"differs from {CORE_PATH}/{name}; edit the canonical file and re-run "
                        "tools/sync_core.py",
                    )
                )
    return problems


def check_license_copies(root: Path) -> list[Problem]:
    """Every skill folder must hold a byte-identical copy of the LICENSE in the root.

    The check is skipped when the root has no LICENSE. tools/sync_core.py writes the copies.
    """
    source = root / LICENSE_NAME
    if not source.is_file():
        return []
    expected = source.read_bytes()
    problems: list[Problem] = []
    for skill_dir in list_skill_dirs(root):
        copy = skill_dir / LICENSE_NAME
        if not copy.is_file():
            problems.append(
                Problem(
                    "license-missing",
                    _rel(copy, root),
                    f"copy of {LICENSE_NAME} is missing; run tools/sync_core.py",
                )
            )
        elif copy.read_bytes() != expected:
            problems.append(
                Problem(
                    "license-drift",
                    _rel(copy, root),
                    f"differs from {LICENSE_NAME}; edit the root file and run tools/sync_core.py",
                )
            )
    return problems


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------


def validate(root: Path) -> list[Problem]:
    """Run every check against the repository at ``root``."""
    root = root.resolve()
    problems = check_marketplace(root)
    problems.extend(check_manifests(root))
    problems.extend(check_versions(root))
    if not (root / SKILLS_PATH).is_dir():
        problems.append(Problem("layout", SKILLS_PATH, "directory does not exist"))
    for skill_dir in list_skill_dirs(root):
        problems.extend(check_skill(skill_dir, root))
    problems.extend(check_core_copies(root))
    problems.extend(check_license_copies(root))
    return problems


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="Validate the fair-and-square plugin layout.")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="repository root (default: the parent of tools/)",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    problems = validate(root)
    for problem in problems:
        print(problem.format())
    skills = len(list_skill_dirs(root))
    if problems:
        print(f"FAILED: {len(problems)} problem(s), {skills} skill(s) checked")
        return 1
    core_note = "" if (root / CORE_PATH).is_dir() else "; no core/, copy check skipped"
    print(f"OK: {skills} skill(s) checked{core_note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
