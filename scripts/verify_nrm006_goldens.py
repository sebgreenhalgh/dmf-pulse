"""Verify every frozen NRM-006 mathematical golden without network or writes."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from dmf_pulse.markets.consensus import evaluate_market_consensus
from dmf_pulse.markets.models import (
    ExclusiveOutcomeQuote,
    MarketNormalisationResult,
    MarketOutcome,
    MarketState,
    NormalisationMethod,
    NormalisationStatus,
    NormalisedOperatorMarket,
    source_decimal_text,
)
from dmf_pulse.markets.normalisation import normalise_complete_market
from dmf_pulse.markets.policy import (
    MarketNormalisationPolicy,
    canonical_json_sha256,
    load_market_normalisation_policy,
)
from dmf_pulse.markets.projection import market_normalisation_semantic_projection

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPOSITORY_ROOT / "fixtures" / "odds" / "NRM-006"
EXPECTED_ROOT = FIXTURE_ROOT / "expected_outputs"
PROVIDER_ID = UUID("00000000-0000-7000-8000-000000000901")
GOLDEN_NAMES = (
    "happy_path_consensus.json",
    "balanced_book.json",
    "heavy_favourite.json",
    "high_overround.json",
    "incomplete_book.json",
    "stale_mixed_books.json",
)


class GoldenVerificationError(Exception):
    """A bounded, deterministic NRM-006 golden mismatch."""


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda constant: (_ for _ in ()).throw(ValueError(constant)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise GoldenVerificationError(f"frozen JSON is unavailable: {path.name}") from exc
    if not isinstance(value, dict):
        raise GoldenVerificationError(f"frozen JSON root is not an object: {path.name}")
    return value


def _instant(value: object, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise GoldenVerificationError(f"frozen {field} is not a timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GoldenVerificationError(f"frozen {field} is not a timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GoldenVerificationError(f"frozen {field} is not UTC-aware")
    return parsed.astimezone(UTC)


def _stable_uuid(label: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"dmf-pulse:nrm-006:{label}")


def _query_quotes(fixture: dict[str, Any], *, case_name: str) -> tuple[ExclusiveOutcomeQuote, ...]:
    books = fixture.get("books")
    if not isinstance(books, list):
        raise GoldenVerificationError(f"{case_name} has no frozen books")
    quotes: list[ExclusiveOutcomeQuote] = []
    for book_index, book in enumerate(books):
        if not isinstance(book, dict):
            raise GoldenVerificationError(f"{case_name} contains a malformed book")
        operator_key = book.get("operator_key")
        observations = book.get("observations")
        if not isinstance(operator_key, str) or not isinstance(observations, list):
            raise GoldenVerificationError(f"{case_name} contains a malformed book")
        book_observation_id = _stable_uuid(f"{case_name}:book:{book_index}")
        for outcome_index, observation in enumerate(observations):
            if not isinstance(observation, dict):
                raise GoldenVerificationError(f"{case_name} contains a malformed observation")
            try:
                fixture_id = UUID(str(observation["fixture_id"]))
                market_id = UUID(str(observation["market_id"]))
                selection_id = UUID(str(observation["selection_id"]))
                operator_id = UUID(str(observation["operator_id"]))
                outcome = MarketOutcome(str(observation["outcome"]))
                observed_at = _instant(observation["observed_at"], field="observed_at")
                received_at = _instant(observation["received_at"], field="received_at")
                usable_at = _instant(observation["usable_at"], field="usable_at")
                source_snapshot_id = UUID(str(observation["source_snapshot_id"]))
                market_state = MarketState(str(observation["market_state"]))
                decimal_odds = observation["decimal_odds"]
                contract_version = observation["contract_version"]
            except (KeyError, TypeError, ValueError) as exc:
                raise GoldenVerificationError(
                    f"{case_name} contains a malformed observation"
                ) from exc
            quotes.append(
                ExclusiveOutcomeQuote(
                    fixture_id=fixture_id,
                    market_id=market_id,
                    selection_id=selection_id,
                    operator_id=operator_id,
                    outcome=outcome,
                    decimal_odds=decimal_odds,
                    observed_at=observed_at,
                    received_at=received_at,
                    usable_at=usable_at,
                    source_snapshot_id=source_snapshot_id,
                    market_state=market_state,
                    contract_version=contract_version,
                    book_observation_id=book_observation_id,
                    odds_observation_id=_stable_uuid(
                        f"{case_name}:book:{book_index}:outcome:{outcome_index}"
                    ),
                    provider_id=PROVIDER_ID,
                    operator_key=operator_key,
                )
            )
    return tuple(quotes)


def _math_quotes(
    fixture: dict[str, Any],
    *,
    case_name: str,
    state: MarketState = MarketState.COMPLETE,
) -> tuple[ExclusiveOutcomeQuote, ...]:
    operator_key = fixture.get("operator_key")
    odds = fixture.get("odds")
    if not isinstance(operator_key, str) or not isinstance(odds, dict):
        raise GoldenVerificationError(f"{case_name} is not a mathematical book fixture")
    observed_at = _instant(fixture.get("observed_at"), field="observed_at")
    fixture_id = _stable_uuid(f"{case_name}:fixture")
    market_id = _stable_uuid(f"{case_name}:market")
    operator_id = _stable_uuid(f"{case_name}:operator")
    book_observation_id = _stable_uuid(f"{case_name}:book")
    snapshot_id = _stable_uuid(f"{case_name}:snapshot")
    quotes: list[ExclusiveOutcomeQuote] = []
    for index, outcome in enumerate(MarketOutcome):
        decimal_odds = odds.get(outcome.value)
        if decimal_odds is None:
            continue
        quotes.append(
            ExclusiveOutcomeQuote(
                fixture_id=fixture_id,
                market_id=market_id,
                selection_id=_stable_uuid(f"{case_name}:selection:{index}"),
                operator_id=operator_id,
                outcome=outcome,
                decimal_odds=decimal_odds,
                observed_at=observed_at,
                received_at=observed_at,
                usable_at=observed_at,
                source_snapshot_id=snapshot_id,
                market_state=state,
                contract_version="the-odds-api-v4-reference-v1",
                book_observation_id=book_observation_id,
                odds_observation_id=_stable_uuid(f"{case_name}:observation:{index}"),
                provider_id=PROVIDER_ID,
                operator_key=operator_key,
            )
        )
    return tuple(quotes)


def _operator_projection(result: NormalisedOperatorMarket) -> dict[str, Any]:
    return {
        "operator_key": result.operator_key,
        "raw_booksum": format(result.raw_booksum, ".12f"),
        "overround": format(result.overround, ".12f"),
        "power_exponent": (
            format(result.power_exponent, ".12f") if result.power_exponent is not None else None
        ),
        "outcomes": [
            {
                "outcome": outcome.outcome.value,
                "decimal_odds": source_decimal_text(outcome.decimal_odds),
                "raw_implied_probability": format(outcome.raw_implied_probability, ".12f"),
                "proportional_probability": format(outcome.proportional_probability, ".12f"),
                "market_probability": format(outcome.market_probability, ".12f"),
            }
            for outcome in result.outcomes
        ],
    }


def _single_book_projection(
    fixture: dict[str, Any],
    *,
    case_name: str,
    policy: MarketNormalisationPolicy,
) -> dict[str, Any]:
    result = normalise_complete_market(
        _math_quotes(fixture, case_name=case_name),
        NormalisationMethod.POWER,
        policy,
    )
    projected: dict[str, Any] = {
        "status": "NORMALISED",
        "policy_id": policy.policy_id,
        "policy_sha256": policy.sha256,
        "operator_market": _operator_projection(result),
    }
    projected["semantic_result_sha256"] = canonical_json_sha256(projected)
    return projected


def _consensus_projection(
    fixture: dict[str, Any],
    *,
    case_name: str,
    policy: MarketNormalisationPolicy,
) -> dict[str, Any]:
    as_of = _instant(fixture.get("as_of"), field="as_of")
    quotes = _query_quotes(fixture, case_name=case_name)
    evaluation = evaluate_market_consensus(
        quotes,
        as_of=as_of,
        mapping_cutoff=as_of,
        policy=policy,
    )
    if evaluation.consensus is None:
        status = NormalisationStatus.INSUFFICIENT
        error_code = "NO_ELIGIBLE_COMPLETE_BOOK"
    else:
        status = (
            NormalisationStatus.DEGRADED
            if evaluation.exclusions or evaluation.warnings
            else NormalisationStatus.NORMALISED
        )
        error_code = None
    result = MarketNormalisationResult(
        status=status,
        fixture_id=quotes[0].fixture_id if quotes else None,
        as_of=as_of,
        consensus=evaluation.consensus,
        excluded_books=evaluation.exclusions,
        warnings=evaluation.warnings,
        error_code=error_code,
    )
    return market_normalisation_semantic_projection(result, policy=policy)


def _incomplete_projection(
    fixture: dict[str, Any], *, policy: MarketNormalisationPolicy
) -> dict[str, Any]:
    as_of = _instant(fixture.get("as_of"), field="as_of")
    quotes = _math_quotes(
        fixture,
        case_name="incomplete_book",
        state=MarketState.INCOMPLETE,
    )
    evaluation = evaluate_market_consensus(
        quotes,
        as_of=as_of,
        mapping_cutoff=as_of,
        policy=policy,
    )
    result = MarketNormalisationResult(
        status=NormalisationStatus.INSUFFICIENT,
        fixture_id=quotes[0].fixture_id,
        as_of=as_of,
        consensus=evaluation.consensus,
        excluded_books=evaluation.exclusions,
        warnings=evaluation.warnings,
        error_code="NO_ELIGIBLE_COMPLETE_BOOK",
    )
    return market_normalisation_semantic_projection(result, policy=policy)


def build_golden_projections(repository_root: Path = REPOSITORY_ROOT) -> dict[str, dict[str, Any]]:
    """Build the six stable semantic projections through production code."""

    fixture_root = repository_root / "fixtures" / "odds" / "NRM-006"
    policy_fixture = _read_object(fixture_root / "normalisation_policy.json")
    policy = load_market_normalisation_policy()
    if canonical_json_sha256(policy_fixture) != policy.sha256:
        raise GoldenVerificationError("frozen fixture policy differs from the wheel policy")
    projections = {
        "happy_path_consensus.json": _consensus_projection(
            _read_object(fixture_root / "happy_path_market_query.json"),
            case_name="happy_path",
            policy=policy,
        ),
        "balanced_book.json": _single_book_projection(
            _read_object(fixture_root / "balanced_book.json"),
            case_name="balanced_book",
            policy=policy,
        ),
        "heavy_favourite.json": _single_book_projection(
            _read_object(fixture_root / "heavy_favourite.json"),
            case_name="heavy_favourite",
            policy=policy,
        ),
        "high_overround.json": _single_book_projection(
            _read_object(fixture_root / "high_overround.json"),
            case_name="high_overround",
            policy=policy,
        ),
        "incomplete_book.json": _incomplete_projection(
            _read_object(fixture_root / "incomplete_book.json"), policy=policy
        ),
        "stale_mixed_books.json": _consensus_projection(
            _read_object(fixture_root / "stale_mixed_books.json"),
            case_name="stale_mixed_books",
            policy=policy,
        ),
    }
    if tuple(projections) != GOLDEN_NAMES:
        raise GoldenVerificationError("golden case set differs from the frozen contract")
    return projections


def verify_goldens(repository_root: Path = REPOSITORY_ROOT) -> dict[str, Any]:
    """Compare all production projections to immutable Pack 1.1 expected outputs."""

    expected_root = repository_root / "fixtures" / "odds" / "NRM-006" / "expected_outputs"
    actual = build_golden_projections(repository_root)
    hashes: dict[str, str] = {}
    for name in GOLDEN_NAMES:
        expected = _read_object(expected_root / name)
        expected_hash = expected.get("semantic_result_sha256")
        expected_material = dict(expected)
        expected_material.pop("semantic_result_sha256", None)
        if expected_hash != canonical_json_sha256(expected_material):
            raise GoldenVerificationError(f"frozen semantic hash is invalid: {name}")
        if actual[name] != expected:
            raise GoldenVerificationError(
                f"production semantic projection differs from frozen oracle: {name}"
            )
        hashes[name] = str(expected_hash)
    return {
        "case_count": len(GOLDEN_NAMES),
        "network_requests": 0,
        "semantic_result_sha256": hashes,
        "status": "PASS",
    }


def main() -> int:
    try:
        report = verify_goldens()
    except GoldenVerificationError as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, sort_keys=True))
        return 1
    except Exception as exc:
        print(
            json.dumps(
                {
                    "error": f"NRM-006 golden verification failed ({type(exc).__name__})",
                    "status": "FAIL",
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
