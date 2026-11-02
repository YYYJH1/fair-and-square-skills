"""The two ways SKILL.md tells an agent to give a skill its input.

In Claude Code the agent writes the input to a file and runs the script with ``--delete-input``.
A heredoc whose body holds braces and quotes needs the user's approval there, and every input of
these skills does. Anywhere else the agent pipes the input through a heredoc. All eight skills must
document both ways in the same words, both commands must run as written, they must print the same
text, and the file route must match the ``allowed-tools`` line, which does not change.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "plugin" / "skills"
SCRIPTS = {
    "rent-split": "rent_split.py",
    "bill-split": "bill_split.py",
    "ride-split": "ride_split.py",
    "slot-lottery": "slot_lottery.py",
    "group-vote": "group_vote.py",
    "chore-split": "chore_split.py",
    "gift-exchange": "gift_exchange.py",
    "stuff-split": "stuff_split.py",
}
PLACEHOLDER = "<input-file>"
HEREDOC_START = "<<'EOF'\n"
# A fenced block that starts at the beginning of a line. Indented blocks are not looked at.
FENCE = re.compile(r"^```[A-Za-z]*\n(.*?)\n```$", re.DOTALL | re.MULTILINE)
ALLOWED_TOOLS = re.compile(r"^allowed-tools: Bash\((.+) \*\)$", re.MULTILINE)
PHRASES = (
    "In Claude Code, give the script the input as a file and let the script delete it.",
    "heredoc body holds both braces and quotes",
    "with the Write tool to a new file in the session's scratchpad directory",
    "in a temporary directory if the session has none",
    "The script deletes the file as soon as it has read it, also when it then rejects the input",
    "never one the user already had, because the script deletes it",
    "If a run stops before it reads the file",
    "add `--delete-input` to the last run only",
    "In Codex and other tools, pass the input on standard input through a heredoc",
    "so that no input file is created",
)


def text_of(skill: str) -> str:
    return (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")


def command_blocks(skill: str) -> list[str]:
    return FENCE.findall(text_of(skill))


def file_route(skill: str) -> str:
    found = [block for block in command_blocks(skill) if "--delete-input" in block]
    assert len(found) == 1, found
    return found[0]


def heredoc_example(skill: str) -> tuple[str, str]:
    """The command (up to the heredoc) and the JSON body of the first heredoc block."""
    block = next(block for block in command_blocks(skill) if HEREDOC_START in block)
    command, _, rest = block.partition(HEREDOC_START)
    return command.strip(), rest.rsplit("\nEOF", 1)[0]


def words(command: str, skill: str) -> list[str]:
    return shlex.split(command.replace("${CLAUDE_SKILL_DIR}", str(SKILLS / skill)))


def run(skill: str, command_words: list[str], stdin: str = "") -> subprocess.CompletedProcess[str]:
    script = SKILLS / skill / "scripts" / SCRIPTS[skill]
    assert command_words[0] == "python3" and Path(command_words[1]) == script, command_words
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-B", "-S", *command_words[1:]],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=120,
        check=False,
    )


@pytest.mark.parametrize("skill", sorted(SCRIPTS))
class TestEverySkillDocumentsBothRoutes:
    def test_the_file_route_is_one_command_in_the_form_the_allowed_tools_line_covers(self, skill):
        route = file_route(skill)
        assert route == (
            f"python3 ${{CLAUDE_SKILL_DIR}}/scripts/{SCRIPTS[skill]} "
            f"--format md --input {PLACEHOLDER} --delete-input"
        )
        prefix = ALLOWED_TOOLS.search(text_of(skill))
        assert prefix is not None
        assert prefix.group(1) == f"python3 ${{CLAUDE_SKILL_DIR}}/scripts/{SCRIPTS[skill]}"
        assert route.startswith(prefix.group(1) + " ")

    def test_the_heredoc_route_stays_for_other_tools(self, skill):
        command, body = heredoc_example(skill)
        assert command == (
            f"python3 ${{CLAUDE_SKILL_DIR}}/scripts/{SCRIPTS[skill]} --format md --input -"
        )
        assert body.lstrip().startswith("{")

    def test_the_file_route_comes_first_and_the_text_gives_the_reason_and_the_cautions(self, skill):
        body = text_of(skill)
        section = body.split("## The script")[1].split("\n## ")[0]
        for phrase in PHRASES:
            assert phrase in section, phrase
        assert section.index("--delete-input`:") < section.index("In Codex and other tools")

    def test_nothing_says_that_the_input_is_never_written_to_disk(self, skill):
        assert "written to disk" not in text_of(skill)

    def test_both_commands_run_as_written_and_print_the_same_text(self, skill, tmp_path):
        command, body = heredoc_example(skill)
        by_heredoc = run(skill, words(command, skill), body)
        path = tmp_path / "input.json"
        path.write_text(body, encoding="utf-8")
        route = file_route(skill).replace(PLACEHOLDER, shlex.quote(str(path)))
        by_file = run(skill, words(route, skill))
        assert by_heredoc.returncode == by_file.returncode == 0, by_file.stderr
        assert by_file.stdout == by_heredoc.stdout != ""
        assert by_file.stderr == by_heredoc.stderr == ""
        assert not path.exists()
