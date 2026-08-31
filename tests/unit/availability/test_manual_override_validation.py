from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from dmf_pulse.availability.manual_override import (
    MAXIMUM_INPUT_BYTES,
    ManualFixtureMinutesInput,
    ManualOverrideError,
    build_manual_minutes_override,
    load_manual_fixture_minutes,
)

from .manual_override_test_support import (
    AWAY_TEAM_ID,
    HOME_TEAM_ID,
    deep_copy_input,
    valid_manual_input,
    with_always_out_player,
    with_always_start_player,
)

pytestmark = pytest.mark.unit


def test_manual_error_and_revalidating_copy_are_stable() -> None:
    error = ManualOverrideError("CODE", "safe message")
    assert str(error) == "CODE: safe message"
    bundle = build_manual_minutes_override(valid_manual_input())
    with pytest.raises(ValidationError, match="semantic identity is invalid"):
        bundle.model_copy(update={"semantic_sha256": "f" * 64})
    invalid = ManualFixtureMinutesInput.model_construct(
        **{**valid_manual_input().model_dump(mode="python"), "fixture_id": "invalid"}
    )
    with pytest.raises(ManualOverrideError) as invalid_error:
        build_manual_minutes_override(invalid)
    assert invalid_error.value.code == "MANUAL_OVERRIDE_INVALID"


@pytest.mark.parametrize(
    "field,value,match",
    (
        ("usable_at", "2026-08-20T10:59:59Z", "usable before"),
        ("expires_at", "2026-08-20T11:39:59Z", "expires before"),
    ),
)
def test_soft_provenance_time_order_is_fail_closed(field: str, value: str, match: str) -> None:
    body = deep_copy_input()
    body["provenance"][field] = value
    with pytest.raises(ValidationError, match=match):
        ManualFixtureMinutesInput.model_validate(body)


@pytest.mark.parametrize(
    "field,value,match",
    (
        ("usable_at", "2026-08-20T10:59:59Z", "usable before"),
        ("expires_at", "2026-08-20T11:39:59Z", "expires before"),
        ("asserted_role", "START", "must assert OUT"),
    ),
)
def test_hard_override_contract_rejects_bad_time_or_role(
    field: str, value: str, match: str
) -> None:
    body = with_always_out_player(include_hard_override=True)
    body["home"]["hard_overrides"][0][field] = value
    with pytest.raises(ValidationError, match=match):
        ManualFixtureMinutesInput.model_validate(body)


def test_scenario_order_roster_bench_and_goalkeeper_coherence_are_fail_closed() -> None:
    body = deep_copy_input()
    body["home"]["scenarios"][0]["players"][0:2] = reversed(
        body["home"]["scenarios"][0]["players"][0:2]
    )
    with pytest.raises(ValidationError, match="sorted by canonical"):
        ManualFixtureMinutesInput.model_validate(body)

    body = deep_copy_input()
    body["home"]["scenarios"].reverse()
    with pytest.raises(ValidationError, match="canonically ordered scenario_id"):
        ManualFixtureMinutesInput.model_validate(body)

    body = deep_copy_input()
    body["home"]["scenarios"][1]["players"][3]["position"] = "MID"
    with pytest.raises(ValidationError, match="identical player roster"):
        ManualFixtureMinutesInput.model_validate(body)

    body = deep_copy_input()
    out = next(row for row in body["home"]["scenarios"][0]["players"] if row["role"] == "OUT")
    out["role"] = "BENCH"
    with pytest.raises(ValidationError, match="BENCH count"):
        ManualFixtureMinutesInput.model_validate(body)

    body = deep_copy_input()
    players = body["home"]["scenarios"][0]["players"]
    out_gk = next(row for row in players if row["role"] == "OUT" and row["position"] == "GK")
    bench_outfield = next(
        row for row in players if row["role"] == "BENCH" and row["position"] != "GK"
    )
    out_gk["role"] = "BENCH"
    bench_outfield["role"] = "OUT"
    bench_outfield["official_minutes"] = 0
    with pytest.raises(ValidationError, match="bench goalkeeper count"):
        ManualFixtureMinutesInput.model_validate(body)


