"""Mutated inputs: every changed, deleted or added field gives either a result or an input error
(or the message that no legal draw exists), and never a crash."""

from __future__ import annotations

import copy
import json

import fsq_core as fc
import gift_exchange as ge
from gift_support import PROPERTY, exchange_data, load_example, six_people
from hypothesis import given
from hypothesis import strategies as st

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
    checking = six_people()
    del checking["random_source"], checking["rules"]
    return [
        (six_people(), False),
        (six_people("ring"), False),
        (load_example("office_twelve.json"), False),
        (
            exchange_data(
                ["a", "b", "c", "d"], [{"pair": ["a", "b"]}, {"giver": "c", "receiver": "d"}]
            ),
            False,
        ),
        (checking, True),
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
    st.integers(0, 4),
    st.data(),
    st.sampled_from(["replace", "delete", "add"]),
    JSON_VALUES,
)
def test_mutated_inputs_never_crash(index, data, action, value):
    document, checking = base_documents()[index]
    path = data.draw(st.sampled_from(sorted(paths(document), key=repr)))
    mutated = edit(document, path, action, value)
    try:
        if checking:
            result = ge.check_result(mutated)
            fc.render_md(result)
            fc.render_json(result)
        else:
            result = ge.solve(mutated)
            fc.render_md(result)
            fc.render_group(result)
            fc.render_dm(result)
            fc.render_json(result)
    except (fc.InputError, ge.NoLegalPlan) as err:
        if isinstance(err, fc.InputError):
            assert err.field and err.message
        else:
            assert err.kind in ("hall", "closed", "exhausted", "limit")
            assert str(err)


@PROPERTY
@given(JSON_VALUES)
def test_any_json_document_is_refused_or_answered_without_a_crash(document):
    try:
        ge.solve(json.loads(json.dumps(document)))
    except (fc.InputError, ge.NoLegalPlan):
        return
    # a random document that is accepted must at least list its people
    assert isinstance(document, dict) and isinstance(document.get("people"), list)
