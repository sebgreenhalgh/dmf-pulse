"""Exact semantic comparisons against the frozen Pack 1.1 NRM-006 oracles."""

from __future__ import annotations

import json
import runpy
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

pytestmark = pytest.mark.golden

GOLDEN_NAMES = (
    "happy_path_consensus.json",
    "balanced_book.json",
    "heavy_favourite.json",
    "high_overround.json",
    "incomplete_book.json",
    "stale_mixed_books.json",
)


@pytest.fixture(scope="module")
def generated_projections(repository_root: Path) -> dict[str, dict[str, Any]]:
    namespace = runpy.run_path(str(repository_root / "scripts" / "verify_nrm006_goldens.py"))
    build = cast(
        Callable[[Path], dict[str, dict[str, Any]]],
        namespace["build_golden_projections"],
    )
    return build(repository_root)


@pytest.mark.parametrize("name", GOLDEN_NAMES)
def test_production_projection_matches_frozen_nrm006_oracle(
    repository_root: Path,
    generated_projections: dict[str, dict[str, Any]],
    name: str,
) -> None:
    expected = json.loads(
        (repository_root / "fixtures" / "odds" / "NRM-006" / "expected_outputs" / name).read_text(
            encoding="utf-8"
        )
    )
    assert generated_projections[name] == expected


def test_standalone_verifier_covers_every_required_golden(repository_root: Path) -> None:
    namespace = runpy.run_path(str(repository_root / "scripts" / "verify_nrm006_goldens.py"))
    verify = cast(Callable[[Path], dict[str, Any]], namespace["verify_goldens"])
    report = verify(repository_root)
    assert report["status"] == "PASS"
    assert report["network_requests"] == 0
    assert report["case_count"] == 6
    assert tuple(report["semantic_result_sha256"]) == GOLDEN_NAMES


def test_two_clean_plus_stale_canary_is_degraded_b_without_math_drift(
    repository_root: Path,
) -> None:
    namespace = runpy.run_path(str(repository_root / "scripts" / "verify_nrm006_goldens.py"))
    fixture = json.loads(
        (
            repository_root / "fixtures" / "contracts" / "MIN-007A" / "two_clean_plus_stale.json"
        ).read_text(encoding="utf-8")
    )
    expected = json.loads(
        (
            repository_root
            / "fixtures"
            / "contracts"
            / "MIN-007A"
            / "two_clean_plus_stale.expected.json"
        ).read_text(encoding="utf-8")
    )
    project = cast(Callable[..., dict[str, Any]], namespace["_consensus_projection"])
    actual = project(
        fixture,
        case_name="two_clean_plus_stale.json",
        policy=namespace["load_market_normalisation_policy"](),
    )
    assert actual == expected
    assert actual["status"] == "DEGRADED"
    assert actual["confidence_grade"] == "B"
    assert actual["eligible_operator_count"] == 2
    assert actual["excluded_books"] == [{"operator_key": "book_gamma", "reason": "STALE"}]
    assert actual["semantic_result_sha256"] == (
        "84c22958b67d2f7d578460c018b71755ec23477f0cef1368a9f68732a00b0790"
    )
