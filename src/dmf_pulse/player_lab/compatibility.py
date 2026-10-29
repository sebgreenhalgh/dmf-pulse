"""Versioned documentation compatibility and an expiring future-cohort proposal.

Public textual rules establish meanings, not the undocumented HTTP JSON schema
or a licence. Nothing in this module authorizes acquisition or retention.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from dmf_pulse.player_lab.actuals import IDENTIFIERS, FinalityContext, parse_actuals
from dmf_pulse.player_lab.contracts import Sealed, seal


class ActualsCompatibility(Sealed):
    schema_version: Literal["player-actuals-compatibility-proposal-v2"] = (
        "player-actuals-compatibility-proposal-v2"
    )
    season: Literal["2026/27"] = "2026/27"
    status: Literal["OFFLINE_CANDIDATE_NOT_LIVE_SCHEMA_OBSERVED"] = (
        "OFFLINE_CANDIDATE_NOT_LIVE_SCHEMA_OBSERVED"
    )
    observed_live_schema: Literal[False] = False
    acquisition_authorized: Literal[False] = False
    real_retention_authorized: Literal[False] = False
    candidate_schema: Literal["offline-fpl-gw-actuals-candidate-v1"] = (
        "offline-fpl-gw-actuals-candidate-v1"
    )
    official_identifiers: tuple[str, ...]
    finality_policy: Literal["FPL_2026_27_NEXT_DAY_0900_LONDON_V1"] = (
        "FPL_2026_27_NEXT_DAY_0900_LONDON_V1"
    )
    textual_sources: tuple[str, ...] = (
        "https://fantasy.premierleague.com/help/new",
        "https://www.premierleague.com/en/news/2174909/",
        "https://www.premierleague.com/en/news/4361991",
    )
    source_observation: Literal["OFFICIAL_INDEXED_HTML_NOT_PROVIDER_JSON"] = (
        "OFFICIAL_INDEXED_HTML_NOT_PROVIDER_JSON"
    )
    unresolved_live_schema: tuple[str, ...] = (
        "Exact fields, types and additive stats in the live response.",
        "Whether zero-valued explain components are sparse or explicit.",
        "Exact defensive_contribution identifier and count semantics.",
        "Availability of independent observed-start labels.",
        "Blank/double Gameweek encoding and possible fixture-count ceiling.",
        "Player identity and fixture attribution after a club transfer.",
        "Authoritative event checked/final markers and extraordinary correction publication.",
    )
    sparse_policy: Literal["BLOCK_NO_ZERO_IMPUTATION"] = "BLOCK_NO_ZERO_IMPUTATION"
    correction_policy: Literal["APPEND_ONLY_NO_MIXED_VINTAGES"] = "APPEND_ONLY_NO_MIXED_VINTAGES"


class CompatibilityCheck(Sealed):
    schema_version: Literal["player-offline-compatibility-check-v1"] = (
        "player-offline-compatibility-check-v1"
    )
    proposal_sha256: str
    candidate_schema_match: Literal[True] = True
    observed_live_schema: Literal[False] = False
    retention_authorized: Literal[False] = False
    expected_players: int
    matched_players: int
    interpretation: Literal["STRUCTURAL_CHECK_ONLY_SOURCE_QUALIFICATION_STILL_REQUIRED"] = (
        "STRUCTURAL_CHECK_ONLY_SOURCE_QUALIFICATION_STILL_REQUIRED"
    )


def actuals_compatibility_proposal() -> ActualsCompatibility:
    return seal(
        ActualsCompatibility.model_construct(
            official_identifiers=tuple(sorted(IDENTIFIERS)), semantic_sha256="0" * 64
        )
    )


def check_offline_compatibility(body: bytes, context: FinalityContext) -> CompatibilityCheck:
    """A structural match never changes source eligibility or admits a live route."""
    result = parse_actuals(body, context)
    return seal(
        CompatibilityCheck.model_construct(
            proposal_sha256=actuals_compatibility_proposal().semantic_sha256,
            expected_players=result.expected_players,
            matched_players=result.matched_players,
            semantic_sha256="0" * 64,
        )
    )


class FutureCohortProposal(Sealed):
    schema_version: Literal["future-player-cohort-candidate-v1"] = (
        "future-player-cohort-candidate-v1"
    )
    assessed_at: datetime
    season: Literal["2026/27"] = "2026/27"
    candidate_gameweek: Literal[9] = 9
    candidate_deadline_at: datetime
    status: Literal["FUTURE_CANDIDATE_REQUIRES_APPROVAL", "EXPIRED_NEXT_DEADLINE_UNRESOLVED"]
    execution_authorized: Literal[False] = False
    freeze_attempted: Literal[False] = False
    real_cohort_size: Literal[0] = 0
    source_url: str = (
        "https://www.premierleague.com/es/news/4750452/"
        "everything-you-need-for-gameweek-9-of-fpl-with-the-latest-tips-and-advice"
    )
    published_date: Literal["2026-10-29"] = "2026-10-29"
    evidence_kind: Literal["OFFICIAL_PUBLIC_HTML_SEARCH_INDEX"] = (
        "OFFICIAL_PUBLIC_HTML_SEARCH_INDEX"
    )
    direct_open_status: Literal["ACCESS_ERROR"] = "ACCESS_ERROR"
    required_before_freeze: tuple[str, ...] = (
        "Separately approved exact source/account/routes/request budget/purpose/code identity.",
        "All retained dependencies and final labels independently source-qualified.",
        "Authenticated current complete catalogue, fixture identities and future deadline.",
        "Preregistered population, rules/models, benchmarks and holdout policy before outcomes.",
        "Original append-only trusted-clock forecast custody before deadline.",
    )


def future_cohort_proposal(*, assessed_at: datetime) -> FutureCohortProposal:
    if assessed_at.tzinfo is None or assessed_at.utcoffset() is None:
        raise ValueError("aware proposal assessment time required")
    deadline = datetime(2026, 10, 31, 11, tzinfo=UTC)
    return seal(
        FutureCohortProposal.model_construct(
            assessed_at=assessed_at,
            candidate_deadline_at=deadline,
            status="FUTURE_CANDIDATE_REQUIRES_APPROVAL"
            if assessed_at < deadline
            else "EXPIRED_NEXT_DEADLINE_UNRESOLVED",
            semantic_sha256="0" * 64,
        )
    )
