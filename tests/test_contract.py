"""Contract tests for every skill script under plugin/skills/*/scripts/.

Each script must be standard library only, free of network access, subprocesses, dynamic code
and file writes. Every skill script must exit 0 on ``--help``, ``--demo`` and ``--selftest``,
``--demo`` must print the same bytes every time, and the script must also start in isolated mode,
which keeps its own folder off ``sys.path``. The shared core copy ``fsq_core.py`` is scanned like
the scripts but is not run: it is a module.

The one exception to "no file system changes" is the shared core, which deletes the ``--input``
file after reading it when ``--delete-input`` is given. The scan allows exactly that: one
``.unlink()`` call, inside ``_delete_input_file``, in a file named ``fsq_core.py``.

The static scan is a guard rail for the promises made in the README. It is not a sandbox, so a
determined author can still get around it. Review stays necessary.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "plugin" / "skills"
TIMEOUT_SECONDS = 120

# Python 3.9 has no sys.stdlib_module_names, so this list of its modules is the fallback.
_STDLIB_FALLBACK = """
    __future__ _collections_abc _thread abc aifc antigravity argparse array ast asynchat
    asyncio asyncore atexit audioop base64 bdb binascii binhex bisect builtins bz2 cProfile
    calendar cgi cgitb chunk cmath cmd code codecs codeop collections colorsys compileall
    concurrent configparser contextlib contextvars copy copyreg crypt csv ctypes curses
    dataclasses datetime dbm decimal difflib dis distutils doctest email encodings ensurepip
    enum errno faulthandler fcntl filecmp fileinput fnmatch formatter fractions ftplib
    functools gc genericpath getopt getpass gettext glob graphlib grp gzip hashlib heapq hmac
    html http idlelib imaplib imghdr imp importlib inspect io ipaddress itertools json keyword
    lib2to3 linecache locale logging lzma mailbox mailcap marshal math mimetypes mmap
    modulefinder msilib msvcrt multiprocessing netrc nis nntplib nt ntpath nturl2path numbers
    opcode operator optparse os ossaudiodev parser pathlib pdb pickle pickletools pipes
    pkgutil platform plistlib poplib posix posixpath pprint profile pstats pty pwd py_compile
    pyclbr pydoc pydoc_data pyexpat queue quopri random re readline reprlib resource
    rlcompleter runpy sched secrets select selectors shelve shlex shutil signal site smtpd
    smtplib sndhdr socket socketserver spwd sqlite3 sre_compile sre_constants sre_parse ssl
    stat statistics string stringprep struct subprocess sunau symbol symtable sys sysconfig
    syslog tabnanny tarfile telnetlib tempfile termios textwrap this threading time timeit
    tkinter token tokenize trace traceback tracemalloc tty turtle turtledemo types typing
    unicodedata unittest urllib uu uuid venv warnings wave weakref webbrowser winreg winsound
    wsgiref xdrlib xml xmlrpc zipapp zipfile zipimport zlib zoneinfo
"""
STDLIB = frozenset(getattr(sys, "stdlib_module_names", None) or _STDLIB_FALLBACK.split())

# Modules a skill script never needs. They reach the network, start processes, run code that
# was not in the file, or change the file system.
_FORBIDDEN_MODULES = """
    subprocess multiprocessing pty ctypes importlib runpy code codeop
    socket socketserver ssl urllib http ftplib smtplib poplib imaplib nntplib telnetlib xmlrpc
    webbrowser pickle marshal shelve shutil tempfile
"""
FORBIDDEN_MODULES = frozenset(_FORBIDDEN_MODULES.split())
FORBIDDEN_BUILTINS = frozenset({"eval", "exec", "compile", "__import__"})
# os functions that start processes or change the file system.
_OS_BLOCKED = """
    system popen fork forkpty kill killpg open remove unlink rmdir removedirs rename renames
    replace mkdir makedirs truncate ftruncate chmod chown symlink link utime mkfifo mknod
