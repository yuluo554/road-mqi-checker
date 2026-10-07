"""确定性随机源：冻结向量 + 跨调用可复现。

向量是本地自算后写死的（不是外部标准的引用），作用是"改了实现必须能察觉"：
两个解释器（3.8 / 3.12）实测产出同一组数，才是基准跨机器可复现的前提。
"""

import pytest

from road_mqi_checker.bench import rng


SEED_ZERO_FIRST4 = (
    16294208416658607535,
    7960286522194355700,
    487617019471545679,
    17909611376780542444,
)
SEED_20261007_FIRST3 = (
    1533248557699214128,
    7189442517568447673,
    16666854780375651253,
)


def test_frozen_vectors():
    assert tuple(rng.stream(0, 4)) == SEED_ZERO_FIRST4
    assert tuple(rng.stream(20261007, 3)) == SEED_20261007_FIRST3


def test_two_instantiations_agree():
    assert rng.stream(1234, 50) == rng.stream(1234, 50)


def test_float_stream_is_reproducible():
    a = [rng.SplitMix64(9).next_float() for _ in range(5)]
    b = [rng.SplitMix64(9).next_float() for _ in range(5)]
    assert a == b
    assert all(0.0 <= value < 1.0 for value in a)


def test_next_below_bounds():
    generator = rng.SplitMix64(3)
    for _ in range(200):
        value = generator.next_below(7)
        assert 0 <= value < 7


def test_next_below_rejects_non_positive():
    with pytest.raises(ValueError):
        rng.SplitMix64(1).next_below(0)


def test_seed_must_be_non_negative_int():
    with pytest.raises(ValueError):
        rng.SplitMix64(-1)
    with pytest.raises(ValueError):
        rng.SplitMix64("7")


def test_choice_requires_non_empty():
    with pytest.raises(ValueError):
        rng.SplitMix64(1).choice([])


def test_sample_without_replacement_is_deterministic_and_unique():
    population = list(range(20))
    first = rng.SplitMix64(77).sample_without_replacement(population, 8)
    second = rng.SplitMix64(77).sample_without_replacement(population, 8)
    assert first == second
    assert len(set(first)) == 8


def test_sample_bounds_checked():
    with pytest.raises(ValueError):
        rng.SplitMix64(1).sample_without_replacement([1, 2], 3)


def test_state_advances_monotonically_modulo():
    generator = rng.SplitMix64(0)
    assert generator.next_u64() != generator.next_u64()
