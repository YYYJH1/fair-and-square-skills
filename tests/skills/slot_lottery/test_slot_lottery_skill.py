"""SKILL.md, the examples and the other public text of the slot-lottery skill."""

from __future__ import annotations

import ast
import json
import os
import re
import shlex
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import ClassVar

import pytest
import theory_doc as doc
from lottery_support import (
    EXAMPLES,
    GOLDEN_ORDER,
    PEOPLE8,
    SCRIPT,
    SKILL_DIR,
    SOURCE,
    run_script,
)

SKILL_MD = SKILL_DIR / "SKILL.md"
TESTS_DIR = Path(__file__).resolve().parent
TRIGGERS = [
    "抽签",
    "抢名额",
    "名额不够怎么分",
    "排班抽签",
    "值班怎么排",
    "lottery",
    "raffle",
    "fair draw",
    "assign slots by preference",
]
# Things that must never reach a public file of this skill: machine paths, e-mail addresses and
# credential words. Names of private projects are checked by the release checklist, not here.
LEAKS = {
    "an absolute path": re.compile(r"(?<![\w./-])/(?:data|home|tmp|Users|var|mnt|root)/\S+"),
    "an e-mail address": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "a credential word": re.compile(r"api[_-]?key|password|secret|token", re.IGNORECASE),
}
OVERCLAIMS = [
    "nobody can cheat",
    "cannot be rigged",
    "tamper-proof",
    "impossible to cheat",
    "谁也做不了手脚",
    "无法作弊",
    "不可能作弊",
]


def text() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def frontmatter() -> dict:
    block = text().split("---")[1]
    fields = {}
    for line in block.strip().splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def code_blocks(language: str) -> list[str]:
    """The contents of the fenced blocks of one language, in order (indentation removed)."""
    pattern = rf"^[ \t]*```{language}\n(.*?)\n[ \t]*```$"
    found = re.findall(pattern, text(), flags=re.DOTALL | re.MULTILINE)
    return [textwrap.dedent(block) for block in found]


class TestFrontmatter:
    def test_only_the_four_frontmatter_fields(self):
        assert sorted(frontmatter()) == ["allowed-tools", "description", "license", "name"]

    def test_name_and_license(self):
        fields = frontmatter()
        assert fields["name"] == "slot-lottery" == SKILL_DIR.name
        assert fields["license"] == "MIT"

    def test_allowed_tools_is_the_one_script(self):
        assert (
            frontmatter()["allowed-tools"]
            == "Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/slot_lottery.py *)"
        )

    def test_description_limits(self):
        description = frontmatter()["description"]
        assert len(description) <= 1024
        assert "<" not in description and ">" not in description
        assert ": " not in description, "a colon and a space would need quoting in YAML"
        assert " #" not in description

    @pytest.mark.parametrize("trigger", TRIGGERS)
    def test_description_has_the_trigger_phrases(self, trigger):
        assert trigger in frontmatter()["description"]

    def test_description_points_to_the_neighbours(self):
        description = frontmatter()["description"]
        assert "group-vote" in description
        assert "bill-split" in description and "rent-split" in description


