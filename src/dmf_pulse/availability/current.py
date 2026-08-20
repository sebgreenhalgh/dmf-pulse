"""Transient current-availability bridge from reviewed FPL input to Stage 7.

The official-FPL material and every derived player row remain in memory.  The
module deliberately exposes no persistence boundary and makes no production
calibration claim: current rosters are evaluated as explicit empty-history
cold starts against the frozen synthetic TEST/REPLAY baseline.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal, Self
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.availability.dataset import semantic_dataset_hash
from dmf_pulse.availability.lineup import LineupScenario
from dmf_pulse.availability.minutes import MinuteConditionalPrediction
from dmf_pulse.availability.pipeline import (
    ARTIFACT_SHA256,
    DATASET_SHA256,
    EVALUATION_SHA256,
    POLICY_SHA256,
    MinutesModelArtifact,
    fit_projection_artifact,
    predict_minutes_baseline,
)
from dmf_pulse.availability.projection import TeamMinutesProjection
from dmf_pulse.availability.resources import availability_resource_json
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.current import CurrentFplFixture, CurrentFplPlayer
from dmf_pulse.markets.current import CurrentMarketConsensusBundle

CURRENT_AVAILABILITY_ADAPTER_VERSION = "gw1-current-availability-stage7-v1"
_IDENTITY_NAMESPACE = UUID("7151293c-5b5d-5cc3-9689-c4e728ea8b55")

AdjustmentType = Literal[
    "HARD_INELIGIBLE",
    "NEW_SIGNING",
    "SOFT_EVIDENCE_NO_MODEL_ADJUSTMENT",
]
EvidenceType = Literal[
    "OFFICIAL_SUSPENSION",
    "FORMAL_INELIGIBILITY",
    "FIXTURE_CANCELLATION",
    "OFFICIAL_TRANSFER_OR_REGISTRATION",
    "MANAGER_QUOTE",
    "TRAINING_REPORT",
    "OFFICIAL_MEDICAL_STATEMENT",
    "ANALYST_JUDGEMENT",
    "FPL_STATUS_ALERT",
]
EvidenceSourceClass = Literal[
    "OFFICIAL_COMPETITION_AUTHORITY",
    "OFFICIAL_CLUB",
    "OFFICIAL_FPL",
    "REPUTABLE_REPORTING",
    "ANALYST_REVIEW",
]

_HARD_EVIDENCE_TYPES = frozenset(
    {"OFFICIAL_SUSPENSION", "FORMAL_INELIGIBILITY", "FIXTURE_CANCELLATION"}
)
_AUTHORITATIVE_SOURCE_CLASSES = frozenset({"OFFICIAL_COMPETITION_AUTHORITY", "OFFICIAL_CLUB"})


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)

    @model_validator(mode="after")
    def normalize_datetimes(self) -> Self:
        for name in self.__class__.model_fields:
            value = getattr(self, name)
            if isinstance(value, datetime):
                if value.tzinfo is None or value.utcoffset() is None:
                    raise ValueError(f"{name} must be timezone-aware")
                object.__setattr__(self, name, value.astimezone(UTC))
        return self


def _uuid(kind: str, *parts: object) -> UUID:
    material = "\x1f".join(
        (CURRENT_AVAILABILITY_ADAPTER_VERSION, kind, *(str(part) for part in parts))
    )
    return uuid5(_IDENTITY_NAMESPACE, material)


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class CurrentAvailabilityReviewPlayer(_FrozenModel):
    official_fpl_player_id: int = Field(gt=0)
    official_fpl_player_identity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    official_fpl_team_id: int = Field(gt=0)
    target_fixture_ids: tuple[int, ...] = Field(min_length=1)
    display_name: str = Field(min_length=1, max_length=200)
    position: Literal["GK", "DEF", "MID", "FWD"]
    fpl_status: str = Field(min_length=1, max_length=20)
    chance_of_playing_next_round: int | None = Field(default=None, ge=0, le=100)
    chance_of_playing_this_round: int | None = Field(default=None, ge=0, le=100)
    fpl_news: str | None = Field(default=None, max_length=2000)
    fpl_news_added: datetime | None = None
    explicit_decision_required: bool

    @model_validator(mode="after")
    def validate_player_review_row(self) -> CurrentAvailabilityReviewPlayer:
        if tuple(sorted(set(self.target_fixture_ids))) != self.target_fixture_ids:
            raise ValueError("target fixture IDs must be unique and sorted")
        expected_required = (
            self.fpl_status != "a"
            or self.chance_of_playing_next_round is not None
            or self.chance_of_playing_this_round is not None
            or bool(self.fpl_news)
            or self.fpl_news_added is not None
        )
        if self.explicit_decision_required != expected_required:
            raise ValueError("FPL availability alert classification is inconsistent")
        return self


class CurrentAvailabilityReviewTemplate(_FrozenModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    contract: Literal["GW1_CURRENT_AVAILABILITY_REVIEW"] = "GW1_CURRENT_AVAILABILITY_REVIEW"
    status: Literal["REVIEW_REQUIRED"] = "REVIEW_REQUIRED"
    disclosure_mode: Literal["PRIVATE_TRANSIENT_OPERATOR_REVIEW"] = (
        "PRIVATE_TRANSIENT_OPERATOR_REVIEW"
    )
    generated_at: datetime
    information_cutoff: datetime
    source_market_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_fpl_availability_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    players: tuple[CurrentAvailabilityReviewPlayer, ...] = Field(min_length=1)
    template_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_template(self) -> CurrentAvailabilityReviewTemplate:
        player_ids = [row.official_fpl_player_id for row in self.players]
        if player_ids != sorted(player_ids) or len(player_ids) != len(set(player_ids)):
            raise ValueError("availability review players must be unique and sorted")
        if self.generated_at > self.information_cutoff:
            raise ValueError("availability review was generated after the information cutoff")
        if self.template_sha256 != _template_sha256(self):
            raise ValueError("availability review template hash is inconsistent")
        return self


def _template_sha256(value: CurrentAvailabilityReviewTemplate) -> str:
    return canonical_sha256(value.model_dump(mode="json", exclude={"template_sha256"}))


class CurrentAvailabilityEvidence(_FrozenModel):
    evidence_type: EvidenceType
    source_class: EvidenceSourceClass
    source_locator: str = Field(min_length=1, max_length=1000)
    observed_at: datetime
    usable_at: datetime
    expires_at: datetime
    confidence: Literal["LOW", "MEDIUM", "HIGH"]
    summary: str = Field(min_length=1, max_length=2000)
    reviewer: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_evidence_window(self) -> CurrentAvailabilityEvidence:
        if self.observed_at > self.usable_at or self.usable_at > self.expires_at:
            raise ValueError("availability evidence temporal order is invalid")
        return self


class CurrentPlayerAvailabilityDecision(_FrozenModel):
    official_fpl_player_id: int = Field(gt=0)
    official_fpl_fixture_id: int = Field(gt=0)
    adjustment: AdjustmentType
    evidence: tuple[CurrentAvailabilityEvidence, ...] = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=2000)


class CurrentAvailabilityApproval(_FrozenModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    contract: Literal["GW1_CURRENT_AVAILABILITY_APPROVAL"] = "GW1_CURRENT_AVAILABILITY_APPROVAL"
    reviewer: str = Field(min_length=1, max_length=200)
    approved_at: datetime
    template_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmed_template_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewed_all_players: Literal[True]
    decisions: tuple[CurrentPlayerAvailabilityDecision, ...]


class CurrentAppliedAvailabilityDecision(_FrozenModel):
    official_fpl_player_id: int = Field(gt=0)
    official_fpl_fixture_id: int = Field(gt=0)
    transient_player_id: UUID
    adjustment: AdjustmentType
    direct_model_effect: Literal["HARD_ZERO", "CONFIDENCE_ONLY", "NONE"]
    prior_player_projection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    posterior_player_projection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CurrentTeamAvailabilityProjection(_FrozenModel):
    official_fpl_fixture_id: int = Field(gt=0)
    official_fpl_team_id: int = Field(gt=0)
    transient_fixture_id: UUID
    transient_team_id: UUID
    prior_projection: TeamMinutesProjection
    posterior_projection: TeamMinutesProjection
    posterior_lineup_scenarios: tuple[LineupScenario, ...] = Field(min_length=256, max_length=256)
    posterior_conditional_minute_pmfs: tuple[MinuteConditionalPrediction, ...] = Field(
        min_length=22
    )
    applied_decisions: tuple[CurrentAppliedAvailabilityDecision, ...]
    limitations: tuple[
        Literal[
            "NO_CURRENT_TEAM_COMPETITIVE_HISTORY_COLD_START",
            "SYNTHETIC_TEST_REPLAY_TRAINING_EVIDENCE",
            "MANAGER_REGIME_UNKNOWN_NOT_INFERRED",
            "PROMOTED_TEAM_STATE_UNKNOWN_NOT_INFERRED",
        ],
        ...,
    ]
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_team_result(self) -> CurrentTeamAvailabilityProjection:
        player_ids = {row.player_id for row in self.posterior_projection.players}
        scenario_hash = hashlib.sha256(
            "".join(row.scenario_sha256 for row in self.posterior_lineup_scenarios).encode("utf-8")
        ).hexdigest()
        minute_keys = [(row.player_id, row.role) for row in self.posterior_conditional_minute_pmfs]
        expected_minute_keys = {
            (player_id, role) for player_id in player_ids for role in ("START", "BENCH")
        }
        scenario_indices = [row.scenario_index for row in self.posterior_lineup_scenarios]
        if (
            self.prior_projection.fixture_id != str(self.transient_fixture_id)
            or self.posterior_projection.fixture_id != str(self.transient_fixture_id)
            or self.prior_projection.team_id != str(self.transient_team_id)
            or self.posterior_projection.team_id != str(self.transient_team_id)
            or scenario_indices != list(range(256))
            or scenario_hash != self.posterior_projection.scenario_set_sha256
            or len(minute_keys) != len(set(minute_keys))
            or set(minute_keys) != expected_minute_keys
            or any(
                {member.player_id for member in scenario.members} != player_ids
                for scenario in self.posterior_lineup_scenarios
            )
            or any(
                scenario.starters
                != tuple(member.player_id for member in scenario.members if member.role == "START")
                or scenario.bench
                != tuple(member.player_id for member in scenario.members if member.role == "BENCH")
                for scenario in self.posterior_lineup_scenarios
            )
            or self.result_sha256 != _team_result_sha256(self)
        ):
            raise ValueError("current team availability projection lineage is inconsistent")
        return self


def _team_result_sha256(value: CurrentTeamAvailabilityProjection) -> str:
    return canonical_sha256(value.model_dump(mode="json", exclude={"result_sha256"}))


class CurrentAvailabilitySummary(_FrozenModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["COMPLETE_WITH_MATERIAL_LIMITATIONS"] = "COMPLETE_WITH_MATERIAL_LIMITATIONS"
    contract: Literal["GW1_CURRENT_AVAILABILITY_MINUTES"] = "GW1_CURRENT_AVAILABILITY_MINUTES"
    run_classification: Literal["PRESEASON_DECISION_SUPPORT"] = "PRESEASON_DECISION_SUPPORT"
    production_status: Literal["NON_PRODUCTION"] = "NON_PRODUCTION"
    decision_information_at: datetime
    fixture_count: int = Field(gt=0)
    team_projection_count: int = Field(gt=0)
    projected_player_rows: int = Field(gt=0)
    review_player_count: int = Field(gt=0)
    flagged_player_fixture_count: int = Field(ge=0)
    hard_ineligible_count: int = Field(ge=0)
    new_signing_count: int = Field(ge=0)
    soft_evidence_count: int = Field(ge=0)
    confidence_grades: dict[str, int]
    model_evidence_mode: Literal["SYNTHETIC_CONTRACT_BASELINE_COLD_START"] = (
        "SYNTHETIC_CONTRACT_BASELINE_COLD_START"
    )
    production_calibration_claim: Literal[False] = False
    fixture_identity_mode: Literal["DETERMINISTIC_TRANSIENT_SURROGATE_NO_DATABASE_RESOLUTION"] = (
        "DETERMINISTIC_TRANSIENT_SURROGATE_NO_DATABASE_RESOLUTION"
    )
    storage_mode: Literal["TRANSIENT_IN_MEMORY"] = "TRANSIENT_IN_MEMORY"
    persistence_performed: Literal[False] = False
    database_accessed: Literal[False] = False
    source_market_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_fpl_availability_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    next_checkpoint: Literal["2.3_FOOTBALL_EVENT_DISTRIBUTIONS"] = (
        "2.3_FOOTBALL_EVENT_DISTRIBUTIONS"
    )


class CurrentAvailabilityBundle(_FrozenModel):
    """Hash-bound in-memory Stage-7 output with reviewed evidence and audit."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    contract: Literal["GW1_CURRENT_AVAILABILITY_MINUTES"] = "GW1_CURRENT_AVAILABILITY_MINUTES"
    run_classification: Literal["PRESEASON_DECISION_SUPPORT"] = "PRESEASON_DECISION_SUPPORT"
    production_status: Literal["NON_PRODUCTION"] = "NON_PRODUCTION"
    storage_mode: Literal["TRANSIENT_IN_MEMORY"] = "TRANSIENT_IN_MEMORY"
    persistence_performed: Literal[False] = False
    database_accessed: Literal[False] = False
    fpl_raw_storage: Literal["DENY"] = "DENY"
    fpl_derived_storage: Literal["DENY"] = "DENY"
    fixture_identity_mode: Literal["DETERMINISTIC_TRANSIENT_SURROGATE_NO_DATABASE_RESOLUTION"] = (
        "DETERMINISTIC_TRANSIENT_SURROGATE_NO_DATABASE_RESOLUTION"
    )
    model_evidence_mode: Literal["SYNTHETIC_CONTRACT_BASELINE_COLD_START"] = (
        "SYNTHETIC_CONTRACT_BASELINE_COLD_START"
    )
    production_calibration_claim: Literal[False] = False
    manager_context_mode: Literal["UNKNOWN_NOT_INFERRED"] = "UNKNOWN_NOT_INFERRED"
    promoted_team_context_mode: Literal["UNKNOWN_NOT_INFERRED"] = "UNKNOWN_NOT_INFERRED"
    decision_information_at: datetime
    adapter_version: Literal["gw1-current-availability-stage7-v1"] = (
        "gw1-current-availability-stage7-v1"
    )
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_evaluation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_market_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_fpl_availability_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_market: CurrentMarketConsensusBundle
    review_template: CurrentAvailabilityReviewTemplate
    approval: CurrentAvailabilityApproval
    team_projections: tuple[CurrentTeamAvailabilityProjection, ...] = Field(min_length=1)
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_bundle(self) -> CurrentAvailabilityBundle:
        source = _revalidate_market(self.source_market)
        template = _build_review_template(source)
        _validate_approval(source, template, self.approval)
        artifact, policy = _load_frozen_resources()
        expected = _build_team_projections(source, self.approval, artifact, policy)
        if (
            source != self.source_market
            or template != self.review_template
            or self.decision_information_at != self.approval.approved_at
            or self.policy_sha256 != POLICY_SHA256
            or self.training_dataset_sha256 != DATASET_SHA256
            or self.model_artifact_sha256 != ARTIFACT_SHA256
            or self.model_evaluation_sha256 != EVALUATION_SHA256
            or self.source_market_semantic_sha256 != source.semantic_sha256
            or self.source_fpl_availability_semantic_sha256
            != template.source_fpl_availability_semantic_sha256
            or self.team_projections != expected
            or self.semantic_sha256 != _bundle_sha256(self)
        ):
            raise ValueError("current availability bundle lineage is inconsistent")
        return self

    def safe_summary(self) -> CurrentAvailabilitySummary:
        decisions = self.approval.decisions
        grades = Counter(
            player.confidence_grade
            for team in self.team_projections
            for player in team.posterior_projection.players
        )
        flagged = sum(
            len(row.target_fixture_ids)
            for row in self.review_template.players
            if row.explicit_decision_required
        )
        return CurrentAvailabilitySummary(
            decision_information_at=self.decision_information_at,
            fixture_count=len({row.official_fpl_fixture_id for row in self.team_projections}),
            team_projection_count=len(self.team_projections),
            projected_player_rows=sum(
                len(row.posterior_projection.players) for row in self.team_projections
            ),
            review_player_count=len(self.review_template.players),
            flagged_player_fixture_count=flagged,
            hard_ineligible_count=sum(d.adjustment == "HARD_INELIGIBLE" for d in decisions),
            new_signing_count=sum(d.adjustment == "NEW_SIGNING" for d in decisions),
            soft_evidence_count=sum(
                d.adjustment == "SOFT_EVIDENCE_NO_MODEL_ADJUSTMENT" for d in decisions
            ),
            confidence_grades=dict(sorted(grades.items())),
            source_market_semantic_sha256=self.source_market_semantic_sha256,
            source_fpl_availability_semantic_sha256=(self.source_fpl_availability_semantic_sha256),
            policy_sha256=self.policy_sha256,
            training_dataset_sha256=self.training_dataset_sha256,
            model_artifact_sha256=self.model_artifact_sha256,
            semantic_sha256=self.semantic_sha256,
        )


