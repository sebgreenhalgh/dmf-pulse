"""Focused MIN-007C role-baseline contract tests."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

from dmf_pulse.availability.dataset import semantic_dataset_hash
from dmf_pulse.availability.role_model import (
    ROLE_ARTIFACT_SHA256,
    RoleModelValidationError,
    fit_role_baseline,
    predict_role_utilities,
)

pytestmark = pytest.mark.unit


def _read(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def role_root(repository_root: Path) -> Path:
    return repository_root / "fixtures/availability/MIN-007C"


@pytest.fixture(scope="module")
def history(repository_root: Path) -> dict[str, object]:
    value = _read(repository_root / "fixtures/availability/MIN-007/canonical_history.json")
    assert isinstance(value, dict)
    return value


@pytest.fixture(scope="module")
def training(repository_root: Path) -> dict[str, object]:
    value = _read(repository_root / "fixtures/availability/MIN-007/training_dataset.json")
    assert isinstance(value, dict)
    return value


@pytest.fixture(scope="module")
def policy(repository_root: Path) -> dict[str, object]:
    value = _read(repository_root / "fixtures/availability/MIN-007C/minutes_baseline_policy.json")
    assert isinstance(value, dict)
    return value


def test_fit_matches_frozen_artifact(
    role_root: Path, training: dict[str, object], policy: dict[str, object]
) -> None:
    expected = _read(role_root / "role_artifact.json")
    artifact = fit_role_baseline(training, policy=policy)
    assert artifact.model_dump(mode="json") == expected
    assert artifact.artifact_sha256 == ROLE_ARTIFACT_SHA256
    assert semantic_dataset_hash(training) == (
        "1466a5dcc9104a2d26f9c6b286d2717b6460423503026f05a58d3a26de040be3"
    )


def test_fit_rejects_wrong_training_lineage(
    training: dict[str, object], policy: dict[str, object]
) -> None:
    changed = copy.deepcopy(training)
    assert isinstance(changed["rows"], list)
    assert isinstance(changed["rows"][0], dict)
    changed["rows"][0]["evidence_type"] = "PRESEASON"
    with pytest.raises(RoleModelValidationError, match="semantic hash"):
        fit_role_baseline(changed, policy=policy)


def test_prediction_is_not_a_public_player_minutes_projection(
    history: dict[str, object],
    role_root: Path,
    training: dict[str, object],
    policy: dict[str, object],
) -> None:
    from dmf_pulse import availability

    artifact = fit_role_baseline(training, policy=policy)
    context = _read(role_root / "role_canaries.json")
    assert isinstance(context, dict)
    first = context["cases"][0]
    result = predict_role_utilities(
        history,
        artifact,
        context=first,
        player_key=first["focus_player_key"],
        policy=policy,
    )
    assert not hasattr(availability, "RoleUtilityPrediction")
    assert not any(key.startswith("p_") for key in result.role_utilities)
    assert result.model_dump(mode="json")["schema_version"] == "role-utility-prediction-v1"


def test_future_and_different_team_rows_cannot_influence_prediction(
    history: dict[str, object],
    role_root: Path,
    training: dict[str, object],
    policy: dict[str, object],
) -> None:
    artifact = fit_role_baseline(training, policy=policy)
    cases = _read(role_root / "role_canaries.json")
    assert isinstance(cases, dict)
    context = cases["cases"][0]
    player_key = context["focus_player_key"]
    baseline = predict_role_utilities(
        history, artifact, context=context, player_key=player_key, policy=policy
    )
    rows = history["rows"]
    assert isinstance(rows, list)
    source = next(row for row in rows if row["player_key"] == player_key)
    assert isinstance(source, dict)
    future = copy.deepcopy(source)
    future["example_id"] = str(uuid5(NAMESPACE_URL, "min007c-future"))
    future["fixture_id"] = str(uuid5(NAMESPACE_URL, "min007c-future-fixture"))
    future["sequence_index"] = 100
    future["feature_cutoff"] = "2026-09-01T12:00:00Z"
    future["label_usable_at"] = "2026-09-01T17:00:00Z"
    other = copy.deepcopy(source)
    other["example_id"] = str(uuid5(NAMESPACE_URL, "min007c-other"))
    other["fixture_id"] = str(uuid5(NAMESPACE_URL, "min007c-other-fixture"))
    other["sequence_index"] = 101
    other["team_key"] = "beta"
    other["team_id"] = "180de9c2-c14a-5b04-82b2-7397ebac60e8"
    changed = copy.deepcopy(history)
    changed["rows"] = [*rows, future, other]
    actual = predict_role_utilities(
        changed, artifact, context=context, player_key=player_key, policy=policy
    )
    assert actual == baseline


def test_explicit_bench_label_is_not_inferred_from_minutes(
    history: dict[str, object],
    role_root: Path,
    training: dict[str, object],
    policy: dict[str, object],
) -> None:
    artifact = fit_role_baseline(training, policy=policy)
    cases = _read(role_root / "role_canaries.json")
    assert isinstance(cases, dict)
    context = next(item for item in cases["cases"] if item["scenario"] == "rare_bench_60_plus")
    baseline = predict_role_utilities(
        history, artifact, context=context, player_key=context["focus_player_key"], policy=policy
    )
    changed = copy.deepcopy(history)
    assert isinstance(changed["rows"], list)
    for row in changed["rows"]:
        if row["player_key"] == context["focus_player_key"] and row["role_label"] == "BENCH":
            row["minutes_label"] = 90
            break
    actual = predict_role_utilities(
        changed, artifact, context=context, player_key=context["focus_player_key"], policy=policy
    )
    assert actual == baseline


def test_history_older_than_newest_twelve_is_ignored(
    history: dict[str, object],
    role_root: Path,
    training: dict[str, object],
    policy: dict[str, object],
) -> None:
    artifact = fit_role_baseline(training, policy=policy)
    cases = _read(role_root / "role_canaries.json")
    assert isinstance(cases, dict)
    context = copy.deepcopy(cases["cases"][0])
    context["cutoff_sequence_index"] = 101
    context["as_of"] = "2026-09-01T12:00:00Z"
    rows = history["rows"]
    assert isinstance(rows, list)
    source = next(row for row in rows if row["player_key"] == context["focus_player_key"])
    assert isinstance(source, dict)
    additions: list[dict[str, object]] = []
    for index in range(3):
        row = copy.deepcopy(source)
        row["example_id"] = str(uuid5(NAMESPACE_URL, f"min007c-window-new-{index}"))
        row["fixture_id"] = str(uuid5(NAMESPACE_URL, f"min007c-window-fixture-{index}"))
        row["sequence_index"] = 100 - index
        additions.append(row)
    base = copy.deepcopy(history)
    base["rows"] = [*rows, *additions]
    old = copy.deepcopy(additions[0])
    old["example_id"] = str(uuid5(NAMESPACE_URL, "min007c-window-old-example"))
    old["fixture_id"] = str(uuid5(NAMESPACE_URL, "min007c-window-old-fixture"))
    old["sequence_index"] = 1
    extended = copy.deepcopy(base)
    extended["rows"] = [*base["rows"], old]
    first = predict_role_utilities(
        base, artifact, context=context, player_key=context["focus_player_key"], policy=policy
    )
    second = predict_role_utilities(
        extended,
        artifact,
        context=context,
        player_key=context["focus_player_key"],
        policy=policy,
    )
    assert first == second


def test_invalid_role_and_unresolved_override_fail_closed(
    history: dict[str, object],
    role_root: Path,
    training: dict[str, object],
    policy: dict[str, object],
) -> None:
    artifact = fit_role_baseline(training, policy=policy)
    cases = _read(role_root / "role_canaries.json")
    assert isinstance(cases, dict)
    context = cases["cases"][0]
    invalid = copy.deepcopy(history)
    assert isinstance(invalid["rows"], list)
    invalid["rows"][0]["role_label"] = "UNKNOWN_ROLE"
    with pytest.raises(RoleModelValidationError, match="invalid role row"):
        predict_role_utilities(
            invalid,
            artifact,
            context=context,
            player_key=context["focus_player_key"],
            policy=policy,
        )
    unresolved = copy.deepcopy(context)
    unresolved["player_overrides"] = {
        context["focus_player_key"]: {"eligibility_status": "UNKNOWN"}
    }
    with pytest.raises(RoleModelValidationError, match="unresolved eligibility"):
        predict_role_utilities(
            history,
            artifact,
            context=unresolved,
            player_key=context["focus_player_key"],
            policy=policy,
        )


def test_policy_hash_and_artifact_are_immutable(
    role_root: Path, training: dict[str, object], policy: dict[str, object]
) -> None:
    artifact = fit_role_baseline(training, policy=policy)
    expected = _read(role_root / "role_artifact.json")
    assert hashlib.sha256((role_root / "role_artifact.json").read_bytes()).hexdigest() == (
        "5028789a467082f526d54572fe3c095025c50cf27c0717a3cefd7452e85997e0"
    )
    assert artifact.model_dump(mode="json") == expected