class TestBody:
    def test_under_500_lines(self):
        assert len(text().splitlines()) < 500

    def test_calls_the_script_through_the_skill_dir_variable_with_a_fallback(self):
        body = text()
        assert "python3 ${CLAUDE_SKILL_DIR}/scripts/slot_lottery.py" in body
        assert (
            "If that variable was not replaced, the script is in the `scripts/` folder "
            "next to this file." in body
        )

    def test_outside_claude_code_the_input_goes_through_standard_input(self):
        assert "--input - <<'EOF'" in text()

    def test_in_claude_code_the_input_goes_through_a_file_that_the_script_deletes(self):
        assert "--input <input-file> --delete-input" in text()

    def test_every_step_states_when_it_is_done(self):
        steps = re.findall(r"^## Step \d\. .*$", text(), flags=re.MULTILINE)
        assert len(steps) == 4
        assert text().count("Done when") == 4

    def test_step_one_fixes_the_rules_in_a_chinese_message(self):
        step = text().split("## Step 1.")[1].split("## Step 2.")[0]
        for needed in (
            "source",
            "deadline",
            "sends no ranking",
            "forfeit",
            "assigned",
            "抽签规则（先定再收，发出后不改）",
            "随机源",
            "候补",
        ):
            assert needed in step, needed

    def test_step_three_waits_for_the_source(self):
        step = text().split("## Step 3.")[1].split("## Step 4.")[0]
        assert "has not been published yet" in step and "stop" in step
        assert "character by character" in step

    def test_quotes_the_rule_that_everything_comes_from_the_script(self):
        assert "Quote every name, position and slot" in text()
        assert "never choose or guess the random source" in text()

    def test_lists_the_guarantees_and_the_limits(self):
        section = text().split("## Guarantees and limits")[1].split("## When not to use")[0]
        for needed in (
            "equally likely",
            "Reproducible",
            "strategy-proof",
            "Pareto",
            "not envy-free",
            "predictable source",
        ):
            assert needed in section, needed

    def test_does_not_overclaim(self):
        body = text().lower()
        for phrase in OVERCLAIMS:
            assert phrase.lower() not in body, phrase

    def test_points_to_the_other_skills_when_not_to_use(self):
        section = text().split("## When not to use")[1].split("## Reference")[0]
        for neighbour in ("group-vote", "bill-split", "rent-split", "chore-split"):
            assert neighbour in section

    def test_cites_the_serial_dictatorship_paper(self):
        assert "10.2307/2998580" in text().split("## Reference")[1]

    def test_every_option_it_mentions_exists(self):
        options = set(re.findall(r"(?<![\w-])(--[a-z][a-z-]*)", text()))
        wanted = {"--format", "--json", "--lang", "--verify", "--source", "--commit", "--demo"}
        assert wanted | {"--input", "--person"} <= options
        help_text = " ".join(run_script("--help").stdout.split())
        for option in options:
            assert option in help_text, option

    def test_every_example_it_mentions_exists(self):
        names = re.findall(r"examples/([A-Za-z0-9_.-]+\.json)", text())
        assert len(set(names)) == 5
        for name in names:
            assert (EXAMPLES / name).is_file(), name

    def test_the_input_fields_table_lists_every_field_the_script_accepts(self):
        import slot_lottery as sl

        table = text().split("The input fields:")[1].split("Options are listed")[0]
        for field in (*sl.TOP_FIELDS, *(f"rules.{rule}" for rule in sl.RULE_FIELDS)):
            if field in ("claimed", "rules"):
                continue  # claimed belongs to --verify, rules is described field by field
            assert f"`{field}`" in table, field


def command_blocks() -> list[str]:
    """The fenced bash blocks except the one for Claude Code, whose file does not exist yet."""
    return [block for block in code_blocks("bash") if "--delete-input" not in block]


def documented_command(index: int) -> tuple[list[str], str]:
    """The command and the standard input of the index-th other fenced bash block of SKILL.md."""
    block = command_blocks()[index]
    command, _, rest = block.partition("<<'EOF'\n")
    stdin = rest.rsplit("\nEOF", 1)[0] if rest else ""
    words = shlex.split(command.replace("${CLAUDE_SKILL_DIR}", str(SKILL_DIR)))
    return words, stdin


def run_words(words: list[str], stdin: str) -> subprocess.CompletedProcess:
    assert words[0] == "python3" and Path(words[1]) == SCRIPT
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-B", "-S", *words[1:]],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=60,
        check=False,
    )


def test_the_documented_command_runs_as_written():
    words, stdin = documented_command(0)
    done = run_words(words, stdin)
    assert done.returncode == 0, done.stderr
    assert "| 1 | Yuki | 抽中 |" in done.stdout
    assert "| 4 | Coco | 候补 1 |" in done.stdout


def test_the_documented_input_is_the_recorded_example():
    _, stdin = documented_command(0)
    assert json.loads(stdin) == json.loads((EXAMPLES / "tickets_8_for_3.json").read_text("utf-8"))