"""
OS_BLOCKED = frozenset(_OS_BLOCKED.split())
OS_BLOCKED_PREFIXES = ("exec", "spawn", "posix_spawn")
# Method names that only make sense on a path being changed (str.replace and friends are not
# listed on purpose).
PATH_WRITE_METHODS = frozenset(
    {"write_text", "write_bytes", "touch", "mkdir", "unlink", "rmdir", "symlink_to", "hardlink_to"}
)
WRITE_MODE_CHARS = frozenset("wax+")
MODE_PATTERN = re.compile(r"[rwaxbtU+]+(?::\w+)?")
# The one deletion that a skill script may contain: the core deletes the --input file after it
# has been read, when --delete-input is given.
DELETE_FILE = "fsq_core.py"
DELETE_FUNCTION = "_delete_input_file"


class Violation(NamedTuple):
    """One forbidden construct found in a script."""

    line: int
    message: str


# --------------------------------------------------------------------------------------
# Static scan
# --------------------------------------------------------------------------------------


def _os_name_blocked(name: str) -> bool:
    """Return True for an os function that starts a process or changes the file system."""
    return name in OS_BLOCKED or name.startswith(OS_BLOCKED_PREFIXES)


def _check_import(line: int, dotted: str, local_modules: frozenset[str]) -> list[Violation]:
    """Check one imported module name."""
    root = dotted.split(".")[0]
    if root in FORBIDDEN_MODULES:
        return [Violation(line, f"import of {dotted!r} is forbidden")]
    if root in STDLIB or root in local_modules:
        return []
    return [
        Violation(line, f"import of {dotted!r}: not in the standard library or next to the script")
    ]


def _check_import_from(node: ast.ImportFrom, local_modules: frozenset[str]) -> list[Violation]:
    """Check a ``from x import y`` statement."""
    if node.level:
        return [Violation(node.lineno, "relative imports do not work when a script runs as a file")]
    module = node.module or ""
    found = _check_import(node.lineno, module, local_modules)
    if module == "os":
        found.extend(
            Violation(node.lineno, f"from os import {alias.name} is forbidden")
            for alias in node.names
            if _os_name_blocked(alias.name)
        )
    return found


def _check_open(node: ast.Call, *, builtin: bool) -> list[Violation]:
    """Flag open() calls that write, append, create or cannot be shown to be read-only."""
    keyword = next((item.value for item in node.keywords if item.arg == "mode"), None)
    if builtin:
        if keyword is not None:
            mode = keyword
        elif len(node.args) > 1:
            mode = node.args[1]
        else:
            return []
        if not (isinstance(mode, ast.Constant) and isinstance(mode.value, str)):
            return [Violation(node.lineno, "open() needs a literal mode string")]
        if WRITE_MODE_CHARS & set(mode.value):
            return [Violation(node.lineno, f"open() in write mode {mode.value!r} is forbidden")]
        return []
    # x.open(...): the mode is the first argument for Path.open and the second elsewhere.
    candidates = [keyword] if keyword is not None else list(node.args[:2])
    return [
        Violation(node.lineno, f".open() in write mode {item.value!r} is forbidden")
        for item in candidates
        if isinstance(item, ast.Constant)
        and isinstance(item.value, str)
        and MODE_PATTERN.fullmatch(item.value)
        and WRITE_MODE_CHARS & set(item.value)
    ]


def _check_call(node: ast.Call) -> list[Violation]:
    """Check a call expression."""
    func = node.func
    if isinstance(func, ast.Name):
        return _check_open(node, builtin=True) if func.id == "open" else []
    if not isinstance(func, ast.Attribute):
        return []
    if isinstance(func.value, ast.Name) and func.value.id == "os" and _os_name_blocked(func.attr):
        return [Violation(node.lineno, f"os.{func.attr}() is forbidden")]
    if func.attr in PATH_WRITE_METHODS:
        return [Violation(node.lineno, f".{func.attr}() changes the file system")]
    if func.attr == "open":
        return _check_open(node, builtin=False)
    return []


def _permitted_deletion(tree: ast.AST) -> set[int]:
    """The id of the one ``.unlink()`` call that may stay: the first one in DELETE_FUNCTION."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == DELETE_FUNCTION:
            calls = [
                call
                for call in ast.walk(node)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "unlink"
            ]
            calls.sort(key=lambda call: (call.lineno, call.col_offset))
            return {id(calls[0])} if calls else set()
    return set()


