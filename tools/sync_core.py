"""Copy the shared files into every skill, or check that the copies are still identical.

core/MANIFEST.txt lists the core files to share, one name per line (blank lines and text after #
are ignored). Each file is copied byte for byte into every existing
plugin/skills/*/scripts/ directory. The LICENSE in the repository root is copied the same way
into every plugin/skills/*/ directory, so a skill folder that is copied elsewhere keeps its
license text. Nothing is created when there are no skills.

    python3 tools/sync_core.py            copy (only files that differ are written)
    python3 tools/sync_core.py --check    write nothing; exit 1 if a copy is missing or differs

Exit codes: 0 all copies match (or were updated), 1 --check found a difference, 2 the
manifest or the core files are unusable.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

CORE_DIR = "core"
MANIFEST_NAME = "MANIFEST.txt"
LICENSE_NAME = "LICENSE"
SKILLS_DIR = Path("plugin") / "skills"


class ManifestError(Exception):
    """core/MANIFEST.txt, or a file it lists, cannot be used."""


def _strip_prefix(token: str) -> str:
    for prefix in ("./", "core/"):
        token = token.removeprefix(prefix)
    return token


def read_manifest(core_dir: Path) -> list[str]:
    """File names listed in core_dir/MANIFEST.txt, each checked to exist in core_dir.

    A line may carry a checksum next to the name (either order); the first token that names
    an existing core file is the name.
    """
    manifest = core_dir / MANIFEST_NAME
    if not manifest.is_file():
        raise ManifestError(f"{manifest} does not exist")
    names: list[str] = []
    for raw in manifest.read_text(encoding="utf-8").splitlines():
        tokens = [_strip_prefix(token) for token in raw.split("#", 1)[0].split()]
        if not tokens:
            continue
        existing = [token for token in tokens if (core_dir / token).is_file()]
        name = existing[0] if existing else tokens[0]
        if "/" in name or "\\" in name or name in ("", ".", ".."):
            raise ManifestError(f"{name!r} in {manifest.name} must be a plain file name")
        if not (core_dir / name).is_file():
            raise ManifestError(
                f"{name} is listed in {manifest.name} but {core_dir / name} is missing"
            )
        if name not in names:
            names.append(name)
    return names


def skill_script_dirs(root: Path) -> list[Path]:
    """Existing plugin/skills/*/scripts/ directories, sorted by skill name."""
    skills = root / SKILLS_DIR
    if not skills.is_dir():
        return []
    return [
        skill / "scripts"
        for skill in sorted(skills.iterdir())
        if skill.is_dir() and (skill / "scripts").is_dir()
    ]


def skill_dirs(root: Path) -> list[Path]:
    """Existing plugin/skills/* directories (dot folders excluded), sorted by skill name."""
    skills = root / SKILLS_DIR
    if not skills.is_dir():
        return []
    return [
        skill
        for skill in sorted(skills.iterdir())
        if skill.is_dir() and not skill.name.startswith(".")
    ]


def sync(root: Path, check: bool = False) -> int:
    """Copy (or with check=True, only compare) the shared files; returns the exit code."""
    try:
        names = read_manifest(root / CORE_DIR)
    except ManifestError as err:
        print(f"sync_core: {err}", file=sys.stderr)
        return 2
    sources = {name: (root / CORE_DIR / name).read_bytes() for name in names}
    copies = [
        (scripts / name, data)
        for scripts in skill_script_dirs(root)
        for name, data in sources.items()
    ]
    license_file = root / LICENSE_NAME
    if license_file.is_file():
        license_text = license_file.read_bytes()
        copies += [(skill / LICENSE_NAME, license_text) for skill in skill_dirs(root)]
    if not copies:
        print("sync_core: no plugin/skills/*/scripts/ directories, nothing to do")
        return 0
    differing = 0
    for copy, data in copies:
        shown = copy.relative_to(root).as_posix()
        if copy.is_file() and copy.read_bytes() == data:
            print(f"ok       {shown}")
        elif check:
            differing += 1
            print(f"{'DIFF' if copy.exists() else 'MISSING':8} {shown}")
        else:
            status = "updated" if copy.exists() else "created"
            copy.write_bytes(data)
            print(f"{status:8} {shown}")
    if check and differing:
        print(
            f"sync_core: {differing} copy(ies) differ from {CORE_DIR}/ or {LICENSE_NAME}; "
            "run python3 tools/sync_core.py",
            file=sys.stderr,
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(
        description="Copy the shared core and LICENSE into each skill."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="write nothing; exit 1 if any copy is missing or differs from core/ or LICENSE",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="repository root (default: the parent of tools/)",
    )
    args = parser.parse_args(argv)
    return sync(args.root.resolve(), check=args.check)


if __name__ == "__main__":
    sys.exit(main())