def test_the_documented_check_of_a_card_runs_as_written():
    words, stdin = documented_command(1)
    assert "--verify" in words and "--source" in words
    done = run_words(words, stdin)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "可以复现" in done.stdout


def test_the_documented_commit_command_runs_as_written():
    words, stdin = documented_command(2)
    assert "--commit" in words and stdin == ""
    done = run_words(words, stdin)
    assert done.returncode == 0, done.stderr
    assert re.search(r"[0-9a-f]{64}", done.stdout)


def test_the_python_snippet_gives_the_recorded_order():
    snippet = code_blocks("python")[0]
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    done = subprocess.run(
        [sys.executable, "-B", "-S", "-c", snippet],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert ast.literal_eval(done.stdout) == GOLDEN_ORDER


def test_the_messages_quoted_in_the_skill_are_what_the_script_prints():
    quoted = re.findall(r"\"(你[^\"]+)\"", text().split("## Step 4.")[1].split("## Recomputing")[0])
    assert len(quoted) == 2
    lottery = run_script("--demo", "--format", "dm").stdout
    shifts = run_script("--input", str(EXAMPLES / "shifts_rsd.json"), "--format", "dm").stdout
    assert quoted[0] in lottery
    assert quoted[1] in shifts


def test_the_numbers_in_the_skill_are_the_numbers_the_script_warns_with():
    out = run_script("--input", str(EXAMPLES / "commit_reveal.json"), "--format", "group")
    for number in ("0.375", "0.643"):
        assert number in out.stdout and number in text()


class TestPublicHygiene:
    FILES: ClassVar[list] = [
        SKILL_MD,
        SCRIPT,
        *sorted(EXAMPLES.glob("*.json")),
    ]

    @pytest.mark.parametrize("path", FILES, ids=lambda path: path.name)
    def test_no_machine_paths_addresses_or_credentials(self, path):
        content = path.read_text(encoding="utf-8")
        for what, pattern in LEAKS.items():
            found = pattern.search(content)
            assert found is None, f"{path.name} contains {what}: {found.group(0)!r}"

    @pytest.mark.parametrize("path", sorted(TESTS_DIR.glob("*.py")), ids=lambda path: path.name)
    def test_the_tests_contain_no_machine_paths_or_addresses(self, path):
        content = path.read_text(encoding="utf-8")
        for what in ("an absolute path", "an e-mail address"):
            found = LEAKS[what].search(content)
            assert found is None, f"{path.name} contains {what}: {found.group(0)!r}"

    def test_the_examples_are_marked_as_made_up(self):
        for name in ("tickets_8_for_3.json", "shifts_rsd.json"):
            assert "虚构示例" in (EXAMPLES / name).read_text(encoding="utf-8")
        assert "虚构示例" in (EXAMPLES / "commit_reveal.json").read_text(encoding="utf-8")


class TestTheorySection:
    def content(self) -> str:
        return doc.section("slot-lottery")

    def test_the_section_holds_no_machine_paths_addresses_or_credentials(self):
        for what, pattern in LEAKS.items():
            text = doc.prose(self.content()) if what == "a credential word" else self.content()
            found = pattern.search(text)
            assert found is None, f"THEORY.md contains {what}: {found.group(0)!r}"

    def test_it_has_the_sections_the_theory_file_expects(self):
        content = self.content()
        assert content.startswith("## slot-lottery")
        for heading in ("### Guarantees", "### Not guaranteed", "### Method"):
            assert heading in content

    def test_it_cites_the_serial_dictatorship_paper(self):
        assert "Abdulkadiroğlu and Sönmez" in self.content()
        assert "10.2307/2998580" in doc.section("References")

    def test_every_test_named_in_the_section_exists(self):
        assert doc.cited(self.content()), "the section should name the tests that check it"
        assert doc.missing_tests(self.content()) == []

    def test_it_states_the_numbers_of_the_recorded_example(self):
        content = self.content()
        assert "15b9c53a44270857eb442863" in content
        assert " ".join(GOLDEN_ORDER) in content
        assert SOURCE.split()[0] in content or "03 11 19 24 33" in content
        assert len(PEOPLE8) == 8
