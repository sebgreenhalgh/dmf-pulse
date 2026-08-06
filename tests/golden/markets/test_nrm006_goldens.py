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
