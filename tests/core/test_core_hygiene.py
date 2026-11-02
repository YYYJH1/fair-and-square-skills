"""The shared core stays small and safe: standard library only, no shell, network, file
writes, dynamic code or random module, valid Python 3.9 grammar, and no work at import. The one
change it makes to the file system is deleting the --input file after it has been read, and
only when --delete-input is given. One test below pins that deletion to a single call."""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import fsq_core as core
import pytest

CORE_DIR = Path(core.__file__).resolve().parent
CORE_FILE = CORE_DIR / "fsq_core.py"
SOURCE = CORE_FILE.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)

ALLOWED_IMPORTS = {
    "__future__",
    "argparse",
    "collections",
    "dataclasses",
    "fractions",
    "hashlib",
    "itertools",
    "json",
    "math",
    "pathlib",
    "re",
    "secrets",
    "stat",
    "sys",
    "textwrap",
    "typing",
}
FORBIDDEN_NAMES = {
    "eval",
    "exec",
    "compile",
    "__import__",
    "open",
    "input",
    "breakpoint",
    "globals",
}
FORBIDDEN_ATTRIBUTES = {
    "system",
    "popen",
    "write_text",
    "write_bytes",
    "mkdir",
    "rmdir",
    "rename",
    "touch",
    "chmod",
    "urlopen",
    "connect",
}
FORBIDDEN_WORDS = (
    r"\b(eval|exec|subprocess|socket|pickle|marshal|importlib|ctypes|urllib|requests)\b"
)


def imported_modules() -> set[str]:
    modules = set()
    for node in ast.walk(TREE):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative imports would break the per-skill copies"
            modules.add((node.module or "").split(".")[0])
    return modules


class TestStaticScan:
    def test_only_standard_library_modules_from_the_allow_list(self):
        assert imported_modules() <= ALLOWED_IMPORTS

    def test_the_random_module_is_never_imported(self):
        assert "random" not in imported_modules()
        assert not re.search(r"\brandom\.", SOURCE)

    def test_no_dynamic_code_or_blocking_builtins(self):
        names = {node.id for node in ast.walk(TREE) if isinstance(node, ast.Name)}
        assert names.isdisjoint(FORBIDDEN_NAMES)

    def test_no_shell_network_or_file_writing_calls(self):
        attributes = {node.attr for node in ast.walk(TREE) if isinstance(node, ast.Attribute)}
        assert attributes.isdisjoint(FORBIDDEN_ATTRIBUTES)

    def test_the_only_file_deletion_is_the_one_behind_delete_input(self):
        # "unlink" is not in FORBIDDEN_ATTRIBUTES, so it is counted here: exactly one call, and
        # it sits in the function that deletes the --input file after it has been read.
        calls = [
            node
            for node in ast.walk(TREE)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "unlink"
        ]
        assert len(calls) == 1
        deleter = next(
            node
            for node in ast.walk(TREE)
            if isinstance(node, ast.FunctionDef) and node.name == "_delete_input_file"
        )
        assert calls[0] in set(ast.walk(deleter))

    def test_that_function_is_called_only_by_read_input(self):
        callers = set()
        for function in (node for node in ast.walk(TREE) if isinstance(node, ast.FunctionDef)):
            for node in ast.walk(function):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "_delete_input_file"
                ):
                    callers.add(function.name)
        assert callers == {"read_input"}

    def test_forbidden_words_do_not_appear_even_in_comments_or_strings(self):
        assert re.findall(FORBIDDEN_WORDS, SOURCE) == []

    def test_reads_files_only_through_path_read_text(self):
        reads = [
            n for n in ast.walk(TREE) if isinstance(n, ast.Attribute) and n.attr == "read_text"
        ]
        assert len(reads) == 1

    def test_parses_with_python_3_9_grammar(self):
        ast.parse(SOURCE, feature_version=(3, 9))

    def test_modern_annotations_are_lazy(self):
        # `X | None` and `list[int]` in signatures are only safe on 3.9 as strings
        first = next(n for n in TREE.body if not isinstance(n, ast.Expr))
        assert isinstance(first, ast.ImportFrom) and first.module == "__future__"
        assert [alias.name for alias in first.names] == ["annotations"]

    def test_no_python_3_10_only_helpers(self):
        for banned in ("bit_count", "pairwise", "strict=True"):
            assert banned not in SOURCE

    def test_source_is_plain_text(self):
        assert "\t" not in SOURCE and "\r" not in SOURCE
        assert SOURCE.endswith("\n") and not SOURCE.endswith("\n\n")
        assert max(len(line) for line in SOURCE.splitlines()) <= 100


class TestImportBehaviour:
    def test_importing_does_nothing_visible(self, tmp_path):
        code = f"import sys; sys.path.insert(0, {str(CORE_DIR)!r}); import fsq_core"
        run = subprocess.run(
            [sys.executable, "-I", "-c", code],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            cwd=tmp_path,
        )
        assert (run.returncode, run.stdout, run.stderr) == (0, "", "")
        assert list(tmp_path.iterdir()) == []

    def test_module_has_a_version_and_a_docstring(self):
        assert re.fullmatch(r"\d+\.\d+\.\d+", core.CORE_VERSION)
        assert core.__doc__ and "standard library" in core.__doc__


class TestManifest:
    def test_manifest_lists_the_core_file(self):
        lines = (CORE_DIR / "MANIFEST.txt").read_text(encoding="utf-8").splitlines()
        names = [line.split("#")[0].strip() for line in lines if line.split("#")[0].strip()]
        assert names == ["fsq_core.py"]
        assert all((CORE_DIR / name).is_file() for name in names)


PUBLIC_API = [
    # errors and exit codes
    "InputError",
    "NoSolution",
    "run_cli",
    # input
    "load_input",
    "parse_input",
    "money",
    "encodable",
    "check_fields",
    "one_line",
    "require_encodable_names",
    "require_source_text",
    # money output and rounding
    "to_cents",
    "fmt_cents",
    "round_shares",
    "round_half_up",
    "round_min_envy",
    # cooperative games
    "shapley_values",
    # seed mapping and commitments
    "make_seed",
    "seed_preimage",
    "seeded_order",
    "SeedStream",
    "shuffle",
    "sample",
    "commit",
    "verify_commit",
    # output
    "Result",
    "render_md",
    "render_dm",
    "render_group",
    "render_json",
    "fill_text",
    # command line
    "standard_args",
    "add_lang_option",
    "exit_codes_epilog",
    "exclusive_modes",
    "read_object",
    "run_selftest",
    "expect",
]


@pytest.mark.parametrize("name", PUBLIC_API)
def test_public_api_is_present(name):
    assert hasattr(core, name), f"fsq_core.{name} is part of the interface skills rely on"


def test_result_has_the_envelope_fields():
    fields = set(core.Result.__dataclass_fields__)
    assert {"inputs_echo", "result", "certificate", "not_modeled", "reproduce"} <= fields
