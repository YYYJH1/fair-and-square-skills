"""Mutated inputs: every changed, deleted or added field gives either a result or an input error
that names a field, and never a crash."""

from __future__ import annotations

import copy
import json

import fsq_core as fc
import slot_lottery as sl
from hypothesis import given
from hypothesis import strategies as st
from lottery_support import (
    PEOPLE6,
    PEOPLE8,
    PROPERTY,
    RSD_PREFS,
    WEEKS,
    da_data,
    load_example,
    lottery_data,
    ps_data,
    reveal_data,
    rsd_data,
)

JSON_LEAVES = (
    st.none()
    | st.booleans()
    | st.integers(-5, 3000)
    | st.floats(allow_nan=False, allow_infinity=False, min_value=-10, max_value=10)
    | st.text(max_size=12)
)
JSON_VALUES = st.recursive(
    JSON_LEAVES,
    lambda children: (
        st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=6), children, max_size=3)
    ),
    max_leaves=8,
)


def base_documents():
    people = ["甲", "乙", "丙", "丁"]
    verifying = lottery_data(PEOPLE8, 3)
    verifying["claimed"] = {"order": ["a", "b"], "seed": "0" * 64}
    rsd_claimed = rsd_data(PEOPLE6, WEEKS, RSD_PREFS)
    rsd_claimed["claimed"] = {"order": ["a"], "allocation": {"阿明": "五一", "老王": None}}
    ps_claimed = ps_data(PEOPLE6, WEEKS, RSD_PREFS, capacities={"五一": 2})
    ps_claimed["claimed"] = {"allocation": {"阿明": "五一", "老王": None}, "seed": "0" * 64}
    da_claimed = load_example("da_parking.json")
    da_claimed["claimed"] = {"order": ["阿明"], "allocation": {"阿明": "充电车位"}}
    return [
        (lottery_data(PEOPLE8, 3), False),
        (rsd_data(PEOPLE6, WEEKS, RSD_PREFS), False),
        (reveal_data(people, revealing=people[:3], non_reveal="assigned"), False),
        (load_example("commit_reveal.json"), False),
        (verifying, True),
        (rsd_claimed, True),
        (load_example("ps_holiday_weeks.json"), False),
        (load_example("da_parking.json"), False),
        (ps_data(PEOPLE6, WEEKS, RSD_PREFS, no_ranking="assigned"), False),
        (da_data(PEOPLE6, WEEKS, RSD_PREFS, no_ranking="assigned"), False),
        (ps_claimed, True),
        (da_claimed, True),
    ]


def paths(value, prefix=()):
    """Every path (a tuple of keys and indices) into a JSON document, the root included."""
    yield prefix
    if isinstance(value, dict):
        for key, child in value.items():
            yield from paths(child, (*prefix, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from paths(child, (*prefix, index))


def edit(document, path, action, value):
    """A copy of document with the value at path replaced, deleted or (for objects) added."""
    document = copy.deepcopy(document)
    if not path:
        return value if action == "replace" else document
    parent = document
    for key in path[:-1]:
        parent = parent[key]
    last = path[-1]
    if action == "delete":
        del parent[last]
    elif action == "add" and isinstance(parent, dict):
        parent[f"{last}_extra"] = value
    else:
        parent[last] = value
    return document


@PROPERTY
@given(
    st.integers(0, 11),
    st.data(),
    st.sampled_from(["replace", "delete", "add"]),
    JSON_VALUES,
)
def test_mutated_inputs_never_crash(index, data, action, value):
    document, verifying = base_documents()[index]
    path = data.draw(st.sampled_from(sorted(paths(document), key=repr)))
    mutated = edit(document, path, action, value)
    try:
        if verifying:
            sl.verify_result(mutated)
        else:
            result = sl.solve(mutated)
            fc.render_md(result)
            fc.render_group(result)
            fc.render_dm(result)
            fc.render_json(result)
    except (fc.InputError, fc.NoSolution) as err:
        if isinstance(err, fc.InputError):
            assert err.field and err.message
        return


@PROPERTY
@given(JSON_VALUES)
def test_any_json_document_is_refused_or_answered_without_a_crash(document):
    try:
        sl.solve(json.loads(json.dumps(document)))
    except (fc.InputError, fc.NoSolution):
        return
    # a random document that is accepted must at least name its mode
    assert isinstance(document, dict) and document.get("mode") in sl.MODES
