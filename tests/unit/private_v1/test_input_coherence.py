from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.fpl_points.models import ProjectionMode
from dmf_pulse.fpl_points.player_prior import load_packaged_player_prior
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.markets.current import CurrentMarketConstraintError, CurrentMarketReadiness
from dmf_pulse.private_v1 import artifacts, service
from dmf_pulse.private_v1.errors import PrivateV1Error
from dmf_pulse.private_v1.models import (
    PrivateCandidateActionPolicy,
    PrivateCanonicalPlayerIdentity,
    PrivateCanonicalPlayerIdentityMap,
    PrivateCurrentOwnership,
    PrivateFixtureScorePrior,
    PrivateReplayManifest,
    PrivateV1ExecutionInput,
    seal_candidate_action_policy,
    seal_canonical_player_identity_map,
    seal_current_ownership,
    seal_execution_input,
    seal_fixture_score_prior,
    seal_replay_manifest,
)
from dmf_pulse.private_v1.service import (
    PrivateV1RecommendationService,
    _fixture_authority,
    _participation_scenarios,
    _verify_current_sources,
    _verify_runtime_artifacts,
)

from .e2e_test_support import build_execution_input


@pytest.fixture(scope="module")
def execution(
    repository_root: Path, tmp_path_factory: pytest.TempPathFactory
) -> PrivateV1ExecutionInput:
    return build_execution_input(repository_root, tmp_path_factory.mktemp("private-v1-input"))


def _replace(value: PrivateV1ExecutionInput, **updates: Any) -> PrivateV1ExecutionInput:
    fields = {name: getattr(value, name) for name in type(value).model_fields}
    fields.update(updates)
    fields["semantic_sha256"] = "0" * 64
    provisional = PrivateV1ExecutionInput.model_construct(**fields)
    return seal_execution_input(provisional)


def _ownership(value: PrivateV1ExecutionInput, **updates: Any) -> PrivateCurrentOwnership:
    fields = {name: getattr(value.ownership, name) for name in type(value.ownership).model_fields}
    fields.update(updates)
    fields["semantic_sha256"] = "0" * 64
    return seal_current_ownership(PrivateCurrentOwnership.model_construct(**fields))


def test_wrong_target_gameweek_and_mixed_cutoff_fail(execution: PrivateV1ExecutionInput) -> None:
    with pytest.raises(ValidationError, match="season, GW, cutoff, or rules"):
        _replace(execution, ownership=_ownership(execution, target_gameweek=2))

    changed = execution.manual_minutes[0].model_copy(
        update={
            "as_of": execution.current_state.information_cutoff - timedelta(minutes=1),
            "information_cutoff": execution.current_state.information_cutoff - timedelta(minutes=1),
        }
    )
    with pytest.raises(ValidationError, match="Stage-7 input cutoff"):
        _replace(execution, manual_minutes=(changed, *execution.manual_minutes[1:]))


@pytest.mark.parametrize("mode", ["missing", "duplicate", "stale"])
def test_fixture_set_must_be_exact(execution: PrivateV1ExecutionInput, mode: str) -> None:
    if mode == "missing":
        minutes = execution.manual_minutes[:-1]
    elif mode == "duplicate":
        minutes = (*execution.manual_minutes, execution.manual_minutes[-1])
    else:
        stale_fixture_id = "00000000-0000-4000-8000-000000099999"
        provenance = execution.manual_minutes[0].provenance.model_copy(
            update={"fixture_scope_id": stale_fixture_id}
        )
        changed = execution.manual_minutes[0].model_copy(
            update={"fixture_id": stale_fixture_id, "provenance": provenance}
        )
        minutes = (changed, *execution.manual_minutes[1:])
    with pytest.raises(ValidationError, match="fixture"):
        _replace(execution, manual_minutes=minutes)


def test_manager_and_candidate_require_exact_canonical_player_ids(
    execution: PrivateV1ExecutionInput,
) -> None:
    manager_id = execution.current_state.manager_state.squad[0].official_fpl_element_id
    mappings = tuple(
        item
        for item in execution.player_identity_map.players
        if item.official_fpl_element_id != manager_id
    )
    reduced = seal_canonical_player_identity_map(
        PrivateCanonicalPlayerIdentityMap.model_construct(
            **{
                name: getattr(execution.player_identity_map, name)
                for name in type(execution.player_identity_map).model_fields
                if name not in {"players", "semantic_sha256"}
            },
            players=mappings,
            semantic_sha256="0" * 64,
        )
    )
    with pytest.raises(ValidationError, match="require canonical player mappings"):
        _replace(execution, player_identity_map=reduced)