def _revalidate_market(value: CurrentMarketConsensusBundle) -> CurrentMarketConsensusBundle:
    try:
        return CurrentMarketConsensusBundle.model_validate_json(value.model_dump_json())
    except (ValueError, IngestionError) as exc:
        raise IngestionError(
            "SOURCE_LINEAGE_INVALID",
            "Checkpoint-2.1 market input failed independent revalidation",
        ) from exc


def _target_fixtures(source: CurrentMarketConsensusBundle) -> tuple[CurrentFplFixture, ...]:
    market_ids = {row.official_fpl_fixture_id for row in source.fixture_markets}
    fixtures = tuple(
        sorted(
            (
                fixture
                for fixture in source.source_input.fpl_input.fixtures
                if fixture.provider_fixture_id in market_ids
                and fixture.event_identity == source.source_input.fpl_input.target_event.identity
            ),
            key=lambda row: row.provider_fixture_id,
        )
    )
    if (
        len(fixtures) != len(market_ids)
        or any(fixture.kickoff_at is None for fixture in fixtures)
        or {fixture.provider_fixture_id for fixture in fixtures} != market_ids
    ):
        raise IngestionError(
            "MAPPING_CONFLICT", "current availability fixture coverage is incomplete"
        )
    return fixtures


def _target_player_material(
    source: CurrentMarketConsensusBundle,
) -> tuple[tuple[CurrentFplPlayer, tuple[int, ...], int], ...]:
    fixtures = _target_fixtures(source)
    team_by_identity = {
        team.identity.canonical_lookup_sha256: team.provider_team_id
        for team in source.source_input.fpl_input.teams
    }
    fixtures_by_team: dict[str, list[int]] = {}
    for fixture in fixtures:
        for identity in (fixture.home_team_identity, fixture.away_team_identity):
            fixtures_by_team.setdefault(identity.canonical_lookup_sha256, []).append(
                fixture.provider_fixture_id
            )
    material: list[tuple[CurrentFplPlayer, tuple[int, ...], int]] = []
    for player in source.source_input.fpl_input.players:
        team_hash = player.team_identity.canonical_lookup_sha256
        fixture_ids = tuple(sorted(set(fixtures_by_team.get(team_hash, ()))))
        if fixture_ids:
            try:
                team_id = team_by_identity[team_hash]
            except KeyError as exc:
                raise IngestionError(
                    "MAPPING_CONFLICT", "current player refers to an unknown official FPL team"
                ) from exc
            material.append((player, fixture_ids, team_id))
    if not material:
        raise IngestionError("QUALITY_BLOCKED", "no current target-team players are available")
    return tuple(sorted(material, key=lambda row: row[0].provider_element_id))


