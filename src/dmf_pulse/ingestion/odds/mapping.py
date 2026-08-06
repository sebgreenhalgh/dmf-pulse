"""Explicit, hash-bound event and bookmaker mapping-plan contract."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.errors import IngestionError
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
