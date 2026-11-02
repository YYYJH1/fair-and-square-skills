"""Commitments for the organizer-goes-first rule."""

from __future__ import annotations

import hashlib
import re
from fractions import Fraction

import fsq_core as core
import pytest
from hypothesis import given
from hypothesis import strategies as st

NONCE = "00112233445566778899aabbccddeeff"
BIDS = {
    "organizer": "阿明",
    "bids": [3000, Fraction(2200), Fraction(3, 2)],
    "total": Fraction(8000),
}

JSON_LEAVES = st.none() | st.booleans() | st.integers(-(10**9), 10**9) | st.text(max_size=8)
JSON_VALUES = st.recursive(
    JSON_LEAVES,
    lambda children: (
        st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=4), children, max_size=4)
    ),
    max_leaves=12,
)
# a bare str is read as JSON text, so top-level payloads are objects or lists
JSON_PAYLOADS = JSON_VALUES.filter(lambda value: isinstance(value, (dict, list)))


class TestRoundTrip:
    def test_commit_then_verify(self):
        digest, nonce = core.commit(BIDS)
        assert re.fullmatch(r"[0-9a-f]{64}", digest)
        assert re.fullmatch(r"[0-9a-f]{32}", nonce)
        assert core.verify_commit(digest, BIDS, nonce) is True

    def test_returns_a_named_pair(self):
        result = core.commit(BIDS)
        assert result.digest == result[0] and result.nonce == result[1]

    @given(JSON_PAYLOADS)
    def test_any_json_payload_round_trips(self, payload):
        digest, nonce = core.commit(payload)
        assert core.verify_commit(digest, payload, nonce)

    def test_changed_payload_or_nonce_fails(self):
        digest, nonce = core.commit(BIDS)
        changed = dict(BIDS, bids=[3000, Fraction(2200), Fraction(3, 2) + Fraction(1, 100)])
        assert core.verify_commit(digest, changed, nonce) is False
        assert core.verify_commit(digest, BIDS, core.new_nonce()) is False
        assert core.verify_commit("0" * 64, BIDS, nonce) is False

    def test_digest_text_is_forgiving_about_case_and_spaces(self):
        digest, nonce = core.commit(BIDS)
        assert core.verify_commit("  " + digest.upper() + "\n", BIDS, nonce) is True

    def test_non_hex_digest_text_is_just_a_mismatch(self):
        _, nonce = core.commit(BIDS)
        assert core.verify_commit("not a digest", BIDS, nonce) is False


class TestNonce:
    def test_nonces_are_fresh_and_128_bit(self):
        nonces = {core.new_nonce() for _ in range(200)}
        assert len(nonces) == 200
        assert all(re.fullmatch(r"[0-9a-f]{32}", n) for n in nonces)

    def test_same_payload_commits_differently_each_time(self):
        digests = {core.commit(BIDS).digest for _ in range(20)}
        assert len(digests) == 20

    def test_nonce_comes_from_secrets(self, monkeypatch):
        monkeypatch.setattr(core.secrets, "token_hex", lambda n: "ab" * n)
        assert core.new_nonce() == "ab" * 16
        assert core.commit(BIDS).nonce == "ab" * 16

    @pytest.mark.parametrize(
        "nonce",
        ["", "abc", "00112233445566778899AABBCCDDEEFF", "g" * 32, "0" * 31, "0" * 33, 5],
    )
    def test_weak_or_malformed_nonce_is_refused(self, nonce):
        with pytest.raises(core.InputError) as caught:
            core.commit(BIDS, nonce)
        assert caught.value.field == "nonce"
        with pytest.raises(core.InputError):
            core.verify_commit("0" * 64, BIDS, nonce)

    def test_commit_without_nonce_generates_one_but_verify_requires_it(self):
        assert re.fullmatch(r"[0-9a-f]{32}", core.commit(BIDS, None).nonce)
        with pytest.raises(core.InputError):
            core.verify_commit("0" * 64, BIDS, None)

    def test_digest_must_be_text(self):
        with pytest.raises(core.InputError) as caught:
            core.verify_commit(None, BIDS, NONCE)
        assert caught.value.field == "digest"
        with pytest.raises(core.InputError):
            core.verify_commit("摘要", BIDS, NONCE)


class TestCanonicalPayload:
    def test_key_order_and_spacing_do_not_matter(self):
        a = core.commit({"x": 1, "y": [1, 2]}, NONCE)
        b = core.commit({"y": [1, 2], "x": 1}, NONCE)
        c = core.commit('{ "y" : [1,\n 2], "x":1 }', NONCE)
        assert a == b == c

    def test_integers_and_whole_decimals_agree(self):
        assert core.commit({"v": 3000}, NONCE) == core.commit('{"v": 3000.00}', NONCE)
        assert core.commit({"v": Fraction(3000)}, NONCE) == core.commit({"v": 3000}, NONCE)
        assert core.commit({"v": Fraction(25, 2)}, NONCE) == core.commit('{"v": 12.50}', NONCE)

    def test_different_values_differ(self):
        assert (
            core.commit({"v": 3000}, NONCE).digest
            != core.commit({"v": Fraction(300001, 100)}, NONCE).digest
        )
        assert core.commit({"v": "3000"}, NONCE).digest != core.commit({"v": 3000}, NONCE).digest
        assert core.commit({"v": [1, 2]}, NONCE).digest != core.commit({"v": [2, 1]}, NONCE).digest

    def test_text_payload_is_json_text(self):
        with pytest.raises(core.InputError) as caught:
            core.commit("not json", NONCE)
        assert caught.value.field == "input"

    def test_lone_surrogate_is_an_input_error(self):
        lone = core.parse_input('"\\ud800"')
        with pytest.raises(core.InputError):
            core.commit({"name": lone}, NONCE)

    def test_floats_are_refused(self):
        with pytest.raises(TypeError):
            core.commit({"v": 1.5}, NONCE)


class TestFormat:
    def test_known_answer(self):
        # the digest is SHA-256 of "fsq-commit-v1", newline, nonce, newline, canonical JSON
        payload = {"a": [1, Fraction(5, 2)]}
        body = '{"a":[1,2.5]}'
        expected = hashlib.sha256(f"fsq-commit-v1\n{NONCE}\n{body}".encode()).hexdigest()
        assert core.commit(payload, NONCE).digest == expected
        assert expected == "c9d6b645630c31324b0a398fb7b580396b8b6b7bf7f734a7fa77af3be2c548fc"

    def test_unicode_payload_is_hashed_as_utf8(self):
        expected = hashlib.sha256(f'fsq-commit-v1\n{NONCE}\n{{"name":"阿明"}}'.encode()).hexdigest()
        assert core.commit({"name": "阿明"}, NONCE).digest == expected