def scan_source(
    source: str, local_modules: frozenset[str] = frozenset(), may_delete_input: bool = False
) -> list[Violation]:
    """Return every forbidden construct in ``source``, sorted by line.

    ``local_modules`` are the module names that sit next to the script and may be imported.
    ``may_delete_input`` lets one ``.unlink()`` call in the function DELETE_FUNCTION pass: the
    deletion of the ``--input`` file in the shared core.
    """
    tree = ast.parse(source)
    permitted = _permitted_deletion(tree) if may_delete_input else set()
    found: list[Violation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.extend(_check_import(node.lineno, alias.name, local_modules))
        elif isinstance(node, ast.ImportFrom):
            found.extend(_check_import_from(node, local_modules))
        elif isinstance(node, ast.Name):
            if node.id in FORBIDDEN_BUILTINS and isinstance(node.ctx, ast.Load):
                found.append(Violation(node.lineno, f"use of {node.id} is forbidden"))
        elif isinstance(node, ast.Call) and id(node) not in permitted:
            found.extend(_check_call(node))
    return sorted(found)


def scan_file(path: Path) -> list[Violation]:
    """Scan one script. Sibling .py files in the same folder count as local modules."""
    local_modules = frozenset(sibling.stem for sibling in path.parent.glob("*.py"))
    found = scan_source(
        path.read_text(encoding="utf-8"), local_modules, may_delete_input=path.name == DELETE_FILE
    )
    if path.stem in STDLIB:
        found.append(Violation(0, f"file name {path.name} shadows a standard library module"))
    return sorted(found)


# --------------------------------------------------------------------------------------
# Running scripts
# --------------------------------------------------------------------------------------


def run_script(
    script: Path, cwd: Path, *args: str, isolated: bool = False, safe_path: bool = False
) -> subprocess.CompletedProcess[str]:
    """Run a script with the current interpreter, without site-packages, in an empty folder.

    ``-S`` hides installed third-party packages, so a stray import fails here the way it would
    on a clean machine. ``-B`` keeps __pycache__ folders out of the skill directories. With
    ``isolated`` the script also runs under ``-I``, which leaves the script's own folder off
    ``sys.path`` and ignores the environment. ``safe_path`` sets PYTHONSAFEPATH, which does the
    same from Python 3.11 on, as the option ``-P`` does, and is ignored by older versions.
    """
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if safe_path:
        env["PYTHONSAFEPATH"] = "1"
    flags = ["-I", "-B", "-S"] if isolated else ["-B", "-S"]
    return subprocess.run(
        [sys.executable, *flags, str(script), *args],
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=TIMEOUT_SECONDS,
        check=False,
    )


def describe(result: subprocess.CompletedProcess[str]) -> str:
    """Format a finished process for an assertion message."""
    return (
        f"exit code {result.returncode}\n"
        f"--- stdout (tail) ---\n{result.stdout[-1500:]}\n"
        f"--- stderr (tail) ---\n{result.stderr[-1500:]}"
    )


# Every .py file in a scripts/ folder is scanned. Only the skill scripts are run: fsq_core.py is
# the module that they import.
PYTHON_FILES = sorted(SKILLS_DIR.glob("*/scripts/*.py"))
SCRIPTS = [path for path in PYTHON_FILES if path.name != DELETE_FILE]


def file_ids(paths: list[Path]) -> list[str]:
    return [f"{path.parent.parent.name}/{path.name}" for path in paths]


# --------------------------------------------------------------------------------------
# Tests over the real skill scripts
# --------------------------------------------------------------------------------------


def test_every_skill_folder_has_exactly_one_script_of_its_own() -> None:
    folders = sorted(path for path in SKILLS_DIR.iterdir() if path.is_dir())
    assert folders, "no skill folders found"
    for folder in folders:
        own = [path for path in SCRIPTS if path.parent.parent == folder]
        assert len(own) == 1, folder.name
        assert (folder / "scripts" / DELETE_FILE).is_file(), folder.name


@pytest.mark.parametrize("script", PYTHON_FILES, ids=file_ids(PYTHON_FILES))
def test_script_uses_only_allowed_constructs(script: Path) -> None:
    violations = scan_file(script)
    report = "\n".join(
        f"{script.relative_to(ROOT).as_posix()}:{item.line}: {item.message}" for item in violations
    )
    assert not violations, report


@pytest.mark.parametrize("script", SCRIPTS, ids=file_ids(SCRIPTS))
def test_help_exits_zero(script: Path, tmp_path: Path) -> None:
    result = run_script(script, tmp_path, "--help")
    assert result.returncode == 0, describe(result)
    assert "Traceback" not in result.stderr, describe(result)


@pytest.mark.parametrize("flag", ["--demo", "--selftest"])
@pytest.mark.parametrize("script", SCRIPTS, ids=file_ids(SCRIPTS))
def test_demo_and_selftest_exit_zero(script: Path, tmp_path: Path, flag: str) -> None:
    result = run_script(script, tmp_path, flag)
    assert result.returncode == 0, f"{flag}: {describe(result)}"


@pytest.mark.parametrize("script", SCRIPTS, ids=file_ids(SCRIPTS))
def test_demo_output_is_identical_on_every_run(script: Path, tmp_path: Path) -> None:
    first = run_script(script, tmp_path, "--demo")
    second = run_script(script, tmp_path, "--demo")
    assert first.returncode == 0, describe(first)
    assert first.stdout == second.stdout


@pytest.mark.parametrize("script", SCRIPTS, ids=file_ids(SCRIPTS))
def test_script_starts_in_isolated_and_safe_path_mode_and_prints_the_same_demo(
    script: Path, tmp_path: Path
) -> None:
    plain = run_script(script, tmp_path, "--demo")
    isolated = run_script(script, tmp_path, "--demo", isolated=True)
    assert isolated.returncode == 0, describe(isolated)
    assert isolated.stdout == plain.stdout
    safe = run_script(script, tmp_path, "--demo", safe_path=True)
    assert safe.returncode == 0, describe(safe)
    assert safe.stdout == plain.stdout


# --------------------------------------------------------------------------------------
# Tests of the scanner itself (these always run)
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "fragment"),
    [
        ("import requests", "requests"),
        ("import numpy as np", "numpy"),
        ("from scipy import optimize", "scipy"),
        ("import subprocess", "subprocess"),
        ("from subprocess import run", "subprocess"),
        ("import socket", "socket"),
        ("import urllib.request", "urllib.request"),
        ("from urllib import parse", "urllib"),
        ("import http.client", "http.client"),
        ("import importlib", "importlib"),
        ("import pickle", "pickle"),
        ("import shutil", "shutil"),
        ("import tempfile", "tempfile"),
        ("eval('1 + 1')", "eval"),
        ("exec('x = 1')", "exec"),
        ("compile('1', 'f', 'eval')", "compile"),
        ("__import__('os')", "__import__"),
        ("f = eval", "eval"),
        ("open('out.txt', 'w')", "write mode"),
        ("open('out.txt', 'a')", "write mode"),
        ("open('out.txt', 'x')", "write mode"),
        ("open('out.txt', 'r+')", "write mode"),
        ("open('out.txt', 'wb')", "write mode"),
        ("open('out.txt', mode='a')", "write mode"),
        ("open('out.txt', mode)", "literal mode"),
        ("import io\nio.open('f', 'w')", "write mode"),
        ("from pathlib import Path\nPath('f').open('w')", "write mode"),
        ("from pathlib import Path\nPath('f').write_text('x')", "write_text"),
        ("from pathlib import Path\nPath('f').write_bytes(b'x')", "write_bytes"),
        ("from pathlib import Path\nPath('f').mkdir()", "mkdir"),
        ("import os\nos.system('ls')", "os.system"),
        ("import os\nos.remove('f')", "os.remove"),
        ("import os\nos.unlink('f')", "os.unlink"),
        ("from pathlib import Path\nPath('f').unlink()", "unlink"),
        ("import os\nos.execv('/bin/ls', [])", "os.execv"),
        ("from os import system", "from os import system"),
        ("from . import sibling", "relative imports"),
    ],
)
def test_scanner_flags_forbidden_constructs(source: str, fragment: str) -> None:
    found = scan_source(source)
    assert found, f"nothing flagged in {source!r}"
    assert any(fragment in item.message for item in found), found


