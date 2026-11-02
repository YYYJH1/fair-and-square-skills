"""SKILL.md, the examples and the other public text of the group-vote skill."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import ClassVar

import fsq_core as fc
import group_vote as gv
import pytest
import theory_doc as doc
from vote_support import EXAMPLES, SCRIPT, SKILL_DIR, run_json, run_script

SKILL_MD = SKILL_DIR / "SKILL.md"
TRIGGERS = [
    "团建投票",
    "投票选去哪",
    "几个选项怎么定",
    "排序投票",
    "ranked choice",
    "pick a restaurant by vote",
]
# Things that must never reach a public file of this skill: machine paths, e-mail addresses
# and credential words. Names of private projects are checked by the release checklist, not here.
LEAKS = {
    "an absolute path": re.compile(r"(?<![\w./-])/(?:data|home|tmp|Users|var|mnt|root)/\S+"),
    "an e-mail address": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "a credential word": re.compile(r"api[_-]?key|password|secret|token", re.IGNORECASE),
}


def text() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def frontmatter() -> dict:
    block = text().split("---")[1]
    fields = {}
    for line in block.strip().splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


class TestFrontmatter:
    def test_only_the_four_frontmatter_fields(self):
        assert sorted(frontmatter()) == ["allowed-tools", "description", "license", "name"]

    def test_name_and_license(self):
        fields = frontmatter()
        assert fields["name"] == "group-vote" == SKILL_DIR.name
        assert fields["license"] == "MIT"

    def test_allowed_tools_is_the_one_script(self):
        assert (
            frontmatter()["allowed-tools"]
            == "Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/group_vote.py *)"
        )

    def test_description_limits(self):
        description = frontmatter()["description"]
        assert len(description) <= 1024
        assert "<" not in description and ">" not in description
        assert ": " not in description, "a colon and a space would need quoting in YAML"

    @pytest.mark.parametrize("trigger", TRIGGERS)
    def test_description_has_the_trigger_phrases(self, trigger):
        assert trigger in frontmatter()["description"]

    def test_description_points_to_the_neighbours(self):
        description = frontmatter()["description"]
        assert "slot-lottery" in description
        assert "bill-split" in description and "rent-split" in description

    def test_description_names_every_rule_the_script_offers(self):
        description = frontmatter()["description"].lower()
        for word in ("plurality", "runoff", "borda", "condorcet", "schulze", "approval", "kemeny"):
            assert word in description, word


class TestBody:
    def test_under_500_lines(self):
        assert len(text().splitlines()) < 500

    def test_calls_the_script_through_the_skill_dir_variable_with_a_fallback(self):
        body = text()
        assert "python3 ${CLAUDE_SKILL_DIR}/scripts/group_vote.py" in body
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

    def test_quotes_the_rule_that_everything_comes_from_the_script(self):
        assert "Quote every winner, count and name exactly as the script prints it." in text()
        assert "Do not count, tally or break a tie yourself." in text()

    def test_step_one_fixes_the_rule_the_tie_break_and_partial_ballots(self):
        step = text().split("## Step 1.")[1].split("## Step 2.")[0]
        for word in ("counting rule", "tie-break", "random source", "ranking may stop early"):
            assert word in step, word
        assert "organizer goes first" in step
        assert "does not vote on the rule after seeing results" in step

    def test_step_one_has_a_rules_message_in_chinese(self):
        step = text().split("## Step 1.")[1].split("## Step 2.")[0]
        assert "> 团建投票规则（先定再收）：" in step
        assert "没排的算并列最后" in step
        assert "平票" in step and "开奖号码" in step
        assert "我先交" in step

    def test_step_two_collects_ballots_privately_and_reads_them_back(self):
        step = text().split("## Step 2.")[1].split("## Step 3.")[0]
        assert "never in the group" in step
        assert "anonymous questionnaire" in step
        assert "wait for confirmation before running" in step

    def test_step_three_explains_exit_code_3(self):
        step = text().split("## Step 3.")[1].split("## Step 4.")[0]
        assert "exits with code 3" in step and "public random source" in step
        assert "Do not choose the winner" in step

    def test_the_limits_of_the_rules_are_stated_in_neutral_words(self):
        section = text().split("## Guarantees and limits")[1].split("## When not to use")[0]
        assert "Condorcet winner" in section and "monotonic" in section
        assert "independent of clones" in section
        assert "Instant runoff and the two-round runoff are not monotonic" in section
        assert "Borda is sensitive to clones" in section
        assert "Gibbard, Satterthwaite" in section
        assert "strategic voting" in section
        assert "every ranking rule that can elect each option" in section
        for loaded in ("fair", "unfair", "rigged", "bad rule", "best rule"):
            assert loaded not in section.lower().replace("unfairly", ""), loaded

    def test_points_to_the_other_skills_when_not_to_use(self):
        section = text().split("## When not to use")[1].split("## Reference")[0]
        assert "slot-lottery" in section
        assert "bill-split" in section and "rent-split" in section and "ride-split" in section

    def test_every_option_it_mentions_exists(self):
        options = set(re.findall(r"(?<![\w-])(--[a-z][a-z-]*)", text()))
        assert {
            "--format",
            "--json",
            "--demo",
            "--lang",
            "--input",
            "--remove",
            "--all-rules",
        } <= options
        help_text = run_script("--help").stdout
        for option in options:
            assert option in help_text, option

    def test_every_example_it_mentions_exists(self):
        names = re.findall(r"examples/([A-Za-z0-9_.-]+\.json)", text())
        assert len(set(names)) == 4
        for name in names:
            assert (EXAMPLES / name).is_file(), name

    def test_every_input_field_in_the_table_is_one_the_script_reads(self):
        rows = re.findall(r"^\| `([a-z_.]+)` \|", text(), flags=re.MULTILINE)
        allowed = (
            set(gv.TOP_FIELDS)
            | {f"rules.{k}" for k in gv.RULE_FIELDS}
            | {"rules.tie_break.random_source"}
        )
        assert rows, "no field table"
        for row in rows:
            assert row in allowed, row
        assert {"options", "ballots", "approvals", "approval_counts", "csv", "rules.method"} <= set(
            rows
        )

    def test_every_method_in_the_text_is_one_the_script_knows(self):
        words = set(
            re.findall(r"`(plurality|runoff|irv|borda|condorcet|schulze|approval|kemeny)`", text())
        )
        assert words == set(gv.METHODS)

    def test_the_numbers_quoted_in_the_text_are_the_scripts(self):
        body = text()
        out = fc.envelope(gv.solve(fc.parse_input(gv.DEMO_JSON), all_rules=True))["result"][
            "per_rule_winners"
        ]
        claim = (
            f"plurality pick {out['plurality']}, a two-round runoff {out['runoff']}, instant runoff "
            f"{out['irv']}, Borda {out['borda']} and the Condorcet method {out['condorcet']}"
        )
        assert claim in body
        assert "27 ballots" in body
        removal = fc.envelope(
            gv.solve(fc.parse_input(gv.DEMO_JSON), all_rules=True, remove=["剧本杀"])
        )["result"]["per_rule_winners"]
        assert set(removal.values()) == {"爬山"}
        assert (
            "removing 剧本杀 or 密室逃脱 makes all seven rules of `--all-rules` pick 爬山" in body
        )


def documented_command() -> tuple[list[str], str]:
    """The command and the standard input of the first heredoc block in SKILL.md."""
    blocks = re.findall(r"```bash\n(python3 .*?)\n```", text(), flags=re.DOTALL)
    block = next((b for b in blocks if "<<'EOF'" in b), None)
    assert block, "no heredoc block"
    command, _, rest = block.partition("<<'EOF'\n")
    stdin = rest.rsplit("\nEOF", 1)[0]
    words = shlex.split(command.replace("${CLAUDE_SKILL_DIR}", str(SKILL_DIR)))
    return words, stdin


def test_the_documented_command_runs_as_written():
    words, stdin = documented_command()
    assert words[0] == "python3" and Path(words[1]) == SCRIPT
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    done = subprocess.run(
        [sys.executable, "-B", "-S", *words[1:]],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert "| 赢家 | 火锅 |" in done.stdout
    assert "| 火锅 | 8 | - | 9 |" in done.stdout
    assert "孔多塞赢家：火锅，在两两比较中胜过其他所有选项。" in done.stdout


def test_the_documented_input_is_valid_json_with_the_documented_rules():
    _, stdin = documented_command()
    data = json.loads(stdin)
    assert data["rules"]["method"] == "condorcet"
    assert data["rules"]["tie_break"]["random_source"]


def test_the_rules_message_example_matches_what_the_script_accepts():
    """The method, the partial policy and the tie-break of the Chinese message are all valid."""
    step = text().split("## Step 1.")[1].split("## Step 2.")[0]
    assert "孔多塞法" in step
    data = fc.parse_input((EXAMPLES / "team_outing_27.json").read_text(encoding="utf-8"))
    data["rules"]["partial"] = "tie_last"
    data["ballots"] = [{"count": 3, "ranking": ["爬山", "火锅"]}, *data["ballots"]]
    out = fc.envelope(gv.solve(data))
    assert out["inputs_echo"]["rules"]["partial"] == "tie_last"


class TestExamplesFolder:
    NAMES: ClassVar[list] = [
        "team_outing_27.json",
        "cycle_three.json",
        "poll_counts.json",
        "questionnaire.csv.json",
    ]

    def test_the_folder_holds_exactly_the_four_examples(self):
        assert sorted(p.name for p in EXAMPLES.iterdir()) == sorted(self.NAMES)

    @pytest.mark.parametrize("name", NAMES)
    def test_each_example_is_a_plain_json_file_with_the_rules_in_it(self, name):
        data = json.loads((EXAMPLES / name).read_text(encoding="utf-8"))
        assert data["rules"]["method"] in gv.METHODS
        assert data["rules"]["tie_break"]["random_source"].startswith("（虚构示例）")

    @pytest.mark.parametrize("name", NAMES)
    def test_each_example_uses_made_up_names_and_text(self, name):
        content = (EXAMPLES / name).read_text(encoding="utf-8")
        assert "虚构" in content

    def test_the_csv_example_keeps_the_table_as_text(self):
        data = json.loads((EXAMPLES / "questionnaire.csv.json").read_text(encoding="utf-8"))
        assert isinstance(data["csv"], str) and data["csv"].count("\n") == 12

    @pytest.mark.parametrize("name", NAMES)
    def test_each_example_runs_in_both_languages(self, name):
        for lang in ("zh", "en"):
            done = run_script("--input", str(EXAMPLES / name), "--lang", lang)
            assert done.returncode == 0, done.stderr

    def test_an_example_can_be_piped_in_the_way_the_skill_says(self):
        data = json.loads((EXAMPLES / "cycle_three.json").read_text(encoding="utf-8"))
        done = run_json(data, "--format", "group")
        assert done.returncode == 0, done.stderr
        assert "烧烤" in done.stdout


class TestPublicHygiene:
    FILES: ClassVar[list] = [
        SKILL_MD,
        SCRIPT,
        *sorted(EXAMPLES.glob("*.json")),
    ]
    TEST_FILES: ClassVar[list] = sorted(Path(__file__).parent.glob("*.py"))

    @pytest.mark.parametrize("path", FILES, ids=lambda path: path.name)
    def test_no_machine_paths_addresses_or_credentials(self, path):
        content = path.read_text(encoding="utf-8")
        for what, pattern in LEAKS.items():
            found = pattern.search(content)
            assert found is None, f"{path.name} contains {what}: {found.group(0)!r}"

    @pytest.mark.parametrize("path", TEST_FILES, ids=lambda path: path.name)
    def test_the_tests_hold_no_machine_paths_or_addresses(self, path):
        content = path.read_text(encoding="utf-8")
        for what in ("an absolute path", "an e-mail address"):
            found = LEAKS[what].search(content)
            assert found is None, f"{path.name} contains {what}: {found.group(0)!r}"

    def test_the_script_has_no_invisible_characters(self):
        content = SCRIPT.read_text(encoding="utf-8")
        assert not [c for c in content if c in "\ufeff\u2028\u2029\u200b\u00a0"]

    def test_the_theory_section_holds_no_machine_paths_addresses_or_credentials(self):
        section = doc.section("group-vote")
        for what, pattern in LEAKS.items():
            text = doc.prose(section) if what == "a credential word" else section
            found = pattern.search(text)
            assert found is None, f"THEORY.md contains {what}: {found.group(0)!r}"

    def test_the_public_prose_has_no_semicolons_or_dashes(self):
        texts = {
            "THEORY.md": doc.section("group-vote"),
            SKILL_MD.name: SKILL_MD.read_text(encoding="utf-8"),
        }
        for name, content in texts.items():
            prose = doc.prose(content)
            for mark in (";", "\u2014", "\u2013", " -- "):
                assert mark not in prose, f"{name} contains {mark!r}"


class TestTheorySection:
    def test_the_section_exists_and_the_papers_are_in_the_reference_list(self):
        content = doc.section("group-vote")
        assert content.startswith("## group-vote")
        for heading in ("### Guarantees", "### Not guaranteed", "### Method"):
            assert heading in content
        references = doc.section("References")
        for doi in (
            "10.1007/s00355-010-0475-4",
            "10.2307/1914083",
            "10.1016/0022-0531(75)90050-2",
            "10.1137/0135023",
            "10.2307/2110496",
            "10.1007/bf00433944",
        ):
            assert f"doi:{doi}" in references, doi

    def test_every_test_named_in_the_section_exists(self):
        content = doc.section("group-vote")
        assert len(doc.cited(content)) > 25, "the section should name the tests that check it"
        assert doc.missing_tests(content) == []

    def test_the_notes_say_what_the_references_of_the_section_are_cited_for(self):
        notes = doc.section("References").split("Notes on the references")[1]
        for needed in (
            "Young and Levenglick (1978) is cited for the rule",
            "Doron and Kronick (1977) shows",
            "Tideman (1987) defines independence of clones",
        ):
            assert needed in notes, needed

    def test_the_skill_cites_the_same_papers_it_relies_on(self):
        body = text()
        for doi in ("10.1007/s00355-010-0475-4", "10.2307/1914083", "10.1016/0022-0531(75)90050-2"):
            assert f"doi:{doi}" in body
