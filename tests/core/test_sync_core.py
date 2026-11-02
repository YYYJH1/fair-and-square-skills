"""tools/sync_core.py: copying the core into the skills and the --check mode."""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SYNC_PATH = REPO_ROOT / "tools" / "sync_core.py"

# CRLF line ends and non-ASCII bytes: copies must be identical byte for byte
CORE_BYTES = b"# shared core\r\nNAME = '\xe9\x98\xbf\xe6\x98\x8e'\r\n"
SCRIPT = "plugin/skills/{skill}/scripts/fsq_core.py"


def load_sync():
    spec = importlib.util.spec_from_file_location("sync_core", SYNC_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sync_core = load_sync()


def make_tree(root: Path, skills=(), manifest="fsq_core.py\n", with_scripts=True) -> Path:
    core = root / "core"
    core.mkdir(parents=True)
    (core / "fsq_core.py").write_bytes(CORE_BYTES)
    (core / "MANIFEST.txt").write_text(manifest, encoding="utf-8")
    for skill in skills:
        folder = root / "plugin" / "skills" / skill
        (folder / "scripts" if with_scripts else folder).mkdir(parents=True)
        (folder / "SKILL.md").write_text("---\nname: x\n---\n", encoding="utf-8")
    return root


def copy_of(root: Path, skill: str) -> Path:
    return root / SCRIPT.format(skill=skill)


class TestNoSkills:
    def test_check_passes_without_a_plugin_directory(self, tmp_path, capsys):
        make_tree(tmp_path)
        assert sync_core.sync(tmp_path, check=True) == 0
        assert "nothing to do" in capsys.readouterr().out

    def test_check_passes_when_the_skills_directory_is_empty(self, tmp_path):
        make_tree(tmp_path)
        skills = tmp_path / "plugin" / "skills"
        skills.mkdir(parents=True)
        (skills / ".gitkeep").write_text("", encoding="utf-8")
        assert sync_core.sync(tmp_path, check=True) == 0
        assert sync_core.sync(tmp_path) == 0
        assert sorted(p.name for p in skills.iterdir()) == [".gitkeep"]

    def test_nothing_is_created_when_there_are_no_skills(self, tmp_path):
        make_tree(tmp_path)
        before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
        assert sync_core.sync(tmp_path) == 0
        assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*")) == before

    def test_skills_without_a_scripts_directory_are_left_alone(self, tmp_path):
        make_tree(tmp_path, skills=["gamma"], with_scripts=False)
        assert sync_core.sync(tmp_path) == 0
        assert not (tmp_path / "plugin" / "skills" / "gamma" / "scripts").exists()
        assert sync_core.sync(tmp_path, check=True) == 0


class TestCopying:
    def test_creates_copies_byte_for_byte(self, tmp_path, capsys):
        make_tree(tmp_path, skills=["alpha", "beta"])
        assert sync_core.sync(tmp_path) == 0
        out = capsys.readouterr().out
        assert out.count("created") == 2
        for skill in ("alpha", "beta"):
            assert copy_of(tmp_path, skill).read_bytes() == CORE_BYTES

    def test_second_run_changes_nothing(self, tmp_path, capsys):
        make_tree(tmp_path, skills=["alpha"])
        sync_core.sync(tmp_path)
        target = copy_of(tmp_path, "alpha")
        stamp = target.stat().st_mtime_ns
        capsys.readouterr()
        assert sync_core.sync(tmp_path) == 0
        assert capsys.readouterr().out.startswith("ok ")
        assert target.stat().st_mtime_ns == stamp

    def test_repairs_a_modified_copy(self, tmp_path, capsys):
        make_tree(tmp_path, skills=["alpha", "beta"])
        sync_core.sync(tmp_path)
        copy_of(tmp_path, "beta").write_bytes(CORE_BYTES + b"# local edit\n")
        capsys.readouterr()
        assert sync_core.sync(tmp_path) == 0
        out = capsys.readouterr().out
        assert "updated  plugin/skills/beta/scripts/fsq_core.py" in out
        assert "ok       plugin/skills/alpha/scripts/fsq_core.py" in out
        assert copy_of(tmp_path, "beta").read_bytes() == CORE_BYTES

    def test_follows_every_file_in_the_manifest(self, tmp_path):
        make_tree(tmp_path, skills=["alpha"], manifest="fsq_core.py\nextra.py  # helper\n")
        (tmp_path / "core" / "extra.py").write_bytes(b"X = 1\n")
        assert sync_core.sync(tmp_path) == 0
        scripts = tmp_path / "plugin" / "skills" / "alpha" / "scripts"
        assert sorted(p.name for p in scripts.iterdir()) == ["extra.py", "fsq_core.py"]
        assert (scripts / "extra.py").read_bytes() == b"X = 1\n"

    def test_files_not_in_the_manifest_are_not_copied(self, tmp_path):
        make_tree(tmp_path, skills=["alpha"])
        (tmp_path / "core" / "private_notes.py").write_text("x = 1\n", encoding="utf-8")
        sync_core.sync(tmp_path)
        scripts = tmp_path / "plugin" / "skills" / "alpha" / "scripts"
        assert [p.name for p in scripts.iterdir()] == ["fsq_core.py"]


class TestCheck:
    def test_detects_a_modified_copy(self, tmp_path, capsys):
        make_tree(tmp_path, skills=["alpha", "beta"])
        sync_core.sync(tmp_path)
        assert sync_core.sync(tmp_path, check=True) == 0
        copy_of(tmp_path, "beta").write_bytes(CORE_BYTES.replace(b"NAME", b"NAMX"))
        capsys.readouterr()
        assert sync_core.sync(tmp_path, check=True) == 1
        captured = capsys.readouterr()
        assert "DIFF     plugin/skills/beta/scripts/fsq_core.py" in captured.out
        assert "ok       plugin/skills/alpha/scripts/fsq_core.py" in captured.out
        assert "tools/sync_core.py" in captured.err

    def test_a_single_changed_byte_is_enough(self, tmp_path):
        make_tree(tmp_path, skills=["alpha"])
        sync_core.sync(tmp_path)
        target = copy_of(tmp_path, "alpha")
        target.write_bytes(CORE_BYTES.replace(b"\r\n", b"\n"))  # line endings only
        assert sync_core.sync(tmp_path, check=True) == 1

    def test_detects_a_missing_copy_and_writes_nothing(self, tmp_path, capsys):
        make_tree(tmp_path, skills=["alpha"])
        assert sync_core.sync(tmp_path, check=True) == 1
        assert "MISSING  plugin/skills/alpha/scripts/fsq_core.py" in capsys.readouterr().out
        assert not copy_of(tmp_path, "alpha").exists()

    def test_detects_when_the_canonical_file_changes(self, tmp_path):
        make_tree(tmp_path, skills=["alpha"])
        sync_core.sync(tmp_path)
        (tmp_path / "core" / "fsq_core.py").write_bytes(CORE_BYTES + b"# new\n")
        assert sync_core.sync(tmp_path, check=True) == 1
        assert sync_core.sync(tmp_path) == 0
        assert sync_core.sync(tmp_path, check=True) == 0


class TestLicense:
    LICENSE = "MIT License\n\nCopyright (c) 2026 Somebody\n"

    def folder(self, root: Path, skill: str) -> Path:
        return root / "plugin" / "skills" / skill

    def test_the_license_of_the_root_is_copied_into_every_skill_folder(self, tmp_path, capsys):
        make_tree(tmp_path, skills=["alpha", "beta"])
        (tmp_path / "LICENSE").write_text(self.LICENSE, encoding="utf-8")
        assert sync_core.sync(tmp_path) == 0
        out = capsys.readouterr().out
        assert "created  plugin/skills/alpha/LICENSE" in out
        for skill in ("alpha", "beta"):
            copy = self.folder(tmp_path, skill) / "LICENSE"
            assert copy.read_bytes() == self.LICENSE.encode("utf-8")
        assert sync_core.sync(tmp_path, check=True) == 0

    def test_a_skill_without_a_scripts_folder_still_gets_the_license(self, tmp_path):
        make_tree(tmp_path, skills=["gamma"], with_scripts=False)
        (tmp_path / "LICENSE").write_text(self.LICENSE, encoding="utf-8")
        assert sync_core.sync(tmp_path) == 0
        assert (self.folder(tmp_path, "gamma") / "LICENSE").is_file()

    def test_check_finds_a_missing_and_a_changed_copy_and_writes_nothing(self, tmp_path, capsys):
        make_tree(tmp_path, skills=["alpha", "beta"])
        (tmp_path / "LICENSE").write_text(self.LICENSE, encoding="utf-8")
        sync_core.sync(tmp_path)
        (self.folder(tmp_path, "alpha") / "LICENSE").write_text("edited\n", encoding="utf-8")
        (self.folder(tmp_path, "beta") / "LICENSE").unlink()
        capsys.readouterr()
        assert sync_core.sync(tmp_path, check=True) == 1
        out = capsys.readouterr().out
        assert "DIFF     plugin/skills/alpha/LICENSE" in out
        assert "MISSING  plugin/skills/beta/LICENSE" in out
        assert not (self.folder(tmp_path, "beta") / "LICENSE").exists()
        assert sync_core.sync(tmp_path) == 0
        assert sync_core.sync(tmp_path, check=True) == 0

    def test_without_a_license_in_the_root_nothing_is_copied(self, tmp_path):
        make_tree(tmp_path, skills=["alpha"])
        assert sync_core.sync(tmp_path) == 0
        assert not (self.folder(tmp_path, "alpha") / "LICENSE").exists()

    def test_dot_folders_next_to_the_skills_are_left_alone(self, tmp_path):
        make_tree(tmp_path, skills=["alpha"])
        (tmp_path / "LICENSE").write_text(self.LICENSE, encoding="utf-8")
        hidden = tmp_path / "plugin" / "skills" / ".cache"
        hidden.mkdir()
        assert sync_core.sync(tmp_path) == 0
        assert list(hidden.iterdir()) == []


class TestManifest:
    def test_comments_blank_lines_prefixes_and_checksums(self, tmp_path):
        make_tree(
            tmp_path,
            manifest="# header\n\ncore/fsq_core.py\n./fsq_core.py  # again\n"
            "abc123 fsq_core.py\nfsq_core.py abc123\n",
        )
        assert sync_core.read_manifest(tmp_path / "core") == ["fsq_core.py"]

    def test_the_real_manifest_is_readable(self):
        assert sync_core.read_manifest(REPO_ROOT / "core") == ["fsq_core.py"]

    @pytest.mark.parametrize("manifest", ["missing.py\n", "../core/fsq_core.py\n", "sub/dir.py\n"])
    def test_unusable_entries_exit_with_2(self, tmp_path, capsys, manifest):
        make_tree(tmp_path, skills=["alpha"], manifest=manifest)
        assert sync_core.sync(tmp_path) == 2
        assert sync_core.sync(tmp_path, check=True) == 2
        assert "sync_core:" in capsys.readouterr().err
        assert not copy_of(tmp_path, "alpha").exists()

    def test_missing_manifest_exits_with_2(self, tmp_path, capsys):
        make_tree(tmp_path, skills=["alpha"])
        (tmp_path / "core" / "MANIFEST.txt").unlink()
        assert sync_core.sync(tmp_path, check=True) == 2
        assert "MANIFEST.txt" in capsys.readouterr().err


class TestCommandLine:
    def run(self, *argv):
        return subprocess.run(
            [sys.executable, str(SYNC_PATH), *argv],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

    def test_check_exit_codes_through_the_script(self, tmp_path):
        make_tree(tmp_path, skills=["alpha"])
        assert self.run("--root", str(tmp_path), "--check").returncode == 1
        assert self.run("--root", str(tmp_path)).returncode == 0
        assert self.run("--root", str(tmp_path), "--check").returncode == 0
        copy_of(tmp_path, "alpha").write_bytes(b"tampered")
        failed = self.run("--root", str(tmp_path), "--check")
        assert failed.returncode == 1 and "DIFF" in failed.stdout

    def test_check_with_no_skills_through_the_script(self, tmp_path):
        make_tree(tmp_path)
        done = self.run("--root", str(tmp_path), "--check")
        assert done.returncode == 0

    def test_help(self):
        done = self.run("--help")
        assert done.returncode == 0 and "--check" in done.stdout and "--root" in done.stdout

    def test_script_is_python_3_9_grammar_and_standard_library_only(self):
        tree = ast.parse(SYNC_PATH.read_text(encoding="utf-8"), feature_version=(3, 9))
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.add((node.module or "").split(".")[0])
        assert modules <= {"__future__", "argparse", "pathlib", "sys"}
