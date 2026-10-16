"""Pinned, post-event P01 authority; no provider access or import-time I/O."""

from __future__ import annotations

import json
from datetime import date, datetime
from importlib import resources
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256, sha256_file
from dmf_pulse.evaluation.p01_frozen_view import P01FrozenScoringView, _read_pinned_representation
from dmf_pulse.evaluation.team_strength_prospective import PublicTeamStrengthForecastV1
from dmf_pulse.ingestion.models import RightsProfile
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    SHA,
    FixtureRegistration,
    FrozenEvidence,
    SealedEvidence,
    StrengthEvidenceError,
    authenticate,
)

CONTEXT_SHA = "6bb80a9c0b17b673044be5b5c53a2eda6c4e4110ef09f7a586e87e0d8432c259"
RIGHTS_SHA = "31261d9304c20a178d730e57e7d06c82423b68a816bac73d517887d58b3caaf2"
FORECAST_SHA = "96a13e8265095672708586dd1fd2a7f9653857594ba5fa325e82c0b3385ab15a"
FORECAST_BYTE_SHA = "e3b7db4ef8db933a6ff5ed940bbe0a250601ad1780361fbef4195282ed27f2ee"
ROUTES = (
    "https://api.openligadb.de/getresulttypes",
    "https://api.openligadb.de/getresultinfos/5996",
    "https://api.openligadb.de/getmatchdata/pl/2026/6",
)


def strict_json(data: bytes) -> object:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise StrengthEvidenceError("duplicate JSON key")
            result[key] = value
        return result

    def constant(value: str) -> object:
        raise StrengthEvidenceError("non-finite JSON constant")

    return json.loads(data, object_pairs_hook=pairs, parse_constant=constant)


def resource_bytes(relative: str, path: Path | None = None) -> bytes:
    if path is not None:
        return path.read_bytes()
    candidate = Path(__file__).resolve().parents[3] / "config" / relative
    if candidate.is_file():
        return candidate.read_bytes()
    return resources.files("dmf_pulse").joinpath("evaluation/resources/" + relative).read_bytes()


class FrozenP01Fixture(FrozenEvidence):
    fixture: FixtureRegistration
    scheduled_date: date
    home_aliases: tuple[str, ...] = Field(min_length=1)
    away_aliases: tuple[str, ...] = Field(min_length=1)


class P01FallbackContext(SealedEvidence):
    schema_version: Literal["public-team-strength-p01-fallback-context-v1"]
    protocol_version: Literal["1.2.0"]
    evaluation_epoch: Literal["EVALUATION_EPOCH_003"]
    original_forecast_epoch: Literal["EVALUATION_EPOCH_001"]
    original_protocol_sha256: SHA
    a01_amendment_sha256: SHA
    a01_clarification_sha256: SHA
    a02_amendment_sha256: SHA
    amendment_id: Literal["CURRENT-TEAM-STRENGTH-001V-P01-FALLBACK-A02"]
    amended_at: datetime
    authorization_request_byte_sha256: SHA
    reason: str = Field(min_length=1)
    classifications: tuple[str, ...] = Field(min_length=13, max_length=13)
    performance_metrics_inspected_before_amendment: Literal[False]
    source: Literal["OpenLigaDB"]
    source_policy: Literal["SINGLE_QUALIFIED_FALLBACK_SOURCE"]
    rights_profile_id: Literal["openligadb_public_final_score_labels_v1"]
    rights_profile_sha256: Literal[
        "31261d9304c20a178d730e57e7d06c82423b68a816bac73d517887d58b3caaf2"
    ]
    forecast_sha256: SHA
    forecast_byte_sha256: SHA
    forecast_origin: datetime
    frozen_at: datetime
    fixture_registry_sha256: SHA
    draw_policy_sha256: SHA
    fixtures: tuple[FrozenP01Fixture, ...] = Field(min_length=10, max_length=10)
    league_id: Literal[5996]
    league_shortcut: Literal["pl"]
    league_season: Literal[2026]
    league_name: Literal["Premier League"]
    matchday: Literal[6]
    allowed_routes: tuple[str, ...]
    reconciliation_status: Literal["OPENFOOTBALL_RECONCILIATION_PENDING"]
    production_active: Literal[False]
    promotion_permitted: Literal[False]
    model_tuning_permitted: Literal[False]
    official_premier_league_used: Literal[False]

    @model_validator(mode="after")
    def exact_cohort(self) -> Self:
        ids = tuple(row.fixture.fixture_id for row in self.fixtures)
        pairs = {(row.fixture.home_team_id, row.fixture.away_team_id) for row in self.fixtures}
        aliases: dict[str, object] = {}
        for row in self.fixtures:
            for names, team in (
                (row.home_aliases, row.fixture.home_team_id),
                (row.away_aliases, row.fixture.away_team_id),
            ):
                for name in names:
                    if not name.strip() or (name in aliases and aliases[name] != team):
                        raise ValueError("ambiguous club alias in frozen mapping")
                    aliases[name] = team
        if (
            len(set(ids)) != 10
            or ids != tuple(sorted(ids))
            or len(pairs) != 10
            or self.allowed_routes != ROUTES
            or not self.forecast_origin <= self.frozen_at < self.amended_at
            or any(row.scheduled_date <= self.frozen_at.date() for row in self.fixtures)
        ):
            raise ValueError("invalid P01 context cohort, authority, routes or timing")
        return self


