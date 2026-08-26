"""Manager fact, price, lineup, and determinism tests for CURRENT-FPL-STATE-001C."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from dmf_pulse.fpl_points.models import ProjectionMode
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.rules.multi_gameweek import build_multi_gameweek_transfer_rules
from tests.unit.ingestion.current_manager_test_support import (
    CurrentManagerTestContext,
    build_context,
    compile_manager,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def context(repository_root: Path, tmp_path: Path) -> CurrentManagerTestContext:
    return build_context(repository_root, tmp_path)


def _changed(
    context: CurrentManagerTestContext,
    mutate: Callable[[dict[str, Any]], None],
) -> dict[str, Any]:
    value = deepcopy(context.declaration)
    mutate(value)
    return value


def _fails(context: CurrentManagerTestContext, value: object, code: str) -> None:
    with pytest.raises(IngestionError) as caught:
        compile_manager(context, value)
    assert caught.value.code == code
    assert "synthetic-operator" not in caught.value.message


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda value: value["squad"].pop(), "VALIDATION_FAILED"),
        (
            lambda value: value["squad"].append(
                {
                    "official_fpl_element_id": 116,
                    "purchase_price_tenths": 65,
                    "observed_selling_price_tenths": 65,
                }
            ),
            "VALIDATION_FAILED",
        ),
        (
            lambda value: value["squad"].__setitem__(1, deepcopy(value["squad"][0])),
            "VALIDATION_FAILED",
        ),
        (
            lambda value: value["squad"][0].__setitem__("official_fpl_element_id", 9999),
            "MAPPING_CONFLICT",
        ),
        (
            lambda value: value["squad"][2].update(
                {
                    "official_fpl_element_id": 118,
                    "purchase_price_tenths": 67,
                    "observed_selling_price_tenths": 67,
                }
            ),
            "VALIDATION_FAILED",
        ),
        (
            lambda value: value["squad"][1].update(
                {
                    "official_fpl_element_id": 116,
                    "purchase_price_tenths": 65,
                    "observed_selling_price_tenths": 65,
                }
            ),
            "VALIDATION_FAILED",
        ),
        (lambda value: value.__setitem__("season_code", "2025/26"), "VALIDATION_FAILED"),
        (lambda value: value.__setitem__("target_gameweek", 3), "MAPPING_CONFLICT"),
    ],
    ids=(
        "fourteen-players",
        "sixteen-players",
        "duplicate-player",
        "unknown-player",
        "position-quota",
        "club-quota",
        "wrong-season",
        "wrong-gameweek",
    ),
)
def test_illegal_squad_declarations_fail_closed(
    context: CurrentManagerTestContext,
    mutate: Callable[[dict[str, Any]], None],
    code: str,
) -> None:
    _fails(context, _changed(context, mutate), code)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["squad"][0].__setitem__("purchase_price_tenths", 50.0),
        lambda value: value["squad"][0].__setitem__("purchase_price_tenths", -1),
        lambda value: value["squad"][0].pop("purchase_price_tenths"),
        lambda value: value["squad"][0].__setitem__("current_price_tenths", 999),
        lambda value: value["squad"][0].__setitem__("observed_selling_price_tenths", 49),
        lambda value: value.__setitem__("bank_tenths", -1),
        lambda value: value.__setitem__("bank_tenths", 1.5),
        lambda value: value.__setitem__("free_transfers", -1),
        lambda value: value.__setitem__("free_transfers", 1.0),
    ],
    ids=(
        "float-purchase",
        "negative-purchase",
        "missing-purchase",
        "operator-current-price",
        "wrong-selling-price",
        "negative-bank",
        "float-bank",
        "negative-ft",
        "float-ft",
    ),
)
def test_invalid_price_bank_and_ft_shapes_are_rejected(
    context: CurrentManagerTestContext,
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    _fails(context, _changed(context, mutate), "VALIDATION_FAILED")


def test_free_transfers_cannot_exceed_active_rule_maximum(
    context: CurrentManagerTestContext,
) -> None:
    maximum = build_multi_gameweek_transfer_rules(
        context.ruleset,
        projection_mode=ProjectionMode.PRODUCTION,
        capability=context.capability,
    ).maximum_free_transfers
    value = _changed(context, lambda item: item.__setitem__("free_transfers", maximum + 1))
    _fails(context, value, "VALIDATION_FAILED")


@pytest.mark.parametrize(
    ("purchase", "expected"),
    [(46, 48), (47, 48), (54, 50), (50, 50)],
    ids=("even-rise", "odd-rise", "fall", "unchanged"),
)
def test_selling_prices_use_the_accepted_rules_function(
    context: CurrentManagerTestContext,
    purchase: int,
    expected: int,
) -> None:
    value = deepcopy(context.declaration)
    value["squad"][0]["purchase_price_tenths"] = purchase
    value["squad"][0]["observed_selling_price_tenths"] = expected
    bundle = compile_manager(context, value)
    assert bundle.squad[0].current_price_tenths == 50
    assert bundle.squad[0].purchase_price_tenths == purchase
    assert bundle.squad[0].selling_price_tenths == expected


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["lineup"]["starting_xi_element_ids"].pop(),
        lambda value: value["lineup"]["starting_xi_element_ids"].__setitem__(0, 9999),
        lambda value: value["lineup"]["bench_outfield_element_ids"].__setitem__(0, 101),
        lambda value: value["lineup"]["bench_outfield_element_ids"].pop(),
        lambda value: value["lineup"]["bench_outfield_element_ids"].__setitem__(1, 107),
        lambda value: value["lineup"].update(
            {
                "starting_xi_element_ids": [
                    101,
                    102,
                    103,
                    104,
                    105,
                    106,
                    108,
                    109,
                    110,
                    113,
                    114,
                ],
                "bench_goalkeeper_element_id": 107,
                "bench_outfield_element_ids": [111, 112, 115],
            }
        ),
        lambda value: value["lineup"].__setitem__("captain_element_id", 107),
        lambda value: value["lineup"].__setitem__("vice_captain_element_id", 112),
        lambda value: value["lineup"].__setitem__("vice_captain_element_id", 108),
    ],
    ids=(
        "wrong-xi-size",
        "outsider-starter",
        "starter-also-benched",
        "incomplete-partition",
        "duplicate-bench",
        "illegal-formation",
        "captain-on-bench",
        "vice-on-bench",
        "captain-equals-vice",
    ),
)
def test_invalid_lineup_and_captaincy_are_rejected(
    context: CurrentManagerTestContext,
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    _fails(context, _changed(context, mutate), "VALIDATION_FAILED")


def test_optional_points_and_rank_remain_operator_declared_and_optional(
    context: CurrentManagerTestContext,
) -> None:
    absent = compile_manager(context)
    assert absent.overall_points is None
    assert absent.overall_rank is None

    value = deepcopy(context.declaration)
    value["overall_points"] = 123
    value["overall_rank"] = 4567
    present = compile_manager(context, value, name="manager-with-rank.json")
    assert present.overall_points == 123
    assert present.overall_rank == 4567
    assert present.provider_verification == "NOT_PROVIDER_VERIFIED"


def test_nonsemantic_input_order_is_canonical_but_bench_order_is_semantic(
    context: CurrentManagerTestContext,
) -> None:
    baseline = compile_manager(context, name="baseline.json")
    reordered = deepcopy(context.declaration)
    reordered["squad"].reverse()
    reordered["lineup"]["starting_xi_element_ids"].reverse()
    reordered["chip_tokens"].reverse()
    canonical = compile_manager(context, reordered, name="reordered.json")
    assert canonical == baseline

    bench_reordered = deepcopy(context.declaration)
    bench_reordered["lineup"]["bench_outfield_element_ids"] = [115, 112, 107]
    changed = compile_manager(context, bench_reordered, name="bench-reordered.json")
    assert changed.lineup.bench_outfield_element_ids == (115, 112, 107)
    assert changed.lineage.manager_declaration_semantic_sha256 != (
        baseline.lineage.manager_declaration_semantic_sha256
    )
    assert changed.semantic_sha256 != baseline.semantic_sha256