@pytest.mark.parametrize(
    "source",
    [
        "import argparse, json, re, sys\nPATTERN = re.compile('a+')",
        "from fractions import Fraction\nvalue = Fraction(1, 3)",
        "from __future__ import annotations",
        "import hashlib\ndigest = hashlib.sha256(b'x').hexdigest()",
        "with open('in.json') as handle:\n    data = handle.read()",
        "with open('in.json', 'r', encoding='utf-8') as handle:\n    data = handle.read()",
        "with open('in.bin', mode='rb') as handle:\n    data = handle.read()",
        "from pathlib import Path\ntext = Path('in.json').read_text()",
        "from pathlib import Path\nwith Path('in.json').open('r') as handle:\n    pass",
        "import ast\nvalue = ast.literal_eval('[1, 2]')",
        "import sys\nsys.stdout.write('ok')",
        "text = 'eval(1) and open(x, \"w\") are only words here'",
        "name = 'a-b'.replace('-', '_')",
    ],
)
def test_scanner_accepts_ordinary_code(source: str) -> None:
    assert scan_source(source) == []


def test_scanner_accepts_imports_of_sibling_modules_only_when_they_exist() -> None:
    source = "from money import to_cents"
    assert scan_source(source, frozenset({"money"})) == []
    assert scan_source(source) != []


