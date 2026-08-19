from __future__ import annotations

import json
from copy import deepcopy
from datetime import timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dmf_pulse.chips.artifacts import persist_decision_artifact, seal_decision_artifact
from dmf_pulse.chips.service import evaluate_chip_opportunities
from dmf_pulse.cli.chips import chips_app
from dmf_pulse.evaluation.artifacts import canonical_json_bytes, sha256_bytes
from tests.support.stage14_chip_fixtures import NOW, service_request, write_service_request

runner = CliRunner()


def test_chips_help_exposes_real_vertical_slice_commands() -> None:
    result = runner.invoke(chips_app, ["--help"])

    assert result.exit_code == 0
    for command in (
        "validate-rules",
        "inventory",
        "captain",
        "triple-captain-value",
        "bench-boost-value",
        "free-hit-value",
        "wildcard-now-vs-later",
        "opportunity",
        "compare",
        "schedule",
        "backtest",
        "validate",
    ):
        assert command in result.stdout


def test_compare_and_schedule_match_shared_library_semantics(tmp_path: Path) -> None:
    request = service_request(keys=("TRIPLE_CAPTAIN", "BENCH_BOOST"))
    path = tmp_path / "request.json"
    write_service_request(path, request)
    expected = evaluate_chip_opportunities(request)

    compare = runner.invoke(chips_app, ["compare", "--input", str(path)])
    schedule = runner.invoke(chips_app, ["schedule", "--input", str(path)])

    assert compare.exit_code == 0
    assert schedule.exit_code == 0
    compare_payload = json.loads(compare.stdout)
    schedule_payload = json.loads(schedule.stdout)
    assert compare_payload["decision_set_hash"] == expected.decision_set_hash
    assert schedule_payload["policy_hash"] == expected.schedule_policy.policy_hash


def test_hold_is_a_successful_cli_outcome(tmp_path: Path) -> None:
    request = service_request(
        current_values={"TRIPLE_CAPTAIN": (-1.0, -1.0)},
        future_values={"TRIPLE_CAPTAIN": (-2.0, -2.0)},
    )
    path = tmp_path / "hold.json"
    write_service_request(path, request)

    result = runner.invoke(chips_app, ["compare", "--input", str(path)])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["decision"]["recommended_action"] == "HOLD"


def test_invalid_input_is_typed_nonzero_without_internal_traceback(tmp_path: Path) -> None:
    path = tmp_path / "invalid.json"
    path.write_text('{"not": "a service request"}\n', encoding="utf-8")

    result = runner.invoke(chips_app, ["compare", "--input", str(path)])

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "CHIP_INPUT_INVALID"
    assert "Traceback" not in result.stdout
    assert result.exception is not None


def test_validate_artifact_performs_detached_and_semantic_validation(tmp_path: Path) -> None:
    artifact = seal_decision_artifact(service_request())
    artifact_path = persist_decision_artifact(artifact, artifact_root=tmp_path)

    result = runner.invoke(
        chips_app,
        ["validate", "--artifact", str(artifact_path)],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout)["artifact_hash"] == artifact.artifact_hash


def test_installed_capability_validation_is_explicitly_not_production_activation() -> None:
    result = runner.invoke(chips_app, ["validate"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["production_eligible"] is False
    assert payload["target_rules_required"] is True


def _assert_typed_failure(result) -> dict[str, object]:
    assert result.exit_code == 2
    assert "Traceback" not in result.stdout
    payload = json.loads(result.stdout)
    assert str(payload["error"]["code"]).startswith("CHIP_")
    return payload


def test_invalid_rules_fail_with_typed_nonzero_error(tmp_path: Path) -> None:
    request = service_request()
    payload = deepcopy(request.chip_bundle.model_dump(mode="json"))
    payload["definitions"][0]["definition_hash"] = "9" * 64
    path = tmp_path / "invalid-rules.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    _assert_typed_failure(runner.invoke(chips_app, ["validate-rules", "--input", str(path)]))


def test_duplicate_inventory_token_fails_with_typed_nonzero_error(tmp_path: Path) -> None:
    payload = service_request().inventory.model_dump(mode="json")
    payload["tokens"].append(deepcopy(payload["tokens"][0]))
    payload["inventory_hash"] = "0" * 64
    path = tmp_path / "duplicate-token.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    _assert_typed_failure(runner.invoke(chips_app, ["inventory", "--input", str(path)]))


@pytest.mark.parametrize(
    ("name", "mutate"),
    (
        (
            "unknown-chip",
            lambda payload: payload["schedule_request"]["opportunities"][0].update(
                chip_key="UNKNOWN_CHIP", opportunity_hash="0" * 64
            ),
        ),
        (
            "illegal-activation",
            lambda payload: payload["schedule_request"]["opportunities"][0].update(
                activation_gameweek=99, opportunity_hash="0" * 64
            ),
        ),
        (
            "invalid-weights",
            lambda payload: payload["schedule_request"]["scenario_universe"][0].update(weight=0.7),
        ),
    ),
)
def test_invalid_service_semantics_fail_typed_without_traceback(
    tmp_path: Path,
    name: str,
    mutate,
) -> None:
    payload = service_request().model_dump(mode="json")
    mutate(payload)
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    _assert_typed_failure(runner.invoke(chips_app, ["compare", "--input", str(path)]))


def test_future_cutoff_artifact_is_rejected_even_with_new_detached_digest(
    tmp_path: Path,
) -> None:
    artifact = seal_decision_artifact(service_request())
    payload = artifact.model_dump(mode="json")
    records = payload["service_request"]["feature_records"]
    next(item for item in records if item["record_id"] == "manager-state")["usable_at"] = (
        (NOW + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    )
    data = canonical_json_bytes(payload)
    digest = sha256_bytes(data)
    path = tmp_path / f"{digest}.json"
    path.write_bytes(data)
    path.with_suffix(".sha256").write_text(f"{digest}  {path.name}\n", encoding="ascii")

    result = runner.invoke(chips_app, ["validate", "--artifact", str(path)])

    _assert_typed_failure(result)


def test_tampered_artifact_is_rejected_without_traceback(tmp_path: Path) -> None:
    artifact = seal_decision_artifact(service_request())
    path = persist_decision_artifact(artifact, artifact_root=tmp_path)
    path.write_bytes(
        path.read_bytes().replace(b'"recommended_action":"USE"', b'"recommended_action":"HOLD"')
    )

    _assert_typed_failure(runner.invoke(chips_app, ["validate", "--artifact", str(path)]))
