"""Pre-result P02+ governance contracts; pure public-only evidence operations."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, time, timedelta
from importlib import resources
from itertools import pairwise
from pathlib import Path
from typing import Final, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.evaluation.team_strength_prospective import PROMOTION_REQUIREMENTS
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    COMMIT,
    SHA,
    FixtureRegistry,
    FrozenEvidence,
    ParsedSnapshot,
    SealedEvidence,
    StrengthEvidenceError,
    authenticate,
    seal,
)

P01_SHA: Final = "96a13e8265095672708586dd1fd2a7f9653857594ba5fa325e82c0b3385ab15a"
DRAW_POLICY_SHA: Final = "444b0b4b8f138bc9188a60e947eb6ff58575c0ceb3f2d825873e9851ddfa49b3"
PARENT_SHA = "3815152e978dd55e1dc1f115055050d4ed6b1735"
PROTOCOL_SHA: Final = "93b9c2e8a0b0f6c00e1299cb410784daabf1eb04efa01baaab5f10d85d10e029"
PRODUCTS = (
    "LEAGUE_BASELINE",
    "PLUG_IN_TEAM_STRENGTH_SHADOW",
    "PARAMETER_MIXTURE_TEAM_STRENGTH_SHADOW",
)
SECONDARY = (
    "team_count_log_loss",
    "goal_rps",
    "home_win_brier",
    "draw_brier",
    "away_win_brier",
    "home_clean_sheet_brier",
    "away_clean_sheet_brier",
    *(f"total_over_{line}.5_brier" for line in range(6)),
    "home_bias",
    "away_bias",
)
STATES = Literal[
    "FROZEN",
    "SCORED",
    "FREEZE_WINDOW_MISSED",
    "SOURCE_BLOCKED",
    "MODEL_FIT_BLOCKED",
    "SCHEDULE_BLOCKED",
    "OUTCOME_NOT_YET_ELIGIBLE",
    "SCORING_BLOCKED",
]


class InferencePolicy(FrozenEvidence):
    method: Literal["PAIRED_WHOLE_COHORT_BLOCK_BOOTSTRAP_SHA256_V1"] = (
        "PAIRED_WHOLE_COHORT_BLOCK_BOOTSTRAP_SHA256_V1"
    )
    resamples: Literal[4096] = 4096
    minimum_complete_cohorts: Literal[10] = 10
    interval: Literal["DESCRIPTIVE_95_PERCENT_NEAREST_RANK_PERCENTILE"] = (
        "DESCRIPTIVE_95_PERCENT_NEAREST_RANK_PERCENTILE"
    )
    seed_domain: Literal["DMF-CTS-001V-PROTOCOL-PRE-RESULT-2026-10-10"] = (
        "DMF-CTS-001V-PROTOCOL-PRE-RESULT-2026-10-10"
    )
    repeated_look_significance_claim: Literal[False] = False


class ProspectiveProtocolV1(SealedEvidence):
    schema_version: Literal["public-team-strength-prospective-protocol-v1"] = (
        "public-team-strength-prospective-protocol-v1"
    )
    campaign_id: Literal["CURRENT-TEAM-STRENGTH-001V"] = "CURRENT-TEAM-STRENGTH-001V"
    protocol_version: str = Field(pattern=r"^[1-9][0-9]*\.0\.0$")
    evaluation_epoch: str = Field(pattern=r"^EVALUATION_EPOCH_[0-9]{3}$")
    effective_from_cohort: Literal["P02"] = "P02"
    created_at: datetime
    code_sha256: SHA
    accepted_code_manifest: tuple[tuple[str, SHA], ...] = Field(min_length=1)
    accepted_implementation_parent: COMMIT = PARENT_SHA
    predecessor_protocol_sha256: SHA | None = None
    amendment_ticket: str | None = Field(default=None, pattern=r"^[A-Z0-9]+(?:-[A-Z0-9]+)+$")
    methodology_sha256: SHA
    model_policy_sha256: Literal[
        "e8d28521fcb90b625a8dbeff4f72de3b178d16ed7cae748a7429d0e42cdd9fd7"
    ] = "e8d28521fcb90b625a8dbeff4f72de3b178d16ed7cae748a7429d0e42cdd9fd7"
    draw_policy_sha256: Literal[
        "444b0b4b8f138bc9188a60e947eb6ff58575c0ceb3f2d825873e9851ddfa49b3"
    ] = DRAW_POLICY_SHA
    cohort_size: Literal[10] = 10
    cohort_selection_rule: Literal["NEXT_UNASSIGNED_NO_SCORE_EPL_DATE_THEN_CANONICAL_ID"] = (
        "NEXT_UNASSIGNED_NO_SCORE_EPL_DATE_THEN_CANONICAL_ID"
    )
    freeze_schedule_rule: Literal["12:00Z_TWO_CALENDAR_DAYS_BEFORE_EARLIEST_DATE"] = (
        "12:00Z_TWO_CALENDAR_DAYS_BEFORE_EARLIEST_DATE"
    )
    freeze_window_hours: Literal[6] = 6
    missed_freeze_policy: Literal["RETAIN_MISS_CONSUME_COHORT_ID_RECOMPUTE_NO_BACKDATE"] = (
        "RETAIN_MISS_CONSUME_COHORT_ID_RECOMPUTE_NO_BACKDATE"
    )
    overlap_policy: Literal["ONE_PERMANENT_CANONICAL_FIXTURE_ASSIGNMENT_PER_CAMPAIGN"] = (
        "ONE_PERMANENT_CANONICAL_FIXTURE_ASSIGNMENT_PER_CAMPAIGN"
    )
    products: tuple[str, ...] = PRODUCTS
    primary_metric: Literal["MEAN_PAIRED_PLUGIN_MINUS_BASELINE_EXACT_SCORE_LOG_LOSS"] = (
        "MEAN_PAIRED_PLUGIN_MINUS_BASELINE_EXACT_SCORE_LOG_LOSS"
    )
    primary_comparison: tuple[str, str] = (PRODUCTS[1], PRODUCTS[0])
    secondary_metrics: tuple[str, ...] = SECONDARY
    exploratory_metrics: Literal["PAIRED_MIXTURE_MINUS_PLUGIN_PROPER_SCORES_RESEARCH_ONLY"] = (
        "PAIRED_MIXTURE_MINUS_PLUGIN_PROPER_SCORES_RESEARCH_ONLY"
    )
    subgroup_registry: tuple[str, ...] = (
        "FORECAST_LEAD_TIME:P01_PILOT_LONG_LEAD,P02_PLUS_STANDARD_WINDOW",
        "PROMOTED_TEAM_INVOLVEMENT:AUTHENTICATED_IS_FORECAST_ENTRANT_OR_SUBGROUP_NOT_AVAILABLE",
        "POST_FREEZE_FIXTURE_MOVE:DATE_UNCHANGED,DATE_CHANGED_AFTER_FREEZE",
    )
    aggregation_policy: Literal[
        "FIXTURE_COHORT_CAMPAIGN_PAIRED_ONLY_SPLIT_EPOCH_MODE_POLICY_LEAD"
    ] = "FIXTURE_COHORT_CAMPAIGN_PAIRED_ONLY_SPLIT_EPOCH_MODE_POLICY_LEAD"
    inference_policy: InferencePolicy = InferencePolicy()
    calibration_policy: Literal["EXISTING_INTERCEPT_SLOPE_RESIDUAL_BRIER_COUNTS_MIN_10_COHORTS"] = (
        "EXISTING_INTERCEPT_SLOPE_RESIDUAL_BRIER_COUNTS_MIN_10_COHORTS"
    )
    interim_review_policy: tuple[int, int] = (5, 10)
    amendment_policy: Literal["EXPLICIT_TICKET_NEW_VERSION_NEW_EPOCH_RETAIN_OLD_EVIDENCE"] = (
        "EXPLICIT_TICKET_NEW_VERSION_NEW_EPOCH_RETAIN_OLD_EVIDENCE"
    )
    promotion_review_policy: Literal["SEPARATE_LATER_HUMAN_DECISION_REQUIRED"] = (
        "SEPARATE_LATER_HUMAN_DECISION_REQUIRED"
    )
    required_promotion_evidence: tuple[str, ...] = PROMOTION_REQUIREMENTS
    production_activation: Literal[False] = False
    automatic_activation: Literal[False] = False
    production_active: Literal[False] = False
    operational_draw_count_selected: Literal[False] = False
    parameter_mixture_status: Literal["RESEARCH_ONLY"] = "RESEARCH_ONLY"
    private_provider_policy: Literal["NO_FPL_ODDS_CREDENTIALS_OR_PRIVATE_DATA"] = (
        "NO_FPL_ODDS_CREDENTIALS_OR_PRIVATE_DATA"
    )
    data_class: Literal["PUBLIC_OPENFOOTBALL_TEAM_ONLY"] = "PUBLIC_OPENFOOTBALL_TEAM_ONLY"
    p01_forecast_sha256: Literal[
        "96a13e8265095672708586dd1fd2a7f9653857594ba5fa325e82c0b3385ab15a"
    ] = P01_SHA
    protocol_semantic_sha256: SHA = Field(exclude=True, default="0" * 64)

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if self.protocol_semantic_sha256 not in {"0" * 64, self.semantic_sha256}:
            raise ValueError("protocol identity alias mismatch")
        object.__setattr__(self, "protocol_semantic_sha256", self.semantic_sha256)
        if (
            self.products != PRODUCTS
            or self.secondary_metrics != SECONDARY
            or self.primary_comparison != (PRODUCTS[1], PRODUCTS[0])
            or self.interim_review_policy != (5, 10)
            or self.required_promotion_evidence != PROMOTION_REQUIREMENTS
            or self.subgroup_registry != type(self).model_fields["subgroup_registry"].default
        ):
            raise ValueError("predeclared policy definitions cannot be changed within this schema")
        if self.accepted_implementation_parent != PARENT_SHA:
            raise ValueError("accepted implementation identity differs")
        if self.accepted_code_manifest != tuple(sorted(set(self.accepted_code_manifest))):
            raise ValueError("code manifest must be canonical")
        if self.code_sha256 != canonical_sha256(
            {
                "git_sha": self.accepted_implementation_parent,
                "files": self.accepted_code_manifest,
            }
        ):
            raise ValueError("code manifest identity mismatch")
        if (self.protocol_version == "1.0.0") != (self.evaluation_epoch == "EVALUATION_EPOCH_001"):
            raise ValueError("protocol version/epoch mismatch")
        if self.protocol_version == "1.0.0":
            if self.predecessor_protocol_sha256 is not None or self.amendment_ticket is not None:
                raise ValueError("initial protocol cannot claim an amendment")
        elif self.predecessor_protocol_sha256 is None or self.amendment_ticket is None:
            raise ValueError("amendments require ticket and predecessor")
        return self


def load_protocol() -> ProspectiveProtocolV1:
    resource = resources.files("dmf_pulse").joinpath(
        "evaluation/resources/team_strength_prospective_protocol_v1.json"
    )
    if resource.is_file():
        body = resource.read_bytes()
    else:
        body = (
            Path(__file__).resolve().parents[3]
            / "config/evaluation/team_strength_prospective_protocol_v1.json"
        ).read_bytes()
    protocol = ProspectiveProtocolV1.model_validate_json(body)
    # The versioned packaged artifact is the immutable authority, never `latest`.
    protocol = authenticate(protocol, PROTOCOL_SHA)
    package = resources.files("dmf_pulse")
    dependencies = package.joinpath("evaluation/resources/team_strength_epoch001_dependencies.json")
    dependency_body = json.loads(
        dependencies.read_bytes()
        if dependencies.is_file()
        else (
            Path(__file__).resolve().parents[3]
            / "config/evaluation/team_strength_epoch001_dependencies.json"
        ).read_bytes()
    )
    if (
        canonical_sha256(dependency_body)
        != "b25fd60a0bf4300ef2bda64143137854d7f894010fb8e1c506fb092942a212b6"
    ):
        raise StrengthEvidenceError("accepted dependency manifest differs")
    for name, expected in (*protocol.accepted_code_manifest, *dependency_body["files"]):
        if name.startswith("src/dmf_pulse/"):
            body = package.joinpath(name.removeprefix("src/dmf_pulse/")).read_bytes()
        elif name == "config/models/current_team_strength_governance.json":
            resource = package.joinpath("ingestion/resources/current_team_strength_governance.json")
            body = (
                resource.read_bytes()
                if resource.is_file()
                else (Path(__file__).resolve().parents[3] / name).read_bytes()
            )
        else:
            raise StrengthEvidenceError("unrecognized accepted methodology source")
        if hashlib.sha256(body).hexdigest() != expected:
            raise StrengthEvidenceError(
                "runtime methodology differs; new approved evaluation epoch required"
            )
    return protocol


class CohortAssignment(FrozenEvidence):
    cohort_id: str = Field(pattern=r"^P[0-9]{2,}$")
    protocol_sha256: SHA
    evaluation_epoch: str
    forecast_sha256: SHA
    fixture_ids: tuple[UUID, ...] = Field(min_length=1, max_length=10)
    scheduled_dates: tuple[date, ...]
    forecast_origin: datetime
    frozen_at: datetime
    dataset_mode: Literal["LIVE_OBSERVED", "RECONSTRUCTED"]
    draw_policy_sha256: SHA
    model_artifact_sha256: SHA
    model_sha256: SHA
    source_snapshot_sha256: SHA
    fixture_registry_sha256: SHA
    methodology_sha256: SHA
    cohort_class: Literal["PROSPECTIVE_PILOT_COHORT", "STANDARD_PROSPECTIVE_COHORT"]
    lead_time_class: Literal["P01_PILOT_LONG_LEAD", "P02_PLUS_STANDARD_WINDOW"]
    promoted_team_fixture_ids: tuple[UUID, ...] | None = None

    @model_validator(mode="after")
    def check_assignment(self) -> Self:
        if self.fixture_ids != tuple(sorted(set(self.fixture_ids))):
            raise ValueError("assigned fixture IDs must be canonical and unique")
        if len(self.scheduled_dates) != len(self.fixture_ids):
            raise ValueError("assignment dates differ from fixtures")
        if self.promoted_team_fixture_ids is not None and (
            self.promoted_team_fixture_ids != tuple(sorted(set(self.promoted_team_fixture_ids)))
            or not set(self.promoted_team_fixture_ids) <= set(self.fixture_ids)
        ):
            raise ValueError("promoted subgroup identity mismatch")
        if (
            self.forecast_origin > self.frozen_at
            or min(self.scheduled_dates) <= self.frozen_at.date()
        ):
            raise ValueError("assignment is not pre-outcome")
        pilot = self.cohort_id == "P01"
        if pilot != (self.cohort_class == "PROSPECTIVE_PILOT_COHORT") or pilot != (
            self.lead_time_class == "P01_PILOT_LONG_LEAD"
        ):
            raise ValueError("pilot classification mismatch")
        if pilot and self.forecast_sha256 != P01_SHA:
            raise ValueError("P01 immutable forecast identity differs")
        if not pilot:
            start, end = freeze_window(min(self.scheduled_dates))
            if not start <= self.forecast_origin <= self.frozen_at <= end:
                raise ValueError("COHORT_FREEZE_WINDOW_MISSED")
        return self


class CohortEvent(FrozenEvidence):
    cohort_id: str = Field(pattern=r"^P[0-9]{2,}$")
    status: STATES
    recorded_at: datetime
    assignment: CohortAssignment | None = None
    score_sha256: SHA | None = None
    scored_at: datetime | None = None
    detail: str = Field(min_length=1, max_length=250)

    @model_validator(mode="after")
    def check_event(self) -> Self:
        if self.assignment is not None and self.assignment.cohort_id != self.cohort_id:
            raise ValueError("event assignment cohort mismatch")
        if self.status in {"FROZEN", "SCORED", "OUTCOME_NOT_YET_ELIGIBLE", "SCORING_BLOCKED"}:
            if self.assignment is None or self.assignment.frozen_at > self.recorded_at:
                raise ValueError("event requires an already-frozen assignment")
        elif self.assignment is not None:
            raise ValueError("failed freeze must not reserve fixture assignments")
        if self.status == "SCORED":
            if self.score_sha256 is None or self.scored_at is None:
                raise ValueError("scored event lacks immutable score identity/time")
            if (
                self.assignment is None
                or not self.assignment.frozen_at < self.scored_at <= self.recorded_at
            ):
                raise ValueError("score timing differs from forecast")
        elif self.score_sha256 is not None or self.scored_at is not None:
            raise ValueError("unscored event cannot contain score evidence")
        return self


class CampaignLedgerV1(SealedEvidence):
    schema_version: Literal["public-team-strength-prospective-campaign-ledger-v1"] = (
        "public-team-strength-prospective-campaign-ledger-v1"
    )
    campaign_id: Literal["CURRENT-TEAM-STRENGTH-001V"] = "CURRENT-TEAM-STRENGTH-001V"
    protocol: ProspectiveProtocolV1
    protocol_history: tuple[ProspectiveProtocolV1, ...] = ()
    created_at: datetime
    predecessor_sha256: SHA | None = None
    events: tuple[CohortEvent, ...]
    data_class: Literal["PUBLIC_OPENFOOTBALL_TEAM_ONLY"] = "PUBLIC_OPENFOOTBALL_TEAM_ONLY"
    production_active: Literal[False] = False

    @model_validator(mode="after")
    def check_history(self) -> Self:
        protocols = {row.semantic_sha256: row for row in (*self.protocol_history, self.protocol)}
        chain = (*self.protocol_history, self.protocol)
        for previous, current in pairwise(chain):
            if (
                current.predecessor_protocol_sha256 != previous.semantic_sha256
                or current.evaluation_epoch == previous.evaluation_epoch
                or current.created_at <= previous.created_at
            ):
                raise ValueError("protocol amendment chain/epoch mismatch")
        if not self.events or self.events[0].assignment != load_pilot_assignment():
            raise ValueError("campaign must preserve the pinned authentic P01 assignment")
        assigned: dict[str, CohortAssignment] = {}
        used: set[UUID] = set()
        states: dict[str, str] = {}
        for row in self.events:
            if row.recorded_at > self.created_at:
                raise ValueError("ledger predates event")
            if row.assignment is not None:
                assignment = row.assignment
                bound_protocol = protocols.get(assignment.protocol_sha256)
                if bound_protocol is None or (
                    assignment.evaluation_epoch != bound_protocol.evaluation_epoch
                    or assignment.draw_policy_sha256 != bound_protocol.draw_policy_sha256
                    or assignment.methodology_sha256 != bound_protocol.methodology_sha256
                ):
                    raise ValueError("model/draw-policy evaluation epoch mismatch")
                if (
                    assignment.cohort_id != "P01"
                    and assignment.forecast_origin < bound_protocol.created_at
                ):
                    raise ValueError("standard cohort predates effective protocol")
                if row.cohort_id in assigned:
                    if assigned[row.cohort_id] != assignment:
                        raise ValueError("historical fixture assignments cannot be rewritten")
                else:
                    if set(assignment.fixture_ids) & used:
                        raise ValueError("canonical fixture already belongs to a prior cohort")
                    if row.status != "FROZEN":
                        raise ValueError("assignment must begin with frozen event")
                    assigned[row.cohort_id] = assignment
                    used.update(assignment.fixture_ids)
            old = states.get(row.cohort_id)
            if old is not None and (
                old not in {"FROZEN", "OUTCOME_NOT_YET_ELIGIBLE", "SCORING_BLOCKED"}
                or row.status not in {"OUTCOME_NOT_YET_ELIGIBLE", "SCORING_BLOCKED", "SCORED"}
            ):
                raise ValueError("terminal cohort identity cannot be reused")
            states[row.cohort_id] = row.status
        if tuple(row.recorded_at for row in self.events) != tuple(
            sorted(row.recorded_at for row in self.events)
        ):
            raise ValueError("ledger event times are not monotonic")
        return self


def append_event(ledger: CampaignLedgerV1, event: CohortEvent) -> CampaignLedgerV1:
    ledger = authenticate(ledger)
    return seal(
        CampaignLedgerV1,
        protocol=ledger.protocol,
        protocol_history=ledger.protocol_history,
        created_at=event.recorded_at,
        predecessor_sha256=ledger.semantic_sha256,
        events=(*ledger.events, event),
    )


def freeze_window(earliest_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(earliest_date - timedelta(days=2), time(12), tzinfo=UTC)
    return start, start + timedelta(hours=6)


def load_pilot_assignment() -> CohortAssignment:
    resource = resources.files("dmf_pulse").joinpath(
        "evaluation/resources/team_strength_p01_reference.json"
    )
    body = (
        resource.read_bytes()
        if resource.is_file()
        else (
            Path(__file__).resolve().parents[3]
            / "config/evaluation/team_strength_p01_reference.json"
        ).read_bytes()
    )
    assignment = CohortAssignment.model_validate_json(body)
    if (
        canonical_sha256(assignment)
        != "5ffa3c5eea4f483a667e104c79e804cc0707b7d5b1aee98eabcc675c90cf80cf"
    ):
        raise StrengthEvidenceError("pinned P01 reference metadata differs")
    return assignment


def initial_campaign_ledger() -> CampaignLedgerV1:
    protocol = load_protocol()
    return seal(
        CampaignLedgerV1,
        protocol=protocol,
        created_at=protocol.created_at,
        events=(
            CohortEvent(
                cohort_id="P01",
                status="FROZEN",
                recorded_at=protocol.created_at,
                assignment=load_pilot_assignment(),
                detail="Existing pre-outcome pilot; unscored and cadence-separate",
            ),
        ),
    )


def advance_campaign_protocol(
    ledger: CampaignLedgerV1, protocol: ProspectiveProtocolV1
) -> CampaignLedgerV1:
    ledger, protocol = authenticate(ledger), authenticate(protocol)
    if (
        protocol.predecessor_protocol_sha256 != ledger.protocol.semantic_sha256
        or protocol.evaluation_epoch == ledger.protocol.evaluation_epoch
        or protocol.created_at <= ledger.created_at
    ):
        raise StrengthEvidenceError("explicit amendment must advance protocol and epoch")
    return seal(
        CampaignLedgerV1,
        protocol=protocol,
        protocol_history=(*ledger.protocol_history, ledger.protocol),
        created_at=protocol.created_at,
        predecessor_sha256=ledger.semantic_sha256,
        events=ledger.events,
    )


class CohortPlanV1(SealedEvidence):
    schema_version: Literal["public-team-strength-prospective-cohort-plan-v1"] = (
        "public-team-strength-prospective-cohort-plan-v1"
    )
    cohort_id: str
    protocol_sha256: SHA
    ledger_sha256: SHA
    schedule_sha256: SHA
    fixture_registry_sha256: SHA
    assessed_at: datetime
    fixture_ids: tuple[UUID, ...]
    scheduled_dates: tuple[date, ...]
    target_freeze: datetime
    freeze_window_end: datetime
    status: Literal["READY", "NOT_YET_IN_FREEZE_WINDOW", "COHORT_FREEZE_WINDOW_MISSED"]

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        if not self.fixture_ids or len(self.fixture_ids) != len(self.scheduled_dates):
            raise ValueError("plan fixture dates missing")
        if len(self.fixture_ids) > 10 or len(set(self.fixture_ids)) != len(self.fixture_ids):
            raise ValueError("invalid cohort size/duplicate fixture")
        if tuple(zip(self.scheduled_dates, self.fixture_ids, strict=True)) != tuple(
            sorted(zip(self.scheduled_dates, self.fixture_ids, strict=True))
        ):
            raise ValueError("cohort selection ordering differs")
        start, end = freeze_window(min(self.scheduled_dates))
        expected = (
            "NOT_YET_IN_FREEZE_WINDOW"
            if self.assessed_at < start
            else ("READY" if self.assessed_at <= end else "COHORT_FREEZE_WINDOW_MISSED")
        )
        if (self.target_freeze, self.freeze_window_end, self.status) != (start, end, expected):
            raise ValueError("freeze window status differs")
        return self


def plan_cohort(
    *,
    ledger: CampaignLedgerV1,
    schedule: ParsedSnapshot,
    registry: FixtureRegistry,
    as_of: datetime,
) -> CohortPlanV1:
    ledger, schedule, registry = (
        authenticate(ledger),
        authenticate(schedule),
        authenticate(registry),
    )
    as_of = FrozenEvidence.utc_datetimes(as_of)
    if max(schedule.lineage.usable_at, registry.registered_at, ledger.created_at) > as_of:
        raise StrengthEvidenceError("post-cutoff public planning evidence")
    if schedule.fixture_registry_sha256 != registry.semantic_sha256:
        raise StrengthEvidenceError("planning registry/schedule identity mismatch")
    assigned = {
        fixture
        for row in ledger.events
        if row.assignment is not None
        for fixture in row.assignment.fixture_ids
    }
    registered = {row.fixture_id: row for row in registry.fixtures}
    eligible = sorted(
        (
            row
            for row in schedule.matches
            if row.fixture.fixture_id not in assigned
            and row.finality == "NO_SCORE"
            and row.home_goals is None
            and row.away_goals is None
            and row.source_match_date > as_of.date()
            and registered.get(row.fixture.fixture_id) == row.fixture
        ),
        key=lambda row: (row.source_match_date, row.fixture.fixture_id),
    )[: ledger.protocol.cohort_size]
    if not eligible:
        raise StrengthEvidenceError("SCHEDULE_BLOCKED: no eligible unassigned future fixtures")
    start, end = freeze_window(eligible[0].source_match_date)
    index = max((int(row.cohort_id[1:]) for row in ledger.events), default=1) + 1
    return seal(
        CohortPlanV1,
        cohort_id=f"P{index:02d}",
        protocol_sha256=ledger.protocol.semantic_sha256,
        ledger_sha256=ledger.semantic_sha256,
        schedule_sha256=schedule.semantic_sha256,
        fixture_registry_sha256=registry.semantic_sha256,
        assessed_at=as_of,
        fixture_ids=tuple(row.fixture.fixture_id for row in eligible),
        scheduled_dates=tuple(row.source_match_date for row in eligible),
        target_freeze=start,
        freeze_window_end=end,
        status="NOT_YET_IN_FREEZE_WINDOW"
        if as_of < start
        else ("READY" if as_of <= end else "COHORT_FREEZE_WINDOW_MISSED"),
    )


def guard_freeze(
    plan: CohortPlanV1,
    *,
    ledger: CampaignLedgerV1,
    schedule: ParsedSnapshot,
    registry: FixtureRegistry,
    forecast_origin: datetime,
    frozen_at: datetime,
) -> None:
    plan = authenticate(plan)
    origin, frozen = (
        FrozenEvidence.utc_datetimes(forecast_origin),
        FrozenEvidence.utc_datetimes(frozen_at),
    )
    if not plan.target_freeze <= origin <= frozen <= plan.freeze_window_end:
        raise StrengthEvidenceError("COHORT_FREEZE_WINDOW_MISSED")
    expected = plan_cohort(
        ledger=ledger, schedule=schedule, registry=registry, as_of=forecast_origin
    )
    if (
        plan.fixture_ids,
        plan.scheduled_dates,
        plan.cohort_id,
        plan.ledger_sha256,
        plan.schedule_sha256,
        plan.protocol_sha256,
    ) != (
        expected.fixture_ids,
        expected.scheduled_dates,
        expected.cohort_id,
        expected.ledger_sha256,
        expected.schedule_sha256,
        expected.protocol_sha256,
    ):
        raise StrengthEvidenceError("cohort plan differs from current authenticated selection")
    if min(plan.scheduled_dates) <= frozen.date():
        raise StrengthEvidenceError("date-only safeguard cannot be weakened")


def next_freeze_opportunity(
    *,
    ledger: CampaignLedgerV1,
    schedule: ParsedSnapshot,
    registry: FixtureRegistry,
    as_of: datetime,
) -> CohortPlanV1:
    """Predict the next window from this vintage; fresh readiness is still required.

    Advance only calendar time, applying the same first-ten rule at each origin.
    Never remove a still-eligible fixture merely to obtain a later window.
    """
    candidate = plan_cohort(ledger=ledger, schedule=schedule, registry=registry, as_of=as_of)
    while candidate.freeze_window_end < as_of or candidate.status == "COHORT_FREEZE_WINDOW_MISSED":
        probe = datetime.combine(candidate.assessed_at.date() + timedelta(days=1), time(), UTC)
        candidate = plan_cohort(ledger=ledger, schedule=schedule, registry=registry, as_of=probe)
    origin = max(as_of, candidate.target_freeze)
    return plan_cohort(ledger=ledger, schedule=schedule, registry=registry, as_of=origin)


def amend_protocol(
    protocol: ProspectiveProtocolV1, *, ticket: str, created_at: datetime
) -> ProspectiveProtocolV1:
    protocol = authenticate(protocol)
    values = protocol.model_dump(
        mode="python", exclude={"semantic_sha256", "protocol_semantic_sha256"}
    )
    values.update(
        protocol_version=f"{int(protocol.protocol_version.split('.')[0]) + 1}.0.0",
        evaluation_epoch=f"EVALUATION_EPOCH_{int(protocol.evaluation_epoch[-3:]) + 1:03d}",
        predecessor_protocol_sha256=protocol.semantic_sha256,
        amendment_ticket=ticket,
        created_at=created_at,
    )
    if created_at <= protocol.created_at:
        raise StrengthEvidenceError("amendment must follow its predecessor")
    return seal(ProspectiveProtocolV1, **values)


def protocol_summary(protocol: ProspectiveProtocolV1) -> dict[str, object]:
    result: dict[str, object] = json.loads(authenticate(protocol).model_dump_json())
    result["protocol_semantic_sha256"] = protocol.semantic_sha256
    return result
