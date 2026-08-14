"""Hierarchical, partition-invariant deterministic seed lineage."""

from __future__ import annotations

import hashlib
import math
import random
from collections.abc import MutableSequence
from typing import Literal, TypeVar

RNG_ALGORITHM: Literal["python-mt19937-pts-v1"] = "python-mt19937-pts-v1"
T = TypeVar("T")


def derive_seed(root_seed: int, *namespace: object) -> int:
    encoded = "\x1f".join([str(root_seed), *(str(item) for item in namespace)]).encode("utf-8")
    digest = hashlib.sha256(encoded).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


class NamedRandom:
    """Small frozen RNG surface used by PTS-009 without a NumPy dependency.

    The wrapper fixes every distribution algorithm used by Stage 9.  A named SHA-256
    child seed makes the semantic draw independent of batching and worker order.
    """

    def __init__(self, seed: int) -> None:
        self._random = random.Random(seed)

    def random(self) -> float:
        return self._random.getrandbits(53) / float(1 << 53)

    def randbelow(self, upper: int) -> int:
        if upper <= 0:
            raise ValueError("upper bound must be positive")
        return self._random.randrange(upper)

    def uniform(self, lower: float, upper: float) -> float:
        return lower + (upper - lower) * self.random()

    def shuffle(self, values: MutableSequence[T]) -> None:
        for index in range(len(values) - 1, 0, -1):
            selected = self.randbelow(index + 1)
            values[index], values[selected] = values[selected], values[index]

    def binomial(self, trials: int, probability: float) -> int:
        if trials < 0 or not 0.0 <= probability <= 1.0:
            raise ValueError("binomial parameters are invalid")
        return sum(self.random() < probability for _ in range(trials))

    def poisson(self, mean: float) -> int:
        if mean < 0.0 or not math.isfinite(mean):
            raise ValueError("Poisson mean must be finite and non-negative")
        if mean == 0.0:
            return 0
        if mean < 30.0:
            threshold = math.exp(-mean)
            product = 1.0
            count = 0
            while product > threshold:
                count += 1
                product *= self.random()
            return count - 1

        # Hörmann transformed rejection (PTRS), fixed here for reproducibility.
        square_root = math.sqrt(mean)
        b = 0.931 + 2.53 * square_root
        a = -0.059 + 0.02483 * b
        inverse_alpha = 1.1239 + 1.1328 / (b - 3.4)
        squeeze = 0.9277 - 3.6224 / (b - 2.0)
        while True:
            centered = self.random() - 0.5
            uniform = self.random()
            distance = 0.5 - abs(centered)
            candidate = math.floor((2.0 * a / distance + b) * centered + mean + 0.43)
            if distance >= 0.07 and uniform <= squeeze:
                return candidate
            if candidate < 0 or (distance < 0.013 and uniform > distance):
                continue
            left = math.log(uniform * inverse_alpha / (a / (distance * distance) + b))
            right = -mean + candidate * math.log(mean) - math.lgamma(candidate + 1.0)
            if left <= right:
                return candidate


def rng_for(root_seed: int, *namespace: object) -> NamedRandom:
    return NamedRandom(derive_seed(root_seed, *namespace))


def stable_identifier(prefix: str, root_seed: int, *namespace: object) -> str:
    encoded = "\x1f".join([prefix, str(root_seed), *(str(item) for item in namespace)]).encode(
        "utf-8"
    )
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"