def _fpl_availability_semantic_sha256(source: CurrentMarketConsensusBundle) -> str:
    players = [
        {
            "chance_of_playing_next_round": player.chance_of_playing_next_round,
            "chance_of_playing_this_round": player.chance_of_playing_this_round,
            "current_price_tenths": player.current_price_tenths,
            "first_name": player.first_name,
            "fpl_news": player.news,
            "fpl_news_added": player.news_added.isoformat() if player.news_added else None,
            "identity": player.identity.model_dump(mode="json"),
            "official_fpl_team_id": team_id,
            "position": player.position.value,
            "provider_code": player.provider_code,
            "provider_element_id": player.provider_element_id,
            "second_name": player.second_name,
            "source_semantic_sha256": player.source_semantic_sha256,
            "status": player.status,
            "target_fixture_ids": fixture_ids,
            "web_name": player.web_name,
        }
        for player, fixture_ids, team_id in _target_player_material(source)
    ]
    return canonical_sha256(
        {
            "players": players,
            "source_bootstrap_semantic_sha256": (
                source.source_input.fpl_input.provenance.bootstrap_semantic_sha256
            ),
            "source_market_semantic_sha256": source.semantic_sha256,
            "target_gameweek": source.source_input.fpl_input.target_gameweek,
        }
    )


