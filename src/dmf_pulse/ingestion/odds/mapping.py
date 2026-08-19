"""Explicit, hash-bound synthetic and current identity mapping plans."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.current import CurrentFplIdentity
from dmf_pulse.ingestion.fpl.parser import parse_rfc3339_timestamp


class _FrozenMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CanonicalFixtureLookup(_FrozenMapping):
    provider: Literal["official_fpl", "synthetic_fpl"]
    namespace: Literal["fpl.fixture.id"]
    external_id: str = Field(min_length=1, max_length=120)
    season_code: Literal["2026/27"]


class FixtureMapping(_FrozenMapping):
    provider: Literal["the_odds_api"]
    provider_event_id: str = Field(min_length=1, max_length=500)
    canonical_fixture_lookup: CanonicalFixtureLookup
    expected_home_team_external_id: str = Field(min_length=1, max_length=120)
    expected_away_team_external_id: str = Field(min_length=1, max_length=120)
    expected_commence_time: datetime
    validity_policy: Literal["SEASON_CONTEXT"]

    @field_validator("expected_commence_time", mode="before")
    @classmethod
    def parse_time(cls, value: object) -> datetime:
        if not isinstance(value, str):
            raise ValueError("expected commence time must be an RFC3339 string")
        return parse_rfc3339_timestamp(value)


class OperatorMapping(_FrozenMapping):
    provider: Literal["the_odds_api"]
    bookmaker_key: str = Field(min_length=1, max_length=500)
    canonical_operator_key: str = Field(min_length=1, max_length=120)
    canonical_display_name: str = Field(min_length=1, max_length=500)
    validity_policy: Literal["PROVIDER_GUARANTEED_OPEN_ENDED"]


class OddsMappingPlan(_FrozenMapping):
    contract_version: Literal["nrm-006-mapping-v2"]
    plan_id: str = Field(min_length=1, max_length=160)
    approved_at: datetime
    evidence_class: Literal["TEST_ONLY", "OFFICIAL", "APPROVED_MANUAL"]
    reviewer: str = Field(min_length=1, max_length=160)
    status: Literal["APPROVED_FOR_TEST", "APPROVED"]
    competition_key: Literal["SYNTHETIC_PL"]
    season_code: Literal["2026/27"]
    fixture_mappings: tuple[FixtureMapping, ...]
    operator_mappings: tuple[OperatorMapping, ...]

    @field_validator("approved_at", mode="before")
    @classmethod
    def parse_approved_at(cls, value: object) -> datetime:
        if not isinstance(value, str):
            raise ValueError("mapping approval time must be an RFC3339 string")
        return parse_rfc3339_timestamp(value)

    @model_validator(mode="after")
    def validate_unique_explicit_mappings(self) -> OddsMappingPlan:
        event_ids = [item.provider_event_id for item in self.fixture_mappings]
        bookmaker_keys = [item.bookmaker_key for item in self.operator_mappings]
        operator_keys = [item.canonical_operator_key for item in self.operator_mappings]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("provider event mapping is duplicated")
        if len(bookmaker_keys) != len(set(bookmaker_keys)):
            raise ValueError("provider bookmaker mapping is duplicated")
        if len(operator_keys) != len(set(operator_keys)):
            raise ValueError("canonical operator mapping is duplicated")
        lookup_providers = {
            item.canonical_fixture_lookup.provider for item in self.fixture_mappings
        }
        if self.evidence_class == "TEST_ONLY":
            if self.status != "APPROVED_FOR_TEST" or lookup_providers != {"synthetic_fpl"}:
                raise ValueError("TEST_ONLY mapping plan must use only synthetic_fpl evidence")
        elif "synthetic_fpl" in lookup_providers or self.status != "APPROVED":
            raise ValueError("production mapping plan cannot use synthetic evidence")
        return self

    @property
    def sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))

    def fixture(self, provider_event_id: str) -> FixtureMapping:
        matches = [
            item for item in self.fixture_mappings if item.provider_event_id == provider_event_id
        ]
        if len(matches) != 1:
            raise IngestionError(
                "MAPPING_CONFLICT", "provider event lacks one explicit fixture mapping"
            )
        return matches[0]

    def operator(self, bookmaker_key: str) -> OperatorMapping:
        matches = [item for item in self.operator_mappings if item.bookmaker_key == bookmaker_key]
        if len(matches) != 1:
            raise IngestionError(
                "MAPPING_CONFLICT", "bookmaker key lacks one explicit operator mapping"
            )
        return matches[0]


type CurrentMappingEvidenceClass = Literal["OFFICIAL", "APPROVED_MANUAL"]


class _FrozenCurrentMapping(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_default=True,
    )

    @model_validator(mode="after")
    def normalize_datetimes(self) -> Self:
        for name in self.__class__.model_fields:
            value = getattr(self, name)
            if isinstance(value, datetime):
                if value.tzinfo is None or value.utcoffset() is None:
                    raise ValueError(f"{name} must be timezone-aware")
                object.__setattr__(self, name, value.astimezone(UTC))
        return self


def _parse_current_mapping_time(value: object, *, label: str) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{label} must be timezone-aware")
        return value.astimezone(UTC)
    if isinstance(value, str):
        return parse_rfc3339_timestamp(value).astimezone(UTC)
    raise ValueError(f"{label} must be an RFC3339 string or aware datetime")


def _validate_team_identity(
    identity: CurrentFplIdentity,
    *,
    team_id: int,
    season_code: str,
) -> None:
    if (
        identity.provider_key != "official_fpl"
        or identity.provider_product != "fantasy_premierleague"
        or identity.entity_type != "TEAM"
        or identity.identifier_namespace != "fpl.team.id"
        or identity.external_id_text != str(team_id)
        or identity.season_code != season_code
    ):
        raise ValueError("official FPL team identity is inconsistent")


class CurrentTeamAliasMapping(_FrozenCurrentMapping):
    """One exact provider string approved for one current official-FPL team."""

    provider: Literal["the_odds_api"] = "the_odds_api"
    provider_team_text: str = Field(min_length=1, max_length=500)
    competition_key: Literal["PL"] = "PL"
    season_code: Literal["2026/27"] = "2026/27"
    official_fpl_team_id: int = Field(gt=0)
    canonical_team_identity: CurrentFplIdentity
    official_fpl_team_name: str = Field(min_length=1, max_length=500)
    evidence_class: CurrentMappingEvidenceClass
    status: Literal["APPROVED"] = "APPROVED"
    reviewer: str = Field(min_length=1, max_length=160)
    approved_at: datetime
    validity_policy: Literal["SEASON_CONTEXT"] = "SEASON_CONTEXT"

    @field_validator("approved_at", mode="before")
    @classmethod
    def parse_approved_at(cls, value: object) -> datetime:
        return _parse_current_mapping_time(value, label="team alias approval time")

    @model_validator(mode="after")
    def validate_identity(self) -> CurrentTeamAliasMapping:
        _validate_team_identity(
            self.canonical_team_identity,
            team_id=self.official_fpl_team_id,
            season_code=self.season_code,
        )
        return self

    @property
    def sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class CurrentTeamAliasPlan(_FrozenCurrentMapping):
    """Operator-supplied, reviewed team alias authority for current use."""

    contract_version: Literal["gw1-fpl-odds-team-alias-plan-v1"] = (
        "gw1-fpl-odds-team-alias-plan-v1"
    )
    plan_id: str = Field(min_length=1, max_length=160)
    plan_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    mapping_algorithm_version: Literal["gw1-fpl-odds-exact-v1"] = (
        "gw1-fpl-odds-exact-v1"
    )
    approved_at: datetime
    evidence_class: CurrentMappingEvidenceClass
    reviewer: str = Field(min_length=1, max_length=160)
    status: Literal["APPROVED"] = "APPROVED"
    usage_scope: Literal["CURRENT_DECISION"] = "CURRENT_DECISION"
    provider: Literal["the_odds_api"] = "the_odds_api"
    competition_key: Literal["PL"] = "PL"
    season_code: Literal["2026/27"] = "2026/27"
    team_mappings: tuple[CurrentTeamAliasMapping, ...] = Field(min_length=2)

    @field_validator("approved_at", mode="before")
    @classmethod
    def parse_approved_at(cls, value: object) -> datetime:
        return _parse_current_mapping_time(value, label="team alias plan approval time")

    @model_validator(mode="after")
    def validate_current_scope(self) -> CurrentTeamAliasPlan:
        provider_texts = [mapping.provider_team_text for mapping in self.team_mappings]
        if len(provider_texts) != len(set(provider_texts)):
            raise ValueError("provider team alias is duplicated or ambiguous")
        for mapping in self.team_mappings:
            if (
                mapping.provider != self.provider
                or mapping.competition_key != self.competition_key
                or mapping.season_code != self.season_code
                or mapping.evidence_class != self.evidence_class
                or mapping.status != self.status
                or mapping.reviewer != self.reviewer
                or mapping.approved_at > self.approved_at
            ):
                raise ValueError("team alias provenance contradicts its plan")
        return self

    @property
    def sha256(self) -> str:
        material = self.model_dump(mode="json")
        material["team_mappings"] = sorted(
            material["team_mappings"],
            key=lambda item: (
                item["provider_team_text"],
                item["official_fpl_team_id"],
            ),
        )
        return canonical_sha256(material)

    def team(self, provider_team_text: str) -> CurrentTeamAliasMapping:
        """Resolve one provider string by exact reviewed equality only."""

        matches = [
            mapping
            for mapping in self.team_mappings
            if mapping.provider_team_text == provider_team_text
        ]
        if len(matches) != 1:
            raise IngestionError(
                "MAPPING_CONFLICT",
                "provider team text lacks one explicit approved mapping",
            )
        return matches[0]


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate mapping-plan key")
        result[key] = value
    return result


def load_mapping_plan(path: Path) -> OddsMappingPlan:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_strict_object)
        return OddsMappingPlan.model_validate(value)
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise IngestionError("MAPPING_CONFLICT", "mapping plan is invalid") from exc


def load_current_team_alias_plan(path: Path) -> CurrentTeamAliasPlan:
    """Load one strict operator-supplied current team alias plan."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_strict_object)
        return CurrentTeamAliasPlan.model_validate(value)
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise IngestionError("MAPPING_CONFLICT", "current team alias plan is invalid") from exc
