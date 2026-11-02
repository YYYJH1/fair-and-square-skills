<p align="center"><b>English</b> · <a href="how-it-works_zh.md">简体中文</a></p>

# How it works

## Who does what

- The agent understands the situation, asks the questions, drafts the messages for the group, turns a group chat or a survey export into the JSON input, reads that input back for confirmation, and quotes the script's output word for word.
- The script validates the input, does the arithmetic with exact fractions, rounds to whole cents, and writes the certificates.
- Each person checks their own line against their own numbers.

Each skill fixes the rule before anyone shares a number, so nobody can choose the rule after seeing the numbers.

## Private input

The numbers are private, so the input needs care too. A script reads it from standard input, which creates no input file, or from a file named by `--input`. An agent that can pipe the input in does so. Claude Code asks the user to approve any command whose heredoc holds braces and quotes, and every input of these skills does. There the skills write the input to a file in the session's scratchpad and run the script with `--delete-input`. The script deletes the file as soon as it has read it, also when it then rejects the input. This is an ordinary deletion and not a secure erase. The file exists until the script reads it, and it stays if the run stops before that.

## Rules for every script

Every script must follow these rules, which `tests/test_contract.py` checks:

- Standard library only, Python 3.9 or later.
- No network, no subprocesses, no `eval` or `exec`, no files written. The one change to the file system is the opt-in `--delete-input`, which deletes the `--input` file after it has been read. Only `core/fsq_core.py` does this, in one place.
- `--help`, `--demo` and `--selftest` exit with status 0, and the demo prints the same bytes on every run.

## Run a script without an agent

Every script has a built-in fictional example. From a clone of this repository:

```
python3 plugin/skills/rent-split/scripts/rent_split.py --demo
python3 plugin/skills/bill-split/scripts/bill_split.py --demo
python3 plugin/skills/ride-split/scripts/ride_split.py --demo
python3 plugin/skills/group-vote/scripts/group_vote.py --demo
python3 plugin/skills/chore-split/scripts/chore_split.py --demo
python3 plugin/skills/chore-split/scripts/chore_split.py --demo-bundle
python3 plugin/skills/slot-lottery/scripts/slot_lottery.py --demo
python3 plugin/skills/gift-exchange/scripts/gift_exchange.py --demo
python3 plugin/skills/stuff-split/scripts/stuff_split.py --demo
```

The text output is Chinese by default. `--lang en` gives English.
