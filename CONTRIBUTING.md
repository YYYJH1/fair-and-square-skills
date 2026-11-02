<p align="center"><b>English</b> · <a href="CONTRIBUTING_zh.md">简体中文</a></p>

# Contributing

This file explains how to set up the repository, run the checks and add a skill.

## Set up

Fork the repository on GitHub, then clone your fork:

```
git clone https://github.com/<your-user>/fair-and-square-skills.git
cd fair-and-square-skills
uv sync
```

`uv sync` creates `.venv` with the development tools (pytest, hypothesis, ruff and scipy). The skill scripts themselves need only Python 3.9 or later.

## Reporting a problem and proposing a change

- Open an issue for a wrong number, a crash or a sentence in a `SKILL.md` that misleads. Give the command, the input and the output. Use made-up names and amounts, because a real bid, ranking or ballot must not appear in a public issue.
- Open a pull request against `main` from a branch of your fork. Say what changes and why, and keep it to one topic. CI has to be green.
- A change that alters what a script prints needs the stored outputs updated, see "Run the checks". Say in the pull request which outputs change and why.
- A new skill starts as an issue that describes the situation it settles and the method it uses. "Rules for a skill" below lists what a skill needs.

## Run the checks

```
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
uv run python tools/validate_plugin.py
```

CI runs the same four commands on Python 3.9 to 3.13. `uv run ruff format .` rewrites the files that the format check would reject. A separate job runs every skill script with `--help`, `--demo` and `--selftest`, and once more under `python -I`, on plain Python 3.9 with no packages installed.

The files in `tests/skills/*/golden/` hold the exact text that the scripts print for the recorded examples. After a change of output that you intend, run `FSQ_UPDATE_GOLDEN=1 uv run pytest -q`, read the `git diff` of every file it rewrote, and commit those files together with the change.

What each check covers:

- `tests/test_validator.py` tests `tools/validate_plugin.py` on throw-away fixture trees.
- `tests/test_contract.py` scans every `.py` file in `plugin/skills/*/scripts/` and runs every skill script. See the rules below.
- `tests/test_shared_behaviour.py` runs all eight scripts the same way and checks what they share: the message for standard input that is not UTF-8, for a field the skill does not know and for a name with an unpaired surrogate, the space between a Latin name and Chinese words, `--lang en`, and `--delete-input`.
- `tests/test_skill_input_routes.py` checks that every SKILL.md documents both ways to pass the input, a file with `--delete-input` for Claude Code and a heredoc for other tools, and that both commands run as written and print the same text.
- `tests/test_skill_template.py` checks that the eight SKILL.md files follow one template: the shape and length of the description, the headings, the language tag of every fenced block, the sentences on options and exit codes, the list of examples, and the wording the repository avoids.
- `tests/test_metadata.py` checks that keywords, links, license and Python versions agree in `pyproject.toml`, the manifests and CI.
- `tests/core/` tests the shared core. Each skill adds its own tests.
- `tests/test_theory.py` checks `docs/THEORY.md`: one section per skill with the same parts, every guarantee followed by the tests that check it, every named test present, every reference with its DOI, and prose without semicolons or dashes.
- `tools/validate_plugin.py` checks the whole layout: SKILL.md frontmatter, referenced files, the plugin manifest, the marketplace entry, the version in four places, and the shared copies of the core and the license.

When you change an English document, change its Chinese version in the same commit, because `tests/test_doc_mirrors.py` checks that the two carry the language switch on the first line, have the same heading levels in the same order and have the same number of code blocks.

## Rules for a skill

A skill is a folder `plugin/skills/<name>/` with `SKILL.md`, `scripts/`, `examples/` and a copy of `LICENSE`. The validator and the contract tests enforce these rules:

- SKILL.md frontmatter uses only fields of the open Agent Skills specification: `name`, `description`, `license`, `compatibility`, `metadata` and `allowed-tools`. Fields that only Claude Code understands are rejected, so the same file loads in every tool.
- `name` is lowercase letters, digits and single hyphens. It equals the folder name and contains neither `claude` nor `anthropic`.
- `description` has at most 1024 characters and no angle brackets.
- Every `scripts/`, `examples/` or `references/` path mentioned in SKILL.md exists.
- Scripts are called as `python3 ${CLAUDE_SKILL_DIR}/scripts/<script>.py`, followed by a sentence saying that the script sits next to SKILL.md when the variable is not replaced. The same section gives two ways to pass the input. In Claude Code the agent writes the input to a file with the Write tool and runs the script with `--input FILE --delete-input`, because a heredoc whose body holds braces and quotes needs the user's approval there. For Codex and other tools the section keeps the heredoc on standard input.
- Scripts use Python 3.9 or later and the standard library only. They never use the network, subprocesses, `eval`, `exec` or `compile`, and they never write a file. The one change they make to the file system is in the shared core: with `--delete-input`, `read_input` deletes the `--input` file after reading it. `tests/test_contract.py` allows that single `unlink` call, in `_delete_input_file` of `fsq_core.py`, and nothing else. Input arrives on standard input or in the `--input` file, and results go to standard output.
- Every script exits 0 on `--help`, `--demo` and `--selftest`, and the demo prints the same bytes on every run. Every script also starts under `python -I`, which leaves its own folder off `sys.path`, so it imports `fsq_core.py` from the folder it sits in.
- Every number in a reply comes from the script's output. Examples use invented names and amounts.
- The skill has a section in `docs/THEORY.md` with the guarantees, what is not guaranteed and the method. A guarantee is written down only after a test checks it, and the test is named next to it as `file::function`.

## Shared core

Code that several skills need lives once in `core/`, and `core/MANIFEST.txt` lists the shared files. Each skill folder must stay self-contained, so `tools/sync_core.py` copies those files into every `plugin/skills/<name>/scripts/`. It also copies the `LICENSE` of the repository root into every `plugin/skills/<name>/`. Before a skill gets its own copy of a check, a rounding rule or a text helper, look in `core/fsq_core.py`. A function that two skills need belongs there, with a test in `tests/core/`.

1. Edit the file under `core/` and never a copy.
2. Run `python3 tools/sync_core.py`.
3. Commit the core file and the copies together.

`python3 tools/sync_core.py --check`, the validator and CI all fail when a copy is missing or differs from its source.

## Maintainers

### Release checklist

1. CI is green on the commit to release.
2. Set the new version in `plugin/.claude-plugin/plugin.json`, in `pyproject.toml` (then run `uv lock`), as `CORE_VERSION` in `core/fsq_core.py` (then run `python3 tools/sync_core.py`) and on the `Version:` line of `docs/THEORY.md`. The validator fails when the four differ. The version must not appear in `.claude-plugin/marketplace.json`, which the validator rejects, because users receive an update only when the version in `plugin.json` changes.
3. Add a section for the version to `CHANGELOG.md`.
4. Run `claude plugin validate . --strict` and `claude plugin validate plugin --strict` locally and fix every warning. The CI runner has no Claude Code, so CI cannot run them for you.
5. Run `python3 tools/validate_plugin.py`, `python3 tools/sync_core.py --check` and the tests once more.
6. Search the tree for credentials and machine-specific absolute paths.
7. Tag the version bump commit as `vX.Y.Z` and push the tag. Copy the section of `CHANGELOG.md` into the release notes.