def test_scanner_reports_line_numbers_in_order() -> None:
    source = "import json\nimport socket\nx = 1\neval('2')\n"
    assert [item.line for item in scan_source(source)] == [2, 4]


def test_scan_file_flags_a_file_that_shadows_a_stdlib_module(tmp_path: Path) -> None:
    script = tmp_path / "statistics.py"
    script.write_text("X = 1\n", encoding="utf-8")
    found = scan_file(script)
    assert [item.line for item in found] == [0]
    assert "shadows" in found[0].message


def test_scan_file_allows_siblings(tmp_path: Path) -> None:
    (tmp_path / "money.py").write_text("X = 1\n", encoding="utf-8")
    script = tmp_path / "tool.py"
    script.write_text("import money\nprint(money.X)\n", encoding="utf-8")
    assert scan_file(script) == []


DELETING_CORE = (
    "from pathlib import Path\n"
    "\n"
    "def _delete_input_file(path):\n"
    "    Path(path).unlink(missing_ok=True)\n"
)


def test_the_deletion_of_the_input_file_passes_only_when_it_is_allowed() -> None:
    assert scan_source(DELETING_CORE, may_delete_input=True) == []
    assert [item.line for item in scan_source(DELETING_CORE)] == [4]


def test_a_second_deletion_or_one_in_another_function_is_still_flagged() -> None:
    twice = DELETING_CORE + "    Path('other').unlink()\n"
    assert [item.line for item in scan_source(twice, may_delete_input=True)] == [5]
    elsewhere = DELETING_CORE + "\ndef other(path):\n    Path(path).unlink()\n"
    assert [item.line for item in scan_source(elsewhere, may_delete_input=True)] == [7]
    renamed = DELETING_CORE.replace(DELETE_FUNCTION, "tidy_up")
    assert [item.line for item in scan_source(renamed, may_delete_input=True)] == [4]


def test_other_file_changes_stay_flagged_next_to_the_allowed_deletion() -> None:
    source = DELETING_CORE + "    Path(path).write_text('x')\n"
    found = scan_source(source, may_delete_input=True)
    assert [item.line for item in found] == [5]
    assert "write_text" in found[0].message


def test_scan_file_allows_the_deletion_only_in_a_file_named_like_the_core(tmp_path: Path) -> None:
    core = tmp_path / DELETE_FILE
    core.write_text(DELETING_CORE, encoding="utf-8")
    assert scan_file(core) == []
    other = tmp_path / "tool.py"
    other.write_text(DELETING_CORE, encoding="utf-8")
    assert [item.line for item in scan_file(other)] == [4]


def test_stdlib_list_contains_the_modules_scripts_use() -> None:
    expected = {"argparse", "json", "re", "fractions", "hashlib", "decimal", "itertools", "sys"}
    assert expected <= STDLIB


def test_run_script_runs_a_script_without_site_packages(tmp_path: Path) -> None:
    script = tmp_path / "hello.py"
    script.write_text("import sys\nprint('site' in sys.modules)\n", encoding="utf-8")
    result = run_script(script, tmp_path)
    assert result.returncode == 0, describe(result)
    assert result.stdout.strip() == "False"
