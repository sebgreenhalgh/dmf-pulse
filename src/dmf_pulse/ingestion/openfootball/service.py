"""Rights-gated assembly of one reconstructed historical league score prior."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from itertools import pairwise
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.football_events._decimal import parse_utc
from dmf_pulse.football_events.score_prior_request import ScorePriorRequest
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.models import (
    CapabilityValue,
    RightsCapability,
    RightsProfile,
    RightsProfileStatus,
)
from dmf_pulse.ingestion.openfootball.client import (
    HttpClientOpenFootballTransport,
    OpenFootballHttpResponse,
    OpenFootballTransport,
    fetch_resource,
)
from dmf_pulse.ingestion.openfootball.config import (
    APPROVED_PROFILE_ID,
    OpenFootballProviderConfig,
    load_provider_config,
    load_rights_profiles,
    provider_config_sha256,
    rights_config_sha256,
)
from dmf_pulse.ingestion.openfootball.parser import (
    SeasonScoreAudit,
    parse_season,
    validate_licence,
)
from dmf_pulse.ingestion.rights import require_rights

_APPROVED_PURPOSE = "private internal historical score-prior estimation"
_APPROVED_ACCOUNT_SCOPE = "public commit-pinned OpenFootball football.json content"
_APPROVED_GEOGRAPHY = "private UK analytical use"
_APPROVAL_ID = "CURRENT-SCORE-PRIOR-001A#openfootball_football_json_score_prior_v1"
_TERMS_SOURCE = "OpenFootball football.json/LICENSE.md"
_TERMS_VERSION = "CC0-1.0; immutable licence blob 670154e3538863b2d9891fd5483160fbdfc89164"
_APPROVED_AT = datetime(2026, 8, 30, 8, 40, 16, 812047, tzinfo=UTC)
_APPROVED_BY = "Sebastian Greenhalgh"
_RETENTION_REASON = (
    "CC0-1.0 imposes no source retention limit; immutable retention is permitted for "
    "reproducibility."
)
_REQUIRED_CAPABILITIES = (
    RightsCapability.AUTOMATED_ACCESS,
    RightsCapability.TRANSIENT_PROCESSING,
    RightsCapability.MODEL_TRAINING,
    RightsCapability.PRIVATE_INTERNAL_USE,
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        del deep
        data = self.model_dump(mode="python", exclude_none=False)
        if update:
            data.update(dict(update))
        return type(self).model_validate(data)


class CurrentScorePriorBuildRequest(_FrozenModel):
    information_cutoff: datetime
    rights_profile_id: str = Field(min_length=1, max_length=120)

    @field_validator("information_cutoff", mode="before")
    @classmethod
    def validate_cutoff(cls, value: object) -> datetime:
        return parse_utc(value, field_name="information_cutoff")


class SourceResourceLineage(_FrozenModel):
    resource_kind: Literal["LICENCE", "SEASON"]
    source_path: str
    git_blob_sha1: str = Field(pattern=r"^[0-9a-f]{40}$")
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(gt=0)
    received_at: datetime

    @field_validator("received_at", mode="before")
    @classmethod
    def validate_received_at(cls, value: object) -> datetime:
        return parse_utc(value, field_name="received_at")


class CurrentScorePriorProvenance(_FrozenModel):
    provider_key: Literal["openfootball_football_json"]
    repository: Literal["openfootball/football.json"]
    source_commit_sha: Literal["f27dcbef681db2c3195f9def62316ce497278781"]
    source_commit_timestamp: datetime
    source_mode: Literal["RECONSTRUCTED"]
    rights_profile_id: Literal["openfootball_football_json_score_prior_v1"]
    rights_profile_version: Literal["1.0.0"]
    human_approval_id: str
    approved_by: str
    approved_at: datetime
    information_cutoff: datetime
    request_started_at: datetime
    validation_completed_at: datetime
    usable_at: datetime
    provider_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rights_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    adapter_version: Literal["openfootball-score-prior-v1"]
    contract_version: Literal["openfootball-score-prior-v1"]
    transport_id: str = Field(min_length=1, max_length=80)
    transport_call_count: Literal[4]
    resources: tuple[
        SourceResourceLineage,
        SourceResourceLineage,
        SourceResourceLineage,
        SourceResourceLineage,
    ]

    @field_validator(
        "source_commit_timestamp",
        "approved_at",
        "information_cutoff",
        "request_started_at",
        "validation_completed_at",
        "usable_at",
        mode="before",
    )
    @classmethod
    def validate_timestamp(cls, value: object, info: ValidationInfo) -> datetime:
        return parse_utc(value, field_name=info.field_name or "timestamp")

    @model_validator(mode="after")
    def validate_temporal_order(self) -> Self:
        receipts = tuple(resource.received_at for resource in self.resources)
        times = (
            self.request_started_at,
            *receipts,
            self.validation_completed_at,
            self.usable_at,
            self.information_cutoff,
        )
        if any(left > right for left, right in pairwise(times)):
            raise ValueError("score-prior provenance timestamps are not monotonic")
        if self.approved_at > self.request_started_at:
            raise ValueError("rights approval occurred after the operation began")
        if self.source_commit_timestamp > receipts[0]:
            raise ValueError("source commit timestamp occurs after source receipt")
        if tuple(resource.resource_kind for resource in self.resources) != (
            "LICENCE",
            "SEASON",
            "SEASON",
            "SEASON",
        ):
            raise ValueError("score-prior resource lineage order is invalid")
        return self


class _CurrentScorePriorSummaryBody(_FrozenModel):
    schema_version: Literal["current-score-prior-summary-v1"]
    status: Literal["CURRENT_SCORE_PRIOR_READY"]
    classification: Literal["WEAK_LEAGUE_LEVEL_SUPPORT_PRIOR"]
    method_id: Literal["PL_LEAGUE_HOME_AWAY_MEAN_3_COMPLETE_SEASONS_V1"]
    model_family: Literal["INDEPENDENT_POISSON_V1"]
    home_goal_rate: Decimal
    away_goal_rate: Decimal
    sample_size: Literal[1140]
    home_goal_total: Literal[1839]
    away_goal_total: Literal[1567]
    source_commit_sha: Literal["f27dcbef681db2c3195f9def62316ce497278781"]
    rights_profile_id: Literal["openfootball_football_json_score_prior_v1"]
    source_mode: Literal["RECONSTRUCTED"]
    usable_at: datetime
    information_cutoff: datetime
    market_evidence_used: Literal[False]
    current_team_strength_claim: Literal[False]
    production_active: Literal[False]
    source_result_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("usable_at", "information_cutoff", mode="before")
    @classmethod
    def validate_summary_time(cls, value: object, info: ValidationInfo) -> datetime:
        return parse_utc(value, field_name=info.field_name or "summary timestamp")


class CurrentScorePriorSummary(_CurrentScorePriorSummaryBody):
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    def verify_semantic_identity(self) -> None:
        body = self.model_dump(mode="json", exclude={"semantic_sha256"})
        if canonical_sha256(body) != self.semantic_sha256:
            raise ValueError("current score-prior summary semantic identity is invalid")

    @model_validator(mode="after")
    def authenticate_summary(self) -> Self:
        self.verify_semantic_identity()
        return self


class _CurrentScorePriorResultBody(_FrozenModel):
    schema_version: Literal["current-score-prior-result-v1"]
    status: Literal["CURRENT_SCORE_PRIOR_READY"]
    classification: Literal["WEAK_LEAGUE_LEVEL_SUPPORT_PRIOR"]
    method_id: Literal["PL_LEAGUE_HOME_AWAY_MEAN_3_COMPLETE_SEASONS_V1"]
    sample_size: Literal[1140]
    home_goal_total: Literal[1839]
    away_goal_total: Literal[1567]
    score_prior_request: ScorePriorRequest
    seasons: tuple[SeasonScoreAudit, SeasonScoreAudit, SeasonScoreAudit]
    provenance: CurrentScorePriorProvenance
    market_evidence_used: Literal[False]
    current_team_strength_claim: Literal[False]
    production_active: Literal[False]


class CurrentScorePriorResult(_CurrentScorePriorResultBody):
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    def verify_semantic_identity(self) -> None:
        body = self.model_dump(mode="json", exclude={"semantic_sha256"})
        if canonical_sha256(body) != self.semantic_sha256:
            raise ValueError("current score-prior result semantic identity is invalid")

    @model_validator(mode="after")
    def authenticate_result(self) -> Self:
        self.verify_semantic_identity()
        return self

    def safe_summary(self) -> CurrentScorePriorSummary:
        self.verify_semantic_identity()
        body = _CurrentScorePriorSummaryBody.model_validate(
            {
                "away_goal_rate": self.score_prior_request.away_goal_rate,
                "away_goal_total": self.away_goal_total,
                "classification": self.classification,
                "current_team_strength_claim": self.current_team_strength_claim,
                "home_goal_rate": self.score_prior_request.home_goal_rate,
                "home_goal_total": self.home_goal_total,
                "information_cutoff": self.provenance.information_cutoff,
                "market_evidence_used": self.market_evidence_used,
                "method_id": self.method_id,
                "model_family": self.score_prior_request.model_family,
                "production_active": self.production_active,
                "rights_profile_id": self.provenance.rights_profile_id,
                "sample_size": self.sample_size,
                "schema_version": "current-score-prior-summary-v1",
                "source_commit_sha": self.provenance.source_commit_sha,
                "source_mode": self.provenance.source_mode,
                "source_result_semantic_sha256": self.semantic_sha256,
                "status": self.status,
                "usable_at": self.provenance.usable_at,
            }
        )
        return CurrentScorePriorSummary.model_validate(
            {
                **body.model_dump(mode="python"),
                "semantic_sha256": canonical_sha256(body),
            }
        )


class _CurrentScorePriorBundleBody(_FrozenModel):
    schema_version: Literal["current-score-prior-bundle-v1"]
    status: Literal["CURRENT_SCORE_PRIOR_READY"]
    fixture_id: UUID
    competition_id: UUID
    home_team_id: UUID
    away_team_id: UUID
    as_of: datetime
    source_result: CurrentScorePriorResult
    source_result_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    method_id: Literal["PL_LEAGUE_HOME_AWAY_MEAN_3_COMPLETE_SEASONS_V1"]
    model_family: Literal["INDEPENDENT_POISSON_V1"]
    score_prior_request: ScorePriorRequest
    source_usable_at: datetime
    source_mode: Literal["RECONSTRUCTED"]

    @field_validator("as_of", "source_usable_at", mode="before")
    @classmethod
    def validate_bundle_time(cls, value: object, info: ValidationInfo) -> datetime:
        return parse_utc(value, field_name=info.field_name or "bundle timestamp")

    @model_validator(mode="after")
    def validate_bindings(self) -> Self:
        if self.home_team_id == self.away_team_id:
            raise ValueError("home_team_id and away_team_id must be distinct")
        if self.source_result_semantic_sha256 != self.source_result.semantic_sha256:
            raise ValueError("bundle source-result identity does not match its source")
        if self.method_id != self.source_result.method_id:
            raise ValueError("bundle method does not match its source")
        if self.model_family != self.score_prior_request.model_family:
            raise ValueError("bundle model family does not match its request")
        if self.score_prior_request != self.source_result.score_prior_request:
            raise ValueError("bundle request does not match its authenticated source")
        if self.source_usable_at != self.source_result.provenance.usable_at:
            raise ValueError("bundle usable time does not match its source")
        if self.source_mode != self.source_result.provenance.source_mode:
            raise ValueError("bundle source mode does not match its source")
        if self.source_usable_at > self.as_of:
            raise ValueError("bundle source became usable after its as-of time")
        return self


class CurrentScorePriorBundle(_CurrentScorePriorBundleBody):
    """Authenticated source prior bound to one exact fixture identity and cutoff."""

    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    def verify_semantic_identity(self) -> None:
        self.source_result.verify_semantic_identity()
        body = self.model_dump(mode="json", exclude={"semantic_sha256"})
        if canonical_sha256(body) != self.semantic_sha256:
            raise ValueError("current score-prior bundle semantic identity is invalid")

    @model_validator(mode="after")
    def authenticate_bundle(self) -> Self:
        self.verify_semantic_identity()
        return self


def build_current_score_prior_bundle(
    source_result: CurrentScorePriorResult,
    *,
    fixture_id: UUID,
    competition_id: UUID,
    home_team_id: UUID,
    away_team_id: UUID,
    as_of: datetime,
) -> CurrentScorePriorBundle:
    """Bind one authenticated source result to an exact downstream fixture context."""

    try:
        source_result.verify_semantic_identity()
        normalized_as_of = parse_utc(as_of, field_name="as_of")
    except ValueError:
        raise IngestionError(
            "VALIDATION_FAILED", "current score-prior source or bundle input is invalid"
        ) from None
    if source_result.provenance.usable_at > normalized_as_of:
        raise IngestionError(
            "POST_CUTOFF", "current score-prior source became usable after the bundle as-of time"
        )
    try:
        body = _CurrentScorePriorBundleBody.model_validate(
            {
                "as_of": normalized_as_of,
                "away_team_id": away_team_id,
                "competition_id": competition_id,
                "fixture_id": fixture_id,
                "home_team_id": home_team_id,
                "method_id": source_result.method_id,
                "model_family": source_result.score_prior_request.model_family,
                "schema_version": "current-score-prior-bundle-v1",
                "score_prior_request": source_result.score_prior_request,
                "source_mode": source_result.provenance.source_mode,
                "source_result": source_result,
                "source_result_semantic_sha256": source_result.semantic_sha256,
                "source_usable_at": source_result.provenance.usable_at,
                "status": source_result.status,
            }
        )
        return CurrentScorePriorBundle.model_validate(
            {
                **body.model_dump(mode="python"),
                "semantic_sha256": canonical_sha256(body),
            }
        )
    except ValueError:
        raise IngestionError("VALIDATION_FAILED", "current score-prior bundle is invalid") from None


def score_prior_request_from_bundle(
    bundle: CurrentScorePriorBundle,
    *,
    fixture_id: UUID,
    competition_id: UUID,
    home_team_id: UUID,
    away_team_id: UUID,
    as_of: datetime,
) -> ScorePriorRequest:
    """Return the exact nested request only for an exact authenticated binding match."""

    try:
        bundle.verify_semantic_identity()
        normalized_as_of = parse_utc(as_of, field_name="as_of")
    except ValueError:
        raise IngestionError(
            "FIXTURE_NOT_APPROVED", "current score-prior bundle authentication failed"
        ) from None
    if (
        fixture_id != bundle.fixture_id
        or competition_id != bundle.competition_id
        or home_team_id != bundle.home_team_id
        or away_team_id != bundle.away_team_id
        or normalized_as_of != bundle.as_of
    ):
        raise IngestionError(
            "FIXTURE_NOT_APPROVED", "current score-prior bundle does not match the target fixture"
        )
    if bundle.source_usable_at > bundle.as_of:
        raise IngestionError(
            "POST_CUTOFF", "current score-prior source became usable after the bundle as-of time"
        )
    return bundle.score_prior_request


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _sample_clock(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise IngestionError("INTERNAL_INVARIANT", "score-prior clock returned a naive timestamp")
    return value.astimezone(UTC)


def _attach_call_count(error: IngestionError, call_count: int) -> IngestionError:
    details = dict(error.details)
    details["transport_call_count"] = call_count
    return IngestionError(
        error.code,
        error.message,
        retryable=error.retryable,
        details=details,
    )


def _fetch_resource_without_disclosure(
    *,
    config: OpenFootballProviderConfig,
    resource_path: str,
    transport: OpenFootballTransport,
) -> OpenFootballHttpResponse | None:
    """Preserve typed failures and erase arbitrary transport exception objects."""

    try:
        return fetch_resource(
            config=config,
            resource_path=resource_path,
            transport=transport,
        )
    except IngestionError:
        raise
    except Exception:
        return None


def _require_exact_profile(profile: RightsProfile, *, checked_at: datetime) -> None:
    exact = (
        profile.rights_profile_id == APPROVED_PROFILE_ID
        and profile.provider_key == "openfootball_football_json"
        and profile.profile_version == "1.0.0"
        and profile.status is RightsProfileStatus.HUMAN_APPROVED
        and profile.approved_purpose == _APPROVED_PURPOSE
        and profile.account_scope == _APPROVED_ACCOUNT_SCOPE
        and profile.geography_scope == _APPROVED_GEOGRAPHY
        and profile.human_approval_id == _APPROVAL_ID
        and profile.approved_by == _APPROVED_BY
        and profile.approved_at == _APPROVED_AT
        and profile.checked_at == _APPROVED_AT
        and profile.terms_source == _TERMS_SOURCE
        and profile.terms_version == _TERMS_VERSION
        and profile.retention_seconds is None
        and profile.retention_reason == _RETENTION_REASON
        and not profile.unresolved_rights
        and not profile.termination_deletion_required
        and not profile.attribution_required
        and profile.attribution_text is None
        and profile.capabilities[RightsCapability.PUBLIC_DISPLAY] is CapabilityValue.DENY
        and profile.capabilities[RightsCapability.REDISTRIBUTION] is CapabilityValue.DENY
        and all(
            profile.capabilities[capability] is CapabilityValue.ALLOW
            for capability in RightsCapability
            if capability not in {RightsCapability.PUBLIC_DISPLAY, RightsCapability.REDISTRIBUTION}
        )
    )
    if not exact:
        raise IngestionError(
            "RIGHTS_BLOCKED",
            "selected rights profile differs from the human-approved source scope",
            details={"transport_call_count": 0},
        )
    for capability in _REQUIRED_CAPABILITIES:
        require_rights(profile, capability, checked_at=checked_at)


def _response_body(response: OpenFootballHttpResponse, *, maximum: int) -> bytes:
    if response.status_code != 200 or response.content_type not in {
        "application/json",
        "text/plain",
        "application/octet-stream",
    }:
        raise IngestionError("SOURCE_UNAVAILABLE", "OpenFootball response is unusable")
    if len(response.body) > maximum:
        raise IngestionError("PAYLOAD_TOO_LARGE", "OpenFootball response is too large")
    return response.body


def _rates(
    audits: tuple[SeasonScoreAudit, SeasonScoreAudit, SeasonScoreAudit],
    config: OpenFootballProviderConfig,
) -> tuple[int, int, int, Decimal, Decimal]:
    sample_size = sum(item.match_count for item in audits)
    home_total = sum(item.home_goals for item in audits)
    away_total = sum(item.away_goals for item in audits)
    with localcontext() as context:
        context.prec = config.working_precision
        home_rate = (Decimal(home_total) / Decimal(sample_size)).quantize(
            config.output_quantum, rounding=ROUND_HALF_EVEN
        )
        away_rate = (Decimal(away_total) / Decimal(sample_size)).quantize(
            config.output_quantum, rounding=ROUND_HALF_EVEN
        )
    if (
        sample_size != 1140
        or home_total != 1839
        or away_total != 1567
        or home_rate != config.expected_home_goal_rate
        or away_rate != config.expected_away_goal_rate
    ):
        raise IngestionError("QUALITY_BLOCKED", "OpenFootball aggregate prior evidence differs")
    return sample_size, home_total, away_total, home_rate, away_rate


class CurrentScorePriorService:
    """Acquire four exact resources and emit no state beyond the returned value."""

    def __init__(
        self,
        *,
        provider_config: OpenFootballProviderConfig | None = None,
        rights_profiles: Mapping[str, RightsProfile] | None = None,
        transport: OpenFootballTransport | None = None,
        clock: Callable[[], datetime] = _utc_now,
        provider_config_identity: str | None = None,
        rights_config_identity: str | None = None,
    ) -> None:
        self._config = provider_config or load_provider_config()
        self._profiles = dict(
            load_rights_profiles() if rights_profiles is None else rights_profiles
        )
        self._transport = transport if transport is not None else HttpClientOpenFootballTransport()
        self._clock = clock
        self._provider_config_sha256 = provider_config_identity or (
            provider_config_sha256()
            if provider_config is None
            else canonical_sha256(provider_config.model_dump(mode="json"))
        )
        self._rights_config_sha256 = rights_config_identity or (
            rights_config_sha256()
            if rights_profiles is None
            else canonical_sha256(
                {
                    "profiles": [
                        profile.model_dump(mode="json")
                        for profile in sorted(
                            self._profiles.values(), key=lambda item: item.rights_profile_id
                        )
                    ],
                    "schema_version": "1.0.0",
                }
            )
        )

    def build(self, request: CurrentScorePriorBuildRequest) -> CurrentScorePriorResult:
        started_at = _sample_clock(self._clock)
        profile = self._profiles.get(request.rights_profile_id)
        if profile is None:
            raise IngestionError(
                "RIGHTS_BLOCKED",
                "selected OpenFootball rights profile is unavailable",
                details={"transport_call_count": 0},
            )
        _require_exact_profile(profile, checked_at=started_at)
        if profile.approved_at > started_at or started_at > request.information_cutoff:
            raise IngestionError(
                "POST_CUTOFF",
                "OpenFootball acquisition is not usable at the information cutoff",
                details={"transport_call_count": 0},
            )

        call_count = 0
        resources: list[SourceResourceLineage] = []
        audits: list[SeasonScoreAudit] = []
        configured_resources = (self._config.licence, *self._config.seasons)
        try:
            for index, resource in enumerate(configured_resources):
                call_count += 1
                response = _fetch_resource_without_disclosure(
                    config=self._config,
                    resource_path=resource.path,
                    transport=self._transport,
                )
                if response is None:
                    raise IngestionError(
                        "SOURCE_UNAVAILABLE", "OpenFootball transport failed unexpectedly"
                    )
                received_at = _sample_clock(self._clock)
                if received_at > request.information_cutoff:
                    raise IngestionError(
                        "POST_CUTOFF", "OpenFootball resource arrived after the information cutoff"
                    )
                raw_body = _response_body(response, maximum=self._config.max_response_bytes)
                if index == 0:
                    validate_licence(raw_body, self._config)
                    kind: Literal["LICENCE", "SEASON"] = "LICENCE"
                else:
                    season = self._config.seasons[index - 1]
                    audits.append(parse_season(raw_body, season=season, config=self._config))
                    kind = "SEASON"
                resources.append(
                    SourceResourceLineage.model_validate(
                        {
                            "byte_size": len(raw_body),
                            "content_sha256": resource.content_sha256,
                            "git_blob_sha1": resource.blob_sha1,
                            "received_at": received_at,
                            "resource_kind": kind,
                            "source_path": resource.path,
                        }
                    )
                )
            validation_completed_at = _sample_clock(self._clock)
            usable_at = _sample_clock(self._clock)
            if usable_at > request.information_cutoff:
                raise IngestionError(
                    "POST_CUTOFF", "OpenFootball prior became usable after the information cutoff"
                )
            if len(audits) != 3 or len(resources) != 4:
                raise IngestionError("INTERNAL_INVARIANT", "score-prior evidence is incomplete")
            audit_tuple = (audits[0], audits[1], audits[2])
            resource_tuple = (resources[0], resources[1], resources[2], resources[3])
            sample_size, home_total, away_total, home_rate, away_rate = _rates(
                audit_tuple, self._config
            )
            provenance = CurrentScorePriorProvenance.model_validate(
                {
                    "adapter_version": self._config.adapter_version,
                    "approved_at": profile.approved_at,
                    "approved_by": profile.approved_by,
                    "contract_version": self._config.contract_version,
                    "human_approval_id": profile.human_approval_id,
                    "information_cutoff": request.information_cutoff,
                    "provider_config_sha256": self._provider_config_sha256,
                    "provider_key": self._config.provider_key,
                    "repository": self._config.repository,
                    "request_started_at": started_at,
                    "resources": resource_tuple,
                    "rights_config_sha256": self._rights_config_sha256,
                    "rights_profile_id": profile.rights_profile_id,
                    "rights_profile_version": profile.profile_version,
                    "source_commit_sha": self._config.commit_sha,
                    "source_commit_timestamp": self._config.commit_timestamp,
                    "source_mode": "RECONSTRUCTED",
                    "transport_call_count": call_count,
                    "transport_id": self._transport.transport_id,
                    "usable_at": usable_at,
                    "validation_completed_at": validation_completed_at,
                }
            )
            result_body: dict[str, object] = {
                "away_goal_total": away_total,
                "classification": "WEAK_LEAGUE_LEVEL_SUPPORT_PRIOR",
                "current_team_strength_claim": False,
                "home_goal_total": home_total,
                "market_evidence_used": False,
                "method_id": self._config.method_id,
                "production_active": False,
                "provenance": provenance,
                "sample_size": sample_size,
                "schema_version": "current-score-prior-result-v1",
                "score_prior_request": ScorePriorRequest(
                    away_goal_rate=away_rate,
                    home_goal_rate=home_rate,
                ),
                "seasons": audit_tuple,
                "status": "CURRENT_SCORE_PRIOR_READY",
            }
            validated_body = _CurrentScorePriorResultBody.model_validate(result_body)
            return CurrentScorePriorResult.model_validate(
                {
                    **validated_body.model_dump(mode="python"),
                    "semantic_sha256": canonical_sha256(validated_body),
                }
            )
        except IngestionError as exc:
            raise _attach_call_count(exc, call_count) from exc
        except ValueError as exc:
            raise _attach_call_count(
                IngestionError("LIFECYCLE_INVARIANT", "score-prior lineage is invalid"),
                call_count,
            ) from exc


__all__ = [
    "CurrentScorePriorBuildRequest",
    "CurrentScorePriorBundle",
    "CurrentScorePriorProvenance",
    "CurrentScorePriorResult",
    "CurrentScorePriorService",
    "CurrentScorePriorSummary",
    "SourceResourceLineage",
    "build_current_score_prior_bundle",
    "score_prior_request_from_bundle",
]
