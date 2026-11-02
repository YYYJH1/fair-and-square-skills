"""SKILL.md, the examples and the other public text of the chore-split skill."""

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

import chore_split as cs
import pytest
import theory_doc as doc
from chore_support import EXAMPLES, SCRIPT, SKILL_DIR, run_script

SKILL_MD = SKILL_DIR / "SKILL.md"
TESTS_DIR = Path(__file__).resolve().parent
TRIGGERS = [
    "分家务",
    "家务怎么分才公平",
    "合租值日表",
    "谁洗碗",
    "chore chart",
    "divide chores fairly",
    "roommate chores",
]
# Things that must never reach a public file of this skill: machine paths, e-mail addresses and
# credential words.
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
    "everybody envy-free",
    "perfectly fair",
    "谁也做不了手脚",
    "绝对公平",
    "完全公平",
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
    def test_only_the_four_fields_the_skills_use(self):
        assert sorted(frontmatter()) == ["allowed-tools", "description", "license", "name"]

    def test_name_and_license(self):
        fields = frontmatter()
        assert fields["name"] == "chore-split" == SKILL_DIR.name
        assert fields["license"] == "MIT"

    def test_allowed_tools_is_the_one_script(self):
        assert (
            frontmatter()["allowed-tools"]
            == "Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/chore_split.py *)"
        )

    def test_description_limits(self):
        description = frontmatter()["description"]
        assert len(description) <= 1024
        assert "<" not in description and ">" not in description
        assert ": " not in description, "a colon and a space would need quoting in YAML"
        assert " #" not in description
        assert description == description.strip() and "\n" not in description

    @pytest.mark.parametrize("trigger", TRIGGERS)
    def test_description_has_the_trigger_phrases(self, trigger):
        assert trigger in frontmatter()["description"]

    def test_description_points_to_the_neighbours(self):
        description = frontmatter()["description"]
        assert "slot-lottery" in description and "bill-split" in description

    def test_description_says_what_it_does_when_to_use_it_and_what_it_gives(self):
        description = frontmatter()["description"]
        assert description.startswith("Use whenever")
        for needed in ("bundled script", "weekly schedule", "one line per person", "cannot do"):
            assert needed in description, needed

    def test_description_says_only_for_chores(self):
        assert "Only for chores" in frontmatter()["description"]


