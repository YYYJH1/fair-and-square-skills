"""Seed mapping: recorded golden values, an independent reimplementation of the
specification, rejection sampling, and sanity checks of uniformity."""

from __future__ import annotations

import hashlib
import json
from collections import Counter

import fsq_core as core
import pytest
from hypothesis import given
from hypothesis import strategies as st

PEOPLE8 = ["阿明", "小红", "大刘", "Coco", "老王", "Yuki", "小周", "Mia"]
SOURCE = "（虚构示例）2026-11-08 某公开开奖号码 03 11 19 24 33 + 02 07"
PEOPLE6 = ["阿明", "小红", "大刘", "Coco", "老王", "Yuki"]

# Recorded with Python 3.10.19, 3.12.14 and 3.13.17, which agree:
#   seed 15b9c53a44270857eb442863…  order Yuki 小周 大刘 Coco 小红 阿明 Mia 老王
RECORDED_SEED_PREFIX = "15b9c53a44270857eb442863"
RECORDED_ORDER = ["Yuki", "小周", "大刘", "Coco", "小红", "阿明", "Mia", "老王"]
RECORDED_WINNERS = ["Yuki", "小周", "大刘"]
FULL_SEED = "15b9c53a44270857eb44286382b897216eaecc0dcf18eb49260f7442cdf87710"


class TestGoldenValues:
    def test_seed_and_order_match_the_recorded_values(self):
        seed = core.make_seed("uniform_lottery_v1", PEOPLE8, 3, SOURCE)
        assert seed.hex().startswith(RECORDED_SEED_PREFIX)
        assert seed.hex() == FULL_SEED
        order = core.shuffle(PEOPLE8, core.SeedStream(seed))
        assert order == RECORDED_ORDER
        assert order[:3] == RECORDED_WINNERS

    def test_sample_and_draw_order(self):
        seed = core.make_seed("uniform_lottery_v1", PEOPLE8, 3, SOURCE)
        assert core.sample(PEOPLE8, 3, core.SeedStream(seed)) == RECORDED_WINNERS
        assert core.draw_order("uniform_lottery_v1", PEOPLE8, 3, SOURCE) == RECORDED_ORDER

    def test_first_raw_draws(self):
        stream = core.SeedStream(core.make_seed("uniform_lottery_v1", PEOPLE8, 3, SOURCE))
        assert [stream.next_u64() for _ in range(3)] == [
            16456245959887957854,
            14481196232767688859,
            9691579642667013697,
        ]
        assert stream.counter == 3

    def test_queue_order_for_the_random_serial_dictatorship_example(self):
        # recorded example: six people, four year-end slots
        seed = core.make_seed("rsd_v1", PEOPLE6, 4, SOURCE)
        assert seed.hex() == "eb68f25b704cc0b16d81364aa5b5857fb68694f339256eb8cd86851266aedd1c"
        assert core.shuffle(PEOPLE6, core.SeedStream(seed)) == [
            "阿明",
            "大刘",
            "Yuki",
            "Coco",
            "老王",
            "小红",
        ]

    def test_index_for_the_gift_exchange_example(self):
        # recorded example: the 92nd of 96 valid arrangements
        seed = core.make_seed("gift_exchange_v1", PEOPLE6, 0, SOURCE)
        assert seed.hex() == "9a42aecf9c28305cd426fff437b7132a9f3ee4aafd89919da97db84c90f6946f"
        assert core.SeedStream(seed).below(96) == 92


