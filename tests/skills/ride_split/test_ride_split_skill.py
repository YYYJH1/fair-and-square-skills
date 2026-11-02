"""SKILL.md, the examples and the other public text of the ride-split skill."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import ClassVar

import pytest
import theory_doc as doc
from ride_support import EXAMPLES, SCRIPT, SKILL_DIR, run_script

SKILL_MD = SKILL_DIR / "SKILL.md"
TRIGGERS = [
    "拼车怎么分钱",
    "打车 AA",
    "顺路下车怎么算",
    "carpool split",
    "split a taxi fare",
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
        assert fields["name"] == "ride-split" == SKILL_DIR.name
        assert fields["license"] == "MIT"

    def test_allowed_tools_is_the_one_script(self):
        assert (
            frontmatter()["allowed-tools"]
            == "Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/ride_split.py *)"
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
        assert "bill-split" in description and "rent-split" in description


class TestBody:
    def test_under_500_lines(self):
        assert len(text().splitlines()) < 500

    def test_calls_the_script_through_the_skill_dir_variable_with_a_fallback(self):
        body = text()
        assert "python3 ${CLAUDE_SKILL_DIR}/scripts/ride_split.py" in body
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

    def test_quotes_the_rule_that_amounts_come_from_the_script(self):
        assert "Quote every amount" in text()

    def test_states_the_size_limits_and_the_core_caveat(self):
        body = text()
        assert "2 to 12 riders" in body and "2 to 6" in body
        assert "up to 4 riders" in body
        assert "can fall outside the core, and the core can be empty" in body

    def test_lists_the_guarantees(self):
        body = text()
        for word in ("add up to the fare", "interchangeable", "adds nothing", "additivity", "core"):
            assert word in body

    def test_points_to_the_other_skills_when_not_to_use(self):
        section = text().split("## When not to use")[1].split("## Reference")[0]
        assert "bill-split" in section and "rent-split" in section

    def test_every_option_it_mentions_exists(self):
        options = set(re.findall(r"(?<![\w-])(--[a-z][a-z-]*)", text()))
        assert {"--format", "--audit", "--json", "--demo", "--lang", "--input"} <= options
        help_text = run_script("--help").stdout
        for option in options:
            assert option in help_text, option

    def test_every_example_it_mentions_exists(self):
        for name in re.findall(r"examples/([A-Za-z0-9_.-]+\.json)", text()):
            assert (EXAMPLES / name).is_file(), name

    def test_every_example_file_is_listed_in_one_sentence(self):
        sentence = text().split("The `examples/` folder holds")[1].split("\n")[0]
        listed = set(re.findall(r"`examples/([A-Za-z0-9_.-]+\.json)`", sentence))
        assert listed == {path.name for path in EXAMPLES.glob("*.json")}
        assert "four complete inputs" in sentence

    def test_the_input_fields_table_lists_every_field_the_script_accepts(self):
        import ride_split as rs

        table = text().split("| Field | Meaning |")[1].split("\n\n")[0]
        fields = {*rs.COMMON_FIELDS, *(f for names in rs.MODE_FIELDS.values() for f in names)}
        for field in sorted(fields):
            if field == "rules":
                field = "rules.method"  # described field by field
            assert f"`{field}`" in table, field


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
    assert "| 小周 | 14.00 | 3.50 | 10.50 | 75% |" in done.stdout
    assert "| 老陈 | 63.00 | 37.00 | 26.00 | 41% |" in done.stdout


def test_the_audit_input_shown_in_the_skill_is_valid():
    match = re.search(r'add `("audit": \{.*?\}\})` to the input', text())
    assert match, "no audit input in SKILL.md"
    audit = json.loads("{" + match.group(1) + "}")["audit"]
    base = json.loads((EXAMPLES / "meter_four_riders.json").read_text(encoding="utf-8"))
    data = {**base, "audit": audit}
    done = run_script("--input", "-", "--audit", "--json", stdin=json.dumps(data))
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["result"]["audit"]["violation_count"] == 3


def test_the_message_quoted_in_the_skill_is_what_the_script_prints():
    quoted = re.search(r"for example: \"([^\"]+)\"", text())
    assert quoted, "no quoted private message in SKILL.md"
    assert quoted.group(1) in run_script("--demo", "--format", "dm").stdout


def test_the_distance_trick_for_private_cars_works():
    data = {
        "mode": "estimates",
        "riders": ["A", "B", "C"],
        "solo_estimate": [10, 25, 40],
        "actual_total": 60,
    }
    done = run_script("--input", "-", "--json", stdin=json.dumps(data))
    assert done.returncode == 0, done.stderr
    shares = json.loads(done.stdout)["result"]["share_cents"]
    # solo prices 10, 25, 40 scaled to 60 are 15, 37.50 and 60: stretches 15 / 3, 22.50 / 2, 22.50
    assert shares == {"A": "5.00", "B": "16.25", "C": "38.75"}


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

    def test_the_theory_section_holds_no_machine_paths_addresses_or_credentials(self):
        section = doc.section("ride-split")
        for what, pattern in LEAKS.items():
            text = doc.prose(section) if what == "a credential word" else section
            found = pattern.search(text)
            assert found is None, f"THEORY.md contains {what}: {found.group(0)!r}"

    def test_the_theory_section_exists_and_cites_the_papers(self):
        content = doc.section("ride-split")
        references = doc.section("References")
        assert "10.1287/mnsc.20.3.370" in references
        assert "10.1007/bf01753431" in references
        assert content.startswith("## ride-split")
        for heading in ("### Guarantees", "### Not guaranteed", "### Method"):
            assert heading in content
        for citation in ("Littlechild and Owen 1973", "Shapley 1971"):
            assert citation in content, citation

    def test_every_test_named_in_the_theory_section_exists(self):
        content = doc.section("ride-split")
        assert doc.cited(content), "the section should name the tests that check its guarantees"
        assert doc.missing_tests(content) == []
