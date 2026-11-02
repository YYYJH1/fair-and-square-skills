"""Exit codes, the shared command-line options, input reading and the self-test runner."""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
import textwrap
from fractions import Fraction
from pathlib import Path

import fsq_core as core
import pytest

CORE_DIR = Path(core.__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[2]


def exit_code(call) -> int:
    with pytest.raises(SystemExit) as caught:
        call()
    return caught.value.code


class TestRunCli:
    def test_success(self):
        assert exit_code(lambda: core.run_cli(lambda: None)) == 0

    def test_returned_code_is_the_exit_code(self):
        assert exit_code(lambda: core.run_cli(lambda: 1)) == 1
        assert exit_code(lambda: core.run_cli(lambda: 0)) == 0

    def test_input_error_exits_2_and_names_the_field(self, capsys):
        def main():
            raise core.InputError("bids.阿明[1]", "must not be negative")

        assert exit_code(lambda: core.run_cli(main)) == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "bids.阿明[1]" in captured.err and "must not be negative" in captured.err

    def test_no_solution_exits_3(self, capsys):
        def main():
            raise core.NoSolution("nobody can live rent-free here")

        assert exit_code(lambda: core.run_cli(main)) == 3
        assert "nobody can live rent-free here" in capsys.readouterr().err

    def test_other_exceptions_are_bugs_and_propagate(self):
        def main():
            raise KeyError("oops")

        with pytest.raises(KeyError):
            core.run_cli(main)

    def test_argv_is_passed_through(self):
        seen = []

        def main(argv):
            seen.append(argv)

        assert exit_code(lambda: core.run_cli(main, ("--demo", "--json"))) == 0
        assert seen == [["--demo", "--json"]]

    def test_works_when_streams_cannot_be_reconfigured(self, monkeypatch):
        monkeypatch.setattr(sys, "stdout", io.StringIO())
        monkeypatch.setattr(sys, "stderr", io.StringIO())
        assert exit_code(lambda: core.run_cli(lambda: None)) == 0

    def test_error_classes(self):
        err = core.InputError("total", "must be positive")
        assert (err.field, err.message, str(err)) == (
            "total",
            "must be positive",
            "total: must be positive",
        )
        assert issubclass(core.NoSolution, Exception)
        assert (core.EXIT_OK, core.EXIT_INPUT, core.EXIT_NO_SOLUTION) == (0, 2, 3)


class TestStandardArgs:
    def parse(self, *argv):
        parser = core.standard_args(argparse.ArgumentParser(prog="demo"))
        return parser.parse_args(list(argv))

    def test_defaults(self):
        args = self.parse()
        assert (args.input, args.format, args.json, args.demo, args.selftest) == (
            "-",
            "md",
            False,
            False,
            False,
        )

    def test_flags(self):
        args = self.parse(
            "--input", "bids.json", "--format", "dm", "--json", "--demo", "--selftest"
        )
        assert (args.input, args.format, args.json, args.demo, args.selftest) == (
            "bids.json",
            "dm",
            True,
            True,
            True,
        )

    def test_delete_input_is_off_unless_asked_for(self):
        assert self.parse().delete_input is False
        assert self.parse("--input", "bids.json").delete_input is False
        assert self.parse("--input", "bids.json", "--delete-input").delete_input is True

    def test_unknown_format_is_a_usage_error(self, capsys):
        assert exit_code(lambda: self.parse("--format", "html")) == 2
        assert "invalid choice" in capsys.readouterr().err

    def test_help_lists_every_shared_option(self, capsys):
        assert exit_code(lambda: self.parse("--help")) == 0
        text = capsys.readouterr().out
        for option in (
            "--input",
            "--delete-input",
            "--format",
            "--json",
            "--demo",
            "--selftest",
            "md",
            "dm",
            "group",
        ):
            assert option in text

    def test_help_says_what_delete_input_does_and_what_it_needs(self, capsys):
        assert exit_code(lambda: self.parse("--help")) == 0
        text = " ".join(capsys.readouterr().out.split())
        assert "delete the --input FILE as soon as it has been read" in text
        assert "even if the input is then rejected" in text
        assert "Needs --input FILE, not standard input" in text
        assert "A file that cannot be read is left alone" in text

    def test_returns_the_parser_for_chaining(self):
        parser = argparse.ArgumentParser()
        assert core.standard_args(parser) is parser


class TestAddLangOption:
    def parse(self, *argv):
        parser = core.standard_args(argparse.ArgumentParser(prog="demo"))
        core.add_lang_option(parser, "names and JSON keys do not change")
        return parser.parse_args(list(argv))

    def test_the_default_is_chinese(self):
        assert self.parse().lang == "zh"

    def test_english_can_be_chosen(self):
        assert self.parse("--lang", "en").lang == "en"

    def test_other_languages_are_a_usage_error(self, capsys):
        assert exit_code(lambda: self.parse("--lang", "fr")) == 2
        assert "invalid choice" in capsys.readouterr().err

    def test_the_choices_are_the_languages_of_the_core(self):
        parser = core.add_lang_option(argparse.ArgumentParser(), "x")
        action = next(a for a in parser._actions if a.dest == "lang")
        assert tuple(action.choices) == core.LANGS

    def test_help_names_the_default_and_what_does_not_change(self, capsys):
        assert exit_code(lambda: self.parse("--help")) == 0
        text = " ".join(capsys.readouterr().out.split())
        assert "--lang {zh,en}" in text
        assert "language of the text output (default zh); names and JSON keys do not change" in text

    def test_it_returns_the_parser_and_appears_where_it_is_called(self, capsys):
        parser = argparse.ArgumentParser(prog="demo")
        assert core.add_lang_option(parser, "x") is parser
        parser.add_argument("--audit", action="store_true")
        assert exit_code(lambda: parser.parse_args(["--help"])) == 0
        text = capsys.readouterr().out
        assert text.index("--lang") < text.index("--audit")


def skill_scripts() -> list[Path]:
    """The eight skill scripts (not the copies of the core next to them)."""
    found = (REPO_ROOT / "plugin" / "skills").glob("*/scripts/*.py")
    return sorted(path for path in found if path.name != "fsq_core.py")


class TestExitCodesEpilog:
    def test_the_default_names_the_self_test_and_says_that_3_is_not_used(self):
        text = " ".join(core.exit_codes_epilog().split())
        assert text == (
            "Exit code 0 means success, 1 a failed self-test and 2 invalid input (the message "
            "names the field). Every valid input has a result, so exit code 3 is not used."
        )

    def test_a_script_with_exit_code_3_says_what_it_means(self):
        text = " ".join(core.exit_codes_epilog(three="the agreed rule has no solution").split())
        assert text == (
            "Exit code 0 means success, 1 a failed self-test, 2 invalid input (the message names "
            "the field) and 3 the agreed rule has no solution."
        )

    def test_exit_code_1_can_have_another_meaning(self):
        text = " ".join(core.exit_codes_epilog(one="a --verify mismatch", three="no draw").split())
        assert "1 a --verify mismatch, 2 invalid input" in text

    def test_the_lines_are_at_most_78_columns_wide(self):
        wrapped = core.exit_codes_epilog(one="a very long reason " * 5, three="another one " * 5)
        assert all(len(line) <= 78 for line in wrapped.splitlines())
        assert "\n" in wrapped

    def test_every_skill_script_ends_its_help_with_this_sentence(self):
        scripts = skill_scripts()
        assert len(scripts) == 8
        for script in scripts:
            done = subprocess.run(
                [sys.executable, "-B", str(script), "--help"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            text = " ".join(done.stdout.split())
            assert "Exit code 0 means success, 1 " in text, script.name
            assert "2 invalid input (the message names the field)" in text, script.name


class TestExclusiveModes:
    def parse(self, *argv):
        parser = core.standard_args(argparse.ArgumentParser(prog="demo"))
        parser.add_argument("--commit", action="store_true")
        parser.add_argument("--verify-commit", metavar="DIGEST")
        return parser.parse_args(list(argv))

    def test_no_mode_and_a_single_mode_pass(self):
        core.exclusive_modes(self.parse(), "--demo", "--selftest")
        core.exclusive_modes(self.parse("--demo"), "--demo", "--selftest")
        core.exclusive_modes(self.parse("--selftest"), "--demo", "--selftest")

    def test_two_modes_are_refused_and_both_names_are_in_the_message(self):
        with pytest.raises(core.InputError) as caught:
            core.exclusive_modes(self.parse("--demo", "--selftest"), "--demo", "--selftest")
        assert caught.value.field == "options"
        assert caught.value.message == "choose at most one of --demo and --selftest"

    def test_three_or_more_names_are_joined_with_a_comma_and_and(self):
        args = self.parse("--commit", "--verify-commit", "abc")
        with pytest.raises(core.InputError) as caught:
            core.exclusive_modes(args, "--demo", "--selftest", "--commit", "--verify-commit")
        assert caught.value.message == (
            "choose at most one of --demo, --selftest, --commit and --verify-commit"
        )

    def test_an_option_with_a_value_counts_even_when_the_value_is_empty(self):
        args = self.parse("--demo", "--verify-commit", "")
        with pytest.raises(core.InputError):
            core.exclusive_modes(args, "--demo", "--verify-commit")

    def test_a_flag_the_parser_does_not_have_is_never_given(self):
        core.exclusive_modes(self.parse("--demo"), "--demo", "--demo-bundle")

    def test_every_script_refuses_demo_with_selftest(self, tmp_path):
        scripts = skill_scripts()
        for script in scripts:
            done = subprocess.run(
                [sys.executable, "-B", str(script), "--demo", "--selftest"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=tmp_path,
                check=False,
            )
            assert done.returncode == 2, script.name
            assert 'field "options": choose at most one of --demo' in done.stderr, script.name
            assert done.stdout == "", script.name


class TestReadObject:
    def args(self, **values):
        base = {"input": "-", "demo": False}
        return argparse.Namespace(**{**base, **values})

    def test_a_json_object_is_returned(self, monkeypatch):
        monkeypatch.setattr(sys, "stdin", io.StringIO('{"a": 1.5}'))
        assert core.read_object(self.args()) == {"a": Fraction(3, 2)}

    def test_the_demo_object_is_returned_as_is(self):
        assert core.read_object(self.args(demo=True), {"a": 1}) == {"a": 1}

    def test_the_demo_text_is_parsed(self):
        assert core.read_object(self.args(demo=True), '{"a": 1}') == {"a": 1}

    @pytest.mark.parametrize("text", ["[]", "3", '"text"', "null"])
    def test_anything_but_an_object_is_an_input_error_naming_input(self, monkeypatch, text):
        monkeypatch.setattr(sys, "stdin", io.StringIO(text))
        with pytest.raises(core.InputError, match="must be a JSON object") as caught:
            core.read_object(self.args())
        assert caught.value.field == "input"

    def test_invalid_utf8_on_standard_input_is_an_input_error(self, monkeypatch):
        raw = io.TextIOWrapper(io.BytesIO(b'{"a": "\xff"}'), encoding="utf-8", errors="strict")
        monkeypatch.setattr(sys, "stdin", raw)
        with pytest.raises(core.InputError, match="is not valid UTF-8") as caught:
            core.read_object(self.args())
        assert caught.value.field == "input"

    def test_a_demo_request_without_an_example_is_an_input_error(self):
        with pytest.raises(core.InputError) as caught:
            core.read_object(self.args(demo=True))
        assert caught.value.field == "--demo"

    def test_a_file_that_is_not_utf8_keeps_its_own_message(self, tmp_path):
        path = tmp_path / "in.json"
        path.write_bytes(b'{"a": "\xff"}')
        with pytest.raises(core.InputError, match="UTF-8"):
            core.read_object(self.args(input=str(path)))


class TestReadInput:
    def args(self, **values):
        base = {"input": "-", "demo": False}
        return argparse.Namespace(**{**base, **values})

    def test_demo_text_is_parsed_like_real_input(self):
        data = core.read_input(self.args(demo=True), demo='{"total": 8000.50}')
        assert data == {"total": Fraction(16001, 2)}

    def test_demo_object_is_returned_as_is(self):
        assert core.read_input(self.args(demo=True), demo={"a": 1}) == {"a": 1}

    def test_demo_without_example_is_an_input_error(self):
        with pytest.raises(core.InputError) as caught:
            core.read_input(self.args(demo=True))
        assert caught.value.field == "--demo"

    def test_file(self, tmp_path):
        path = tmp_path / "in.json"
        path.write_text('{"名": 0.29}', encoding="utf-8")
        assert core.read_input(self.args(input=str(path))) == {"名": Fraction(29, 100)}

    def test_file_with_a_byte_order_mark(self, tmp_path):
        path = tmp_path / "in.json"
        path.write_bytes(b"\xef\xbb\xbf" + '{"名": 1}'.encode())
        assert core.read_input(self.args(input=str(path))) == {"名": 1}

    def test_missing_file(self, tmp_path):
        with pytest.raises(core.InputError, match="cannot read"):
            core.read_input(self.args(input=str(tmp_path / "nope.json")))

    def test_file_that_is_not_utf8(self, tmp_path):
        path = tmp_path / "in.json"
        path.write_bytes(b'{"a": "\xff"}')
        with pytest.raises(core.InputError, match="UTF-8"):
            core.read_input(self.args(input=str(path)))

    def test_invalid_json_in_a_file(self, tmp_path):
        path = tmp_path / "in.json"
        path.write_text("{", encoding="utf-8")
        with pytest.raises(core.InputError, match="not valid JSON"):
            core.read_input(self.args(input=str(path)))

    def test_standard_input(self, monkeypatch):
        monkeypatch.setattr(sys, "stdin", io.StringIO('{"a": 1.5}'))
        assert core.read_input(self.args()) == {"a": Fraction(3, 2)}

    def test_a_terminal_is_not_read(self, monkeypatch):
        class Terminal:
            def isatty(self):
                return True

            def read(self, *_):
                raise AssertionError("must not block on a terminal")

        monkeypatch.setattr(sys, "stdin", Terminal())
        with pytest.raises(core.InputError, match="standard input"):
            core.read_input(self.args())

    def test_missing_standard_input(self, monkeypatch):
        monkeypatch.setattr(sys, "stdin", None)
        with pytest.raises(core.InputError, match="standard input"):
            core.read_input(self.args())

    def test_namespace_without_the_standard_options(self, monkeypatch):
        monkeypatch.setattr(sys, "stdin", io.StringIO("[1]"))
        assert core.read_input(argparse.Namespace()) == [1]


class TestEmit:
    def result(self):
        return core.Result(
            title="T",
            result={"x": core.Cents(150)},
            tables=[core.Table(["h"], [["1.50"]])],
            person_lines={"a": ["mine"]},
            group_lines=["all"],
        )

    def test_choice_follows_the_arguments(self):
        for argv, expected in (
            ({"format": "md", "json": False}, core.render_md),
            ({"format": "dm", "json": False}, core.render_dm),
            ({"format": "group", "json": False}, core.render_group),
            ({"format": "md", "json": True}, core.render_json),
        ):
            out = io.StringIO()
            core.emit(self.result(), argparse.Namespace(**argv), out)
            assert out.getvalue() == expected(self.result())

    def test_defaults_to_markdown_on_standard_output(self, capsys):
        core.emit(self.result(), argparse.Namespace())
        assert capsys.readouterr().out == core.render_md(self.result())


class TestSelftest:
    def test_core_checks_pass(self, capsys):
        assert core.run_selftest() == 0
        out = capsys.readouterr().out
        assert "selftest: 7 passed, 0 failed" in out
        assert "FAIL" not in out and "seed golden" in out

    def test_check_names_are_unique(self):
        names = [name for name, _ in core.core_selftest_checks()]
        assert len(names) == len(set(names)) >= 5

    def test_failures_are_reported_and_counted(self, capsys):
        def boom():
            raise ValueError("bad number")

        def wrong():
            raise AssertionError("not equal")

        code = core.run_selftest(
            [("fine", lambda: None), ("boom", boom), ("wrong", wrong)], include_core=False
        )
        out = capsys.readouterr().out
        assert code == 1
        assert "ok   fine" in out
        assert "FAIL boom: ValueError: bad number" in out
        assert "FAIL wrong: AssertionError: not equal" in out
        assert "selftest: 1 passed, 2 failed" in out

    def test_extra_checks_run_after_the_core_ones(self, capsys):
        calls = []
        assert core.run_selftest([("mine", lambda: calls.append(1))]) == 0
        assert calls == [1] and "ok   mine" in capsys.readouterr().out

    def test_a_broken_core_check_is_caught(self, monkeypatch, capsys):
        monkeypatch.setattr(core, "_GOLDEN_ORDER", ["wrong"])
        assert core.run_selftest() == 1
        assert "FAIL seed golden" in capsys.readouterr().out


SKILL_SCRIPT = textwrap.dedent(
    """
    import argparse
    import sys

    sys.path.insert(0, {core_dir!r})
    import fsq_core as core

    DEMO = '{{"people": ["阿明", "小红", "大刘"], "total": 100.00, "bill_id": "dinner-1"}}'


    def main():
        parser = core.standard_args(argparse.ArgumentParser(description="demo skill"))
        args = parser.parse_args()
        if args.selftest:
            return core.run_selftest()
        data = core.require_object(core.read_input(args, DEMO), "input")
        people = core.require_names(data.get("people"), "people", min_len=2)
        total = core.money(data.get("total"), "total", allow_zero=False)
        if len(people) > 5:
            raise core.NoSolution("more than five people")
        cents = core.apportion(core.to_cents(total), {{p: Fraction(1) for p in people}}, "dinner-1")
        shown = {{p: core.fmt_cents(c) for p, c in cents.items()}}
        result = core.Result(
            title="Split",
            inputs_echo={{"total": core.Cents(core.to_cents(total)), "people": people}},
            result={{"owes": {{p: core.Cents(c) for p, c in cents.items()}}}},
            tables=[core.Table(["who", "owes"], [[p, shown[p]] for p in people])],
            person_lines={{p: ["you owe " + shown[p]] for p in people}},
            group_lines=["split done, check your private message"],
            reproduce="python3 demo.py --demo",
        )
        core.emit(result, args)
        return 0


    from fractions import Fraction

    core.run_cli(main)
    """
)


@pytest.fixture
def skill_script(tmp_path):
    path = tmp_path / "demo_skill.py"
    path.write_text(SKILL_SCRIPT.format(core_dir=str(CORE_DIR)), encoding="utf-8")
    return path


def run_script(script, *argv, stdin=""):
    return subprocess.run(
        [sys.executable, str(script), *argv],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        cwd=script.parent,
    )


class TestEndToEnd:
    def test_demo_in_every_format(self, skill_script):
        md = run_script(skill_script, "--demo")
        assert md.returncode == 0 and md.stderr == ""
        assert (
            "| 阿明 | 33.34 |" in md.stdout
            or "| 小红 | 33.34 |" in md.stdout
            or "| 大刘 | 33.34 |" in md.stdout
        )
        dm = run_script(skill_script, "--demo", "--format", "dm")
        assert dm.returncode == 0 and "--- 发给 小红 ---\nyou owe " in dm.stdout
        group = run_script(skill_script, "--demo", "--format", "group")
        assert group.stdout == "Split\nsplit done, check your private message\n"
        data = json.loads(run_script(skill_script, "--demo", "--json").stdout)
        assert sorted(data["result"]["owes"].values(), key=float) == ["33.33", "33.33", "33.34"]
        assert data["inputs_echo"]["total"] == "100.00"

    def test_same_input_same_bytes(self, skill_script):
        first = run_script(skill_script, "--demo", "--json").stdout
        assert run_script(skill_script, "--demo", "--json").stdout == first

    def test_standard_input_with_decimals(self, skill_script):
        out = run_script(
            skill_script, "--json", stdin='{"people": ["a", "b"], "total": 0.29, "bill_id": "x"}'
        )
        assert out.returncode == 0
        assert sorted(json.loads(out.stdout)["result"]["owes"].values()) == ["0.14", "0.15"]

    @pytest.mark.parametrize(
        ("stdin", "field"),
        [
            ('{"people": ["a"], "total": 5}', "people"),
            ('{"people": ["a", "a"], "total": 5}', "people[1]"),
            ('{"people": ["a", "b"], "total": 0.295}', "total"),
            ('{"people": ["a", "b"], "total": 0}', "total"),
            ('{"people": ["a", "b"], "total": true}', "total"),
            ("[]", "input"),
            ("{not json", "input"),
        ],
    )
    def test_invalid_input_exits_2_naming_the_field(self, skill_script, stdin, field):
        out = run_script(skill_script, stdin=stdin)
        assert out.returncode == 2
        assert out.stdout == ""
        assert f'field "{field}"' in out.stderr

    def test_no_solution_exits_3(self, skill_script):
        names = ", ".join(f'"p{i}"' for i in range(6))
        out = run_script(skill_script, stdin=f'{{"people": [{names}], "total": 6}}')
        assert out.returncode == 3 and "more than five people" in out.stderr

    def test_selftest_and_help(self, skill_script):
        out = run_script(skill_script, "--selftest")
        assert out.returncode == 0 and "selftest: 7 passed, 0 failed" in out.stdout
        helped = run_script(skill_script, "--help")
        assert helped.returncode == 0 and "--selftest" in helped.stdout

    def test_chinese_survives_a_c_locale(self, skill_script):
        env = {
            "PATH": "/usr/bin:/bin",
            "LC_ALL": "C",
            "LANG": "C",
            "PYTHONUTF8": "0",
            "PYTHONCOERCECLOCALE": "0",
        }
        out = subprocess.run(
            [sys.executable, str(skill_script), "--demo", "--format", "group"],
            capture_output=True,
            check=False,
            env=env,
            cwd=skill_script.parent,
        )
        assert out.returncode == 0
        assert out.stdout.decode("utf-8") == "Split\nsplit done, check your private message\n"
        names = subprocess.run(
            [sys.executable, str(skill_script), "--format", "dm"],
            input='{"people": ["阿明", "小红"], "total": 3}'.encode(),
            capture_output=True,
            check=False,
            env=env,
            cwd=skill_script.parent,
        )
        assert names.returncode == 0
        assert "--- 发给 阿明 ---" in names.stdout.decode("utf-8")


class TestDeleteInput:
    """--delete-input: the --input file is deleted once it has been read, whatever follows."""

    def args(self, path, **values):
        base = {"input": str(path), "demo": False, "delete_input": True}
        return argparse.Namespace(**{**base, **values})

    def write(self, tmp_path, content='{"名": 0.29}', name="in.json"):
        path = tmp_path / name
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
        return path

    def test_a_good_file_is_read_and_then_deleted(self, tmp_path):
        path = self.write(tmp_path)
        assert core.read_input(self.args(path)) == {"名": Fraction(29, 100)}
        assert not path.exists()

    def test_a_file_with_a_byte_order_mark_is_read_and_deleted(self, tmp_path):
        path = self.write(tmp_path, b"\xef\xbb\xbf" + '{"名": 1}'.encode())
        assert core.read_input(self.args(path)) == {"名": 1}
        assert not path.exists()

    @pytest.mark.parametrize(
        ("content", "message"),
        [
            (b"{", "not valid JSON"),
            (b"", "not valid JSON"),
            (b'{"a": NaN}', "not valid JSON"),
            (b'{"a": 1, "a": 2}', "not valid JSON"),
            (b'{"a": "\xff"}', "not valid UTF-8"),
        ],
        ids=["truncated", "empty", "nan", "duplicate-key", "not-utf8"],
    )
    def test_a_rejected_input_is_deleted_all_the_same(self, tmp_path, content, message):
        path = self.write(tmp_path, content)
        with pytest.raises(core.InputError, match=message):
            core.read_input(self.args(path))
        assert not path.exists()

    def test_a_file_that_is_too_large_is_deleted_all_the_same(self, tmp_path, monkeypatch):
        monkeypatch.setattr(core, "MAX_INPUT_CHARS", 10)
        path = self.write(tmp_path, '{"a": 1, "b": 2}')
        with pytest.raises(core.InputError, match="too large"):
            core.read_input(self.args(path))
        assert not path.exists()

    def test_a_value_that_is_not_an_object_is_deleted_all_the_same(self, tmp_path):
        path = self.write(tmp_path, "[1, 2]")
        with pytest.raises(core.InputError, match="must be a JSON object"):
            core.read_object(self.args(path))
        assert not path.exists()

    def test_the_file_stays_when_the_option_is_off(self, tmp_path):
        path = self.write(tmp_path)
        assert core.read_input(self.args(path, delete_input=False)) == {"名": Fraction(29, 100)}
        assert core.read_input(argparse.Namespace(input=str(path), demo=False)) == {
            "名": Fraction(29, 100)
        }
        assert path.exists()

    def test_only_the_file_that_was_read_is_deleted(self, tmp_path):
        path = self.write(tmp_path)
        neighbour = self.write(tmp_path, "keep me", name="other.json")
        core.read_input(self.args(path))
        assert sorted(item.name for item in tmp_path.iterdir()) == ["other.json"]
        assert neighbour.read_text(encoding="utf-8") == "keep me"

    def test_standard_input_is_refused_and_not_touched(self, monkeypatch):
        class Trap:
            def isatty(self):
                raise AssertionError("must not look at standard input")

            def read(self, *_):
                raise AssertionError("must not read standard input")

        monkeypatch.setattr(sys, "stdin", Trap())
        with pytest.raises(core.InputError, match="needs --input FILE") as caught:
            core.read_input(self.args("-"))
        assert caught.value.field == "--delete-input"

    def test_leaving_out_the_input_option_means_standard_input_and_is_refused_too(
        self, monkeypatch
    ):
        monkeypatch.setattr(sys, "stdin", io.StringIO('{"a": 1}'))
        parser = core.standard_args(argparse.ArgumentParser())
        with pytest.raises(core.InputError, match="needs --input FILE") as caught:
            core.read_input(parser.parse_args(["--delete-input"]))
        assert caught.value.field == "--delete-input"
        assert sys.stdin.read() == '{"a": 1}'

    def test_a_missing_file_is_an_error_and_nothing_is_deleted(self, tmp_path):
        self.write(tmp_path, "keep me", name="other.json")
        with pytest.raises(core.InputError, match="cannot read") as caught:
            core.read_input(self.args(tmp_path / "nope.json"))
        assert caught.value.field == "input"
        assert [item.name for item in tmp_path.iterdir()] == ["other.json"]

    def test_a_directory_is_refused_and_keeps_its_contents(self, tmp_path):
        folder = tmp_path / "folder"
        folder.mkdir()
        (folder / "a.json").write_text("{}", encoding="utf-8")
        with pytest.raises(core.InputError, match="not a regular file") as caught:
            core.read_input(self.args(folder))
        assert caught.value.field == "--delete-input"
        assert [item.name for item in folder.iterdir()] == ["a.json"]

    def test_a_symbolic_link_is_refused_and_it_and_its_target_both_stay(self, tmp_path):
        target = self.write(tmp_path, "{}", name="real.json")
        link = tmp_path / "link.json"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            pytest.skip("this system cannot make symbolic links")
        with pytest.raises(core.InputError, match="not a regular file") as caught:
            core.read_input(self.args(link))
        assert caught.value.field == "--delete-input"
        assert link.is_symlink() and target.exists()

    def test_a_file_that_cannot_be_deleted_is_reported_and_not_ignored(self, tmp_path, monkeypatch):
        path = self.write(tmp_path)

        def refuse(self, missing_ok=False):
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(Path, "unlink", refuse)
        with pytest.raises(
            core.InputError, match="could not delete it: Permission denied"
        ) as caught:
            core.read_input(self.args(path))
        assert caught.value.field == "--delete-input"
        assert str(path) in str(caught.value)
        assert path.exists()

    def test_a_file_that_vanishes_before_it_is_deleted_is_not_an_error(self, tmp_path, monkeypatch):
        path = self.write(tmp_path)
        real = Path.read_text

        def read_then_vanish(self, *args, **kwargs):
            text = real(self, *args, **kwargs)
            self.unlink()
            return text

        monkeypatch.setattr(Path, "read_text", read_then_vanish)
        assert core.read_input(self.args(path)) == {"名": Fraction(29, 100)}

    def test_the_demo_reads_no_file_and_deletes_none(self, tmp_path):
        path = self.write(tmp_path)
        assert core.read_input(self.args(path, demo=True), demo={"a": 1}) == {"a": 1}
        assert path.exists()


class TestDeleteInputEndToEnd:
    """The same behaviour through a real script: exit codes, messages and files left behind."""

    GOOD = '{"people": ["a", "b"], "total": 0.29, "bill_id": "x"}'

    def make(self, skill_script, text, name="bids.json"):
        path = skill_script.parent / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_the_result_is_the_one_from_standard_input_and_the_file_is_gone(self, skill_script):
        path = self.make(skill_script, self.GOOD)
        from_file = run_script(skill_script, "--input", str(path), "--delete-input", "--json")
        from_stdin = run_script(skill_script, "--json", stdin=self.GOOD)
        assert from_file.returncode == 0 and from_file.stderr == ""
        assert from_file.stdout == from_stdin.stdout
        assert not path.exists()
        assert skill_script.exists()

    def test_a_rejected_input_exits_2_naming_the_field_and_the_file_is_gone(self, skill_script):
        path = self.make(skill_script, '{"people": ["a"], "total": 5}')
        out = run_script(skill_script, "--input", str(path), "--delete-input")
        assert out.returncode == 2 and out.stdout == ""
        assert 'field "people"' in out.stderr
        assert not path.exists()

    def test_a_rule_with_no_solution_exits_3_and_the_file_is_gone(self, skill_script):
        names = ", ".join(f'"p{i}"' for i in range(6))
        path = self.make(skill_script, f'{{"people": [{names}], "total": 6}}')
        out = run_script(skill_script, "--input", str(path), "--delete-input")
        assert out.returncode == 3 and "more than five people" in out.stderr
        assert not path.exists()

    def test_standard_input_with_the_option_exits_2_before_reading(self, skill_script):
        message = (
            'error: invalid input, field "--delete-input": '
            "needs --input FILE (standard input leaves no file to delete)\n"
        )
        for argv in (("--delete-input",), ("--input", "-", "--delete-input")):
            out = run_script(skill_script, *argv, stdin=self.GOOD)
            assert (out.returncode, out.stdout, out.stderr) == (2, "", message)

    def test_a_missing_path_exits_2_and_the_folder_is_left_as_it_was(self, skill_script):
        other = self.make(skill_script, "keep me", name="other.json")
        before = sorted(item.name for item in skill_script.parent.iterdir())
        out = run_script(skill_script, "--input", "nope.json", "--delete-input")
        assert out.returncode == 2 and out.stdout == ""
        assert out.stderr == (
            'error: invalid input, field "input": cannot read nope.json: '
            "No such file or directory\n"
        )
        assert sorted(item.name for item in skill_script.parent.iterdir()) == before
        assert other.read_text(encoding="utf-8") == "keep me"

    def test_the_demo_leaves_the_file_alone(self, skill_script):
        path = self.make(skill_script, self.GOOD)
        out = run_script(skill_script, "--demo", "--input", str(path), "--delete-input")
        assert out.returncode == 0
        assert path.exists()