def test_stale_team_membership_and_fuzzy_identity_fail(
    execution: PrivateV1ExecutionInput,
) -> None:
    original = execution.player_identity_map.players[0]
    wrong_team = 2 if original.official_fpl_team_id != 2 else 3
    changed = original.model_copy(update={"official_fpl_team_id": wrong_team})
    stale = seal_canonical_player_identity_map(
        PrivateCanonicalPlayerIdentityMap.model_construct(
            source_class=execution.player_identity_map.source_class,
            resolved_at=execution.player_identity_map.resolved_at,
            information_cutoff=execution.player_identity_map.information_cutoff,
            teams=execution.player_identity_map.teams,
            players=(changed, *execution.player_identity_map.players[1:]),
            semantic_sha256="0" * 64,
        )
    )
    with pytest.raises(ValidationError, match="current FPL membership"):
        _replace(execution, player_identity_map=stale)

    with pytest.raises(ValidationError):
        PrivateCanonicalPlayerIdentity(
            official_fpl_element_id=1,
            official_fpl_team_id=1,
            canonical_player_id="Player Name",  # type: ignore[arg-type]
        )


def test_candidate_scope_cannot_include_owned_duplicate_or_unmapped_player(
    execution: PrivateV1ExecutionInput,
) -> None:
    owned = execution.current_state.manager_state.squad[0].official_fpl_element_id
    policy = seal_candidate_action_policy(
        PrivateCandidateActionPolicy.model_construct(
            allowed_transfer_in_element_ids=(owned,),
            maximum_transfers=1,
            rationale="Negative owned-player contract test.",
            semantic_sha256="0" * 64,
        )
    )
    with pytest.raises(ValidationError, match="known current non-squad"):
        _replace(execution, candidate_action_policy=policy)

    with pytest.raises(ValidationError, match="unique and sorted"):
        PrivateCandidateActionPolicy.model_validate(
            {
                **execution.candidate_action_policy.model_dump(mode="python"),
                "allowed_transfer_in_element_ids": (999, 999),
            }
        )


def test_ownership_chronology_and_attestation_are_not_inferred(
    execution: PrivateV1ExecutionInput,
) -> None:
    members = list(execution.ownership.members)
    members[0] = members[0].model_copy(update={"acquired_gameweek": 2})
    with pytest.raises(ValidationError, match="acquisition cannot be after"):
        _ownership(execution, members=tuple(members))
    with pytest.raises(ValidationError, match="timestamps are out of order"):
        _ownership(
            execution,
            declared_at=execution.ownership.attested_at + timedelta(minutes=1),
        )


def test_synthetic_and_real_score_prior_lineage_cannot_be_relabelled(
    execution: PrivateV1ExecutionInput,
) -> None:
    prior = execution.score_priors[0]
    with pytest.raises(ValidationError, match="current score-prior bundle binding differs"):
        seal_fixture_score_prior(
            PrivateFixtureScorePrior.model_construct(
                **{
                    name: getattr(prior, name)
                    for name in type(prior).model_fields
                    if name not in {"source_class", "semantic_sha256"}
                },
                source_class="CURRENT_SCORE_PRIOR_BUNDLE",
                semantic_sha256="0" * 64,
            )
        )
    with pytest.raises(ValidationError, match="synthetic score priors require"):
        _replace(
            execution,
            retention_class="PRIVATE_TRANSIENT_NO_RETENTION",
            synthetic_source_attestation=None,
        )


def test_stage7_scenario_identity_alignment_is_explicit(
    execution: PrivateV1ExecutionInput,
) -> None:
    value = execution.manual_minutes[0]
    changed_scenario = value.away.scenarios[0].model_copy(update={"scenario_id": "DIFFERENT"})
    changed_away = value.away.model_copy(
        update={"scenarios": (changed_scenario, *value.away.scenarios[1:])}
    )
    changed = value.model_copy(update={"away": changed_away})
    with pytest.raises(PrivateV1Error, match="STAGE7_SCENARIO_ALIGNMENT_INVALID"):
        _participation_scenarios(
            changed,
            gameweek_id="GW-1",
            home_projection=object(),
            away_projection=object(),
        )


def test_policy_hashes_and_execution_mode_are_bound(
    execution: PrivateV1ExecutionInput,
) -> None:
    with pytest.raises(ValidationError, match="Monte Carlo policy hash"):
        _replace(execution, stage9_monte_carlo_policy_sha256="f" * 64)
    with pytest.raises(ValidationError, match="allocation configuration hash"):
        _replace(execution, event_allocation_config_sha256="f" * 64)
    with pytest.raises(ValidationError, match="permits only TEST or REPLAY"):
        _replace(execution, projection_mode=ProjectionMode.PRODUCTION)
    with pytest.raises(ValidationError, match="synthetic retention requires"):
        _replace(execution, synthetic_source_attestation=None)


def test_packaged_stage8_and_player_prior_artifacts_are_execution_bound(
    execution: PrivateV1ExecutionInput,
) -> None:
    prior = load_packaged_player_prior()
    _verify_runtime_artifacts(execution, prior)
    with pytest.raises(PrivateV1Error, match="PLAYER_PRIOR_IDENTITY_MISMATCH"):
        _verify_runtime_artifacts(
            _replace(execution, expected_player_prior_artifact_sha256="f" * 64),
            prior,
        )
    with pytest.raises(PrivateV1Error, match="STAGE8_POLICY_IDENTITY_MISMATCH"):
        _verify_runtime_artifacts(
            _replace(execution, expected_stage8_policy_sha256="f" * 64),
            prior,
        )


