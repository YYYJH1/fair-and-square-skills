"""SKILL.md of stuff-split: frontmatter, the steps, the commands, and the claims.

SKILL.md is part of the product, so its rules are tested like code: its frontmatter, its length,
that every command in it runs, and that what it says about the script is what the script does.
The two ways to give the input are checked for all skills in tests/test_skill_input_routes.py.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import stuff_split as ss
from stuff_split_support import EXAMPLES, REPO, SCRIPT, SKILL, SKILL_MD, run_script

SCRIPT_NAME = "stuff_split.py"
COMMAND_START = f"python3 ${{CLAUDE_SKILL_DIR}}/scripts/{SCRIPT_NAME}"
TEXT = SKILL_MD.read_text(encoding="utf-8")
HEREDOC_START = "<<'EOF'\n"
FENCE = re.compile(r"^```[A-Za-z]*\n(.*?)\n```$", re.DOTALL | re.MULTILINE)
TRIGGERS = [
    "毕业分家当",
    "搬家分东西",
    "合租散伙东西怎么分",
    "遗产怎么分",
    "divide our stuff fairly",
    "split an inheritance",
    "who gets the sofa",
    "roommates moving out",
]
OVERCLAIMS = [
    "nobody can cheat",
    "cannot be rigged",
    "tamper-proof",
    "impossible to cheat",
    "everybody envy-free",
    "perfectly fair",
    "absolutely fair",
    "谁也做不了手脚",
    "绝对公平",
    "完全公平",
]
# Words that would rank one rule above another in the text.
RANKING_WORDS = ("stronger", "better than", "best rule", "superior", "weaker", "更强", "更好的方案")


def load_validator():
    spec = importlib.util.spec_from_file_location(
        "validate_plugin_for_stuff_split", REPO / "tools" / "validate_plugin.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


vp = load_validator()


def frontmatter():
    parts = vp.split_frontmatter(TEXT)
    assert parts is not None
    return vp.parse_frontmatter(parts[0])


def blocks():
    return FENCE.findall(TEXT)


def bash_blocks():
    return re.findall(r"^```bash\n(.*?)^```$", TEXT, re.MULTILINE | re.DOTALL)


def words(command):
    return shlex.split(command.replace("${CLAUDE_SKILL_DIR}", str(SKILL)))


def run_words(command_words, stdin=""):
    assert command_words[0] == "python3" and Path(command_words[1]) == SCRIPT, command_words
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


# --------------------------------------------------------------------------------------
# Frontmatter
# --------------------------------------------------------------------------------------


def test_the_repository_validator_accepts_the_skill():
    assert vp.check_skill(SKILL, REPO) == []


def test_frontmatter_uses_only_fields_of_the_open_specification():
    fields = frontmatter()
    assert set(fields) == {"name", "description", "license", "allowed-tools"}
    assert fields["name"] == "stuff-split" == SKILL.name
    assert fields["license"] == "MIT"
    assert fields["allowed-tools"] == f"Bash({COMMAND_START} *)"


def test_the_description_is_plain_yaml_of_at_most_1024_characters():
    description = frontmatter()["description"]
    assert len(description) <= 1024
    assert "<" not in description and ">" not in description
    assert ": " not in description, "a colon and a space would need quoting in YAML"
    assert " #" not in description
    assert description == description.strip() and "\n" not in description


@pytest.mark.parametrize("trigger", TRIGGERS)
def test_the_description_has_the_trigger_phrases(trigger):
    assert trigger in frontmatter()["description"]


def test_the_description_says_what_it_does_when_to_use_it_and_what_it_gives():
    description = frontmatter()["description"]
    assert description.startswith("Use whenever")
    for needed in (
        "bundled script",
        "private money value",
        "Knaster's sealed bids",
        "envy-free up to one item",
        "Pareto efficient",
        "one checkable line per person",
        "private messages",
        "group summary",
    ):
        assert needed in description, needed


def test_the_description_points_to_the_neighbours():
    description = frontmatter()["description"]
    for neighbour in ("rent-split", "bill-split", "chore-split", "slot-lottery"):
        assert neighbour in description


# --------------------------------------------------------------------------------------
# The commands
# --------------------------------------------------------------------------------------


def heredoc_example():
    block = next(block for block in blocks() if HEREDOC_START in block)
    command, _, rest = block.partition(HEREDOC_START)
    return command.strip(), rest.rsplit("\nEOF", 1)[0]


def test_the_documented_input_is_the_recorded_example_and_the_demo():
    _, body = heredoc_example()
    recorded = json.loads((EXAMPLES / "three_roommates.json").read_text(encoding="utf-8"))
    assert json.loads(body) == recorded == json.loads(ss.DEMO_JSON)


def test_the_demo_command_in_skill_md_runs(tmp_path):
    block = next(block for block in bash_blocks() if "--demo" in block)
    assert block.strip() == f"{COMMAND_START} --demo"
    done = run_words(words(block.strip()))
    assert done.returncode == 0 and "钢琴的例子" in done.stdout


def test_every_bash_block_starts_with_the_allowed_command():
    assert len(bash_blocks()) == 3
    for block in bash_blocks():
        assert block.startswith(COMMAND_START), block.splitlines()[0]


# --------------------------------------------------------------------------------------
# The body
# --------------------------------------------------------------------------------------


def test_the_body_is_short_and_in_english_apart_from_the_quoted_chinese():
    assert len(TEXT.splitlines()) < 500
    body = TEXT.split("---", 2)[2]
    prose = re.sub(r"```.*?```", "", body, flags=re.DOTALL)
    prose = re.sub(r"^>.*$", "", prose, flags=re.MULTILINE)  # the Chinese rules message
    chinese = "".join(re.findall(r"[一-鿿]+", prose))
    assert len(chinese) < 120, len(chinese)
    assert len(re.findall(r"[A-Za-z]+", prose)) > 900


def test_the_script_is_called_through_the_skill_dir_variable_with_a_fallback_sentence():
    assert f"${{CLAUDE_SKILL_DIR}}/scripts/{SCRIPT_NAME}" in TEXT
    assert "If that variable was not replaced, the script is in the `scripts/` folder" in TEXT


def test_each_step_says_when_it_is_done():
    steps = re.findall(r"^## Step \d\. .*$", TEXT, flags=re.MULTILINE)
    assert len(steps) == 4
    assert TEXT.count("Done when") == 4


def test_the_required_sections_are_present():
    headings = re.findall(r"^## (.*)$", TEXT, re.MULTILINE)
    for wanted in (
        "The three rules",
        "The script",
        "Guarantees and limits",
        "When not to use",
        "Reference",
    ):
        assert wanted in headings, wanted
    assert "Step 3. Run" in " ".join(headings)


def test_the_text_states_the_ban_on_doing_arithmetic_and_on_guessing_the_source():
    assert "Quote every name, item, amount and count exactly as the script prints it" in TEXT
    assert "Do not compute, compare or adjust anything yourself" in TEXT
    assert "never choose or guess the random source" in TEXT


def test_step_one_fixes_the_rules_in_a_chinese_message():
    step = TEXT.split("## Step 1.")[1].split("## Step 2.")[0]
    for needed in (
        "Ask first whether money can change hands",
        "Nobody should be told that one rule is simply better",
        "organizer goes first",
        "public random source",
        "no new vote on the rule",
        "分家当规则（先定再收，发出后不改）",
        "A 无嫉妒加转账",
        "B Knaster 暗标法",
        "C 不转钱",
        "我先交",
        "不再换分法，也不重新分",
    ):
        assert needed in step, needed


def test_step_two_collects_privately_and_reads_back():
    step = TEXT.split("## Step 2.")[1].split("## Step 3.")[0]
    for needed in ("privately", "never in a public chain message", "show it back", "wait for"):
        assert needed in step, needed
    assert "Do not change a value to make a result look better" in step


def test_step_three_waits_for_the_source_and_runs_three_formats():
    step = TEXT.split("## Step 3.")[1].split("## Step 4.")[0]
    for needed in ("wait until it is published", "Do not run the script with a placeholder"):
        assert needed in step, needed
    for fmt in ("--format md", "--format dm", "--format group"):
        assert fmt in step


def test_step_four_hands_out_the_three_outputs_and_handles_cash_and_turns():
    step = TEXT.split("## Step 4.")[1].split("## Guarantees and limits")[0]
    for needed in (
        "for the organizer only",
        "--format dm",
        "--format group",
        "add up to zero",
        "does not say who hands money to whom",
        "took turns",
        "report it as printed",
    ):
        assert needed in step, needed


def test_the_quoted_line_in_step_four_is_what_the_script_prints():
    step = TEXT.split("## Step 4.")[1].split("## Guarantees and limits")[0]
    quoted = re.findall(r"\"(按你的估值，阿明那份值[^\"]+)\"", step)
    assert len(quoted) == 1
    dm = run_script("--demo", "--format", "dm").stdout
    assert quoted[0] in dm


def test_the_rules_message_names_what_the_script_needs():
    message = TEXT.split("Example (Chinese):")[1].split("## Step 2.")[0]
    for needed in ("三选一", "最多愿意出多少", "11 月 8 日公开的开奖号码", "我先交", "同时交"):
        assert needed in message, needed


def test_the_three_rules_table_names_every_method_and_what_each_costs():
    table = TEXT.split("## The three rules")[1].split("## The script")[0]
    for method in ss.METHODS:
        assert f"`{method}`" in table
    for needed in (
        "What it promises",
        "What it costs",
        "Somebody can end up with less than under `knaster`",
        "Somebody may envy somebody",
        "2,000,000",
        "EF1",
        "Pareto efficient",
    ):
        assert needed in table, needed


def test_the_text_never_ranks_one_rule_above_another():
    lowered = TEXT.lower()
    for word in RANKING_WORDS:
        assert word.lower() not in lowered, word


def test_does_not_overclaim():
    lowered = TEXT.lower()
    for phrase in OVERCLAIMS:
        assert phrase.lower() not in lowered, phrase


def test_the_guarantees_and_limits_say_what_is_and_is_not_promised():
    section = TEXT.split("## Guarantees and limits")[1].split("## When not to use")[0]
    for needed in (
        "`envy_free`: every item goes to a person who values it most",
        "the cash adds up to exactly zero",
        "No division with cash gives the poorest-off person more",
        "at most one cent",
        "`knaster`:",
        "never below the fair share",
        "Somebody may envy somebody",
        "`max_nash`:",
        "2,000,000",
        "EF1 and Pareto efficient",
        "It is not free of envy",
        "Not strategy-proof, under any of the three rules",
        "Ties never change what anybody ends with",
        "never split",
    ):
        assert needed in section, needed


def test_when_not_to_use_points_to_the_neighbours():
    section = TEXT.split("## When not to use")[1].split("## Reference")[0]
    for neighbour in ("rent-split", "bill-split", "chore-split", "slot-lottery"):
        assert neighbour in section


def test_the_references_carry_their_dois():
    reference = TEXT.split("## Reference")[1]
    assert "10.1145/3355902" in reference and "10.1017/cbo9780511598975" in reference


# --------------------------------------------------------------------------------------
# What the text says about the script
# --------------------------------------------------------------------------------------


def test_every_option_it_mentions_exists():
    options = set(re.findall(r"(?<![\w-])(--[a-z][a-z-]*)", TEXT))
    assert {"--format", "--demo", "--input", "--delete-input", "--lang", "--selftest"} <= options
    help_text = " ".join(run_script("--help").stdout.split())
    for option in options:
        assert option in help_text, option


def test_every_example_it_mentions_exists_and_all_five_are_mentioned():
    names = set(re.findall(r"examples/([A-Za-z0-9_.-]+\.json)", TEXT))
    assert names == {path.name for path in EXAMPLES.glob("*.json")}
    assert len(names) == 5
    assert "five complete inputs" in TEXT


def test_the_input_fields_table_lists_every_field_the_script_accepts():
    table = TEXT.split("The input fields:")[1].split("Options are listed")[0]
    for field in ss.TOP_FIELDS:
        if field != "rules":
            assert f"`{field}`" in table, field
    for field in ss.RULE_FIELDS:
        assert f"`rules.{field}`" in table, field


def test_the_sizes_in_the_table_are_the_ones_the_script_enforces():
    table = TEXT.split("The input fields:")[1].split("Options are listed")[0]
    assert f"2 to {ss.MAX_PEOPLE}" in table and f"1 to {ss.MAX_ITEMS}" in table
    assert f"{ss.MAX_ALLOCATIONS:,}" in TEXT


def test_the_exit_codes_in_the_text_are_the_script_ones():
    for needed in (
        "Exit code 2 means invalid input and the message names the field",
        "Exit code 1 means a failed self-test",
        "there is no exit code 3",
    ):
        assert needed in TEXT, needed


def test_the_text_about_the_examples_is_what_the_script_finds():
    piano = ss.compute(
        ss.parse_problem(json.loads((EXAMPLES / "piano_knaster.json").read_text("utf-8")))
    )
    assert piano.envy["甲"], "one heir envies another under knaster"
    assert "In the piano example one heir envies another" in TEXT
    roommates = ss.compute(
        ss.parse_problem(json.loads((EXAMPLES / "three_roommates.json").read_text("utf-8")))
    )
    assert sorted(roommates.envy) == ["大刘", "小红", "阿明"] and roommates.envy["小红"] == {
        "阿明": 500
    }
    assert roommates.bundles["阿明"][0] == "冰箱"
    assert "two people envy the one who got the fridge" in TEXT
    big = ss.compute(
        ss.parse_problem(json.loads((EXAMPLES / "moving_out_14_items.json").read_text("utf-8")))
    )
    assert big.fell_back
    weighted = ss.compute(
        ss.parse_problem(json.loads((EXAMPLES / "weighted_knaster.json").read_text("utf-8")))
    )
    assert weighted.tops.needs_order and weighted.problem.weights is not None
    assert weighted.problem.source is not None and weighted.priority.method == "random_source"