def load_context(path: Path | None = None) -> P01FallbackContext:
    raw = resource_bytes("evaluation/team_strength_p01_fallback_a02.json", path)
    strict_json(raw)
    return authenticate(P01FallbackContext.model_validate_json(raw), CONTEXT_SHA)


def require_openligadb_rights(path: Path | None = None) -> RightsProfile:
    raw = resource_bytes("rights/openligadb_p01_fallback.json", path)
    value = strict_json(raw)
    if not isinstance(value, dict) or set(value) != {"payload", "semantic_sha256"}:
        raise StrengthEvidenceError("OPENLIGADB_RIGHTS_IDENTITY_MISMATCH")
    if value["semantic_sha256"] != RIGHTS_SHA or canonical_sha256(value["payload"]) != RIGHTS_SHA:
        raise StrengthEvidenceError("OPENLIGADB_RIGHTS_IDENTITY_MISMATCH")
    profile = RightsProfile.model_validate_json(json.dumps(value["payload"]))
    if profile.rights_profile_id != "openligadb_public_final_score_labels_v1":
        raise StrengthEvidenceError("OPENLIGADB_RIGHTS_IDENTITY_MISMATCH")
    return profile


def authenticate_p01(path: Path) -> P01FrozenScoringView:
    context = load_context()
    require_openligadb_rights()
    if path.is_symlink() or sha256_file(path) != context.forecast_byte_sha256:
        raise StrengthEvidenceError("P01_FORECAST_BYTE_IDENTITY_MISMATCH")
    raw = path.read_bytes()
    strict_json(raw)
    forecast = _read_pinned_representation(
        raw,
        expected_byte_sha256=context.forecast_byte_sha256,
        expected_semantic_sha256=context.forecast_sha256,
    )
    require_forecast_binding(forecast, context=context)
    if forecast.dataset_mode != "LIVE_OBSERVED":
        raise StrengthEvidenceError("P01 live forecast mode differs")
    return forecast


def require_forecast_binding(
    forecast: PublicTeamStrengthForecastV1 | P01FrozenScoringView, *, context: P01FallbackContext
) -> None:
    """Pure admission binding, also exercised with separate synthetic sealed contexts."""
    forecast, context = authenticate(forecast), authenticate(context)
    if (
        forecast.semantic_sha256 != context.forecast_sha256
        or forecast.fixture_registry.semantic_sha256 != context.fixture_registry_sha256
        or forecast.forecast_origin != context.forecast_origin
        or forecast.frozen_at != context.frozen_at
        or forecast.draw_set.draw_policy_sha256 != context.draw_policy_sha256
        or tuple((row.fixture, row.scheduled_date) for row in forecast.forecasts)
        != tuple((row.fixture, row.scheduled_date) for row in context.fixtures)
    ):
        raise StrengthEvidenceError("P01 forecast/cohort binding differs")
