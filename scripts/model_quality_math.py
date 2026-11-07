"""Opt-in MQ000 finite-grid ordinal scores and PMF quantile contracts.

No accepted scorer, optimizer, source, metric registry or model is changed.
Inputs are exact bounded int/Decimal values; outputs use exact Fractions.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

METRIC_VERSION = "MQ000_FIXED_GRID_ORDINAL_RPS_V1"
SUMMARY_VERSION = "MQ000_LOWER_INVERSE_CDF_SUMMARY_V1"
MAX_CATEGORIES = 10000
MAX_DIGITS = 128
MAX_EXPONENT = 100


def _number(value: int | Decimal) -> Fraction:
    if type(value) is int:
        if abs(value) >= 10**MAX_DIGITS:
            raise ValueError("NUMERIC_SIZE_LIMIT")
        return Fraction(value)
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError("EXACT_FINITE_INT_OR_DECIMAL_REQUIRED")
    parts = value.as_tuple()
    if len(parts.digits) > MAX_DIGITS or abs(parts.exponent) > MAX_EXPONENT:
        raise ValueError("NUMERIC_SIZE_LIMIT")
    return Fraction(value)


def _pmf(value: Mapping[int | Decimal, int | Decimal]) -> tuple[tuple[Fraction, Fraction], ...]:
    if not 1 <= len(value) <= MAX_CATEGORIES:
        raise ValueError("BOUNDED_NONEMPTY_PMF_REQUIRED")
    rows = tuple(sorted((_number(key), _number(mass)) for key, mass in value.items()))
    if len({key for key, _ in rows}) != len(rows):
        raise ValueError("DUPLICATE_NUMERIC_SUPPORT")
    if any(not 0 <= mass <= 1 for _, mass in rows) or sum((p for _, p in rows), Fraction()) != 1:
        raise ValueError("EXACT_NORMALIZED_NONNEGATIVE_PMF_REQUIRED")
    return rows


@dataclass(frozen=True)
class FixedGridScore:
    metric_version: str
    target_grid: tuple[Fraction, ...]
    grid_sha256: str
    observed: Fraction
    score: Fraction


def fixed_grid_rps(
    pmf: Mapping[int | Decimal, int | Decimal],
    observed: int | Decimal,
    *,
    target_grid: Sequence[int | Decimal],
) -> FixedGridScore:
    """Unnormalized lower-is-better ordinal RPS on one declared common grid.

    Grid spacing has no weight: this is not point-distance CRPS. Zero-mass
    PMF keys outside the grid are rejected too. A singleton category is valid
    and scores zero. Undeclared observed categories fail; zero-probability
    observed categories inside the grid are valid. Grids cannot be compared
    interchangeably; the full grid and its versioned digest travel with score.
    """
    if not 1 <= len(target_grid) <= MAX_CATEGORIES:
        raise ValueError("BOUNDED_NONEMPTY_GRID_REQUIRED")
    grid = tuple(_number(x) for x in target_grid)
    if grid != tuple(sorted(set(grid))):
        raise ValueError("STRICTLY_INCREASING_GRID_REQUIRED")
    rows = _pmf(pmf)
    truth = _number(observed)
    grid_members = set(grid)
    if truth not in grid_members or any(x not in grid_members for x, _ in rows):
        raise ValueError("DECLARED_TARGET_GRID_MEMBERSHIP_REQUIRED")
    probabilities = dict(rows)
    cumulative = Fraction()
    score = Fraction()
    for threshold in grid[:-1]:
        cumulative += probabilities.get(threshold, Fraction())
        score += (cumulative - int(truth <= threshold)) ** 2
    encoded = json.dumps(
        {"version": METRIC_VERSION, "grid": [[x.numerator, x.denominator] for x in grid]},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return FixedGridScore(METRIC_VERSION, grid, hashlib.sha256(encoded).hexdigest(), truth, score)


def paired_rps_delta(challenger: FixedGridScore, champion: FixedGridScore) -> Fraction:
    """Compare the same outcome/grid/version; negative favors the challenger."""
    if (
        challenger.metric_version != champion.metric_version
        or challenger.metric_version != METRIC_VERSION
        or challenger.target_grid != champion.target_grid
        or challenger.grid_sha256 != champion.grid_sha256
        or challenger.observed != champion.observed
    ):
        raise ValueError("SAME_VERSION_GRID_AND_OBSERVATION_REQUIRED")
    return challenger.score - champion.score


@dataclass(frozen=True)
class PmfSummary:
    contract_version: str
    mean: Fraction
    p10: Fraction
    p50: Fraction
    p90: Fraction


def summarize_pmf(pmf: Mapping[int | Decimal, int | Decimal]) -> PmfSummary:
    """Derive finite mean and inclusive lower inverse-CDF quantiles exactly.

    No mean/quantile monotonicity assumption is made. In particular a rare
    sufficiently large tail can place the mean above p90 or below p10.
    """
    rows = _pmf(pmf)
    mean = sum((x * p for x, p in rows), Fraction())
    quantiles = []
    for alpha in (Fraction(1, 10), Fraction(1, 2), Fraction(9, 10)):
        cumulative = Fraction()
        for x, p in rows:
            cumulative += p
            if cumulative >= alpha:
                quantiles.append(x)
                break
    p10, p50, p90 = quantiles
    if not p10 <= p50 <= p90:
        raise ArithmeticError("INVERSE_CDF_ORDERING_BROKEN")
    return PmfSummary(SUMMARY_VERSION, mean, p10, p50, p90)


def main() -> None:
    """Explicitly requested owned algebraic demonstration; no model or data call."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owned-demonstration", action="store_true")
    args = parser.parse_args()
    if not args.owned_demonstration:
        parser.error("explicit --owned-demonstration required")
    score = fixed_grid_rps({0: Decimal(".5"), 2: Decimal(".5")}, 1, target_grid=(0, 1, 2))
    padded = fixed_grid_rps({0: Decimal(".5"), 1: 0, 2: Decimal(".5")}, 1, target_grid=(0, 1, 2))
    tail = summarize_pmf({0: Decimal(".99"), 100: Decimal(".01")})
    print(
        json.dumps(
            {
                "metric_version": score.metric_version,
                "target_grid": [str(x) for x in score.target_grid],
                "grid_sha256": score.grid_sha256,
                "score": str(score.score),
                "zero_key_invariant": score == padded,
                "summary_version": tail.contract_version,
                "rare_tail_mean": str(tail.mean),
                "rare_tail_p90": str(tail.p90),
                "production_or_historical_metric_changed": False,
                "predictive_accuracy_claim": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