def _build_review_template(
    source: CurrentMarketConsensusBundle,
) -> CurrentAvailabilityReviewTemplate:
    player_rows = tuple(
        CurrentAvailabilityReviewPlayer(
            official_fpl_player_id=player.provider_element_id,
            official_fpl_player_identity_sha256=player.identity.canonical_lookup_sha256,
            official_fpl_team_id=team_id,
            target_fixture_ids=fixture_ids,
            display_name=player.web_name,
            position=player.position.value,
            fpl_status=player.status,
            chance_of_playing_next_round=player.chance_of_playing_next_round,
            chance_of_playing_this_round=player.chance_of_playing_this_round,
            fpl_news=player.news,
            fpl_news_added=player.news_added,
            explicit_decision_required=(
                player.status != "a"
                or player.chance_of_playing_next_round is not None
                or player.chance_of_playing_this_round is not None
                or bool(player.news)
                or player.news_added is not None
            ),
        )
        for player, fixture_ids, team_id in _target_player_material(source)
    )
    provisional = CurrentAvailabilityReviewTemplate.model_construct(
        generated_at=source.as_of,
        information_cutoff=source.source_input.information_cutoff,
        source_market_semantic_sha256=source.semantic_sha256,
        source_fpl_availability_semantic_sha256=_fpl_availability_semantic_sha256(source),
        players=player_rows,
        template_sha256="0" * 64,
    )
    return CurrentAvailabilityReviewTemplate(
        generated_at=source.as_of,
        information_cutoff=source.source_input.information_cutoff,
        source_market_semantic_sha256=source.semantic_sha256,
        source_fpl_availability_semantic_sha256=_fpl_availability_semantic_sha256(source),
        players=player_rows,
        template_sha256=_template_sha256(provisional),
    )


