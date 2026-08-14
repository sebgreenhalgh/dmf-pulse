from __future__ import annotations

import json
from pathlib import Path

import pytest

from dmf_pulse.fpl_points.artifacts import (
    canonical_json_bytes,
    load_verified_model,
    persist_model_artifact,
    sha256_bytes,
)
from dmf_pulse.fpl_points.errors import FplPointsError
from dmf_pulse.fpl_points.evaluation import evaluate_player_distribution, reconcile_official_score
from dmf_pulse.fpl_points.models import FixtureProjectionResult
from dmf_pulse.fpl_points.service import FplPointsService
from tests.support.factories import H_MID, make_request, mc_policy, reference_engine


def _result() -> FixtureProjectionResult:
    return FplPointsService(reference_engine(), mc_policy()).project(make_request(scenario_count=8))


def test_distribution_evaluation_and_official_reconciliation() -> None:
    result = _result()
    player_id = H_MID
    summary = result.player_summaries[player_id]
    observed = next(iter(summary.pmf))
    evaluation = evaluate_player_distribution(summary, observed)
    assert evaluation.probability_mass_observed == summary.pmf[observed]
    assert evaluation.log_score is not None
    modeled = result.scenarios[0].players[player_id]
    official = modeled.model_dump(mode="python")
    official.pop("bps")
    official.pop("bps_competition_rank")
    official.pop("bps_tied_at_rank")
    reconciled = reconcile_official_score(player_id, modeled, official)
    assert reconciled.exact_match is True
    official["total"] += 1
    assert reconcile_official_score(player_id, modeled, official).exact_match is False


def test_write_once_collision_and_sidecar_failures(tmp_path: Path) -> None:
    result = _result()
    path = persist_model_artifact(
        result, artifact_root=tmp_path, category="fixture", identity_parts=("GW", "FIX")
    )
    path.write_text("different", encoding="utf-8")
    with pytest.raises(FplPointsError) as exc:
        persist_model_artifact(
            result, artifact_root=tmp_path, category="fixture", identity_parts=("GW", "FIX")
        )
    assert exc.value.code == "ARTIFACT_COLLISION"


def test_invalid_noncanonical_and_embedded_hash_fail_closed(tmp_path: Path) -> None:
    result = _result()
    path = persist_model_artifact(
        result, artifact_root=tmp_path, category="fixture", identity_parts=("GW", "FIX")
    )
    sidecar = path.with_suffix(".sha256")
    sidecar.unlink()
    with pytest.raises(FplPointsError) as exc:
        load_verified_model(path, FixtureProjectionResult)
    assert exc.value.code == "ARTIFACT_UNAVAILABLE"

    data = json.loads(canonical_json_bytes(result))
    data["result_sha256"] = "9" * 64
    tampered = (json.dumps(data, separators=(",", ":"), sort_keys=True) + "\n").encode()
    path.write_bytes(tampered)
    sidecar.write_text(f"{sha256_bytes(tampered)}  {path.name}\n", encoding="ascii")
    with pytest.raises(FplPointsError) as exc:
        load_verified_model(path, FixtureProjectionResult)
    assert exc.value.code == "ARTIFACT_EMBEDDED_HASH_MISMATCH"

    pretty = (json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True) + "\n").encode()
    path.write_bytes(pretty)
    sidecar.write_text(f"{sha256_bytes(pretty)}  {path.name}\n", encoding="ascii")
    with pytest.raises(FplPointsError) as exc:
        load_verified_model(path, FixtureProjectionResult)
    assert exc.value.code == "ARTIFACT_NONCANONICAL"
