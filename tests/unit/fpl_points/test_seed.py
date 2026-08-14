from __future__ import annotations

import math

import pytest

from dmf_pulse.fpl_points.seed import NamedRandom, derive_seed, rng_for, stable_identifier


def test_named_rng_primitives_are_deterministic_and_validate_parameters() -> None:
    first = NamedRandom(42)
    second = NamedRandom(42)
    assert first.random() == second.random()
    assert first.uniform(-2.0, 4.0) == second.uniform(-2.0, 4.0)
    assert first.randbelow(17) == second.randbelow(17)
    with pytest.raises(ValueError, match="upper bound"):
        first.randbelow(0)
    with pytest.raises(ValueError, match="binomial"):
        first.binomial(-1, 0.5)
    with pytest.raises(ValueError, match="binomial"):
        first.binomial(1, 1.1)
    assert NamedRandom(7).binomial(20, 0.0) == 0
    assert NamedRandom(7).binomial(20, 1.0) == 20


def test_shuffle_poisson_and_named_identifiers_cover_small_and_large_paths() -> None:
    values = [1, 2, 3, 4]
    NamedRandom(11).shuffle(values)
    assert sorted(values) == [1, 2, 3, 4]
    empty: list[int] = []
    NamedRandom(11).shuffle(empty)
    assert empty == []

    with pytest.raises(ValueError, match="Poisson mean"):
        NamedRandom(1).poisson(-1.0)
    with pytest.raises(ValueError, match="Poisson mean"):
        NamedRandom(1).poisson(math.inf)
    assert NamedRandom(1).poisson(0.0) == 0
    assert NamedRandom(1).poisson(2.0) >= 0
    large = [NamedRandom(seed).poisson(80.0) for seed in range(40)]
    assert all(type(value) is int and value >= 0 for value in large)
    assert len(set(large)) > 1

    assert derive_seed(9, "a") == derive_seed(9, "a")
    assert derive_seed(9, "a") != derive_seed(9, "b")
    assert rng_for(9, "a").random() == rng_for(9, "a").random()
    assert stable_identifier("pts", 9, "a") == stable_identifier("pts", 9, "a")
    assert stable_identifier("pts", 9, "a").startswith("pts-")
