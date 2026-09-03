"""Strict content-bound contracts for one private V1 recommendation and replay."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from dmf_pulse.assurance.canonical import canonical_json_bytes, canonical_sha256
from dmf_pulse.availability.current_model import CurrentModelFixtureMinutesInput
from dmf_pulse.availability.manual_override import ManualFixtureMinutesInput
from dmf_pulse.football_events.score_prior_request import ScorePriorRequest
from dmf_pulse.fpl_points.artifacts import semantic_sha256 as fpl_semantic_sha256
from dmf_pulse.fpl_points.models import (
    EventAllocationConfig,
    MonteCarloPolicy,
    ProjectionMode,
)
from dmf_pulse.fpl_points.player_prior import CurrentGwStalePriorCarryForwardPolicy
from dmf_pulse.ingestion.current_state import CurrentUnifiedStateBundle
from dmf_pulse.ingestion.fpl.direct_payloads import CurrentPenaltyHierarchy
from dmf_pulse.ingestion.openfootball.service import CurrentScorePriorBundle
from dmf_pulse.markets.current import (
    CurrentMarketCanonicalIdentityView,
    CurrentMarketConstraintBundle,
)
from dmf_pulse.rules.models import CapabilityArtifact, CompiledRuleset, RulesetStatus
from dmf_pulse.rules.private_transient import (
    PrivateTransientRulesAuthority,
    validate_private_transient_rules_authority,
)

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
GitSha = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)

    def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False) -> Self:
        """Revalidate copies so nested tampering cannot bypass public invariants."""

        del deep
        payload = self.model_dump(mode="python", exclude_none=False)
        if update:
            payload.update(update)
        return type(self).model_validate(payload)


def _utc(value: datetime, *, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _semantic_hash(value: BaseModel, field: str = "semantic_sha256") -> str:
    return canonical_sha256(value.model_dump(mode="json", exclude={field}))


class PrivateCurrentOwnershipMember(_FrozenModel):
    """One truthful purchase-cohort fact required by the accepted Stage-11 state."""

    official_fpl_element_id: PositiveInt
    acquired_gameweek: PositiveInt


class PrivateCurrentOwnership(_FrozenModel):
    """Operator-attested acquisition timing absent from current manager state 001C."""

    schema_version: Literal["private-current-ownership-v1"] = "private-current-ownership-v1"
    source_class: Literal["OPERATOR_DECLARED_PRIVATE_TRANSIENT", "PROVIDER_OBSERVED_RECONSTRUCTED"]
    attestation_status: Literal["HUMAN_ATTESTED", "PROVIDER_OBSERVED"]
    provider_verification: Literal["NOT_PROVIDER_VERIFIED", "PROVIDER_VERIFIED"]
    target_gameweek: PositiveInt
    declared_at: datetime
    attested_at: datetime
    information_cutoff: datetime
    members: Annotated[tuple[PrivateCurrentOwnershipMember, ...], Field(min_length=1)]
    semantic_sha256: Sha256

    @field_validator("declared_at", "attested_at", "information_cutoff")
    @classmethod
    def timestamps_are_utc(cls, value: datetime, info: Any) -> datetime:
        return _utc(value, label=str(info.field_name))

    @model_validator(mode="after")
    def ownership_is_canonical_and_sealed(self) -> Self:
        ids = tuple(member.official_fpl_element_id for member in self.members)
        if ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
            raise ValueError("ownership members must be unique and ordered by official element ID")
        expected_status = (
            ("HUMAN_ATTESTED", "NOT_PROVIDER_VERIFIED")
            if self.source_class == "OPERATOR_DECLARED_PRIVATE_TRANSIENT"
            else ("PROVIDER_OBSERVED", "PROVIDER_VERIFIED")
        )
        if (self.attestation_status, self.provider_verification) != expected_status:
            raise ValueError("ownership provenance fields contradict the source class")
        if any(member.acquired_gameweek > self.target_gameweek for member in self.members):
            raise ValueError("ownership acquisition cannot be after the target Gameweek")
        if not self.declared_at <= self.attested_at <= self.information_cutoff:
            raise ValueError("ownership attestation timestamps are out of order")
        if self.semantic_sha256 != _semantic_hash(self):
            raise ValueError("ownership semantic hash does not match")
        return self


def seal_current_ownership(value: PrivateCurrentOwnership) -> PrivateCurrentOwnership:
    return value.model_copy(update={"semantic_sha256": _semantic_hash(value)})


class PrivateCandidateActionPolicy(_FrozenModel):
    """Full upstream incoming universe and the governed private transfer-count scope."""

    schema_version: Literal["private-candidate-action-policy-v1"] = (
        "private-candidate-action-policy-v1"
    )
    allowed_transfer_in_element_ids: tuple[PositiveInt, ...]
    maximum_transfers: Annotated[StrictInt, Field(ge=0, le=2)]
    rationale: StrictStr = Field(min_length=1, max_length=500)
    semantic_sha256: Sha256

    @model_validator(mode="after")
    def policy_is_canonical_and_sealed(self) -> Self:
        if self.allowed_transfer_in_element_ids != tuple(
            sorted(self.allowed_transfer_in_element_ids)
        ) or len(self.allowed_transfer_in_element_ids) != len(
            set(self.allowed_transfer_in_element_ids)
        ):
            raise ValueError("allowed transfer-in element IDs must be unique and sorted")
        if self.maximum_transfers > 0 and not self.allowed_transfer_in_element_ids:
            raise ValueError("a nonzero transfer scope requires at least one incoming candidate")
        if self.semantic_sha256 != _semantic_hash(self):
            raise ValueError("candidate action policy semantic hash does not match")
        return self


def seal_candidate_action_policy(
    value: PrivateCandidateActionPolicy,
) -> PrivateCandidateActionPolicy:
    return value.model_copy(update={"semantic_sha256": _semantic_hash(value)})


class PrivateCanonicalTeamIdentity(_FrozenModel):
    official_fpl_team_id: PositiveInt
    canonical_team_id: UUID


class PrivateCanonicalPlayerIdentity(_FrozenModel):
    official_fpl_element_id: PositiveInt
    official_fpl_team_id: PositiveInt
    canonical_player_id: UUID


class PrivateCanonicalPlayerIdentityMap(_FrozenModel):
    """Explicit DAT-003/operator mapping absent from the current catalogue view."""

    schema_version: Literal["private-current-player-identity-map-v1"] = (
        "private-current-player-identity-map-v1"
    )
    source_class: Literal[
        "DAT_003_OPERATOR_EXPORT",
        "OPERATOR_INITIATED_DETERMINISTIC",
        "REPOSITORY_SYNTHETIC",
    ]
    resolved_at: datetime
    information_cutoff: datetime
    teams: Annotated[tuple[PrivateCanonicalTeamIdentity, ...], Field(min_length=1)]
    players: Annotated[tuple[PrivateCanonicalPlayerIdentity, ...], Field(min_length=1)]
    semantic_sha256: Sha256

    @field_validator("resolved_at", "information_cutoff")
    @classmethod
    def mapping_times_are_utc(cls, value: datetime, info: Any) -> datetime:
        return _utc(value, label=str(info.field_name))

    @model_validator(mode="after")
    def mapping_is_canonical_and_sealed(self) -> Self:
        team_ids = tuple(item.official_fpl_team_id for item in self.teams)
        player_ids = tuple(item.official_fpl_element_id for item in self.players)
        canonical_team_ids = tuple(item.canonical_team_id for item in self.teams)
        canonical_player_ids = tuple(item.canonical_player_id for item in self.players)
        if (
            team_ids != tuple(sorted(team_ids))
            or player_ids != tuple(sorted(player_ids))
            or len(team_ids) != len(set(team_ids))
            or len(player_ids) != len(set(player_ids))
            or len(canonical_team_ids) != len(set(canonical_team_ids))
            or len(canonical_player_ids) != len(set(canonical_player_ids))
        ):
            raise ValueError("canonical player/team mappings must be unique and sorted")
        if not {item.official_fpl_team_id for item in self.players} <= set(team_ids):
            raise ValueError("canonical player mapping references an unknown mapped team")
        if self.resolved_at > self.information_cutoff:
            raise ValueError("canonical identity mapping is post-cutoff")
        if self.semantic_sha256 != _semantic_hash(self):
            raise ValueError("canonical player identity map semantic hash does not match")
        return self


def seal_canonical_player_identity_map(
    value: PrivateCanonicalPlayerIdentityMap,
) -> PrivateCanonicalPlayerIdentityMap:
    return value.model_copy(update={"semantic_sha256": _semantic_hash(value)})


class PrivateFixtureScorePrior(_FrozenModel):
    """Fixture-bound score prior with honest synthetic or authenticated-current lineage."""

    schema_version: Literal["private-fixture-score-prior-v1"] = "private-fixture-score-prior-v1"
    source_class: Literal["REPOSITORY_OWNED_SYNTHETIC", "CURRENT_SCORE_PRIOR_BUNDLE"]
    fixture_id: UUID
    competition_id: UUID
    home_team_id: UUID
    away_team_id: UUID
    as_of: datetime
    score_prior_request: ScorePriorRequest
    current_bundle: CurrentScorePriorBundle | None = None
    semantic_sha256: Sha256

    @field_validator("as_of")
    @classmethod
    def score_prior_time_is_utc(cls, value: datetime) -> datetime:
        return _utc(value, label="as_of")

    @model_validator(mode="after")
    def score_prior_is_truthfully_bound_and_sealed(self) -> Self:
        if self.home_team_id == self.away_team_id:
            raise ValueError("score-prior fixture teams must be distinct")
        if self.source_class == "REPOSITORY_OWNED_SYNTHETIC":
            if self.current_bundle is not None:
                raise ValueError("synthetic score prior cannot claim a current source bundle")
        else:
            bundle = self.current_bundle
            if bundle is None or (
                bundle.fixture_id != self.fixture_id
                or bundle.competition_id != self.competition_id
                or bundle.home_team_id != self.home_team_id
                or bundle.away_team_id != self.away_team_id
                or bundle.as_of != self.as_of
                or bundle.score_prior_request != self.score_prior_request
            ):
                raise ValueError("current score-prior bundle binding differs")
        if self.semantic_sha256 != _semantic_hash(self):
            raise ValueError("fixture score-prior semantic hash does not match")
        return self


def seal_fixture_score_prior(value: PrivateFixtureScorePrior) -> PrivateFixtureScorePrior:
    return value.model_copy(update={"semantic_sha256": _semantic_hash(value)})


class PrivateV1ExecutionInput(_FrozenModel):
    """One path-free exact input family for live transient execution or frozen replay."""

    schema_version: Literal["private-v1-execution-input-v1"] = "private-v1-execution-input-v1"
    run_id: StrictStr = Field(pattern=r"^[A-Z0-9][A-Z0-9_-]{0,99}$")
    code_sha: GitSha
    projection_mode: ProjectionMode
    retention_class: Literal[
        "SYNTHETIC_REPLAY_ALLOWED",
        "PRIVATE_TRANSIENT_NO_RETENTION",
    ]
    synthetic_source_attestation: Literal["REPOSITORY_OWNED_SYNTHETIC_ONLY"] | None = None
    chip_action: Literal["NO_CHIP"] = "NO_CHIP"
    current_state: CurrentUnifiedStateBundle
    player_identity_map: PrivateCanonicalPlayerIdentityMap
    market_identity_view: CurrentMarketCanonicalIdentityView
    market_constraints: CurrentMarketConstraintBundle
    score_priors: Annotated[tuple[PrivateFixtureScorePrior, ...], Field(min_length=1)]
    manual_minutes: Annotated[
        tuple[ManualFixtureMinutesInput | CurrentModelFixtureMinutesInput, ...],
        Field(min_length=1),
    ]
    ownership: PrivateCurrentOwnership
    candidate_action_policy: PrivateCandidateActionPolicy
    ruleset: CompiledRuleset
    full_season_capability: CapabilityArtifact
    private_rules_authority: PrivateTransientRulesAuthority | None = None
    player_prior_carry_forward_policy: CurrentGwStalePriorCarryForwardPolicy | None = None
    current_penalty_hierarchy: CurrentPenaltyHierarchy | None = None
    root_seed: Annotated[StrictInt, Field(ge=0, le=2**63 - 1)]
    scenario_count: Annotated[StrictInt, Field(ge=1, le=1_000_000)]
    stage9_monte_carlo_policy: MonteCarloPolicy
    stage9_monte_carlo_policy_sha256: Sha256
    event_allocation_config: EventAllocationConfig
    event_allocation_config_sha256: Sha256
    expected_stage8_policy_sha256: Sha256
    expected_player_prior_artifact_sha256: Sha256
    expected_player_prior_acceptance_sha256: Sha256
    require_stage9_mc_pass: StrictBool
    semantic_sha256: Sha256

    @model_validator(mode="after")
    def source_family_is_coherent_and_sealed(self) -> Self:
        if self.projection_mode not in {ProjectionMode.TEST, ProjectionMode.REPLAY}:
            raise ValueError("private V1 execution permits only TEST or REPLAY mode")
        synthetic = self.retention_class == "SYNTHETIC_REPLAY_ALLOWED"
        if synthetic != (self.synthetic_source_attestation is not None):
            raise ValueError("synthetic retention requires the exact synthetic-source attestation")
        if synthetic and self.projection_mode is not ProjectionMode.TEST:
            raise ValueError("synthetic replay authority is restricted to TEST mode")
        if (
            any(item.source_class == "REPOSITORY_OWNED_SYNTHETIC" for item in self.score_priors)
            and not synthetic
        ):
            raise ValueError("synthetic score priors require synthetic replay authority")
        current = self.current_state
        market = self.market_constraints
        if self.ruleset.status is RulesetStatus.VERIFIED:
            if (
                synthetic
                or self.retention_class != "PRIVATE_TRANSIENT_NO_RETENTION"
                or self.private_rules_authority is None
            ):
                raise ValueError(
                    "VERIFIED rules require explicit private transient no-retention authority"
                )
            validate_private_transient_rules_authority(
                self.private_rules_authority,
                ruleset=self.ruleset,
                capability=self.full_season_capability,
                information_cutoff=current.information_cutoff,
            )
        elif self.private_rules_authority is not None:
            raise ValueError("private VERIFIED-rules authority cannot be attached to ACTIVE rules")
        carry_forward = self.player_prior_carry_forward_policy
        if current.target_gameweek == 1 and carry_forward is not None:
            raise ValueError("GW1 execution cannot claim current-GW stale carry-forward")
        if current.target_gameweek > 1 and (
            carry_forward is None
            or carry_forward.target_gameweek != current.target_gameweek
            or carry_forward.current_fpl_bundle_sha256 != current.fpl_input.semantic_sha256
            or carry_forward.prior_artifact_sha256 != self.expected_player_prior_artifact_sha256
            or carry_forward.historical_acceptance_sha256
            != self.expected_player_prior_acceptance_sha256
            or carry_forward.declared_at > current.information_cutoff
        ):
            raise ValueError("current Gameweek requires an exact stale-prior carry-forward policy")
        if carry_forward is not None and not {
            item.current_official_fpl_element_id for item in carry_forward.fallback_assignments
        } <= {item.official_fpl_element_id for item in self.player_identity_map.players}:
            raise ValueError("stale-prior fallback assignment is outside the player universe")
        if (
            market.season_code != current.season_code
            or market.target_gameweek != current.target_gameweek
            or market.information_cutoff != current.information_cutoff
            or self.ownership.target_gameweek != current.target_gameweek
            or self.ownership.information_cutoff != current.information_cutoff
            or self.player_identity_map.information_cutoff != current.information_cutoff
            or self.ruleset.ruleset_hash != current.lineage.ruleset_sha256
            or self.full_season_capability.capability_hash
            != current.lineage.full_season_capability_sha256
        ):
            raise ValueError("private execution sources differ in season, GW, cutoff, or rules")
        manager_ids = tuple(item.official_fpl_element_id for item in current.manager_state.squad)
        ownership_ids = tuple(item.official_fpl_element_id for item in self.ownership.members)
        if ownership_ids != manager_ids:
            raise ValueError("ownership facts must cover the current manager squad exactly")
        current_squad = set(manager_ids)
        incoming = set(self.candidate_action_policy.allowed_transfer_in_element_ids)
        current_player_ids = {item.provider_element_id for item in current.fpl_input.players}
        if incoming & current_squad or not incoming <= current_player_ids:
            raise ValueError("incoming candidates must be known current non-squad players")
        current_team_by_player = {
            item.provider_element_id: int(item.team_identity.external_id_text)
            for item in current.fpl_input.players
        }
        mapped_players = {
            item.official_fpl_element_id: item for item in self.player_identity_map.players
        }
        if not set(mapped_players) <= current_player_ids or any(
            current_team_by_player[element_id] != item.official_fpl_team_id
            for element_id, item in mapped_players.items()
        ):
            raise ValueError("canonical player map differs from current FPL membership")
        if not (current_squad | incoming) <= set(mapped_players):
            raise ValueError("manager and incoming candidates require canonical player mappings")
        hierarchy = self.current_penalty_hierarchy
        if hierarchy is not None:
            if (
                hierarchy.information_cutoff != current.information_cutoff
                or hierarchy.source_bootstrap_payload_sha256
                != current.fpl_input.provenance.bootstrap_payload_sha256
            ):
                raise ValueError("current penalty hierarchy source binding differs")
            current_team_ids = {item.provider_team_id for item in current.fpl_input.teams}
            hierarchy_team_ids = {entry.official_fpl_team_id for entry in hierarchy.teams}
            if hierarchy_team_ids != current_team_ids:
                raise ValueError("current penalty hierarchy team coverage differs")
            for entry in hierarchy.entries:
                mapping = mapped_players.get(entry.official_fpl_element_id)
                if mapping is None:
                    raise ValueError("current penalty hierarchy player is outside the identity map")
                if mapping.official_fpl_team_id != entry.official_fpl_team_id:
                    raise ValueError("current penalty hierarchy player/team mapping differs")
        fixture_sets = {
            "markets": {str(item.canonical_fixture_id) for item in market.fixtures},
            "score_priors": {str(item.fixture_id) for item in self.score_priors},
            "minutes": {item.fixture_id for item in self.manual_minutes},
        }
        expected = fixture_sets["markets"]
        if not expected or any(values != expected for values in fixture_sets.values()):
            raise ValueError("markets, score priors and Stage-7 inputs must cover exact fixtures")
        model_stage7_count = sum(
            isinstance(item, CurrentModelFixtureMinutesInput) for item in self.manual_minutes
        )
        if model_stage7_count not in {0, len(self.manual_minutes)}:
            raise ValueError("Stage-7 input families cannot be mixed in one execution")
        for collection in (
            self.score_priors,
            self.manual_minutes,
        ):
            if len(collection) != len(expected):
                raise ValueError("fixture-scoped input contains a duplicate identity")
        manual_player_ids = {
            player.player_id
            for fixture in self.manual_minutes
            for team in (fixture.home, fixture.away)
            for player in team.scenarios[0].players
        }
        manual_team_ids = {
            team_id
            for fixture in self.manual_minutes
            for team_id in (fixture.home_team_id, fixture.away_team_id)
        }
        if manual_player_ids != {str(item.canonical_player_id) for item in mapped_players.values()}:
            raise ValueError("Stage-7 player universe differs from the canonical player map")
        if not manual_team_ids <= {
            str(item.canonical_team_id) for item in self.player_identity_map.teams
        }:
            raise ValueError("Stage-7 team universe differs from the canonical team map")
        if any(
            item.information_cutoff != current.information_cutoff for item in self.manual_minutes
        ):
            raise ValueError("Stage-7 input cutoff differs from the unified current cutoff")
        if any(item.as_of != current.information_cutoff for item in self.score_priors):
            raise ValueError("score-prior bundle must be bound at the decision cutoff")
        if self.stage9_monte_carlo_policy_sha256 != canonical_sha256(
            self.stage9_monte_carlo_policy.model_dump(mode="json")
        ):
            raise ValueError("Stage-9 Monte Carlo policy hash does not match")
        if self.event_allocation_config_sha256 != canonical_sha256(
            self.event_allocation_config.model_dump(mode="json")
        ):
            raise ValueError("event-allocation configuration hash does not match")
        if self.semantic_sha256 != _semantic_hash(self):
            raise ValueError("private execution input semantic hash does not match")
        return self


def seal_execution_input(value: PrivateV1ExecutionInput) -> PrivateV1ExecutionInput:
    payload = value.model_dump(mode="json", exclude_none=False)
    payload["semantic_sha256"] = _semantic_hash(value)
    return PrivateV1ExecutionInput.model_validate_json(canonical_json_bytes(payload))


class PrivateDecisionStatus(StrEnum):
    SUCCESS = "SUCCESS"
    BLOCKED = "BLOCKED"


class PrivateTransferMove(_FrozenModel):
    player_out_id: StrictStr
    player_in_id: StrictStr
    official_fpl_element_out: PositiveInt
    official_fpl_element_in: PositiveInt


class PrivateTacticalDecision(_FrozenModel):
    starting_xi: tuple[StrictStr, ...]
    bench_goalkeeper: StrictStr
    bench_outfield_order: tuple[StrictStr, StrictStr, StrictStr]
    captain: StrictStr
    vice_captain: StrictStr
    captain_decision_sha256: Sha256
    captain_scoring_layer: Literal["STAGE10_EXACT_TACTICAL_EVALUATOR"]
    captain_verification_layer: Literal["CHIPS_CAPTAINCY_OPTIMISE_CAPTAIN_VICE"]
    captain_points_application_count: Literal[1] = 1


class PrivateGainMass(_FrozenModel):
    points: StrictInt
    probability: Decimal = Field(gt=Decimal("0"), le=Decimal("1"))


class PrivatePairedComparison(_FrozenModel):
    scenario_count: PositiveInt
    recommended_expected_points_before_hit: Decimal
    no_transfer_expected_points: Decimal
    transfer_hit_points: NonNegativeInt
    recommended_expected_points_after_hit: Decimal
    net_expected_uplift: Decimal
    gain_p10: StrictInt
    gain_median: StrictInt
    gain_p90: StrictInt
    probability_recommended_beats_baseline: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    probability_gain_at_least_four: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    probability_loss_at_least_four: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    gain_pmf: tuple[PrivateGainMass, ...]
    semantic_sha256: Sha256

    @model_validator(mode="after")
    def comparison_reconciles(self) -> Self:
        if (
            self.recommended_expected_points_before_hit - self.transfer_hit_points
            != self.recommended_expected_points_after_hit
            or self.recommended_expected_points_after_hit - self.no_transfer_expected_points
            != self.net_expected_uplift
            or sum((item.probability for item in self.gain_pmf), Decimal(0)) != Decimal(1)
            or self.semantic_sha256 != _semantic_hash(self)
        ):
            raise ValueError("paired comparison does not reconcile")
        return self


class PrivateFrontierComparison(_FrozenModel):
    """One exact-count plan compared with hold on the same weighted scenarios."""

    scenario_count: PositiveInt
    plan_expected_points_before_hit: Decimal
    baseline_expected_points: Decimal
    transfer_hit_points: NonNegativeInt
    plan_expected_points_after_hit: Decimal
    expected_uplift: Decimal
    gain_p10: StrictInt
    gain_median: StrictInt
    gain_p90: StrictInt
    probability_plan_beats_hold: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    probability_gain_at_least_four: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    probability_loss_at_least_four: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    gain_pmf: tuple[PrivateGainMass, ...]
    semantic_sha256: Sha256

    @model_validator(mode="after")
    def comparison_reconciles(self) -> Self:
        if (
            self.plan_expected_points_before_hit - self.transfer_hit_points
            != self.plan_expected_points_after_hit
            or self.plan_expected_points_after_hit - self.baseline_expected_points
            != self.expected_uplift
            or not self.gain_p10 <= self.gain_median <= self.gain_p90
            or sum((item.probability for item in self.gain_pmf), Decimal(0)) != Decimal(1)
            or self.semantic_sha256 != _semantic_hash(self)
        ):
            raise ValueError("frontier paired comparison does not reconcile")
        return self


class PrivateFreeTransferState(_FrozenModel):
    """Compiled FT transition with immediate and next-deadline states kept distinct."""

    transition_event: StrictStr
    unlimited_transfers_without_hits: StrictBool
    manager_state_before: NonNegativeInt
    effective_before_action: NonNegativeInt
    transfer_count: NonNegativeInt
    used_by_action: NonNegativeInt
    paid_transfers: NonNegativeInt
    hit_points: NonNegativeInt
    remaining_immediately_after_action: NonNegativeInt
    granted_for_next_deadline: NonNegativeInt
    next_decision_deadline: NonNegativeInt
    maximum_free_transfers: PositiveInt
    semantic_sha256: Sha256

    @model_validator(mode="after")
    def transition_reconciles(self) -> Self:
        ordinary_counts_reconcile = self.unlimited_transfers_without_hits or (
            self.used_by_action + self.paid_transfers == self.transfer_count
        )
        unlimited_counts_reconcile = not self.unlimited_transfers_without_hits or (
            self.used_by_action == 0 and self.paid_transfers == 0 and self.hit_points == 0
        )
        if (
            not ordinary_counts_reconcile
            or not unlimited_counts_reconcile
            or self.used_by_action > self.effective_before_action
            or self.remaining_immediately_after_action
            != self.effective_before_action - self.used_by_action
            or self.next_decision_deadline > self.maximum_free_transfers
            or self.semantic_sha256 != _semantic_hash(self)
        ):
            raise ValueError("free-transfer transition does not reconcile")
        return self


class PrivateTransferFrontierPoint(_FrozenModel):
    transfer_count: NonNegativeInt
    action_id: StrictStr
    action_signature: StrictStr
    action_sha256: Sha256
    transfers: tuple[PrivateTransferMove, ...]
    resulting_squad: tuple[StrictStr, ...]
    tactics: PrivateTacticalDecision
    formation: tuple[PositiveInt, PositiveInt, PositiveInt]
    comparison_vs_hold: PrivateFrontierComparison
    bank_after_tenths: NonNegativeInt
    free_transfer_state: PrivateFreeTransferState
    tactical_plan_sha256: Sha256
    stage11_plan_sha256: Sha256
    semantic_sha256: Sha256

    @model_validator(mode="after")
    def point_is_canonical_and_sealed(self) -> Self:
        transfer_out = tuple(sorted(item.player_out_id for item in self.transfers))
        transfer_in = tuple(sorted(item.player_in_id for item in self.transfers))
        action_digest = fpl_semantic_sha256(
            {
                "event": self.free_transfer_state.transition_event,
                "transfers_out": transfer_out,
                "transfers_in": transfer_in,
            }
        )
        expected_action_id = f"transfer-{action_digest[:32]}"
        expected_action_signature = (
            f"{self.free_transfer_state.transition_event}|"
            f"{','.join(transfer_out)}->{','.join(transfer_in)}"
        )
        expected_action_sha256 = fpl_semantic_sha256(
            {
                "action_id": expected_action_id,
                "transfers_out": transfer_out,
                "transfers_in": transfer_in,
                "transition_event": self.free_transfer_state.transition_event,
            }
        )
        tactical_ids = {
            *self.tactics.starting_xi,
            self.tactics.bench_goalkeeper,
            *self.tactics.bench_outfield_order,
        }
        if (
            len(self.transfers) != self.transfer_count
            or len(transfer_out) != len(set(transfer_out))
            or len(transfer_in) != len(set(transfer_in))
            or self.action_id != expected_action_id
            or self.action_signature != expected_action_signature
            or self.action_sha256 != expected_action_sha256
            or self.resulting_squad != tuple(sorted(set(self.resulting_squad)))
            or len(self.resulting_squad) != 15
            or tactical_ids != set(self.resulting_squad)
            or sum(self.formation) != 10
            or not 3 <= self.formation[0] <= 5
            or not 2 <= self.formation[1] <= 5
            or not 1 <= self.formation[2] <= 3
            or self.comparison_vs_hold.transfer_hit_points != self.free_transfer_state.hit_points
            or self.free_transfer_state.transfer_count != self.transfer_count
            or self.semantic_sha256 != _semantic_hash(self)
        ):
            raise ValueError("private transfer-frontier point does not reconcile")
        return self


class PrivateTransferFrontierDelta(_FrozenModel):
    lower_transfer_count: NonNegativeInt
    higher_transfer_count: PositiveInt
    immediate_expected_points_delta: Decimal
    plan_relationship: Literal["STRICT_EXTENSION", "NON_NESTED"]
    nested_incremental_transfers: tuple[PrivateTransferMove, ...] = ()

    @model_validator(mode="after")
    def delta_reconciles(self) -> Self:
        if self.lower_transfer_count >= self.higher_transfer_count:
            raise ValueError("frontier delta transfer counts must increase")
        if self.plan_relationship == "NON_NESTED" and self.nested_incremental_transfers:
            raise ValueError("a non-nested frontier delta cannot claim an incremental move")
        if self.plan_relationship == "STRICT_EXTENSION" and not self.nested_incremental_transfers:
            raise ValueError("a strict frontier extension must expose its incremental move")
        return self


class PrivateTransferFrontier(_FrozenModel):
    schema_version: Literal["private-transfer-frontier-v1"] = "private-transfer-frontier-v1"
    objective: Literal["ONE_GAMEWEEK_ZERO_TERMINAL_VALUE_OBJECTIVE"]
    future_free_transfer_value_included: Literal[False] = False
    points: tuple[PrivateTransferFrontierPoint, ...]
    deltas: tuple[PrivateTransferFrontierDelta, ...]
    action_space_disclosure: StrictStr
    stage9_projection_sha256: Sha256
    stage9_joint_scenario_sha256: Sha256
    optimiser_request_sha256: Sha256
    optimiser_result_sha256: Sha256
    candidate_action_policy_sha256: Sha256
    semantic_sha256: Sha256

    @model_validator(mode="after")
    def frontier_is_canonical_and_sealed(self) -> Self:
        if not self.points:
            raise ValueError("frontier requires at least the hold plan")
        counts = tuple(item.transfer_count for item in self.points)
        if counts != tuple(sorted(set(counts))):
            raise ValueError("frontier points must be canonically ordered")
        if self.points[0].transfer_count != 0:
            raise ValueError("frontier requires at least the hold plan")
        expected_pairs = tuple(
            (lower.transfer_count, higher.transfer_count)
            for lower, higher in zip(self.points, self.points[1:], strict=False)
        )
        actual_pairs = tuple(
            (item.lower_transfer_count, item.higher_transfer_count) for item in self.deltas
        )
        expected_values = tuple(
            higher.comparison_vs_hold.plan_expected_points_after_hit
            - lower.comparison_vs_hold.plan_expected_points_after_hit
            for lower, higher in zip(self.points, self.points[1:], strict=False)
        )
        actual_values = tuple(item.immediate_expected_points_delta for item in self.deltas)
        if (
            actual_pairs != expected_pairs
            or actual_values != expected_values
            or self.semantic_sha256 != _semantic_hash(self)
        ):
            raise ValueError("private transfer frontier does not reconcile")
        return self


def seal_private_frontier_comparison(
    value: PrivateFrontierComparison,
) -> PrivateFrontierComparison:
    return value.model_copy(update={"semantic_sha256": _semantic_hash(value)})


def seal_private_free_transfer_state(
    value: PrivateFreeTransferState,
) -> PrivateFreeTransferState:
    return value.model_copy(update={"semantic_sha256": _semantic_hash(value)})


def seal_private_transfer_frontier_point(
    value: PrivateTransferFrontierPoint,
) -> PrivateTransferFrontierPoint:
    return value.model_copy(update={"semantic_sha256": _semantic_hash(value)})


def seal_private_transfer_frontier(
    value: PrivateTransferFrontier,
) -> PrivateTransferFrontier:
    return value.model_copy(update={"semantic_sha256": _semantic_hash(value)})


class PrivateDecisionLineage(_FrozenModel):
    current_state_sha256: Sha256
    player_identity_map_sha256: Sha256
    fpl_input_sha256: Sha256
    fixture_source_sha256: Sha256
    odds_market_sha256: Sha256
    manager_state_sha256: Sha256
    market_constraints_sha256: Sha256
    score_prior_sha256_by_fixture: dict[StrictStr, Sha256]
    stage7_input_sha256_by_fixture: dict[StrictStr, Sha256]
    stage7_context_sha256_by_fixture: dict[StrictStr, Sha256]
    stage8_result_sha256_by_fixture: dict[StrictStr, Sha256]
    stage8_policy_sha256: Sha256
    player_prior_artifact_sha256: Sha256
    player_prior_acceptance_sha256: Sha256
    player_prior_binding_sha256_by_fixture: dict[StrictStr, Sha256]
    player_prior_carry_forward_policy_sha256: Sha256 | None
    private_rules_authority_sha256: Sha256 | None
    stage9_result_sha256: Sha256
    stage9_joint_matrix_sha256: Sha256
    optimiser_request_sha256: Sha256
    optimiser_result_sha256: Sha256
    candidate_action_policy_sha256: Sha256
    ownership_sha256: Sha256
    ruleset_sha256: Sha256
    execution_input_sha256: Sha256
    code_sha: GitSha


class PrivateV1Decision(_FrozenModel):
    schema_version: Literal["private-v1-decision-v1"] = "private-v1-decision-v1"
    status: Literal[PrivateDecisionStatus.SUCCESS]
    engineering_status: Literal["PRIVATE_V1_E2E_001A_IMPLEMENTED_PENDING_INDEPENDENT_REVIEW"]
    activation_status: Literal["NOT_PRODUCTION_ACTIVE"]
    execution_status: Literal[
        "SYNTHETIC_REPLAYABLE_RECOMMENDATION",
        "REAL_PRIVATE_TRANSIENT_RECOMMENDATION",
    ]
    replay_retention: Literal[
        "ALLOWED_REPOSITORY_OWNED_SYNTHETIC_ONLY",
        "FORBIDDEN_BY_CURRENT_RIGHTS_PROFILE",
    ]
    run_id: StrictStr
    season: Literal["2026/27"]
    target_gameweek: PositiveInt
    information_cutoff: datetime
    projection_mode: ProjectionMode
    action: Literal["NO_TRANSFER", "TRANSFER"]
    transfers: tuple[PrivateTransferMove, ...]
    resulting_squad: tuple[StrictStr, ...]
    tactics: PrivateTacticalDecision
    no_transfer_tactics: PrivateTacticalDecision
    chip_action: Literal["NO_CHIP"]
    paired_comparison: PrivatePairedComparison
    transfer_frontier: PrivateTransferFrontier | None = None
    stage7_family: Literal[
        "PRIVATE_MANUAL_TRANSIENT_OVERRIDE_V1",
        "REGULARISED_EMPIRICAL_BAYES_COHERENCE_V1",
    ]
    stage7_model_derived: bool
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    player_prior_status: Literal[
        "HISTORICAL_GW1_ACCEPTED_SCOPE",
        "PRIVATE_CURRENT_GW_STALE_PRIOR_CARRY_FORWARD_V1",
    ]
    player_prior_evidence_cutoff: datetime
    player_prior_fallback_player_ids: tuple[StrictStr, ...]
    scenario_count: PositiveInt
    stage9_monte_carlo_status: Literal["PASS", "CONTINUE", "BLOCKED"]
    stage9_monte_carlo_reasons: tuple[StrictStr, ...]
    solver_optimality: Literal["EXACT_DECLARED_TREE_AND_ACTION_SPACE"]
    action_space_disclosure: StrictStr
    warnings: tuple[StrictStr, ...]
    lineage: PrivateDecisionLineage
    semantic_sha256: Sha256

    @field_validator("information_cutoff", "player_prior_evidence_cutoff")
    @classmethod
    def cutoff_is_utc(cls, value: datetime) -> datetime:
        return _utc(value, label="information_cutoff")

    def semantic_hash(self) -> str:
        payload = self.model_dump(mode="json", exclude={"semantic_sha256"})
        if self.transfer_frontier is None:
            payload.pop("transfer_frontier")
        return canonical_sha256(payload)

    @model_validator(mode="after")
    def decision_is_canonical_and_sealed(self) -> Self:
        if self.stage7_model_derived != (
            self.stage7_family == "REGULARISED_EMPIRICAL_BAYES_COHERENCE_V1"
        ):
            raise ValueError("Stage-7 family and model-derived flag differ")
        if (self.action == "NO_TRANSFER") != (len(self.transfers) == 0):
            raise ValueError("decision action and transfer list disagree")
        if self.resulting_squad != tuple(sorted(self.resulting_squad)):
            raise ValueError("resulting squad must be canonically ordered")
        if self.player_prior_fallback_player_ids != tuple(
            sorted(set(self.player_prior_fallback_player_ids))
        ):
            raise ValueError("player-prior fallback identities must be unique and sorted")
        if (self.execution_status == "REAL_PRIVATE_TRANSIENT_RECOMMENDATION") != (
            self.replay_retention == "FORBIDDEN_BY_CURRENT_RIGHTS_PROFILE"
        ):
            raise ValueError("private execution status and replay retention disagree")
        if self.warnings != tuple(sorted(set(self.warnings))):
            raise ValueError("decision warnings must be unique and sorted")
        if self.stage9_monte_carlo_reasons != tuple(sorted(set(self.stage9_monte_carlo_reasons))):
            raise ValueError("Stage-9 Monte Carlo reasons must be unique and sorted")
        if self.transfer_frontier is not None:
            frontier = self.transfer_frontier
            recommended = next(
                (
                    item
                    for item in frontier.points
                    if item.transfer_count == len(self.transfers)
                    and item.action_signature.endswith(
                        "|"
                        + ",".join(sorted(move.player_out_id for move in self.transfers))
                        + "->"
                        + ",".join(sorted(move.player_in_id for move in self.transfers))
                    )
                ),
                None,
            )
            if (
                frontier.action_space_disclosure != self.action_space_disclosure
                or frontier.stage9_projection_sha256 != self.lineage.stage9_result_sha256
                or frontier.stage9_joint_scenario_sha256 != self.lineage.stage9_joint_matrix_sha256
                or frontier.optimiser_request_sha256 != self.lineage.optimiser_request_sha256
                or frontier.optimiser_result_sha256 != self.lineage.optimiser_result_sha256
                or frontier.candidate_action_policy_sha256
                != self.lineage.candidate_action_policy_sha256
                or recommended is None
                or recommended.transfers != self.transfers
                or recommended.resulting_squad != self.resulting_squad
                or recommended.tactics != self.tactics
                or recommended.comparison_vs_hold.plan_expected_points_before_hit
                != self.paired_comparison.recommended_expected_points_before_hit
                or recommended.comparison_vs_hold.baseline_expected_points
                != self.paired_comparison.no_transfer_expected_points
                or recommended.comparison_vs_hold.transfer_hit_points
                != self.paired_comparison.transfer_hit_points
                or recommended.comparison_vs_hold.plan_expected_points_after_hit
                != self.paired_comparison.recommended_expected_points_after_hit
                or recommended.comparison_vs_hold.expected_uplift
                != self.paired_comparison.net_expected_uplift
            ):
                raise ValueError("private decision and transfer frontier disagree")
        if self.semantic_sha256 != self.semantic_hash():
            raise ValueError("private decision semantic hash does not match")
        return self


def seal_private_decision(value: PrivateV1Decision) -> PrivateV1Decision:
    return value.model_copy(update={"semantic_sha256": value.semantic_hash()})


class PrivateReplayFile(_FrozenModel):
    relative_path: StrictStr = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
    sha256: Sha256
    byte_count: NonNegativeInt


class PrivateReplayManifest(_FrozenModel):
    schema_version: Literal["private-v1-replay-manifest-v1"] = "private-v1-replay-manifest-v1"
    run_id: StrictStr
    code_sha: GitSha
    execution_input_semantic_sha256: Sha256
    decision_semantic_sha256: Sha256
    files: tuple[PrivateReplayFile, ...]
    network_required: Literal[False] = False
    absolute_paths_embedded: Literal[False] = False
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def manifest_is_canonical_and_sealed(self) -> Self:
        paths = tuple(item.relative_path for item in self.files)
        if paths != tuple(sorted(paths)) or len(paths) != len(set(paths)):
            raise ValueError("replay files must be unique and sorted")
        if self.manifest_sha256 != _semantic_hash(self, "manifest_sha256"):
            raise ValueError("replay manifest semantic hash does not match")
        return self


def seal_replay_manifest(value: PrivateReplayManifest) -> PrivateReplayManifest:
    return value.model_copy(update={"manifest_sha256": _semantic_hash(value, "manifest_sha256")})


__all__ = [
    "PrivateCandidateActionPolicy",
    "PrivateCanonicalPlayerIdentity",
    "PrivateCanonicalPlayerIdentityMap",
    "PrivateCanonicalTeamIdentity",
    "PrivateCurrentOwnership",
    "PrivateCurrentOwnershipMember",
    "PrivateDecisionLineage",
    "PrivateDecisionStatus",
    "PrivateFreeTransferState",
    "PrivateFrontierComparison",
    "PrivateGainMass",
    "PrivatePairedComparison",
    "PrivateReplayFile",
    "PrivateReplayManifest",
    "PrivateTacticalDecision",
    "PrivateTransferFrontier",
    "PrivateTransferFrontierDelta",
    "PrivateTransferFrontierPoint",
    "PrivateTransferMove",
    "PrivateV1Decision",
    "PrivateV1ExecutionInput",
    "seal_candidate_action_policy",
    "seal_canonical_player_identity_map",
    "seal_current_ownership",
    "seal_execution_input",
    "seal_private_decision",
    "seal_private_free_transfer_state",
    "seal_private_frontier_comparison",
    "seal_private_transfer_frontier",
    "seal_private_transfer_frontier_point",
    "seal_replay_manifest",
]
