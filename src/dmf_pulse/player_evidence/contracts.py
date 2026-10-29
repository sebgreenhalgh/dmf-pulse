"""Strict fixture participation, temporal identity and descriptive feature contracts."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StrictInt, StrictStr, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.player_lab.contracts import LabModel, Sha

Identifier = Annotated[StrictStr, Field(min_length=1, max_length=100)]
Season = Annotated[StrictStr, Field(pattern=r"^20\d{2}/\d{2}$")]
Role = Literal["START", "BENCH", "OUT", "UNKNOWN"]
Reason = Literal[
    "NOT_REPORTED",
    "POST_CUTOFF",
    "MAPPING_UNRESOLVED",
    "ROSTER_NOT_PROVEN",
    "OTHER_TEAM",
    "FIXTURE_NOT_FINAL",
    "OUTSIDE_WINDOW",
    "UNSUPPORTED_MINUTE_CONVENTION",
    "ROLE_UNKNOWN",
    "MINUTES_UNKNOWN",
    "NO_ELIGIBLE_HISTORY",
]


class EvidenceError(ValueError):
    """A typed evidence error with no provider payload in its message."""


class EvidenceSource(LabModel):
    source_id: Identifier
    provider_id: Identifier
    payload_sha256: Sha
    licence_id: Identifier
    approval_id: Identifier
    purpose: Literal["DESCRIPTIVE_EVIDENCE", "MODEL_TRAINING", "PRODUCTION_PREDICTION"]
    mode: Literal["SYNTHETIC", "RECONSTRUCTED", "LIVE_OBSERVED"]
    qualification: Literal["OWNED_QUALIFIED", "PROPOSED", "REVOKED"]


class Timed(LabModel):
    observed_at: datetime
    usable_at: datetime

    @model_validator(mode="after")
    def temporal(self) -> Self:
        if self.observed_at > self.usable_at:
            raise ValueError("evidence usable time precedes observation")
        return self

    @property
    def semantic_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class IdentityMapping(Timed):
    mapping_id: Identifier
    kind: Literal["PLAYER", "TEAM"]
    season: Season
    provider_id: Identifier
    canonical_id: UUID
    effective_from: datetime
    effective_until: datetime

    @model_validator(mode="after")
    def interval(self) -> Self:
        if self.effective_from >= self.effective_until:
            raise ValueError("identity effective interval is empty")
        return self


class EvidenceFixture(Timed):
    fixture_id: UUID
    provider_fixture_id: Identifier
    season: Season
    home_provider_team_id: Identifier
    away_provider_team_id: Identifier
    kickoff_at: datetime
    finished_at: datetime
    status: Literal["FINAL", "ABANDONED", "INCOMPLETE"]

    @model_validator(mode="after")
    def fixture_identity(self) -> Self:
        if self.home_provider_team_id == self.away_provider_team_id:
            raise ValueError("fixture teams must differ")
        if not self.kickoff_at < self.finished_at <= self.observed_at:
            raise ValueError("fixture completion clocks differ")
        return self


class RosterMembership(Timed):
    season: Season
    provider_fixture_id: Identifier
    provider_player_id: Identifier
    provider_team_id: Identifier
    status: Literal["VERIFIED_ELIGIBLE", "UNKNOWN"]


class Participation(Timed):
    season: Season
    provider_fixture_id: Identifier
    provider_player_id: Identifier
    provider_team_id: Identifier
    revision: Annotated[StrictInt, Field(ge=0)]
    supersedes_sha256: Sha | None
    role: Role
    role_missing_reason: Literal["NOT_REPORTED", "NOT_SUPPORTED"] | None
    minutes: Annotated[StrictInt, Field(ge=0, le=150)] | None
    minutes_missing_reason: Literal["NOT_REPORTED", "NOT_SUPPORTED"] | None
    minute_convention: Literal["REGULATION_0_90", "INCLUDING_STOPPAGE", "UNSUPPORTED"]

    @model_validator(mode="after")
    def participation_values(self) -> Self:
        if (self.role == "UNKNOWN") != (self.role_missing_reason is not None):
            raise ValueError("unknown role needs its reason; known role has no missing reason")
        if (self.minutes is None) != (self.minutes_missing_reason is not None):
            raise ValueError("unknown minutes need their reason")
        if self.role == "OUT" and self.minutes not in {None, 0}:
            raise ValueError("OUT cannot claim positive minutes")
        if self.minute_convention == "REGULATION_0_90" and self.minutes is not None:
            if self.minutes > 90:
                raise ValueError("regulation minute evidence exceeds convention")
            if self.role == "START" and self.minutes == 0:
                raise ValueError("START zero is unsupported by this evidence convention")
        if (self.revision == 0) != (self.supersedes_sha256 is None):
            raise ValueError("revision predecessor is required exactly after initial vintage")
        return self


class ParticipationDataset(LabModel):
    schema_version: Literal["fixture-participation-evidence-v1"]
    source_id: Identifier
    mode: Literal["SYNTHETIC", "RECONSTRUCTED", "LIVE_OBSERVED"]
    mappings: tuple[IdentityMapping, ...]
    fixtures: tuple[EvidenceFixture, ...]
    memberships: tuple[RosterMembership, ...]
    observations: tuple[Participation, ...]

    @model_validator(mode="after")
    def exact_relations_and_revisions(self) -> Self:
        if len({item.mapping_id for item in self.mappings}) != len(self.mappings):
            raise ValueError("mapping identities are duplicated")
        fixture_keys = {(item.season, item.provider_fixture_id) for item in self.fixtures}
        if len(fixture_keys) != len(self.fixtures) or len(
            {item.fixture_id for item in self.fixtures}
        ) != len(self.fixtures):
            raise ValueError("fixture identities are duplicated")
        fixtures = {(item.season, item.provider_fixture_id): item for item in self.fixtures}
        memberships = {
            (item.season, item.provider_fixture_id, item.provider_player_id)
            for item in self.memberships
        }
        if len(memberships) != len(self.memberships):
            raise ValueError("fixture roster identities are duplicated")
        chains: dict[tuple[str, str, str], list[Participation]] = defaultdict(list)
        observed_items: tuple[RosterMembership | Participation, ...] = (
            *self.memberships,
            *self.observations,
        )
        for item in observed_items:
            fixture = fixtures.get((item.season, item.provider_fixture_id))
            if fixture is None or item.provider_team_id not in {
                fixture.home_provider_team_id,
                fixture.away_provider_team_id,
            }:
                raise ValueError("participation fixture/team identity differs")
            if isinstance(item, Participation):
                if item.observed_at < fixture.finished_at:
                    raise ValueError("participation observation precedes fixture completion")
                chains[(item.season, item.provider_fixture_id, item.provider_player_id)].append(
                    item
                )
        for values in chains.values():
            values.sort(key=lambda item: item.revision)
            for index, item in enumerate(values):
                if item.revision != index:
                    raise ValueError("participation revision chain is duplicated or incomplete")
                if index and (
                    item.supersedes_sha256 != values[index - 1].semantic_sha256
                    or item.usable_at <= values[index - 1].usable_at
                    or item.observed_at < values[index - 1].observed_at
                ):
                    raise ValueError("participation revision lineage differs")
        return self


class PlayerScope(LabModel):
    player_id: UUID
    team_id: UUID


class FeatureRequest(LabModel):
    season: Season
    players: Annotated[tuple[PlayerScope, ...], Field(min_length=1, max_length=1000)]
    cutoff: datetime
    history_start: datetime
    target_kickoff: datetime
    maximum_fixtures: Annotated[StrictInt, Field(ge=1, le=100)] = 10

    @model_validator(mode="after")
    def cutoff_and_population(self) -> Self:
        if not self.history_start < self.cutoff < self.target_kickoff:
            raise ValueError("history/cutoff/target clocks differ")
        identifiers = tuple(str(item.player_id) for item in self.players)
        if identifiers != tuple(sorted(set(identifiers))):
            raise ValueError("requested players must be unique and ordered")
        return self


class Ratio(LabModel):
    numerator: Annotated[StrictInt, Field(ge=0)]
    denominator: Annotated[StrictInt, Field(ge=0)]
    value: Decimal | None

    @model_validator(mode="after")
    def exact_ratio(self) -> Self:
        if self.denominator == 0:
            if self.numerator != 0 or self.value is not None:
                raise ValueError("empty empirical ratio must be explicitly unavailable")
        else:
            with localcontext() as context:
                context.prec = 40
                context.rounding = ROUND_HALF_EVEN
                if self.value != Decimal(self.numerator) / Decimal(self.denominator):
                    raise ValueError("empirical ratio differs from its counts")
        return self


class MinuteDistribution(LabModel):
    sample_count: Annotated[StrictInt, Field(ge=0)]
    counts: dict[StrictInt, StrictInt]

    @model_validator(mode="after")
    def counted(self) -> Self:
        if any(not 0 <= key <= 90 or value <= 0 for key, value in self.counts.items()):
            raise ValueError("empirical minute counts are invalid")
        if sum(self.counts.values()) != self.sample_count:
            raise ValueError("empirical minute sample count differs")
        return self


class SelectedEvidence(LabModel):
    fixture_id: UUID
    participation_sha256: Sha
    revision: Annotated[StrictInt, Field(ge=0)]
    identity_mapping_sha256s: tuple[Sha, ...]
    membership_sha256: Sha

    @model_validator(mode="after")
    def exact_mapping_receipt(self) -> Self:
        if len(self.identity_mapping_sha256s) != 2 or self.identity_mapping_sha256s != tuple(
            sorted(set(self.identity_mapping_sha256s))
        ):
            raise ValueError("selected evidence requires its exact player and team mapping")
        return self


class PlayerFeatures(LabModel):
    player_id: UUID
    team_id: UUID
    opportunity_count: Annotated[StrictInt, Field(ge=0)]
    selected_count: Annotated[StrictInt, Field(ge=0)]
    coverage_status: Literal["COMPLETE", "PARTIAL", "NO_ELIGIBLE_HISTORY"]
    role_counts: dict[Role, StrictInt]
    start_rate: Ratio
    mean_minutes: Ratio
    sixty_plus_rate: Ratio
    all_minutes: MinuteDistribution
    starter_minutes: MinuteDistribution
    bench_minutes: MinuteDistribution
    latest_observation_age_seconds: Annotated[StrictInt, Field(ge=0)] | None
    missingness: dict[Reason, StrictInt]
    selected: tuple[SelectedEvidence, ...]

    @model_validator(mode="after")
    def reconcile_empirical_support(self) -> Self:
        if set(self.role_counts) != {"START", "BENCH", "OUT", "UNKNOWN"} or any(
            value < 0 for value in self.role_counts.values()
        ):
            raise ValueError("role counts must explicitly cover all four evidence states")
        if (
            self.selected_count != len(self.selected)
            or self.selected_count > self.opportunity_count
            or sum(self.role_counts.values()) != self.selected_count
            or len({item.fixture_id for item in self.selected}) != len(self.selected)
        ):
            raise ValueError("selected participation counts do not reconcile")
        if (
            self.start_rate.numerator != self.role_counts["START"]
            or self.start_rate.denominator != self.selected_count - self.role_counts["UNKNOWN"]
            or self.mean_minutes.denominator != self.all_minutes.sample_count
            or self.mean_minutes.numerator
            != sum(minute * count for minute, count in self.all_minutes.counts.items())
            or self.sixty_plus_rate.denominator != self.all_minutes.sample_count
            or self.sixty_plus_rate.numerator
            != sum(count for minute, count in self.all_minutes.counts.items() if minute >= 60)
            or self.all_minutes.sample_count > self.selected_count
            or self.starter_minutes.sample_count > self.role_counts["START"]
            or self.bench_minutes.sample_count > self.role_counts["BENCH"]
        ):
            raise ValueError("empirical features differ from recorded support")
        if any(value <= 0 for value in self.missingness.values()):
            raise ValueError("missingness counts must be positive")
        expected_status = (
            "NO_ELIGIBLE_HISTORY"
            if not self.opportunity_count
            else "PARTIAL"
            if self.missingness
            else "COMPLETE"
        )
        if self.coverage_status != expected_status or (self.selected_count == 0) != (
            self.latest_observation_age_seconds is None
        ):
            raise ValueError("coverage or age differs from selected evidence")
        return self


class EvidenceFeatureSet(LabModel):
    schema_version: Literal["descriptive-player-evidence-features-v1"] = (
        "descriptive-player-evidence-features-v1"
    )
    mode: Literal["SYNTHETIC"] = "SYNTHETIC"
    status: Literal["EVIDENCE_ONLY_NOT_MODEL_INPUT"] = "EVIDENCE_ONLY_NOT_MODEL_INPUT"
    production_activation: Literal[False] = False
    predictive_uncertainty_status: Literal["NOT_ESTIMATED_EMPIRICAL_SUPPORT_ONLY"] = (
        "NOT_ESTIMATED_EMPIRICAL_SUPPORT_ONLY"
    )
    source: EvidenceSource
    request: FeatureRequest
    players: tuple[PlayerFeatures, ...]
    unattributed_player_membership_count: Annotated[StrictInt, Field(ge=0)]
    arithmetic_policy: Literal["DECIMAL_40_HALF_EVEN"] = "DECIMAL_40_HALF_EVEN"
    limitations: tuple[str, ...] = (
        "OWNED_SYNTHETIC_ENGINEERING_ACCEPTANCE_NOT_REAL_PLAYER_HISTORY",
        "DESCRIPTIVE_RATES_ARE_NOT_CALIBRATED_PREDICTIVE_PROBABILITIES",
        "CURRENT_ACCEPTED_STAGE7_STAGE9_MODELS_UNCHANGED",
        "ONLY_EXACT_REQUESTED_TEAM_FIXTURE_MEMBERSHIP_INCLUDED",
        "NO_REAL_SOURCE_QUALIFIED_NO_TRAINING_OR_ACTIVATION",
    )

    @model_validator(mode="after")
    def exact_report_population(self) -> Self:
        if (
            self.source.mode != "SYNTHETIC"
            or self.source.purpose != "DESCRIPTIVE_EVIDENCE"
            or self.source.qualification != "OWNED_QUALIFIED"
            or tuple((item.player_id, item.team_id) for item in self.players)
            != tuple((item.player_id, item.team_id) for item in self.request.players)
        ):
            raise ValueError("feature report source or exact requested population differs")
        return self

    @property
    def semantic_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))