def test_execution_serialisation_contains_no_paths_or_secret_fields(
    execution: PrivateV1ExecutionInput,
) -> None:
    rendered = execution.model_dump_json()
    assert "bootstrap_path" not in rendered
    assert "fixtures_path" not in rendered
    assert "api_key" not in rendered.casefold()
    assert "password" not in rendered.casefold()
    assert "session_cookie" not in rendered.casefold()


def test_current_source_failures_are_stage_typed_and_redacted(
    execution: PrivateV1ExecutionInput,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _ingestion_failure(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise IngestionError("VALIDATION_FAILED", "sensitive upstream state")

    monkeypatch.setattr(service.CurrentUnifiedStateService, "verify", _ingestion_failure)
    with pytest.raises(PrivateV1Error) as caught:
        _verify_current_sources(execution)
    assert caught.value.code == "CURRENT_STATE_INVALID"
    assert "sensitive upstream state" not in str(caught.value)

    monkeypatch.setattr(service.CurrentUnifiedStateService, "verify", lambda *args, **kwargs: None)

    def _market_failure(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise CurrentMarketConstraintError("CURRENT_MARKET_INPUT_INVALID")

    monkeypatch.setattr(service.CurrentMarketConstraintService, "verify", _market_failure)
    with pytest.raises(PrivateV1Error) as caught:
        _verify_current_sources(execution)
    assert caught.value.code == "CURRENT_MARKET_INVALID"


def test_blocked_market_and_changed_fixture_authority_fail_closed(
    execution: PrivateV1ExecutionInput,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    changed = deepcopy(execution)
    object.__setattr__(
        changed.market_constraints.fixtures[0], "readiness", CurrentMarketReadiness.BLOCKED
    )
    monkeypatch.setattr(service.CurrentUnifiedStateService, "verify", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        service.CurrentMarketConstraintService, "verify", lambda *args, **kwargs: None
    )
    with pytest.raises(PrivateV1Error) as caught:
        _verify_current_sources(changed)
    assert caught.value.code == "CURRENT_MARKET_BLOCKED"

    changed = deepcopy(execution)
    object.__setattr__(
        changed.market_identity_view,
        "fixtures",
        changed.market_identity_view.fixtures[:-1],
    )
    with pytest.raises(PrivateV1Error) as caught:
        _fixture_authority(changed)
    assert caught.value.code == "FIXTURE_SET_MISMATCH"


def test_replay_result_mismatch_is_typed(
    execution: PrivateV1ExecutionInput,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    frozen = object()
    monkeypatch.setattr(
        artifacts,
        "verify_replay_bundle",
        lambda directory: (
            SimpleNamespace(manifest_sha256="a" * 64),
            execution,
            frozen,
            "frozen report",
        ),
    )
    monkeypatch.setattr(
        PrivateV1RecommendationService,
        "run",
        lambda self, value: SimpleNamespace(decision=object(), report="changed report"),
    )

    with pytest.raises(PrivateV1Error) as caught:
        PrivateV1RecommendationService().replay(tmp_path)

    assert caught.value.code == "REPLAY_RESULT_MISMATCH"


def test_every_required_upstream_change_changes_the_replay_manifest(
    execution: PrivateV1ExecutionInput,
) -> None:
    base_payload = execution.model_dump(mode="json", exclude={"semantic_sha256"})

    def _manifest_sha(payload: dict[str, Any]) -> str:
        provisional = PrivateReplayManifest.model_construct(
            run_id=execution.run_id,
            code_sha=execution.code_sha,
            execution_input_semantic_sha256=canonical_sha256(payload),
            decision_semantic_sha256="d" * 64,
            files=(),
            manifest_sha256="0" * 64,
        )
        return seal_replay_manifest(provisional).manifest_sha256

    baseline = _manifest_sha(base_payload)
    variants: list[dict[str, Any]] = []

    changed = deepcopy(base_payload)
    changed["current_state"]["manager_state"]["semantic_sha256"] = "f" * 64
    variants.append(changed)

    changed = deepcopy(base_payload)
    changed["market_constraints"]["semantic_sha256"] = "f" * 64
    variants.append(changed)

    changed = deepcopy(base_payload)
    changed["manual_minutes"][0]["provenance"]["reason"] += " changed"
    variants.append(changed)

    changed = deepcopy(base_payload)
    changed["expected_player_prior_artifact_sha256"] = "f" * 64
    variants.append(changed)

    changed = deepcopy(base_payload)
    changed["root_seed"] += 1
    variants.append(changed)

    assert all(_manifest_sha(payload) != baseline for payload in variants)
    assert len({_manifest_sha(payload) for payload in variants}) == len(variants)
