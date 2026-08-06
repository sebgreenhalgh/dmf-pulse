"""Database boundary for public market observation queries."""

from __future__ import annotations

from datetime import UTC, datetime

from dmf_pulse.database.engine import session_factory
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.service import (
    DATABASE_REF,
    _validate_database_reference,
)
from dmf_pulse.ingestion.fpl.service import (
    _engine as _fpl_database_engine,
)
from dmf_pulse.markets.consensus import evaluate_market_consensus
from dmf_pulse.markets.models import (
    ExclusionReason,
    ExclusiveOutcomeQuote,
    MarketNormalisationResult,
    MarketQueryResult,
    NormalisationStatus,
)
from dmf_pulse.markets.normalisation import code_identity
from dmf_pulse.markets.policy import (
    CONFIDENCE_GATE_POLICY_SHA256,
    canonical_json_sha256,
    load_market_normalisation_policy,
)
from dmf_pulse.markets.projection import market_normalisation_semantic_projection
from dmf_pulse.markets.repository import MarketObservationRepository


def _canonical_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    return value.astimezone(UTC)


class MarketService:
    def observations(
        self,
        *,
        fixture_external_provider: str,
        fixture_external_id: str,
        season_code: str,
        as_of: datetime,
        database_url_ref: str = DATABASE_REF,
    ) -> MarketQueryResult:
        _validate_database_reference(database_url_ref)
        engine = _fpl_database_engine(database_url_ref)
        try:
            factory = session_factory(engine)
            with factory() as session:
                repository = MarketObservationRepository(session)
                fixture_id = repository.resolve_fixture(
                    external_provider=fixture_external_provider,
                    external_id=fixture_external_id,
                    season_code=season_code,
                    as_of=as_of,
                )
                return repository.observations(fixture_id=fixture_id, as_of=as_of)
        finally:
            engine.dispose()

    def normalise(
        self,
        *,
        fixture_external_provider: str,
        fixture_external_id: str,
        season_code: str,
        as_of: datetime,
        database_url_ref: str = DATABASE_REF,
    ) -> MarketNormalisationResult:
        """Build and persist one exact stored-observation consensus; never use network."""

        _validate_database_reference(database_url_ref)
        cutoff = _canonical_utc(as_of)
        policy = load_market_normalisation_policy()
        engine = _fpl_database_engine(database_url_ref)
        try:
            factory = session_factory(engine)
            with factory.begin() as session:
                repository = MarketObservationRepository(session)
                try:
                    fixture_id = repository.resolve_fixture(
                        external_provider=fixture_external_provider,
                        external_id=fixture_external_id,
                        season_code=season_code,
                        as_of=cutoff,
                    )
                except IngestionError as exc:
                    if exc.code != "MAPPING_CONFLICT":
                        raise
                    return MarketNormalisationResult(
                        status=NormalisationStatus.BLOCKED,
                        fixture_id=None,
                        as_of=cutoff,
                        consensus=None,
                        excluded_books=(),
                        warnings=(),
                        error_code="MAPPING_UNAVAILABLE",
                    )
                normalisation_input = repository.normalisation_input(
                    fixture_id=fixture_id,
                    fixture_external_provider=fixture_external_provider,
                    fixture_external_id=fixture_external_id,
                    as_of=cutoff,
                    stale_after_seconds=policy.freshness.stale_after_seconds,
                )
                observations: list[ExclusiveOutcomeQuote] = []
                for observation in normalisation_input.eligible_observations:
                    if not isinstance(observation, ExclusiveOutcomeQuote):
                        raise IngestionError(
                            "CANONICAL_INVARIANT",
                            "market observation lacks immutable normalisation lineage",
                        )
                    observations.append(observation)
                evaluation = evaluate_market_consensus(
                    observations,
                    as_of=cutoff,
                    mapping_cutoff=cutoff,
                    policy=policy,
                    initial_exclusions=normalisation_input.exclusions,
                    initial_warnings=normalisation_input.warnings,
                )
                if evaluation.consensus is None:
                    eligibility_reasons = {
                        exclusion.reason for exclusion in normalisation_input.exclusions
                    }
                    blocking_reasons = {
                        ExclusionReason.MAPPING_UNAVAILABLE,
                        ExclusionReason.RIGHTS_BLOCKED,
                        ExclusionReason.QUALITY_BLOCKED,
                    }
                    wholly_blocked = (
                        bool(normalisation_input.exclusions)
                        and not observations
                        and eligibility_reasons <= blocking_reasons
                    )
                    if ExclusionReason.RIGHTS_BLOCKED in eligibility_reasons:
                        blocked_code = "RIGHTS_BLOCKED"
                    elif ExclusionReason.QUALITY_BLOCKED in eligibility_reasons:
                        blocked_code = "QUALITY_BLOCKED"
                    else:
                        blocked_code = "MAPPING_UNAVAILABLE"
                    result = MarketNormalisationResult(
                        status=(
                            NormalisationStatus.BLOCKED
                            if wholly_blocked
                            else NormalisationStatus.INSUFFICIENT
                        ),
                        fixture_id=fixture_id,
                        as_of=cutoff,
                        consensus=None,
                        excluded_books=evaluation.exclusions,
                        warnings=evaluation.warnings,
                        error_code=(
                            blocked_code if wholly_blocked else "NO_ELIGIBLE_COMPLETE_BOOK"
                        ),
                    )
                else:
                    degraded = bool(evaluation.exclusions or evaluation.warnings)
                    result = MarketNormalisationResult(
                        status=(
                            NormalisationStatus.DEGRADED
                            if degraded
                            else NormalisationStatus.NORMALISED
                        ),
                        fixture_id=fixture_id,
                        as_of=cutoff,
                        consensus=evaluation.consensus,
                        excluded_books=evaluation.exclusions,
                        warnings=evaluation.warnings,
                        error_code=None,
                    )
                canonical_mapping_cutoff = (
                    result.consensus.mapping_cutoff
                    if result.consensus is not None
                    else result.as_of
                )
                input_signature = canonical_json_sha256(
                    {
                        "as_of": result.as_of.isoformat(),
                        "code_identity": code_identity(),
                        "confidence_gate_policy_sha256": CONFIDENCE_GATE_POLICY_SHA256,
                        "consensus_input_signature_sha256": (
                            evaluation.consensus.input_signature_sha256
                            if evaluation.consensus is not None
                            else None
                        ),
                        "exclusions": [
                            exclusion.model_dump(mode="json") for exclusion in evaluation.exclusions
                        ],
                        "mapping_cutoff": canonical_mapping_cutoff.isoformat(),
                        "policy_sha256": policy.sha256,
                        "source_book_observation_ids": sorted(
                            str(item.book_observation_id)
                            for item in normalisation_input.source_books
                        ),
                        "source_observation_ids": sorted(
                            str(item.odds_observation_id)
                            for item in normalisation_input.source_observations
                        ),
                        "warnings": list(evaluation.warnings),
                    }
                )
                projection = market_normalisation_semantic_projection(result, policy=policy)
                semantic_hash = str(projection["semantic_result_sha256"])
                repository.persist_normalisation(
                    result=result,
                    policy=policy,
                    observations=normalisation_input.source_observations,
                    book_sources=normalisation_input.source_books,
                    input_signature_sha256=input_signature,
                    semantic_result_sha256=semantic_hash,
                )
                return result
        finally:
            engine.dispose()