def build_current_availability_review(
    source: CurrentMarketConsensusBundle,
) -> CurrentAvailabilityReviewTemplate:
    """Generate the private, transient operator review bound to current FPL rows."""

    validated = _revalidate_market(source)
    fpl = validated.source_input.fpl_input
    if (
        fpl.rights.derived_storage != "DENY"
        or fpl.rights.database_accessed
        or fpl.rights.raw_storage_performed
        or fpl.rights.derived_storage_performed
    ):
        raise IngestionError("RIGHTS_BLOCKED", "official FPL retention boundary is invalid")
    return _build_review_template(validated)


def _validate_approval(
    source: CurrentMarketConsensusBundle,
    template: CurrentAvailabilityReviewTemplate,
    approval: CurrentAvailabilityApproval,
) -> None:
    if (
        approval.template_sha256 != template.template_sha256
        or approval.confirmed_template_sha256 != template.template_sha256
    ):
        raise IngestionError(
            "MAPPING_CONFLICT", "availability approval is not bound to the current review"
        )
    if not template.generated_at <= approval.approved_at <= template.information_cutoff:
        raise IngestionError("POST_CUTOFF", "availability approval is outside the usable window")

    valid_keys = {
        (row.official_fpl_player_id, fixture_id)
        for row in template.players
        for fixture_id in row.target_fixture_ids
    }
    decision_keys = [
        (row.official_fpl_player_id, row.official_fpl_fixture_id) for row in approval.decisions
    ]
    if len(decision_keys) != len(set(decision_keys)) or not set(decision_keys) <= valid_keys:
        raise IngestionError(
            "MAPPING_CONFLICT", "availability decisions are duplicate or outside current scope"
        )
    required_keys = {
        (row.official_fpl_player_id, fixture_id)
        for row in template.players
        if row.explicit_decision_required
        for fixture_id in row.target_fixture_ids
    }
    if not required_keys <= set(decision_keys):
        raise IngestionError(
            "QUALITY_BLOCKED", "every current FPL availability alert requires explicit review"
        )

    fixtures = {row.provider_fixture_id: row for row in _target_fixtures(source)}
    for decision in approval.decisions:
        fixture = fixtures[decision.official_fpl_fixture_id]
        assert fixture.kickoff_at is not None
        for evidence in decision.evidence:
            if evidence.reviewer != approval.reviewer:
                raise IngestionError(
                    "MAPPING_CONFLICT", "availability evidence reviewer contradicts approval"
                )
            if evidence.usable_at > approval.approved_at:
                raise IngestionError(
                    "POST_CUTOFF", "availability evidence was not usable at decision time"
                )
            if evidence.expires_at < fixture.kickoff_at:
                raise IngestionError(
                    "QUALITY_BLOCKED", "availability evidence expires before its target fixture"
                )
        if decision.adjustment == "HARD_INELIGIBLE" and any(
            evidence.evidence_type == "FIXTURE_CANCELLATION"
            and evidence.source_class in _AUTHORITATIVE_SOURCE_CLASSES
            and evidence.confidence == "HIGH"
            for evidence in decision.evidence
        ):
            raise IngestionError(
                "QUALITY_BLOCKED",
                "confirmed fixture cancellation blocks the complete fixture projection",
            )
        if decision.adjustment == "HARD_INELIGIBLE" and not any(
            evidence.evidence_type in _HARD_EVIDENCE_TYPES
            and evidence.source_class in _AUTHORITATIVE_SOURCE_CLASSES
            and evidence.confidence == "HIGH"
            for evidence in decision.evidence
        ):
            raise IngestionError(
                "QUALITY_BLOCKED",
                "hard ineligibility requires fresh high-confidence authoritative evidence",
            )
        if decision.adjustment == "NEW_SIGNING" and not any(
            evidence.evidence_type == "OFFICIAL_TRANSFER_OR_REGISTRATION"
            and evidence.source_class in _AUTHORITATIVE_SOURCE_CLASSES
            and evidence.confidence == "HIGH"
            for evidence in decision.evidence
        ):
            raise IngestionError(
                "QUALITY_BLOCKED",
                "new-signing status requires official transfer or registration evidence",
            )