class TestBody:
    def test_under_500_lines(self):
        assert len(text().splitlines()) < 500

    def test_calls_the_script_through_the_skill_dir_variable_with_a_fallback(self):
        body = text()
        assert "python3 ${CLAUDE_SKILL_DIR}/scripts/chore_split.py" in body
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
            "random source",
            "start moves",
            "cannot do",
            "likes",
            "deadline",
            "organizer goes first",
            "no re-pick",
            "分家务规则（先定再收，发出后不改）",
            "公开开奖的号码",
            "先手往后轮一位",
            "我先交",
            "不重挑，也不改规则",
        ):
            assert needed in step, needed

    def test_step_two_collects_privately_and_reads_back(self):
        step = text().split("## Step 2.")[1].split("## Step 3.")[0]
        for needed in ("privately", "never in a public chain message", "show it back", "units"):
            assert needed in step, needed
        assert "wait for confirmation" in step

    def test_step_three_waits_for_the_source(self):
        step = text().split("## Step 3.")[1].split("## Step 4.")[0]
        assert "has not been published yet" in step and "stop" in step
        assert "character by character" in step

    def test_step_four_hands_out_the_three_outputs_and_handles_the_failures(self):
        step = text().split("## Step 4.")[1].split("## When someone cannot")[0]
        for needed in (
            "for the organizer only",
            "--format dm",
            "--format group",
            "does not repair the split",
            "exited with code 3",
        ):
            assert needed in step, needed

    def test_quotes_the_rule_that_everything_comes_from_the_script(self):
        assert "Quote every name, chore, round and number" in text()
        assert "never choose or guess the random source" in text()

    def test_lists_the_guarantees_and_the_limits(self):
        section = text().split("## Guarantees and limits")[1].split("## When not to use")[0]
        for needed in (
            "Envy-free up to one chore (EF1)",
            "Not full envy-freeness",
            "Rankings only",
            "Not strategy-proof",
            "One week at a time",
            "Only chores",
            "refuses it (exit code 2)",
            "`cannot` lists the guarantee can fail",
            "Paying somebody to take a chore",
            "cannot check that it was fixed in advance",
        ):
            assert needed in section, needed

    def test_says_what_the_guarantee_is_about_in_plain_words(self):
        section = text().split("## Guarantees and limits")[1]
        assert "once one of their own chores is set aside" in section
        assert "a chore they rank later never costs less" in section
        assert "nobody has to say how much they mind anything" in section

    def test_does_not_overclaim(self):
        body = text().lower()
        for phrase in OVERCLAIMS:
            assert phrase.lower() not in body, phrase

    def test_points_to_the_other_skills_when_not_to_use(self):
        section = text().split("## When not to use")[1].split("## Reference")[0]
        for neighbour in ("slot-lottery", "bill-split"):
            assert neighbour in section

    def test_cites_the_chores_paper_in_both_versions(self):
        reference = text().split("## Reference")[1]
        assert "10.24963/ijcai.2019/8" in reference
        assert "10.1007/s10458-021-09532-8" in reference

    def test_every_option_it_mentions_exists(self):
        options = set(re.findall(r"(?<![\w-])(--[a-z][a-z-]*)", text()))
        assert {"--format", "--json", "--lang", "--demo", "--input"} <= options
        help_text = " ".join(run_script("--help").stdout.split())
        for option in options:
            assert option in help_text, option

    def test_every_example_it_mentions_exists(self):
        names = re.findall(r"examples/([A-Za-z0-9_.-]+\.json)", text())
        assert set(names) == {path.name for path in EXAMPLES.glob("*.json")}
        assert len(set(names)) == 5
        for name in names:
            assert (EXAMPLES / name).is_file(), name

    def test_the_input_fields_table_lists_every_field_the_script_accepts(self):
        table = text().split("The input fields:")[1].split("Options are listed")[0]
        fields = (
            *cs.TOP_FIELDS,
            *cs.BUNDLE_TOP_FIELDS,
            *(f"rules.{rule}" for rule in (*cs.RULE_FIELDS, *cs.BUNDLE_RULE_FIELDS)),
        )
        for field in fields:
            if field == "rules":
                continue  # described field by field
            assert f"`{field}`" in table, field

    def test_the_sizes_in_the_table_are_the_ones_the_script_enforces(self):
        table = text().split("The input fields:")[1].split("Options are listed")[0]
        assert f"2 to {cs.MAX_PEOPLE}" in table
        assert f"up to {cs.MAX_CHORES}" in table and f"{cs.MAX_TOTAL_UNITS} units in all" in table
        assert f"1 to {cs.MAX_WEEKS}" in table

    def test_the_exit_codes_in_the_text_are_the_script_ones(self):
        body = text()
        for needed in (
            "Exit code 2 means invalid input and the message names the field",
            "Exit code 3 means a chore is on every person's `cannot` list",
            "Exit code 1 means a failed self-test",
        ):
            assert needed in body, needed

    def test_the_text_about_the_cannot_example_is_what_the_script_finds(self):
        data = json.loads((EXAMPLES / "cannot_cook.json").read_text("utf-8"))
        plan = cs.compute(cs.parse_problem(data))
        chores = dict(plan.problem.chores)
        assert chores["做饭"] == 5 and sum(chores.values()) == 10
        body = text()
        assert "dinner is five of the ten chores a week" in body
        week = plan.weeks[0]
        assert sorted(len(week.bundles[p]) for p in week.order) == [1, 3, 3, 3]
        assert "the three others end up with more chores than that housemate" in body


def command_blocks() -> list[str]:
    """The fenced bash blocks except the one for Claude Code, whose file does not exist yet."""
    return [block for block in code_blocks("bash") if "--delete-input" not in block]


def documented_command(index: int) -> tuple[list[str], str]:
    """The command and the standard input of the index-th heredoc block of SKILL.md."""
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


def test_there_are_two_command_blocks_and_the_heredoc_one_runs_as_written():
    assert len(code_blocks("bash")) == 2
    assert len(command_blocks()) == 1
    words, stdin = documented_command(0)
    done = run_words(words, stdin)
    assert done.returncode == 0, done.stderr
    assert "| 1 | 阿明、小红、大刘 | 倒垃圾、做饭 | 洗碗、擦窗 | 拖地、刷厕所 |" in done.stdout


