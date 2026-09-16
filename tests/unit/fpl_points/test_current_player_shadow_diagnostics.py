"""Aggregate-only reporting, source integrity, and no active-path integration."""

import json
from datetime import timedelta

import pytest

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.fpl_points.current_player_posterior import CurrentPlayerAllocationShadow, seal
from dmf_pulse.fpl_points.current_player_shadow import compile_current_player_shadow
from dmf_pulse.fpl_points.current_player_shadow_diagnostics import movement, safe_shadow_summary
from tests.unit.fpl_points.current_shadow_support import synthetic_inputs

pytestmark = pytest.mark.unit


def reseal_json(value):
    if isinstance(value, list):
        return [reseal_json(v) for v in value]
    if isinstance(value, dict):
        result = {k: reseal_json(v) for k, v in value.items()}
        if "semantic_sha256" in result:
            result["semantic_sha256"] = canonical_sha256(
                {k: v for k, v in result.items() if k != "semantic_sha256"}
            )
        return result
    return value


def test_summary_determinism_safe_surface_and_six_comparisons(
    repository_root, monkeypatch, tmp_path
):
    inputs = synthetic_inputs(repository_root)
    shadow = compile_current_player_shadow(**inputs)
    before = tuple(tmp_path.iterdir())
    summary = safe_shadow_summary(shadow, inputs["history"])
    assert summary == safe_shadow_summary(shadow, inputs["history"])
    assert before == tuple(tmp_path.iterdir())
    assert len(summary["world_sensitivity"]["comparisons"]) == 6
    assert summary["historical_donor_count"] == 599
    assert summary["current_player_count"] == 20
    assert summary["individual_prior_count"] + summary["fallback_prior_count"] == 20
    text = json.dumps(summary)
    for forbidden in (
        "Synthetic",
        "SH100",
        "player_id",
        "team_id",
        "bearer",
        "secret",
        "source_body",
        "player_name",
    ):
        assert forbidden not in text
    assert "CURRENT_PLAYER_HISTORY_ONLY_FOUR_COMPLETED_GWS" in summary["model_gaps"]["gaps"]
    assert all(
        item["rate_per90"] is not None for item in summary["model_gaps"]["position_evidence"]
    )
    assert all(
        item["team_assist_tv"]["maximum"] <= 1
        for item in summary["world_sensitivity"]["comparisons"]
    )
    empty = movement(())
    assert empty.count == 0 and empty.maximum is None
    assert movement((0.0, 1.0, 2.0, 3.0)).median == 1.5


@pytest.mark.parametrize(
    "tamper",
    (
        "window",
        "cutoff",
        "identity",
        "row_identity",
        "source_gw",
        "source_digest",
        "reconciliation",
        "quality",
        "coverage",
        "missing_current",
    ),
)
def test_resealed_history_relational_tampering_blocked(repository_root, tamper):
    inputs = synthetic_inputs(repository_root)
    history = inputs["history"]
    payload = history.model_dump(mode="json")
    entry = payload["entries"][1]
    if tamper == "window":
        payload["target_gameweek"] += 1
    if tamper == "cutoff":
        payload["information_cutoff"] = (
            history.information_cutoff + timedelta(seconds=1)
        ).isoformat()
    if tamper == "identity":
        entry["current_player_identity_sha256"] = "f" * 64
        for row in entry["observations"]:
            row["current_player_identity_sha256"] = "f" * 64
    if tamper == "row_identity":
        entry["observations"][0]["current_player_identity_sha256"] = "f" * 64
    if tamper == "source_gw":
        entry["observations"][0]["source_gameweek_identity_sha256"] = "f" * 64
    if tamper == "source_digest":
        entry["observations"][0]["source_body_sha256"] = "f" * 64
    if tamper == "reconciliation":
        entry["reconciliation_minutes"] = "NOT_APPLICABLE"
    if tamper == "quality":
        entry["quality"] = ["SOURCE_MALFORMED"]
    if tamper == "coverage":
        payload["coverage"]["historical_row_count"] += 1
    if tamper == "missing_current":
        payload["entries"].pop()
    with pytest.raises(ValueError):
        changed = type(history).model_validate_json(json.dumps(reseal_json(payload)))
        compile_current_player_shadow(**(inputs | {"history": changed}))


@pytest.mark.parametrize(
    "field,value",
    (
        ("position", "GK"),
        ("source_team_id", 99),
        ("donor_source_player_id", 999999),
        ("current_team_id", "00000000-0000-4000-8000-000000000099"),
        ("source_player_identity_sha256", "f" * 64),
    ),
)
def test_resealed_binding_mismatch_blocked(repository_root, field, value):
    inputs = synthetic_inputs(repository_root)
    binding = inputs["binding"]
    payload = binding.model_dump(mode="json")
    entry = next(e for e in payload["entries"] if e["source_player_id"] == 10002)
    entry[field] = value
    with pytest.raises(Exception):
        changed = type(binding).model_validate_json(json.dumps(reseal_json(payload)))
        compile_current_player_shadow(**(inputs | {"binding": changed}))


@pytest.mark.parametrize("field", ("season_minutes", "season_starts"))
def test_bootstrap_exposure_mismatch_fails(repository_root, field):
    inputs = synthetic_inputs(repository_root)
    fpl = inputs["current_fpl"]
    players = list(fpl.players)
    players[0] = players[0].model_copy(update={field: 999})
    with pytest.raises(ValueError):
        compile_current_player_shadow(
            **(inputs | {"current_fpl": fpl.model_copy(update={"players": tuple(players)})})
        )


def test_missing_window_rows_no_history_and_order_failures(repository_root):
    inputs = synthetic_inputs(
        repository_root, missing_rows=tuple((10002, gw) for gw in range(1, 5))
    )
    shadow = compile_current_player_shadow(**inputs)
    entry = next(
        e for e in shadow.worlds[0].posterior.entries if e.binding.source_player_id == 10002
    )
    assert all(
        r.status in ("CURRENT_HISTORY_UNAVAILABLE", "STRUCTURAL_NON_GK_ZERO") for r in entry.rates
    )
    assert all(r.included_events is None for r in entry.rates)
    payload = inputs["history"].model_dump(mode="json")
    payload["entries"][0]["observations"].reverse()
    with pytest.raises(ValueError):
        type(inputs["history"]).model_validate_json(json.dumps(reseal_json(payload)))


def test_summary_rejects_different_source_history(repository_root):
    inputs = synthetic_inputs(repository_root)
    shadow = compile_current_player_shadow(**inputs)
    other = synthetic_inputs(repository_root, gameweeks=1)
    with pytest.raises(ValueError, match="history differs"):
        safe_shadow_summary(shadow, other["history"])
    summary = safe_shadow_summary(compile_current_player_shadow(**other), other["history"])
    assert "CURRENT_PLAYER_HISTORY_ONLY_FOUR_COMPLETED_GWS" not in summary["model_gaps"]["gaps"]


def test_worlds_cannot_mix_current_likelihood(repository_root):
    inputs = synthetic_inputs(repository_root)
    shadow = compile_current_player_shadow(**inputs)
    other_inputs = synthetic_inputs(repository_root, changes={(10002, 1): {"assists": 4}})
    other = compile_current_player_shadow(**other_inputs)
    with pytest.raises(ValueError, match="likelihood"):
        seal(
            CurrentPlayerAllocationShadow.model_construct(
                worlds=(shadow.worlds[0], other.worlds[1], shadow.worlds[2]),
                semantic_sha256="0" * 64,
            )
        )
