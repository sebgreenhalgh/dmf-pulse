"""Semantic branch proofs for the frozen MIN-007 role-model core."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

from dmf_pulse.availability import role_model as role
from dmf_pulse.availability.models import HistoryRow

pytestmark = pytest.mark.unit


def _read(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


@pytest.fixture(scope="module")
def data_root(repository_root: Path) -> Path:
    return repository_root / "fixtures/availability"


@pytest.fixture(scope="module")
def training(data_root: Path) -> dict[str, object]:
    return _read(data_root / "MIN-007/training_dataset.json")


@pytest.fixture(scope="module")
def history(data_root: Path) -> dict[str, object]:
    return _read(data_root / "MIN-007/canonical_history.json")


@pytest.fixture(scope="module")
def policy(data_root: Path) -> dict[str, object]:
    return _read(data_root / "MIN-007C/minutes_baseline_policy.json")


@pytest.fixture(scope="module")
def stable_context(data_root: Path) -> dict[str, object]:
    cases = _read(data_root / "MIN-007C/role_canaries.json")
    items = cases["cases"]
    assert isinstance(items, list)
    return next(item for item in items if item["scenario"] == "stable_xi")


@pytest.fixture(scope="module")
def artifact(training: dict[str, object], policy: dict[str, object]) -> role.RoleBaselineArtifact:
    return role.fit_role_baseline(training, policy=policy)


def _raises(message: str, function: object, *arguments: object, **keywords: object) -> None:
    assert callable(function)
    with pytest.raises(ValueError, match=message):
        function(*arguments, **keywords)


def test_frozen_models_reject_identity_and_prediction_contract_violations(
    artifact: role.RoleBaselineArtifact,
) -> None:
    body = artifact.model_dump(mode="json")
    for name, message in (
        ("artifact_sha256", "identity"),
        ("policy_sha256", "policy lineage"),
        ("training_dataset_sha256", "training lineage"),
    ):
        changed = dict(body)
        changed[name] = "0" * 64
        _raises(message, role.RoleBaselineArtifact.model_validate, changed)

    valid = {
        "schema_version": "role-utility-prediction-v1",
        "player_key": "semantic-player",
        "position": "MID",
        "role_utilities": {
            "START": Decimal("0.5"),
            "BENCH": Decimal("0.25"),
            "OUT": Decimal("0.25"),
        },
        "target_team_competitive_history_count": 3,
        "confidence_grade": "B",
        "confidence_reasons": ("BASELINE_MODEL_CAP_B",),
    }
    assert role.RoleUtilityPrediction.model_validate(valid).model_dump(mode="json")[
        "role_utilities"
    ] == {
        "START": "0.500000000000",
        "BENCH": "0.250000000000",
        "OUT": "0.250000000000",
    }
    invalid_cases = (
        ("role_utilities", {"START": Decimal(1)}, "roles are incomplete"),
        (
            "role_utilities",
            {"START": Decimal("1.1"), "BENCH": Decimal(0), "OUT": Decimal("-0.1")},
            "Decimal values",
        ),
        (
            "role_utilities",
            {"START": Decimal("0.4"), "BENCH": Decimal("0.3"), "OUT": Decimal("0.2")},
            "sum exactly",
        ),
        ("confidence_reasons", ("Z", "BASELINE_MODEL_CAP_B"), "lexicographically sorted"),
        (
            "confidence_reasons",
            ("BASELINE_MODEL_CAP_B", "BASELINE_MODEL_CAP_B"),
            "must be unique",
        ),
        ("confidence_reasons", ("OTHER",), "cap reason"),
    )
    for key, value, message in invalid_cases:
        changed = dict(valid)
        changed[key] = value
        _raises(message, role.RoleUtilityPrediction.model_validate, changed)


def test_private_mapping_scalar_uuid_policy_and_normalisation_boundaries(
    policy: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    class Dumpable:
        def model_dump(self, *, mode: str) -> Mapping[str, object]:
            assert mode == "json"
            return {"semantic": "value"}

    assert role._mapping({"semantic": "value"}, label="mapping") == {"semantic": "value"}
    assert role._mapping(Dumpable(), label="dumpable") == {"semantic": "value"}

    class NonMappingDumpable:
        def model_dump(self, *, mode: str) -> list[str]:
            assert mode == "json"
            return ["not", "a", "mapping"]

    _raises("mapping or validated", role._mapping, NonMappingDumpable(), label="value")
    _raises("mapping or validated", role._mapping, object(), label="value")
    for value in (True, -1, "1"):
        _raises("integer >= 0", role._strict_int, value, label="number")
    assert role._strict_int(1, label="number", minimum=1) == 1
    _raises("boolean", role._strict_bool, 1, label="flag")
    assert role._strict_bool(False, label="flag") is False
    _raises("UUID string", role._uuid_text, 7, label="identifier")
    _raises("UUID string", role._uuid_text, "not-a-uuid", label="identifier")
    assert role._uuid_text("06527612-3dbd-5207-869f-a09b477baa3d", label="identifier") == (
        "06527612-3dbd-5207-869f-a09b477baa3d"
    )

    changed_policy = dict(policy)
    changed_policy["recency_decay"] = "0.840000"
    _raises("frozen minutes baseline", role._policy_mapping, changed_policy)
    monkeypatch.setattr(role, "FROZEN_POLICY_SHA256", "0" * 64)
    _raises("semantic hash", role._policy_mapping, policy)
    monkeypatch.undo()
    assert role._policy_mapping(policy)["role_prior_strength"] == "2.000000"

    _raises(
        "no positive mass",
        role._normalise_scores,
        {"START": Decimal(0), "BENCH": Decimal(0), "OUT": Decimal(0)},
    )
    normalised = role._normalise_scores(
        {"START": Decimal(2), "BENCH": Decimal(1), "OUT": Decimal(1)}
    )
    assert normalised == {"START": Decimal("0.5"), "BENCH": Decimal("0.25"), "OUT": Decimal("0.25")}
    vector = role._public_vector((Decimal("0.3333333333333"),) * 3)
    assert vector == (
        Decimal("0.333333333334"),
        Decimal("0.333333333333"),
        Decimal("0.333333333333"),
    )
    with localcontext() as decimal_context:
        decimal_context.traps[InvalidOperation] = False
        _raises(
            "residual correction failed",
            role._public_vector,
            (Decimal("Infinity"), Decimal(0), Decimal(0)),
        )


def test_history_training_and_artifact_validation_paths(
    training: dict[str, object], policy: dict[str, object], artifact: role.RoleBaselineArtifact
) -> None:
    _raises("rows sequence", role._as_history_rows, {"rows": "not-rows"})
    _raises("rows must be mappings", role._as_history_rows, {"rows": [object()]})
    direct_row = HistoryRow.model_validate(training["rows"][0])
    assert role._as_history_rows({"rows": [direct_row]}) == (direct_row,)
    unsupported = copy.deepcopy(training["rows"][0])
    assert isinstance(unsupported, dict)
    unsupported["evidence_type"] = "OTHER"
    _raises("evidence type", role._as_history_rows, {"rows": [unsupported]})
    duplicate = copy.deepcopy(training["rows"][0])
    assert isinstance(duplicate, dict)
    _raises("duplicate example_id", role._as_history_rows, {"rows": [duplicate, duplicate]})
    invalid = copy.deepcopy(training["rows"][0])
    assert isinstance(invalid, dict)
    invalid["minutes_label"] = 99
    _raises("invalid role row", role._as_history_rows, {"rows": [invalid]})
    _raises("368-row TRAIN", role._training_rows, {"rows": []})
    eval_dataset = copy.deepcopy(training)
    assert isinstance(eval_dataset["rows"], list)
    eval_dataset["rows"][0]["split"] = "EVAL"
    _raises("368-row TRAIN", role._training_rows, eval_dataset)
    changed_dataset = copy.deepcopy(training)
    assert isinstance(changed_dataset["rows"], list)
    changed_dataset["rows"][0]["fixture_key"] = "changed-semantic-input"
    _raises("semantic hash", role._training_rows, changed_dataset)

    body = artifact.model_dump(mode="json")
    changed = dict(body)
    changed["history_window"] = 0
    _raises("schema validation", role._artifact_mapping, changed)
    forged = dict(body)
    forged["history_window"] = 11
    _raises("semantic identity", role._artifact_mapping, forged)


def test_context_roster_and_override_validation_paths(
    history: dict[str, object],
    stable_context: dict[str, object],
    artifact: role.RoleBaselineArtifact,
    policy: dict[str, object],
) -> None:
    _raises("required field", role._context_mapping, {})
    invalid_context = dict(stable_context)
    invalid_context["team_key"] = ""
    _raises("team_key", role._context_mapping, invalid_context)
    invalid_context = dict(stable_context)
    invalid_context["new_manager"] = 1
    _raises("boolean", role._context_mapping, invalid_context)
    invalid_context = dict(stable_context)
    invalid_context["current_manager_team_lineups"] = True
    _raises("integer", role._context_mapping, invalid_context)
    invalid_context = dict(stable_context)
    invalid_context["player_overrides"] = []
    _raises("overrides", role._context_mapping, invalid_context)

    context = role._context_mapping(stable_context)
    rows = role._as_history_rows(history)
    _raises(
        "must contain rosters",
        role._player,
        {"rows": history["rows"]},
        rows,
        context,
        "alpha_mid_1",
    )
    bad_roster = copy.deepcopy(history)
    bad_roster["rosters"] = {"alpha": "bad"}
    _raises("target team roster", role._player, bad_roster, rows, context, "alpha_mid_1")
    malformed_other_roster = copy.deepcopy(history)
    malformed_other_roster["rosters"]["beta"] = "not-a-roster"
    _raises("roster identities", role._player, malformed_other_roster, rows, context, "alpha_mid_1")
    other_roster_bad = copy.deepcopy(history)
    other_roster_bad["rosters"]["beta"] = ["not-a-player"]
    _raises(
        "roster players must be mappings",
        role._player,
        other_roster_bad,
        rows,
        context,
        "alpha_mid_1",
    )
    target_roster_bad = copy.deepcopy(history)
    target_roster_bad["rosters"]["alpha"] = ["not-a-player"]
    _raises(
        "roster players must be mappings",
        role._player,
        target_roster_bad,
        rows,
        context,
        "alpha_mid_1",
    )
    _raises("not present", role._player, history, rows, context, "missing-player")

    duplicate = copy.deepcopy(history)
    roster = duplicate["rosters"]["alpha"]
    assert isinstance(roster, list)
    roster.append(copy.deepcopy(roster[0]))
    _raises("duplicate player_key", role._player, duplicate, rows, context, roster[0]["player_key"])
    bad_override = copy.deepcopy(stable_context)
    bad_override["player_overrides"] = {"alpha_mid_1": {"player_id": "not-a-uuid"}}
    _raises(
        "UUID string",
        role.predict_role_utilities,
        history,
        artifact,
        context=bad_override,
        player_key="alpha_mid_1",
        policy=policy,
    )
    absent_new_signing = copy.deepcopy(stable_context)
    absent_new_signing["player_overrides"] = {
        "alpha_mid_1": {"player_id": str(uuid5(NAMESPACE_URL, "different-player"))}
    }
    _raises(
        "requires explicit new_signing",
        role.predict_role_utilities,
        history,
        artifact,
        context=absent_new_signing,
        player_key="alpha_mid_1",
        policy=policy,
    )
    collision = copy.deepcopy(stable_context)
    roster_ids = history["rosters"]["alpha"]
    assert isinstance(roster_ids, list)
    collision["player_overrides"] = {
        "alpha_mid_1": {"new_signing": True, "player_id": roster_ids[0]["player_id"]}
    }
    _raises(
        "collides",
        role.predict_role_utilities,
        history,
        artifact,
        context=collision,
        player_key="alpha_mid_1",
        policy=policy,
    )

    empty_key = copy.deepcopy(history)
    empty_key["rosters"]["alpha"] = copy.deepcopy(empty_key["rosters"]["alpha"])
    empty_key["rosters"]["alpha"][0]["player_key"] = ""
    _raises("player.player_key", role._player, empty_key, rows, context, "")
    wrong_team = copy.deepcopy(history)
    wrong_team["rosters"]["alpha"] = copy.deepcopy(wrong_team["rosters"]["alpha"])
    wrong_team["rosters"]["alpha"][0]["team_key"] = "beta"
    _raises(
        "does not belong",
        role._player,
        wrong_team,
        rows,
        context,
        wrong_team["rosters"]["alpha"][0]["player_key"],
    )
    wrong_position = copy.deepcopy(history)
    wrong_position["rosters"]["alpha"] = copy.deepcopy(wrong_position["rosters"]["alpha"])
    wrong_position["rosters"]["alpha"][0]["position"] = "SWEEPER"
    _raises(
        "position is invalid",
        role._player,
        wrong_position,
        rows,
        context,
        wrong_position["rosters"]["alpha"][0]["player_key"],
    )
    malformed_override_context = dict(context)
    malformed_override_context["player_overrides"] = {"alpha_mid_1": []}
    _raises(
        "override must be a mapping",
        role._player,
        history,
        rows,
        malformed_override_context,
        "alpha_mid_1",
    )


def test_temporal_weighting_ordering_and_confidence_semantics(
    history: dict[str, object],
    stable_context: dict[str, object],
    artifact: role.RoleBaselineArtifact,
    policy: dict[str, object],
) -> None:
    context = role._context_mapping(stable_context)
    rows = role._as_history_rows(history)
    player = role._player(history, rows, context, "alpha_mid_1")
    retained = role._eligible_rows(rows, player, context, 12)
    assert retained == tuple(
        sorted(retained, key=lambda row: (-row.sequence_index, str(row.example_id)))
    )
    assert all(
        row.feature_cutoff < context["as_of"] and row.label_usable_at <= context["as_of"]
        for row in retained
    )
    assert role._eligible_rows(rows, player, context, 0) == ()

    no_history_player = dict(player)
    no_history_player["hard_ineligible"] = False
    assert role._confidence(no_history_player, context, 0) == (
        "D",
        ("BASELINE_MODEL_CAP_B", "NO_TARGET_TEAM_COMPETITIVE_HISTORY"),
    )
    assert role._confidence(no_history_player, context, 2)[0] == "C"
    manager_context = dict(context)
    manager_context["new_manager"] = True
    manager_context["current_manager_team_lineups"] = 0
    manager_context["promoted_team"] = True
    manager_context["target_league_team_lineups"] = 0
    grade, reasons = role._confidence(no_history_player, manager_context, 3)
    assert grade == "C"
    assert reasons == (
        "BASELINE_MODEL_CAP_B",
        "NEW_MANAGER_REGIME",
        "PROMOTED_TEAM_EARLY_REGIME",
    )
    assert role._confidence(no_history_player, manager_context, 0) == (
        "D",
        (
            "BASELINE_MODEL_CAP_B",
            "NEW_MANAGER_REGIME",
            "NO_TARGET_TEAM_COMPETITIVE_HISTORY",
            "PROMOTED_TEAM_EARLY_REGIME",
        ),
    )
    assert role._confidence(no_history_player, manager_context, 5)[0] == "C"
    new_signing = dict(no_history_player)
    new_signing["new_signing"] = True
    assert role._confidence(new_signing, context, 0)[0] == "D"
    assert role._confidence(new_signing, context, 3)[0] == "C"
    hard_ineligible = dict(no_history_player)
    hard_ineligible["hard_ineligible"] = True
    assert role._confidence(hard_ineligible, context, 10) == (
        "B",
        ("BASELINE_MODEL_CAP_B", "HARD_INELIGIBLE_OVERRIDE"),
    )

    _raises(
        "player_key",
        role.predict_role_utilities,
        history,
        artifact,
        context=stable_context,
        player_key="",
        policy=policy,
    )
    result = role.predict_role_utilities(
        history, artifact, context=stable_context, player_key="alpha_mid_1", policy=policy
    )
    assert sum(result.role_utilities.values(), Decimal(0)) == Decimal(1)
    assert result.role_utilities["START"] > result.role_utilities["OUT"]
    hard_context = copy.deepcopy(stable_context)
    hard_context["player_overrides"] = {"alpha_mid_1": {"hard_ineligible": True}}
    hard = role.predict_role_utilities(
        history, artifact, context=hard_context, player_key="alpha_mid_1", policy=policy
    )
    assert hard.role_utilities == {"START": Decimal(0), "BENCH": Decimal(0), "OUT": Decimal(1)}

    preseason_history = copy.deepcopy(history)
    for row in preseason_history["rows"]:
        if row["player_key"] == "alpha_mid_1":
            row["evidence_type"] = "PRESEASON"
            break
    preseason = role.predict_role_utilities(
        preseason_history, artifact, context=stable_context, player_key="alpha_mid_1", policy=policy
    )
    assert preseason.role_utilities != result.role_utilities