def test_the_documented_input_is_the_recorded_example():
    _, stdin = documented_command(0)
    assert json.loads(stdin) == json.loads((EXAMPLES / "three_roommates.json").read_text("utf-8"))


def test_the_message_quoted_in_the_skill_is_what_the_script_prints():
    step = text().split("## Step 4.")[1].split("## When someone cannot")[0]
    quoted = re.findall(r"\"(第 1 周，对[^\"]+)\"", step)
    assert len(quoted) == 1
    dm = run_script("--demo", "--format", "dm").stdout
    assert quoted[0] in dm


def test_the_json_block_of_plan_b_is_the_example_file_and_runs_as_written():
    blocks = code_blocks("json")
    assert len(blocks) == 1
    assert json.loads(blocks[0]) == json.loads(
        (EXAMPLES / "bundle_three_roommates.json").read_text("utf-8")
    )
    by_block = run_script("--input", "-", stdin=blocks[0])
    by_file = run_script("--input", str(EXAMPLES / "bundle_three_roommates.json"))
    assert by_block.returncode == 0, by_block.stderr
    assert by_block.stdout == by_file.stdout
    assert "| 大刘 | 做饭、刷厕所 | 2 / 2 | 70.00 | 收 25.00 | -45.00 |" in by_block.stdout


def test_the_certificate_quoted_for_plan_b_is_what_the_script_prints():
    step = text().split("## Step 4.")[1].split("## When someone cannot")[0]
    quoted = re.findall(r"\"(按你自己填的代价，你这份每周的折算是[^\"]+)\"", step)
    assert len(quoted) == 1
    dm = run_script("--demo-bundle", "--format", "dm").stdout
    assert quoted[0] in dm


def test_the_rules_message_for_plan_b_names_what_the_script_needs():
    step = text().split("## Step 1.")[1].split("## Step 2.")[0]
    message = step.split("Example for plan B (Chinese):")[1]
    for needed in (
        "分家务规则（包干加补偿，先定再收，发出后不改）",
        "上限",
        "总代价最小的分法",
        "加起来为 0 的补偿",
        "公用的钱罐",
        "不能小于 0，喜欢做的填 0",
        "公开随机源",
        "我先交",
        "不重分，也不改规则",
    ):
        assert needed in message, needed
    for needed in (
        "rules.plan",
        "`bundle_pay`",
        "The split.",
        "The money.",
        "What a cost is.",
        "Ties.",
    ):
        assert needed in step, needed


class TestPlanB:
    def section(self, start: str, end: str) -> str:
        return text().split(start)[1].split(end)[0]

    def test_the_intro_and_the_description_mention_both_plans(self):
        assert "Plan B" in text().split("## The script")[0]
        description = frontmatter()["description"]
        assert "second plan" in description and "fixed bundle" in description

    def test_step_two_collects_costs_and_caps_and_reads_them_back(self):
        step = self.section("## Step 2.", "## Step 3.")
        for needed in ("plan B", "`costs` and `caps`", "no `likes` in plan B", "cost 0"):
            assert needed in step, needed

    def test_step_three_does_not_wait_for_a_source_that_plan_b_did_not_name(self):
        step = self.section("## Step 3.", "## Step 4.")
        assert "In plan B the source is optional" in step and "order of the names" in step

    def test_step_four_says_what_to_say_about_the_payments(self):
        step = self.section("## Step 4.", "## When someone cannot")
        for needed in (
            "common pot",
            "Do not work out who pays whom",
            "add up to zero",
            "nobody's costs",
            "exited with code 3 in plan B",
        ):
            assert needed in step, needed

    def test_the_guarantees_of_plan_b_and_their_limits_are_listed(self):
        section = self.section("## Guarantees and limits", "## When not to use")
        for needed in (
            "Plan A, taking turns:",
            "Plan B, bundles with compensation:",
            "Cheapest split.",
            "No envy by their own costs.",
            "one cent of envy can remain",
            "The worst-off person.",
            "A split that costs more sometimes leaves the worst-off person better off",
            "no split does better for the worst-off person",
            "Not strategy-proof. A person who knows the other costs",
            "Costs as entered.",
            "One typical week, repeated.",
            "Plan A moves no money",
            "What an outside cleaner costs is not calculated by either plan",
        ):
            assert needed in section, needed

    def test_it_cites_the_payment_rule_it_borrows(self):
        reference = text().split("## Reference")[1]
        assert "10.1145/3131361" in reference and "total rent of zero" in reference

    def test_it_does_not_say_that_plan_b_is_best_for_everybody(self):
        body = text().lower()
        for phrase in ("best for everybody", "fair for everybody", "everyone gets the best"):
            assert phrase not in body, phrase


