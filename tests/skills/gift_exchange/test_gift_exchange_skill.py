"""SKILL.md, the examples and the other public text of the gift-exchange skill."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import ClassVar

import gift_exchange as ge
import pytest
import theory_doc as doc
from gift_support import (
    EXAMPLES,
    GOLDEN_PLAN,
    GOLDEN_SEED,
    RING_CIRCLE,
    SCRIPT,
    SKILL_DIR,
    THREE,
    THREE_FORBIDDEN,
    exchange_data,
    run_json,
    run_script,
)

SKILL_MD = SKILL_DIR / "SKILL.md"
TESTS_DIR = Path(__file__).resolve().parent
TRIGGERS = [
    "Secret Santa",
    "gift exchange",
    "who gives to whom",
    "交换礼物",
    "圣诞交换礼物",
    "抽签送礼",
    "年会互送礼物",
    "情侣不能抽到对方",
]
# Things that must never reach a public file of this skill: machine paths, e-mail addresses and
# credential words. The trigger phrase "Secret Santa" is the one use of such a word.
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


def without_the_trigger_phrase(content: str) -> str:
    return content.replace("Secret Santa", "")


class TestFrontmatter:
    def test_only_the_four_frontmatter_fields(self):
        assert sorted(frontmatter()) == ["allowed-tools", "description", "license", "name"]

    def test_name_and_license(self):
        fields = frontmatter()
        assert fields["name"] == "gift-exchange" == SKILL_DIR.name
        assert fields["license"] == "MIT"

    def test_allowed_tools_is_the_one_script(self):
        assert (
            frontmatter()["allowed-tools"]
            == "Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/gift_exchange.py *)"
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
        for neighbour in ("bill-split", "slot-lottery", "group-vote"):
            assert neighbour in description

    def test_description_says_what_the_script_does(self):
        description = frontmatter()["description"]
        for needed in ("Hall's theorem", "private message", "single circle", "recompute"):
            assert needed in description, needed


class TestBody:
    def test_under_500_lines(self):
        assert len(text().splitlines()) < 500

    def test_calls_the_script_through_the_skill_dir_variable_with_a_fallback(self):
        body = text()
        assert "python3 ${CLAUDE_SKILL_DIR}/scripts/gift_exchange.py" in body
        assert (
            "If that variable was not replaced, the script is in the `scripts/` folder "
            "next to this file." in body
        )

    def test_every_step_states_when_it_is_done(self):
        steps = re.findall(r"^## Step \d\. .*$", text(), flags=re.MULTILINE)
        assert len(steps) == 4
        assert text().count("Done when") == 4

    def test_step_one_fixes_the_rules_in_a_chinese_message(self):
        step = text().split("## Step 1.")[1].split("## Step 2.")[0]
        for needed in (
            "The way of giving",
            "The exclusions",
            "The public source",
            "The deadline",
            "Who sees the table",
            "After the draw",
            "交换礼物规则（先定再收，发出后不改）",
            "随机源",
            "不能互送",
        ):
            assert needed in step, needed

    def test_step_two_runs_the_check_before_the_source_exists(self):
        step = text().split("## Step 2.")[1].split("## Step 3.")[0]
        assert "--check" in step and "no `random_source`" in step
        assert "Exit code 3" in step and "Do not drop an exclusion yourself" in step

    def test_step_three_waits_for_the_source(self):
        step = text().split("## Step 3.")[1].split("## Step 4.")[0]
        assert "has not been published yet" in step and "stop" in step
        assert "character by character" in step

    def test_step_four_gives_each_reader_only_what_they_may_see(self):
        step = text().split("## Step 4.")[1].split("## Recomputing")[0]
        for needed in (
            "for the organizer only",
            "No message names anybody else's receiver",
            "does not say who gives to whom",
            "holds back the source text, the seed, the exclusions and the number of the plan",
            "After the exchange, publish the recompute material",
        ):
            assert needed in step, needed

    def test_quotes_the_rule_that_everything_comes_from_the_script(self):
        assert "Quote every name and number exactly as the script prints it" in text()
        assert "never choose or guess the random source" in text()
        assert "Show a pairing only to the organizer" in text()

    def test_lists_the_guarantees_and_the_limits(self):
        section = text().split("## Guarantees and limits")[1].split("## When not to use")[0]
        for needed in (
            "Legal.",
            "The check is exact",
            "Hall's theorem",
            "Equal chances",
            "Reproducible",
            "private only from people who do not recompute it",
            "two people may give to each other",
            "predictable source",
            "Not supported",
        ):
            assert needed in section, needed

    def test_does_not_overclaim(self):
        body = text().lower()
        for phrase in OVERCLAIMS:
            assert phrase.lower() not in body, phrase

    def test_points_to_the_other_skills_when_not_to_use(self):
        section = text().split("## When not to use")[1].split("## Reference")[0]
        for neighbour in ("bill-split", "slot-lottery", "group-vote"):
            assert neighbour in section

    def test_cites_hall_with_the_doi(self):
        assert "10.1112/jlms/s1-10.37.26" in text().split("## Reference")[1]

    def test_names_all_four_rules(self):
        for rule in ge.RULE_NAMES.values():
            assert rule in text(), rule

    def test_every_option_it_mentions_exists(self):
        options = set(re.findall(r"(?<![\w-])(--[a-z][a-z-]*)", text()))
        wanted = {"--format", "--json", "--lang", "--check", "--demo", "--selftest", "--input"}
        assert wanted | {"--delete-input"} <= options
        help_text = " ".join(run_script("--help").stdout.split())
        for option in options:
            assert option in help_text, option

    def test_every_example_it_mentions_exists(self):
        names = re.findall(r"examples/([A-Za-z0-9_.-]+\.json)", text())
        assert len(set(names)) == 3
        for name in names:
            assert (EXAMPLES / name).is_file(), name

    def test_the_input_fields_table_lists_every_field_the_script_accepts(self):
        table = text().split("The input fields:")[1].split("Options are listed")[0]
        for field in (*ge.TOP_FIELDS, *(f"rules.{rule}" for rule in ge.RULE_FIELDS)):
            if field == "rules":
                continue  # described field by field
            assert f"`{field}`" in table, field
        for field in ge.FORBIDDEN_FIELDS:
            assert f'"{field}"' in table or f"`{field}`" in table, field


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
    assert words[2:] == ["--format", "md", "--input", "-"]
    done = run_words(words, stdin)
    assert done.returncode == 0, done.stderr
    for giver, receiver in GOLDEN_PLAN.items():
        assert f"| {giver} | {receiver} |" in done.stdout


def test_the_documented_input_is_the_recorded_example():
    _, stdin = documented_command(0)
    assert json.loads(stdin) == json.loads((EXAMPLES / "six_with_couples.json").read_text("utf-8"))
    assert json.loads(stdin) == json.loads(ge.DEMO_JSON)


def test_the_python_snippet_gives_the_recorded_plan():
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
    lines = done.stdout.splitlines()
    assert lines[0] == "plan 13 of 96"
    assert {a: b for a, b in (line.split(" -> ") for line in lines[1:])} == GOLDEN_PLAN


def test_the_snippet_for_a_circle_changes_only_the_rule_name_and_the_filter():
    """The text says how to adapt the snippet. Do it, and compare with the script."""
    snippet = code_blocks("python")[0]
    snippet = snippet.replace("gift_exchange_any_enum_v1", "gift_exchange_ring_enum_v1")
    snippet = snippet.replace(
        "for plan in itertools.permutations(range(n))\n    if all(",
        "for plan in itertools.permutations(range(n))\n    if ring(plan) and all(",
    )
    snippet = (
        "def ring(plan):\n"
        "    seen, person = 0, plan[0]\n"
        "    while person != 0:\n"
        "        person, seen = plan[person], seen + 1\n"
        "    return seen == len(plan) - 1\n\n"
    ) + snippet
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
    lines = done.stdout.splitlines()
    assert lines[0] == "plan 10 of 40"
    got = {a: b for a, b in (line.split(" -> ") for line in lines[1:])}
    chain, person = [RING_CIRCLE[0]], got[RING_CIRCLE[0]]
    while person != RING_CIRCLE[0]:
        chain.append(person)
        person = got[person]
    assert chain == RING_CIRCLE


def test_the_hall_sentence_quoted_in_the_skill_is_what_the_script_prints():
    quoted = re.findall(r"\"(甲、乙[^\"]+)\"", text())
    assert quoted == ["甲、乙这 2 个人能送的只有丙（1 人）"]
    done = run_json(exchange_data(THREE, THREE_FORBIDDEN), "--check")
    assert quoted[0] in done.stderr


def test_the_message_quoted_in_the_skill_is_what_the_script_prints():
    quoted = re.findall(r"\"(你要送礼物给：[^\"]+)\"", text())
    assert quoted == ["你要送礼物给：Yuki。"]
    assert quoted[0] in run_script("--demo", "--format", "dm").stdout


def test_the_chinese_names_of_the_two_ways_in_the_rules_message_are_the_ones_the_script_prints():
    step = text().split("## Step 1.")[1].split("## Step 2.")[0]
    assert "任意错排" in step
    assert "任意错排" == ge.TEXT["zh"]["mode_any"]
    assert "「一圈传下去」" in step and ge.TEXT["zh"]["mode_ring"] == "一圈传下去"


class TestPublicHygiene:
    FILES: ClassVar[list] = [
        SKILL_MD,
        SCRIPT,
        *sorted(EXAMPLES.glob("*.json")),
    ]

    @pytest.mark.parametrize("path", FILES, ids=lambda path: path.name)
    def test_no_machine_paths_addresses_or_credentials(self, path):
        content = without_the_trigger_phrase(path.read_text(encoding="utf-8"))
        for what, pattern in LEAKS.items():
            found = pattern.search(content)
            assert found is None, f"{path.name} contains {what}: {found.group(0)!r}"

    @pytest.mark.parametrize("path", sorted(TESTS_DIR.glob("*.py")), ids=lambda path: path.name)
    def test_the_tests_contain_no_machine_paths_or_addresses(self, path):
        content = path.read_text(encoding="utf-8")
        for what in ("an absolute path", "an e-mail address"):
            found = LEAKS[what].search(content)
            assert found is None, f"{path.name} contains {what}: {found.group(0)!r}"

    def test_the_trigger_phrase_is_the_only_use_of_a_credential_word(self):
        found = LEAKS["a credential word"].findall(SKILL_MD.read_text(encoding="utf-8"))
        assert [word.lower() for word in found] == ["secret"] * len(found)
        assert text().count("Secret Santa") == len(found)

    def test_the_examples_are_marked_as_made_up(self):
        for path in EXAMPLES.glob("*.json"):
            assert "虚构示例" in path.read_text(encoding="utf-8"), path.name

    def test_the_golden_files_contain_no_machine_paths_or_addresses(self):
        for path in sorted((TESTS_DIR / "golden").glob("*.txt")):
            content = path.read_text(encoding="utf-8")
            for what in ("an absolute path", "an e-mail address"):
                assert LEAKS[what].search(content) is None, f"{path.name}: {what}"


class TestTheorySection:
    """What only the gift-exchange section of docs/THEORY.md says.

    The structure of the section, the tests it names, its prose and its references in general are
    checked for every skill by tests/test_theory.py.
    """

    def content(self) -> str:
        return doc.section("gift-exchange")

    def test_it_states_the_numbers_of_the_recorded_example(self):
        content = self.content()
        assert GOLDEN_SEED[:24] in content
        for needed in ("96 legal plans", "40 of them are single circles", "number 13 of 96"):
            assert needed in content, needed
        assert "number 10 of 40" in content

    def test_it_cites_hall_and_berge_and_the_references_have_their_dois(self):
        content = self.content()
        assert re.search(r"Hall[^\n]{0,80}1935", content) and re.search(
            r"Berge[^\n]{0,80}1957", content
        )
        references = doc.section("References")
        assert "10.1112/jlms/s1-10.37.26" in references
        assert "10.1073/pnas.43.9.842" in references