def test_hard_override_order_scope_membership_and_scenario_alignment_are_closed() -> None:
    body = with_always_out_player(include_hard_override=True)
    body["home"]["hard_overrides"].append(deepcopy(body["home"]["hard_overrides"][0]))
    with pytest.raises(ValidationError, match="unique canonically ordered"):
        ManualFixtureMinutesInput.model_validate(body)

    body = with_always_out_player(include_hard_override=True)
    body["home"]["hard_overrides"][0]["player_id"] = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    with pytest.raises(ValidationError, match="outside the team roster"):
        ManualFixtureMinutesInput.model_validate(body)

    body = with_always_out_player(include_hard_override=True)
    override = body["home"]["hard_overrides"][0]
    override["override_type"] = "OFFICIAL_LINEUP_NON_FPL_CUTOFF"
    override["asserted_role"] = "BENCH"
    with pytest.raises(ValidationError, match="does not match every"):
        ManualFixtureMinutesInput.model_validate(body)


@pytest.mark.parametrize(
    "mutation,match",
    (
        ("same_teams", "distinct"),
        ("wrong_side", "requested fixture side"),
        ("wrong_fixture_scope", "fixture scope"),
        ("soft_not_usable", "not usable at as_of"),
        ("soft_expired", "expired at as_of"),
        ("cross_team_player", "both teams"),
        ("hard_scope", "fixture/team scope"),
        ("hard_not_usable", "hard override is not usable"),
        ("hard_expired", "hard override is expired"),
    ),
)
def test_fixture_and_cutoff_cross_contracts_are_fail_closed(mutation: str, match: str) -> None:
    body = (
        with_always_out_player(include_hard_override=True)
        if mutation.startswith("hard_")
        else deep_copy_input()
    )
    if mutation == "same_teams":
        body["away_team_id"] = HOME_TEAM_ID
        body["away"]["team_id"] = HOME_TEAM_ID
    elif mutation == "wrong_side":
        body["home"]["team_id"] = AWAY_TEAM_ID
    elif mutation == "wrong_fixture_scope":
        body["provenance"]["fixture_scope_id"] = "10000000-0000-7000-8000-000000000999"
    elif mutation == "soft_not_usable":
        body["provenance"]["usable_at"] = "2026-08-20T11:50:01Z"
    elif mutation == "soft_expired":
        body["provenance"]["expires_at"] = "2026-08-20T11:50:00Z"
    elif mutation == "cross_team_player":
        shared_id = body["home"]["scenarios"][0]["players"][0]["player_id"]
        for scenario in body["away"]["scenarios"]:
            scenario["players"][0]["player_id"] = shared_id
    elif mutation == "hard_scope":
        body["home"]["hard_overrides"][0]["team_id"] = AWAY_TEAM_ID
    elif mutation == "hard_not_usable":
        body["home"]["hard_overrides"][0]["usable_at"] = "2026-08-20T11:50:01Z"
    elif mutation == "hard_expired":
        body["home"]["hard_overrides"][0]["expires_at"] = "2026-08-20T11:50:00Z"
    with pytest.raises(ValidationError, match=match):
        ManualFixtureMinutesInput.model_validate(body)


def test_soft_degenerate_start_requires_official_lineup_hard_override() -> None:
    soft = ManualFixtureMinutesInput.model_validate(
        with_always_start_player(include_hard_override=False)
    )
    with pytest.raises(ManualOverrideError) as error:
        build_manual_minutes_override(soft)
    assert error.value.code == "SOFT_DEGENERATE_ROLE"
    hard = ManualFixtureMinutesInput.model_validate(
        with_always_start_player(include_hard_override=True)
    )
    bundle = build_manual_minutes_override(hard)
    player_id = hard.home.hard_overrides[0].player_id
    projection = next(item for item in bundle.home.players if item.player_id == player_id)
    assert projection.p_start == "1.000000000000"


def test_bounded_loader_accepts_valid_json_and_rejects_float_duplicate_nan_and_size(
    tmp_path: Path,
) -> None:
    valid = tmp_path / "valid.json"
    valid.write_text(json.dumps(deep_copy_input()), encoding="utf-8")
    assert load_manual_fixture_minutes(valid) == valid_manual_input()

    for name, text in (
        ("float.json", json.dumps(deep_copy_input()).replace('"count": 64', '"count": 64.0', 1)),
        ("duplicate.json", '{"schema_version":"x","schema_version":"y"}'),
        ("nan.json", '{"value":NaN}'),
    ):
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        with pytest.raises(ManualOverrideError) as error:
            load_manual_fixture_minutes(path)
        assert error.value.code == "MANUAL_OVERRIDE_INPUT_INVALID"

    with pytest.raises(ManualOverrideError):
        load_manual_fixture_minutes(tmp_path / "missing.json")
    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b" " * (MAXIMUM_INPUT_BYTES + 1))
    with pytest.raises(ManualOverrideError):
        load_manual_fixture_minutes(oversized)