def test_the_rules_message_in_the_skill_names_the_same_things_the_script_needs():
    step = text().split("## Step 1.")[1].split("## Step 2.")[0]
    message = step.split("Example (Chinese):")[1]
    for needed in ("洗碗每周 3 次就是 3 件", "公开开奖的号码", "从最不讨厌到最讨厌", "先排 4 周"):
        assert needed in message, needed


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

    @pytest.mark.parametrize(
        "path", sorted((TESTS_DIR / "golden").glob("*.txt")), ids=lambda p: p.name
    )
    def test_the_stored_outputs_contain_no_machine_paths_or_addresses(self, path):
        content = path.read_text(encoding="utf-8")
        for what in ("an absolute path", "an e-mail address", "a credential word"):
            found = LEAKS[what].search(content)
            assert found is None, f"{path.name} contains {what}: {found.group(0)!r}"

    def test_the_examples_are_marked_as_made_up(self):
        for path in sorted(EXAMPLES.glob("*.json")):
            assert "虚构示例" in path.read_text(encoding="utf-8"), path.name

    def test_the_script_does_not_write_or_reach_out(self):
        source = SCRIPT.read_text(encoding="utf-8")
        for forbidden in ("import random", "subprocess", "socket", "urllib", "open(", "eval("):
            assert forbidden not in source, forbidden


class TestTheorySection:
    def content(self) -> str:
        return doc.section("chore-split")

    def test_the_section_holds_no_machine_paths_addresses_or_credentials(self):
        for what, pattern in LEAKS.items():
            text = doc.prose(self.content()) if what == "a credential word" else self.content()
            found = pattern.search(text)
            assert found is None, f"THEORY.md contains {what}: {found.group(0)!r}"

    def test_it_has_the_sections_the_theory_file_expects(self):
        content = self.content()
        assert content.startswith("## chore-split")
        for heading in ("### Guarantees", "### Not guaranteed", "### Method"):
            assert heading in content

    def test_it_cites_the_chores_paper_in_both_versions(self):
        references = doc.section("References")
        assert "10.24963/ijcai.2019/8" in references
        assert "10.1007/s10458-021-09532-8" in references
        for name in ("Aziz", "Caragiannis", "Igarashi", "Walsh"):
            assert name in references
        assert "Aziz et al. (2019, 2022)" in self.content()

    def test_every_test_named_in_the_section_exists(self):
        named = {ref.shown() for ref in doc.cited(self.content())}
        assert len(named) >= 20, "the section should name the tests that check its guarantees"
        assert doc.missing_tests(self.content()) == []

    def test_it_writes_out_both_cases_of_the_ef1_argument(self):
        content = self.content()
        for needed in (
            "Case 1, a smaller than b",
            "Case 2, a larger than b",
            "If k = l + 1",
            "If l = k + 1",
            "If l = k,",
            "no cost is negative",
            "EF1 and not more",
        ):
            assert needed in content, needed

    def test_it_states_what_is_not_guaranteed(self):
        section = doc.subsection("chore-split", "Not guaranteed")
        for needed in (
            "Strategy-proofness",
            "Equal burden",
            "Several weeks together",
            "Tasks that somebody likes",
            "Chores that somebody cannot do",
            "Paying somebody to take a chore",
            "fixed in advance",
        ):
            assert needed in section, needed

    def test_it_has_no_semicolons_or_dashes_in_its_prose(self):
        prose = re.sub(r"`[^`]*`", "", self.content())
        assert ";" not in prose and "—" not in prose and "–" not in prose
