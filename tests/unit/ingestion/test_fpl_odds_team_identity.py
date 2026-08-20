"""Checkpoint-1.4A exact current FPL/Odds team identity contracts."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.current import (
    CurrentFplInputBundle,
    CurrentFplInputRequest,
    CurrentFplInputService,
)
from dmf_pulse.ingestion.odds.config import load_rights_profiles
from dmf_pulse.ingestion.odds.current import build_current_odds_input
from dmf_pulse.ingestion.odds.identity import (
    bind_current_team_resolution_request,
    resolve_current_team_identities,
)
from dmf_pulse.ingestion.odds.mapping import CurrentTeamAliasMapping, CurrentTeamAliasPlan
from dmf_pulse.ingestion.odds.models import QuotaSource, QuotaState
from dmf_pulse.ingestion.odds.parser import parse_odds_payload

pytestmark = pytest.mark.unit

CAPTURED = datetime(2026, 8, 18, 12, tzinfo=UTC)
FPL_RECEIVED = datetime(2026, 8, 18, 12, 5, tzinfo=UTC)
ODDS_RECEIVED = datetime(2026, 8, 20, 12, tzinfo=UTC)
CUTOFF = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)
DECIDED = datetime(2026, 8, 20, 12, 1, tzinfo=UTC)
APPROVED = datetime(2026, 8, 18, 13, tzinfo=UTC)
SOURCE_SNAPSHOT_ID = UUID("00000000-0000-0000-0000-000000001401")
SANITIZED_TARGET = (
    "https://api.the-odds-api.com/v4/sports/soccer_epl/odds?"
    "regions=uk&markets=h2h%2Ctotals&oddsFormat=decimal&dateFormat=iso&commenceTimeFrom="
    "2026-08-21T17%3A30%3A00Z"
)


def _write_fpl_pair(repository_root: Path, tmp_path: Path) -> tuple[Path, Path]:
    source = repository_root / "fixtures/fpl/FPL-004/happy_path"
    bootstrap_path = tmp_path / "bootstrap.json"
    fixtures_path = tmp_path / "fixtures.json"
    bootstrap_path.write_bytes((source / "bootstrap.json").read_bytes())
    fixtures_path.write_bytes((source / "fixtures.json").read_bytes())
    return bootstrap_path, fixtures_path


def _fpl_input(repository_root: Path, tmp_path: Path) -> CurrentFplInputBundle:
    bootstrap_path, fixtures_path = _write_fpl_pair(repository_root, tmp_path)
    request = CurrentFplInputRequest(
        bootstrap_path=bootstrap_path,
        fixtures_path=fixtures_path,
        competition_key="PL",
        season_code="2026/27",
        captured_at=CAPTURED,
        information_cutoff=CUTOFF,
        rights_profile_id="fpl_official_private_manual_v1",
        gameweek=1,
    )
    return CurrentFplInputService(clock=lambda: FPL_RECEIVED).compile(request)


def _odds_value(repository_root: Path) -> list[dict[str, Any]]:
    value = json.loads(
        (repository_root / "fixtures/odds/ODD-005/happy_path.json").read_text(encoding="utf-8")
    )
    assert isinstance(value, list)
    return value


def _odds_input(repository_root: Path, value: object | None = None):
    body = json.dumps(
        _odds_value(repository_root) if value is None else value,
        allow_nan=False,
        separators=(",", ":"),
    ).encode()
    parsed = parse_odds_payload(body)
    profile = load_rights_profiles()["the_odds_api_private_analytics_v1"]
    return build_current_odds_input(
        parsed,
        profile=profile,
        source_snapshot_id=SOURCE_SNAPSHOT_ID,
        request_started_at=ODDS_RECEIVED - timedelta(seconds=1),
        received_at=ODDS_RECEIVED,
        information_cutoff=CUTOFF,
        usable_at=ODDS_RECEIVED + timedelta(seconds=1),
        quota=QuotaState(
            remaining=499,
            used=2,
            last_cost=2,
            observed_at=ODDS_RECEIVED,
            source=QuotaSource.RESPONSE_HEADERS,
        ),
        request_fingerprint="1" * 64,
        sanitized_target=SANITIZED_TARGET,
        attempt_count=1,
        transport_call_count=1,
        provider_request_id_sha256="2" * 64,
    )


def _mapping(
    provider_text: str,
    team: object,
    *,
    approved_at: datetime = APPROVED,
    official_name: str | None = None,
) -> CurrentTeamAliasMapping:
    return CurrentTeamAliasMapping(
        provider_team_text=provider_text,
        official_fpl_team_id=team.provider_team_id,
        canonical_team_identity=team.identity,
        official_fpl_team_name=official_name or team.official_name,
        evidence_class="APPROVED_MANUAL",
        reviewer="Sebastian Greenhalgh",
        approved_at=approved_at,
    )


def _plan(
    fpl_input: CurrentFplInputBundle,
    *,
    home_text: str = "Alpha Athletic",
    away_text: str = "Beta Borough",
    approved_at: datetime = APPROVED,
    mappings: tuple[CurrentTeamAliasMapping, ...] | None = None,
) -> CurrentTeamAliasPlan:
    resolved = mappings or (
        _mapping(home_text, fpl_input.teams[0], approved_at=approved_at),
        _mapping(away_text, fpl_input.teams[1], approved_at=approved_at),
    )
    return CurrentTeamAliasPlan(
        plan_id="gw1-2026-27-current-team-aliases",
        plan_version="1.0.0",
        approved_at=approved_at,
        evidence_class="APPROVED_MANUAL",
        reviewer="Sebastian Greenhalgh",
        team_mappings=resolved,
    )


def _resolve(fpl_input: CurrentFplInputBundle, odds_input: object, plan: CurrentTeamAliasPlan):
    request = bind_current_team_resolution_request(
        fpl_input,
        odds_input,
        plan,
        mapping_decided_at=DECIDED,
    )
    return resolve_current_team_identities(fpl_input, odds_input, plan, request)


def _rename_home(value: list[dict[str, Any]], replacement: str) -> None:
    event = value[0]
    original = event["home_team"]
    event["home_team"] = replacement
    for bookmaker in event["bookmakers"]:
        for market in bookmaker["markets"]:
            for outcome in market["outcomes"]:
                if outcome["name"] == original:
                    outcome["name"] = replacement


def test_exact_and_explicit_alias_resolution_are_transient_and_hash_bound(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input = _fpl_input(repository_root, tmp_path)
    value = _odds_value(repository_root)
    _rename_home(value, "Alpha A.")
    odds_input = _odds_input(repository_root, value)
    plan = _plan(fpl_input, home_text="Alpha A.")

    result = _resolve(fpl_input, odds_input, plan)

    assert result.contract == "FPL_ODDS_TEAM_IDENTITY_MAP"
    assert result.storage_mode == "TRANSIENT_IN_MEMORY"
    assert result.persistence_performed is False
    assert result.team("Alpha A.").official_fpl_team_id == 1
    assert result.team("Beta Borough").official_fpl_team_id == 2
    assert result.team("Alpha A.").official_fpl_team_identity == fpl_input.teams[0].identity
    assert result.team_alias_plan_sha256 == plan.sha256
    assert len(result.semantic_sha256) == 64


def test_team_resolution_is_order_independent_and_deterministic(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input = _fpl_input(repository_root, tmp_path)
    odds_input = _odds_input(repository_root)
    plan = _plan(fpl_input)
    reversed_plan = _plan(fpl_input, mappings=tuple(reversed(plan.team_mappings)))

    first = _resolve(fpl_input, odds_input, plan)
    second = _resolve(fpl_input, odds_input, reversed_plan)

    assert plan.sha256 == reversed_plan.sha256
    assert first.semantic_sha256 == second.semantic_sha256
    assert first.team_mappings == second.team_mappings


@pytest.mark.parametrize(
    "provider_text",
    (
        "Alpha Athleti",
        "Alpha",
        "Alpha-Athletic",
        "alpha athletic",
    ),
)
def test_unapproved_variants_do_not_fuzzy_match(
    repository_root: Path,
    tmp_path: Path,
    provider_text: str,
) -> None:
    fpl_input = _fpl_input(repository_root, tmp_path)
    value = _odds_value(repository_root)
    _rename_home(value, provider_text)
    odds_input = _odds_input(repository_root, value)
    plan = _plan(fpl_input)

    with pytest.raises(IngestionError) as raised:
        _resolve(fpl_input, odds_input, plan)

    assert raised.value.code == "MAPPING_CONFLICT"


def test_duplicate_or_ambiguous_provider_alias_is_rejected_at_plan_validation(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input = _fpl_input(repository_root, tmp_path)
    duplicate = (
        _mapping("Shared Alias", fpl_input.teams[0]),
        _mapping("Shared Alias", fpl_input.teams[1]),
    )

    with pytest.raises(ValidationError, match="duplicated or ambiguous"):
        _plan(fpl_input, mappings=duplicate)


def test_alias_cannot_bind_an_inconsistent_official_identity(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input = _fpl_input(repository_root, tmp_path)
    values = _mapping("Alpha Athletic", fpl_input.teams[0]).model_dump(mode="python")
    values["canonical_team_identity"] = fpl_input.teams[1].identity

    with pytest.raises(ValidationError, match="identity is inconsistent"):
        CurrentTeamAliasMapping.model_validate(values)


def test_stale_official_name_fails_against_current_fpl_input(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input = _fpl_input(repository_root, tmp_path)
    mappings = (
        _mapping("Alpha Athletic", fpl_input.teams[0], official_name="Former Alpha Name"),
        _mapping("Beta Borough", fpl_input.teams[1]),
    )
    plan = _plan(fpl_input, mappings=mappings)

    with pytest.raises(IngestionError) as raised:
        _resolve(fpl_input, _odds_input(repository_root), plan)

    assert raised.value.code == "MAPPING_CONFLICT"


def test_two_provider_participants_cannot_resolve_to_one_fpl_team(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input = _fpl_input(repository_root, tmp_path)
    mappings = (
        _mapping("Alpha Athletic", fpl_input.teams[0]),
        _mapping("Beta Borough", fpl_input.teams[0]),
    )
    plan = _plan(fpl_input, mappings=mappings)

    with pytest.raises(IngestionError) as raised:
        _resolve(fpl_input, _odds_input(repository_root), plan)

    assert raised.value.code == "MAPPING_CONFLICT"


def test_future_alias_plan_is_not_available_before_cutoff(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input = _fpl_input(repository_root, tmp_path)
    plan = _plan(fpl_input, approved_at=CUTOFF + timedelta(seconds=1))
    request = bind_current_team_resolution_request(
        fpl_input,
        _odds_input(repository_root),
        plan,
        mapping_decided_at=DECIDED,
    )

    with pytest.raises(IngestionError) as raised:
        resolve_current_team_identities(
            fpl_input,
            _odds_input(repository_root),
            plan,
            request,
        )

    assert raised.value.code == "POST_CUTOFF"


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("fpl_input_semantic_sha256", "a" * 64),
        ("fpl_identity_view_sha256", "b" * 64),
        ("odds_provider_provenance_sha256", "c" * 64),
        ("odds_identity_semantic_sha256", "d" * 64),
        ("team_alias_plan_sha256", "e" * 64),
        ("team_alias_plan_version", "9.9.9"),
    ),
)
def test_bound_lineage_substitution_fails_closed(
    repository_root: Path,
    tmp_path: Path,
    field: str,
    replacement: str,
) -> None:
    fpl_input = _fpl_input(repository_root, tmp_path)
    odds_input = _odds_input(repository_root)
    plan = _plan(fpl_input)
    request = bind_current_team_resolution_request(
        fpl_input,
        odds_input,
        plan,
        mapping_decided_at=DECIDED,
    ).model_copy(update={field: replacement})

    with pytest.raises(IngestionError) as raised:
        resolve_current_team_identities(fpl_input, odds_input, plan, request)

    assert raised.value.code == "MAPPING_CONFLICT"


def test_cutoff_mismatch_and_rights_bypass_fail_closed(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input = _fpl_input(repository_root, tmp_path)
    odds_input = _odds_input(repository_root)
    plan = _plan(fpl_input)
    shifted_temporal = odds_input.temporal.model_copy(
        update={"information_cutoff": CUTOFF - timedelta(seconds=1)}
    )
    shifted_odds = odds_input.model_copy(update={"temporal": shifted_temporal})
    shifted_request = bind_current_team_resolution_request(
        fpl_input,
        shifted_odds,
        plan,
        mapping_decided_at=DECIDED,
    )

    with pytest.raises(IngestionError) as cutoff_error:
        resolve_current_team_identities(fpl_input, shifted_odds, plan, shifted_request)
    assert cutoff_error.value.code == "MAPPING_CONFLICT"

    altered_rights = fpl_input.rights.model_copy(update={"derived_storage": "ALLOW"})
    altered_fpl = fpl_input.model_copy(update={"rights": altered_rights})
    rights_request = bind_current_team_resolution_request(
        altered_fpl,
        odds_input,
        plan,
        mapping_decided_at=DECIDED,
    )
    with pytest.raises(IngestionError) as rights_error:
        resolve_current_team_identities(altered_fpl, odds_input, plan, rights_request)
    assert rights_error.value.code == "RIGHTS_BLOCKED"


def test_current_plan_schema_rejects_wrong_scope_and_test_only_authority(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input = _fpl_input(repository_root, tmp_path)
    values = _plan(fpl_input).model_dump(mode="python")

    for field, replacement in (
        ("competition_key", "SYNTHETIC_PL"),
        ("season_code", "2025/26"),
        ("provider", "another_provider"),
        ("evidence_class", "TEST_ONLY"),
        ("status", "APPROVED_FOR_TEST"),
    ):
        altered = dict(values)
        altered[field] = replacement
        with pytest.raises(ValidationError):
            CurrentTeamAliasPlan.model_validate(altered)