def spec_seed(rule, participants, n_slots, source):
    """Seed exactly as the specification words it, written with the standard json module."""
    text = json.dumps(
        {"rule": rule, "participants": sorted(participants), "n_slots": n_slots, "source": source},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(text.encode("utf-8")).digest()


def spec_order(seed, names):
    """Counter stream, rejection sampling and Fisher-Yates, reimplemented from the spec."""
    counter = 0

    def uniform_below(n):
        nonlocal counter
        while True:
            block = hashlib.sha256(seed + counter.to_bytes(8, "big")).digest()
            counter += 1
            x = int.from_bytes(block[:8], "big")
            if x < 2**64 - (2**64 % n):
                return x % n

    items = sorted(names)
    for i in range(len(items) - 1, 0, -1):
        j = uniform_below(i + 1)
        items[i], items[j] = items[j], items[i]
    return items


NAME_LISTS = st.lists(st.text(min_size=1, max_size=5), min_size=0, max_size=12, unique=True)


class TestAgainstTheSpecification:
    @given(
        st.text(min_size=1, max_size=20),
        NAME_LISTS,
        st.integers(0, 50),
        st.text(min_size=1, max_size=40).filter(lambda s: s.strip() != ""),
    )
    def test_seed_and_order_follow_the_spec(self, rule, names, n_slots, source):
        try:
            expected_seed = spec_seed(rule, names, n_slots, source)
        except UnicodeEncodeError:
            return  # lone surrogates cannot be hashed; covered by a separate test
        seed = core.make_seed(rule, names, n_slots, source)
        assert seed == expected_seed
        assert core.shuffle(names, core.SeedStream(seed)) == spec_order(seed, names)

    @given(NAME_LISTS, st.randoms(use_true_random=False))
    def test_result_does_not_depend_on_listing_order(self, names, rnd):
        listed = list(names)
        rnd.shuffle(listed)
        assert core.draw_order("r", listed, 1, "src") == core.draw_order("r", names, 1, "src")


class TestMakeSeed:
    def test_every_component_matters(self):
        base = core.make_seed("r", ["a", "b"], 1, "s")
        assert core.make_seed("r", ["b", "a"], 1, "s") == base  # order of listing is irrelevant
        assert core.make_seed("r2", ["a", "b"], 1, "s") != base
        assert core.make_seed("r", ["a", "c"], 1, "s") != base
        assert core.make_seed("r", ["a", "b", "c"], 1, "s") != base
        assert core.make_seed("r", ["a", "b"], 2, "s") != base
        assert core.make_seed("r", ["a", "b"], 1, "s2") != base
        assert core.make_seed("r", ["a", "b"], 1, "s ") != base  # source text is used verbatim

    @pytest.mark.parametrize(
        ("first", "second"),
        [
            (("r", ["ab", "c"], 1, "s"), ("r", ["a", "bc"], 1, "s")),
            (("r", ["a,b"], 1, "s"), ("r", ["a", "b"], 1, "s")),
            (("r", ["a"], 1, 's","n_slots":2'), ("r", ["a"], 2, "s")),
            (("r", ["a"], 1, "b"), ("r", [], 1, 'b","participants":["a')),
            (("rule", ["x"], 1, "s"), ("r", ["ule", "x"], 1, "s")),
        ],
    )
    def test_no_two_inputs_share_a_preimage(self, first, second):
        assert core.make_seed(*first) != core.make_seed(*second)

    def test_seed_is_32_bytes(self):
        seed = core.make_seed("r", ["a"], 1, "s")
        assert isinstance(seed, bytes) and len(seed) == 32

    @pytest.mark.parametrize(
        "args",
        [
            ("", ["a"], 1, "s"),
            ("r", ["a"], 1, ""),
            ("r", ["a"], 1, "   "),
            ("r", ["a", "a"], 1, "s"),
            ("r", ["a", 1], 1, "s"),
            ("r", ["a"], -1, "s"),
            ("r", ["a"], True, "s"),
            ("r", ["a"], 1.0, "s"),
            ("r", ["a"], 1, None),
        ],
    )
    def test_contract_violations(self, args):
        with pytest.raises(ValueError):
            core.make_seed(*args)

    def test_lone_surrogates_are_an_input_error(self):
        lone = core.parse_input('"\\ud800"')
        with pytest.raises(core.InputError):
            core.make_seed("r", [lone], 1, "s")
        with pytest.raises(core.InputError):
            core.make_seed("r", ["a"], 1, "src" + lone)


SLOT_PREIMAGE = (
    '{"n_slots":3,"participants":["Coco","Mia","Yuki","大刘","小周","小红","老王","阿明"],'
    '"rule":"uniform_lottery_v1","source":"（虚构示例）2026-11-08 某公开开奖号码 03 11 19 24 33 + 02 07"}'
)


class TestSeedPreimage:
    def test_it_is_the_canonical_json_of_the_four_inputs(self):
        assert core.seed_preimage("uniform_lottery_v1", PEOPLE8, 3, SOURCE) == SLOT_PREIMAGE

    def test_its_sha256_is_the_seed(self):
        preimage = core.seed_preimage("uniform_lottery_v1", PEOPLE8, 3, SOURCE)
        digest = hashlib.sha256(preimage.encode("utf-8")).digest()
        assert digest == core.make_seed("uniform_lottery_v1", PEOPLE8, 3, SOURCE)
        assert digest.hex() == FULL_SEED

    def test_it_follows_the_specification_whatever_the_listing_order(self):
        text = core.seed_preimage("r", ["b", "a"], 2, "s")
        assert text == json.dumps(
            {"rule": "r", "participants": ["a", "b"], "n_slots": 2, "source": "s"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @pytest.mark.parametrize(
        "args",
        [
            ("", ["a"], 1, "s"),
            ("r", ["a"], 1, ""),
            ("r", ["a"], 1, "   "),
            ("r", ["a", "a"], 1, "s"),
            ("r", ["a", 1], 1, "s"),
            ("r", ["a"], -1, "s"),
            ("r", ["a"], True, "s"),
            ("r", ["a"], 1.0, "s"),
            ("r", ["a"], 1, None),
        ],
    )
    def test_it_refuses_what_make_seed_refuses(self, args):
        with pytest.raises(ValueError):
            core.seed_preimage(*args)

    def test_the_source_text_is_used_verbatim(self):
        assert core.seed_preimage("r", ["a"], 1, " s ") != core.seed_preimage("r", ["a"], 1, "s")


class TestSeededOrder:
    def test_it_gives_the_order_the_seed_and_the_preimage_of_the_recorded_example(self):
        drawn = core.seeded_order("uniform_lottery_v1", PEOPLE8, 3, SOURCE)
        assert drawn.order == RECORDED_ORDER
        assert drawn.seed_hex == FULL_SEED
        assert drawn.preimage == SLOT_PREIMAGE

    def test_it_unpacks_as_a_triple(self):
        order, seed_hex, preimage = core.seeded_order("uniform_lottery_v1", PEOPLE8, 3, SOURCE)
        assert (order, seed_hex, preimage) == (RECORDED_ORDER, FULL_SEED, SLOT_PREIMAGE)

    @given(NAME_LISTS, st.randoms(use_true_random=False))
    def test_the_order_equals_draw_order_whatever_the_listing_order(self, names, rnd):
        listed = list(names)
        rnd.shuffle(listed)
        drawn = core.seeded_order("r", listed, 1, "src")
        assert drawn.order == core.draw_order("r", names, 1, "src")
        assert drawn.seed_hex == core.make_seed("r", names, 1, "src").hex()
        assert drawn.preimage == core.seed_preimage("r", names, 1, "src")

    def test_the_input_list_is_not_changed(self):
        names = ["b", "a", "c"]
        core.seeded_order("r", names, 1, "src")
        assert names == ["b", "a", "c"]

    def test_bad_input_is_refused_like_in_make_seed(self):
        with pytest.raises(ValueError):
            core.seeded_order("r", ["a", "a"], 1, "src")
        with pytest.raises(core.InputError):
            core.seeded_order("r", ["a" + core.parse_input('"\\ud800"')], 1, "src")


class Scripted(core.SeedStream):
    """A stream that replays chosen 64-bit values, to reach the rejection branch."""

    def __init__(self, values):
        super().__init__(bytes(32))
        self.values = list(values)
        self.used = 0

    def next_u64(self):
        self.used += 1
        return self.values.pop(0)


class TestSeedStream:
    def test_rejection_sampling_skips_the_biased_tail(self):
        # 2**64 mod 3 is 1, so only x = 2**64 - 1 is rejected for n = 3
        stream = Scripted([2**64 - 1, 5])
        assert stream.below(3) == 2
        assert stream.used == 2
        stream = Scripted([2**64 - 2])
        assert stream.below(3) == (2**64 - 2) % 3
        assert stream.used == 1

    def test_power_of_two_never_rejects(self):
        assert Scripted([2**64 - 1]).below(2**64) == 2**64 - 1
        stream = Scripted([2**64 - 1])
        assert stream.below(8) == 7 and stream.used == 1

    def test_n_equal_one_consumes_one_draw(self):
        stream = Scripted([12345])
        assert stream.below(1) == 0
        assert stream.used == 1

    @pytest.mark.parametrize("bad", [0, -3, True, 2.0, 2**64 + 1, None])
    def test_bad_bounds(self, bad):
        with pytest.raises(ValueError):
            core.SeedStream(bytes(32)).below(bad)

    @pytest.mark.parametrize("bad", [b"", bytes(31), bytes(33), "00" * 32, None])
    def test_bad_seed(self, bad):
        with pytest.raises(ValueError):
            core.SeedStream(bad)

    def test_from_hex_and_reproducibility(self):
        a = core.SeedStream.from_hex(FULL_SEED)
        b = core.SeedStream(bytes.fromhex(FULL_SEED))
        assert [a.below(100) for _ in range(20)] == [b.below(100) for _ in range(20)]

    @pytest.mark.parametrize("n", [10, 7])
    def test_values_are_uniform_enough(self, n):
        stream = core.SeedStream(core.make_seed("chi-square", ["a", "b"], 1, f"fixed source {n}"))
        draws = 20000
        counts = Counter(stream.below(n) for _ in range(draws))
        assert set(counts) == set(range(n))
        expected = draws / n
        chi2 = sum((counts[k] - expected) ** 2 / expected for k in range(n))
        # chi-square critical value at p = 0.0001: 33.7 for 9 degrees of freedom, 27.9 for 6
        assert chi2 < {10: 33.7, 7: 27.9}[n]

    def test_shuffles_of_three_are_uniform_enough(self):
        counts = Counter()
        trials = 6000
        for trial in range(trials):
            order = core.draw_order("chi-square-shuffle", ["a", "b", "c"], 0, f"source {trial}")
            counts["".join(order)] += 1
        assert len(counts) == 6
        expected = trials / 6
        chi2 = sum((count - expected) ** 2 / expected for count in counts.values())
        assert chi2 < 20.5  # p = 0.001 for 5 degrees of freedom

    def test_each_person_wins_about_k_over_n_of_the_time(self):
        wins = Counter()
        trials = 4000
        for trial in range(trials):
            wins.update(core.draw_order("share", PEOPLE8, 3, f"draw {trial}")[:3])
        for name in PEOPLE8:
            assert abs(wins[name] / trials - 3 / 8) < 0.05


class TestShuffleAndSample:
    @given(NAME_LISTS)
    def test_is_a_permutation_and_leaves_the_input_alone(self, names):
        original = list(names)
        out = core.shuffle(names, core.SeedStream(bytes(32)))
        assert names == original
        assert sorted(out) == sorted(original)
        assert isinstance(out, list)

    def test_small_cases(self):
        stream = core.SeedStream(bytes(32))
        assert core.shuffle([], stream) == []
        assert core.shuffle(["x"], stream) == ["x"]
        assert stream.counter == 0  # nothing to draw for fewer than two items

    def test_works_for_any_sortable_items(self):
        out = core.shuffle([3, 1, 2], core.SeedStream(bytes(32)))
        assert sorted(out) == [1, 2, 3]

    def test_sample_is_a_prefix_of_the_shuffle(self):
        for k in range(len(PEOPLE8) + 1):
            seed = core.make_seed("s", PEOPLE8, k, "src")
            assert (
                core.sample(PEOPLE8, k, core.SeedStream(seed))
                == core.shuffle(PEOPLE8, core.SeedStream(seed))[:k]
            )

    @pytest.mark.parametrize("k", [-1, 9, True, 2.0, None])
    def test_sample_bounds(self, k):
        with pytest.raises(ValueError):
            core.sample(PEOPLE8, k, core.SeedStream(bytes(32)))