def _load_frozen_resources() -> tuple[MinutesModelArtifact, dict[str, Any]]:
    training = availability_resource_json("MIN-007/training_dataset.json")
    policy = availability_resource_json("MIN-007G/minutes_baseline_policy.json")
    if (
        semantic_dataset_hash(training) != DATASET_SHA256
        or canonical_sha256(policy) != POLICY_SHA256
    ):
        raise IngestionError("INTERNAL_INVARIANT", "frozen availability resources drifted")
    artifact = fit_projection_artifact(training, policy=policy)
    if artifact.artifact_sha256 != ARTIFACT_SHA256:
        raise IngestionError("INTERNAL_INVARIANT", "frozen availability identities drifted")
    return artifact, policy


def current_player_id(player: CurrentFplPlayer) -> UUID:
    """Return the governed transient identity used by current Stage-7 outputs."""

    return _uuid("player", player.identity.canonical_lookup_sha256)


def _decision_effect(adjustment: AdjustmentType) -> Literal["HARD_ZERO", "CONFIDENCE_ONLY", "NONE"]:
    if adjustment == "HARD_INELIGIBLE":
        return "HARD_ZERO"
    if adjustment == "NEW_SIGNING":
        return "CONFIDENCE_ONLY"
    return "NONE"


def _team_projection(
    *,
    source: CurrentMarketConsensusBundle,
    fixture: CurrentFplFixture,
    official_team_id: int,
    team_identity_sha256: str,
    approval: CurrentAvailabilityApproval,
    artifact: MinutesModelArtifact,
    policy: Mapping[str, Any],
) -> CurrentTeamAvailabilityProjection:
    fixture_market = next(
        row
        for row in source.fixture_markets
        if row.official_fpl_fixture_id == fixture.provider_fixture_id
    )
    team_id = _uuid("team", team_identity_sha256)
    team_key = f"official_fpl_team_{official_team_id}"
    players = tuple(
        sorted(
            (
                player
                for player in source.source_input.fpl_input.players
                if player.team_identity.canonical_lookup_sha256 == team_identity_sha256
            ),
            key=lambda row: row.provider_element_id,
        )
    )
    roster = [
        {
            "player_id": str(current_player_id(player)),
            "player_key": f"official_fpl_player_{player.provider_element_id}",
            "position": player.position.value,
            "team_id": str(team_id),
            "team_key": team_key,
        }
        for player in players
    ]
    history = {"rows": [], "rosters": {team_key: roster}}
    decisions = tuple(
        sorted(
            (
                decision
                for decision in approval.decisions
                if decision.official_fpl_fixture_id == fixture.provider_fixture_id
                and any(
                    player.provider_element_id == decision.official_fpl_player_id
                    for player in players
                )
            ),
            key=lambda row: row.official_fpl_player_id,
        )
    )
    players_by_official_id = {player.provider_element_id: player for player in players}
    overrides: dict[str, dict[str, object]] = {}
    for decision in decisions:
        player = players_by_official_id[decision.official_fpl_player_id]
        override: dict[str, object] = {"player_id": str(current_player_id(player))}
        if decision.adjustment == "HARD_INELIGIBLE":
            override["hard_ineligible"] = True
        elif decision.adjustment == "NEW_SIGNING":
            override["new_signing"] = True
        else:
            continue
        overrides[f"official_fpl_player_{player.provider_element_id}"] = override
    context = {
        "schema_version": "minutes-prediction-context-v1",
        "scenario": "gw1_current_cold_start",
        "fixture_id": str(fixture_market.transient_fixture_id),
        "team_key": team_key,
        "team_id": str(team_id),
        "as_of": _utc_text(approval.approved_at),
        "cutoff_sequence_index": 1,
        "manager_regime_id": str(_uuid("unknown-manager-regime", team_identity_sha256)),
        "bench_size": 9,
        "bench_goalkeeper_slots": 1,
        "current_manager_team_lineups": 0,
        "target_league_team_lineups": 0,
        "promoted_team": False,
        "new_manager": False,
        "player_overrides": {},
    }
    prior = predict_minutes_baseline(history, artifact, context=context, policy=policy)
    posterior_context = dict(context)
    posterior_context["player_overrides"] = overrides
    posterior = predict_minutes_baseline(
        history, artifact, context=posterior_context, policy=policy
    )
    if prior.projection is None or posterior.projection is None:
        raise IngestionError(
            "QUALITY_BLOCKED",
            "current target team has insufficient eligible players for a coherent Stage-7 squad",
            details={
                "official_fpl_fixture_id": fixture.provider_fixture_id,
                "official_fpl_team_id": official_team_id,
                "prior_error": prior.error_code,
                "posterior_error": posterior.error_code,
            },
        )
    prior_players = {row.player_id: row for row in prior.projection.players}
    posterior_players = {row.player_id: row for row in posterior.projection.players}
    posterior_lineup_scenarios = tuple(
        LineupScenario.model_validate_json(
            json.dumps(row, allow_nan=False, separators=(",", ":"), sort_keys=True)
        )
        for row in posterior.core_scenarios
    )
    posterior_conditional_minute_pmfs = tuple(
        MinuteConditionalPrediction.model_validate_json(
            json.dumps(row, allow_nan=False, separators=(",", ":"), sort_keys=True)
        )
        for row in posterior.core_minute_pmfs
    )
    applications = tuple(
        CurrentAppliedAvailabilityDecision(
            official_fpl_player_id=decision.official_fpl_player_id,
            official_fpl_fixture_id=decision.official_fpl_fixture_id,
            transient_player_id=current_player_id(
                players_by_official_id[decision.official_fpl_player_id]
            ),
            adjustment=decision.adjustment,
            direct_model_effect=_decision_effect(decision.adjustment),
            prior_player_projection_sha256=prior_players[
                str(current_player_id(players_by_official_id[decision.official_fpl_player_id]))
            ].projection_sha256,
            posterior_player_projection_sha256=posterior_players[
                str(current_player_id(players_by_official_id[decision.official_fpl_player_id]))
            ].projection_sha256,
            decision_sha256=canonical_sha256(decision.model_dump(mode="json")),
        )
        for decision in decisions
    )
    provisional = CurrentTeamAvailabilityProjection.model_construct(
        official_fpl_fixture_id=fixture.provider_fixture_id,
        official_fpl_team_id=official_team_id,
        transient_fixture_id=fixture_market.transient_fixture_id,
        transient_team_id=team_id,
        prior_projection=prior.projection,
        posterior_projection=posterior.projection,
        posterior_lineup_scenarios=posterior_lineup_scenarios,
        posterior_conditional_minute_pmfs=posterior_conditional_minute_pmfs,
        applied_decisions=applications,
        limitations=(
            "NO_CURRENT_TEAM_COMPETITIVE_HISTORY_COLD_START",
            "SYNTHETIC_TEST_REPLAY_TRAINING_EVIDENCE",
            "MANAGER_REGIME_UNKNOWN_NOT_INFERRED",
            "PROMOTED_TEAM_STATE_UNKNOWN_NOT_INFERRED",
        ),
        result_sha256="0" * 64,
    )
    return CurrentTeamAvailabilityProjection(
        official_fpl_fixture_id=fixture.provider_fixture_id,
        official_fpl_team_id=official_team_id,
        transient_fixture_id=fixture_market.transient_fixture_id,
        transient_team_id=team_id,
        prior_projection=prior.projection,
        posterior_projection=posterior.projection,
        posterior_lineup_scenarios=posterior_lineup_scenarios,
        posterior_conditional_minute_pmfs=posterior_conditional_minute_pmfs,
        applied_decisions=applications,
        limitations=provisional.limitations,
        result_sha256=_team_result_sha256(provisional),
    )


