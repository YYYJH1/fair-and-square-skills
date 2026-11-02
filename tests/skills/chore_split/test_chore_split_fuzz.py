"""Fuzzing: whatever is put into a valid input, the script either answers or refuses with exit
code 2 or 3. It never fails with a traceback."""

from __future__ import annotations

import copy
import json

import chore_split as cs
import fsq_core as fc
from chore_support import PROPERTY, load_example, run_script
from hypothesis import given, settings
from hypothesis import strategies as st

SCALARS = (
    st.none()
    | st.booleans()
    | st.integers(-5, 200)
    | st.floats(allow_nan=False, allow_infinity=False, width=32)
    | st.text(max_size=6)
)
JSON_VALUES = st.recursive(
    SCALARS,
    lambda children: (
        st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=4), children, max_size=3)
    ),
    max_leaves=8,
)
EXAMPLE_NAMES = ["three_roommates.json", "weekly_rota.json", "cannot_cook.json"]
TOP_KEYS = ["people", "chores", "rankings", "cannot", "likes", "weeks", "rules"]


def refuses_or_answers(data):
    """True when the input was answered, False when it was refused the proper way."""
    text = json.dumps(data, ensure_ascii=False)
    try:
        result = cs.solve(fc.parse_input(text))
    except (fc.InputError, fc.NoSolution):
        return False
    for fmt in ("md", "dm", "group"):
        assert fc.render(result, fmt).strip()
    return True


@PROPERTY
@given(st.sampled_from(EXAMPLE_NAMES), st.sampled_from(TOP_KEYS), JSON_VALUES)
def test_any_value_in_any_top_level_field_is_answered_or_refused(name, key, value):
    data = copy.deepcopy(load_example(name))
    data[key] = value
    refuses_or_answers(data)


@PROPERTY
@given(st.sampled_from(EXAMPLE_NAMES), st.data())
def test_any_value_deeper_in_the_input_is_answered_or_refused(name, draw):
    data = copy.deepcopy(load_example(name))
    where = draw.draw(st.sampled_from(["rankings", "rules", "chores", "cannot", "people"]))
    container = data.get(where)
    value = draw.draw(JSON_VALUES)
    if isinstance(container, dict) and container:
        key = draw.draw(st.sampled_from(sorted(container)))
        container[key] = value
    elif isinstance(container, list) and container:
        container[draw.draw(st.integers(0, len(container) - 1))] = value
    else:
        data.setdefault(where, {})
        if isinstance(data[where], dict):
            data[where][draw.draw(st.text(max_size=4))] = value
    refuses_or_answers(data)


@PROPERTY
@given(st.sampled_from(EXAMPLE_NAMES), st.data())
def test_dropping_or_adding_a_field_is_answered_or_refused(name, draw):
    data = copy.deepcopy(load_example(name))
    if draw.draw(st.booleans()):
        data.pop(draw.draw(st.sampled_from(sorted(data))))
    else:
        data[draw.draw(st.text(min_size=1, max_size=5))] = draw.draw(JSON_VALUES)
    refuses_or_answers(data)


@settings(deadline=None, max_examples=60, derandomize=True, database=None)
@given(st.text(max_size=60))
def test_arbitrary_text_on_standard_input_never_crashes(text):
    done = run_script("--input", "-", stdin=text)
    assert done.returncode in (0, 2)
    assert "Traceback" not in done.stderr


def test_a_valid_input_is_answered():
    assert refuses_or_answers(load_example("weekly_rota.json")) is True