def _build_team_projections(
    source: CurrentMarketConsensusBundle,
    approval: CurrentAvailabilityApproval,
    artifact: MinutesModelArtifact,
    policy: Mapping[str, Any],
) -> tuple[CurrentTeamAvailabilityProjection, ...]:
    teams = {
        team.identity.canonical_lookup_sha256: team.provider_team_id
        for team in source.source_input.fpl_input.teams
    }
    results: list[CurrentTeamAvailabilityProjection] = []
    for fixture in _target_fixtures(source):
        for identity in (fixture.home_team_identity, fixture.away_team_identity):
            identity_hash = identity.canonical_lookup_sha256
            results.append(
                _team_projection(
                    source=source,
                    fixture=fixture,
                    official_team_id=teams[identity_hash],
                    team_identity_sha256=identity_hash,
                    approval=approval,
                    artifact=artifact,
                    policy=policy,
                )
            )
    return tuple(
        sorted(results, key=lambda row: (row.official_fpl_fixture_id, row.official_fpl_team_id))
    )


def _bundle_sha256(value: CurrentAvailabilityBundle) -> str:
    return canonical_sha256(value.model_dump(mode="json", exclude={"semantic_sha256"}))


def build_current_availability(
    source: CurrentMarketConsensusBundle,
    approval: CurrentAvailabilityApproval,
) -> CurrentAvailabilityBundle:
    """Apply reviewed current evidence and produce complete transient Stage-7 output."""

    validated = _revalidate_market(source)
    template = _build_review_template(validated)
    _validate_approval(validated, template, approval)
    artifact, policy = _load_frozen_resources()
    projections = _build_team_projections(validated, approval, artifact, policy)
    values: dict[str, Any] = {
        "decision_information_at": approval.approved_at,
        "policy_sha256": POLICY_SHA256,
        "training_dataset_sha256": DATASET_SHA256,
        "model_artifact_sha256": ARTIFACT_SHA256,
        "model_evaluation_sha256": EVALUATION_SHA256,
        "source_market_semantic_sha256": validated.semantic_sha256,
        "source_fpl_availability_semantic_sha256": (
            template.source_fpl_availability_semantic_sha256
        ),
        "source_market": validated,
        "review_template": template,
        "approval": approval,
        "team_projections": projections,
    }
    provisional = CurrentAvailabilityBundle.model_construct(**values, semantic_sha256="0" * 64)
    return CurrentAvailabilityBundle(**values, semantic_sha256=_bundle_sha256(provisional))


__all__ = [
    "CURRENT_AVAILABILITY_ADAPTER_VERSION",
    "CurrentAppliedAvailabilityDecision",
    "CurrentAvailabilityApproval",
    "CurrentAvailabilityBundle",
    "CurrentAvailabilityEvidence",
    "CurrentAvailabilityReviewPlayer",
    "CurrentAvailabilityReviewTemplate",
    "CurrentAvailabilitySummary",
    "CurrentPlayerAvailabilityDecision",
    "CurrentTeamAvailabilityProjection",
    "build_current_availability",
    "build_current_availability_review",
    "current_player_id",
]
