"""Offline A2 comparison contract over real canonical Stage-11 solves."""

from __future__ import annotations

import inspect
import json
import socket
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.private_v1 import live_shadow_observation as a2
from dmf_pulse.private_v1.live_shadow_observation import (
    _live_pair,
    _run_live_comparison,
    _validated_control_alignment,
    safe_live_observation_summary,
)
from dmf_pulse.private_v1.one_command import PrivateV1OneCommandService
from dmf_pulse.private_v1.shadow_comparison import _canonical_value
from tests.unit.private_v1.a2_test_support import build_a2_comparison_inputs

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def live_case(repository_root, tmp_path_factory):
    prepared, history, shadow = build_a2_comparison_inputs(
        repository_root,
        tmp_path_factory.mktemp("a2-live-comparison"),
    )
    calls: list[str] = []

    def forbidden(*args, **kwargs):
        calls.append("network")
        raise AssertionError("four-world solve must not access the network")

    patch = pytest.MonkeyPatch()
    patch.setattr(socket, "create_connection", forbidden)
    patch.setattr(socket, "getaddrinfo", forbidden)
    patch.setattr(socket.socket, "connect", forbidden)
    patch.setattr(a2, "DirectFplClient", forbidden)
    patch.setattr(a2, "CurrentOddsTransientService", forbidden)
    patch.setattr(a2, "CurrentScorePriorService", forbidden)
    try:
        observation, stale = _run_live_comparison(
            prepared,
            history,
            shadow,
            progress=a2.NullProgress(),
            network_state=lambda: (0, 0, 0),
        )
    finally:
        patch.undo()
    assert calls == []
    return observation, stale, prepared


def test_real_four_world_solve_is_complete_controlled_and_transient(live_case) -> None:
    observation, stale, prepared = live_case

    assert stale.decision.status == "SUCCESS"
    assert tuple(item.world for item in observation.results) == (
        "STALE",
        "CENTRAL_TEMPORARY",
        "LOW_SHRINKAGE",
        "HIGH_SHRINKAGE",
    )
    assert len(observation.pairs) == 6
    assert all(item.solver_status == "OPTIMAL" for item in observation.results)
    assert all(item.recommended_plan_present for item in observation.results)
    assert all(item.no_transfer_baseline_present for item in observation.results)
    assert all(item.horizon_frontier_present for item in observation.results)
    assert observation.stage7_identical_across_worlds
    assert observation.stage8_identical_across_worlds
    assert observation.root_randomness_aligned
    assert observation.scenario_identity_aligned
    assert observation.prices_identical_across_worlds
    assert observation.manager_state_identical_across_worlds
    assert observation.rules_identical_across_worlds
    assert observation.work_budget_semantics_identical_across_worlds
    assert observation.fixture_order_identical_across_worlds
    assert observation.terminal_policy_identical_across_worlds
    assert observation.candidate_policy_identical_across_worlds
    assert observation.candidate_universe_same_across_worlds
    assert observation.new_network_requests_during_world_comparison == 0
    assert observation.persistence_performed is False
    assert observation.model_training_performed is False
    assert observation.production_activation is False
    assert observation.rolling_execution_input_sha256 == prepared.rolling_execution.semantic_sha256


def test_live_contract_seal_rejects_control_tampering(live_case) -> None:
    observation, _, _ = live_case
    with pytest.raises(ValueError, match=r"control divergence|semantic hash"):
        replace(observation, stage7_identical_across_worlds=False)


@pytest.mark.parametrize(
    "field",
    ("fixture_order_sha256", "terminal_policy_sha256", "candidate_policy_sha256"),
)
def test_comparison_blocks_omitted_control_hash_divergence(live_case, field) -> None:
    observation, _, _ = live_case
    payload = asdict(observation.results[1])
    payload[field] = "f" * 64
    payload.pop("semantic_sha256")
    changed = replace(
        observation.results[1],
        **{
            field: "f" * 64,
            "semantic_sha256": canonical_sha256(_canonical_value(payload)),
        },
    )
    results = (
        observation.results[0],
        changed,
        observation.results[2],
        observation.results[3],
    )

    with pytest.raises(ValueError, match="controls diverged"):
        _validated_control_alignment(results)


def test_candidate_screen_difference_is_disclosed_not_rejected(monkeypatch, live_case) -> None:
    observation, _, _ = live_case
    left, right = observation.results[:2]
    monkeypatch.setattr(
        a2,
        "_pair",
        lambda *_: SimpleNamespace(
            left=left.world,
            right=right.world,
            root_action_changed=True,
            full_plan_changed=True,
            starting_xi_changed=False,
            captain_changed=False,
            vice_captain_changed=False,
            continuation_changed=False,
            candidate_screen_equal=False,
            optimal_utility_delta=right.plan_expected_horizon_utility
            - left.plan_expected_horizon_utility,
            hold_utility_delta=right.baseline_expected_horizon_utility
            - left.baseline_expected_horizon_utility,
            uplift_delta=right.expected_uplift - left.expected_uplift,
            classification="WORLD_SENSITIVE_ROOT_ACTION",
        ),
    )

    pair = _live_pair(left, right)

    assert pair.classification == "LIVE_ROOT_ACTION_DIFFERENCE_CANDIDATE_SCREEN_CONFOUNDED"
    assert pair.candidate_screen_equal is False


def test_safe_summary_is_decision_level_and_releases_no_posterior_rows(live_case) -> None:
    observation, _, prepared = live_case
    summary = safe_live_observation_summary(observation, prepared)
    encoded = json.dumps(summary, sort_keys=True)

    assert len(summary["worlds"]) == 4
    assert len(summary["robustness"]["pair_classifications"]) == 6
    assert "entry_id" not in encoded
    assert "posterior_mean" not in encoded
    assert "historical_mean" not in encoded
    assert "source_body" not in encoded
    assert "credential" not in encoded
    assert "api_key" not in encoded.casefold()
    assert summary["persistence_performed"] is False
    assert summary["model_training_performed"] is False


def test_normal_service_has_no_public_world_selection_mechanism(repository_root) -> None:
    parameters = inspect.signature(PrivateV1OneCommandService).parameters
    source = (repository_root / "scripts/run_r9c_a2_live_shadow.py").read_text(encoding="utf-8")

    assert "world" not in parameters
    assert all(not name.startswith("shadow") for name in parameters)
    assert "--world" not in source
    assert "--output" not in source
    assert "while " not in source


def test_a1_artifact_hashes_remain_exact(repository_root) -> None:
    base = repository_root / "evidence/tickets/PRIVATE-V1-ONE-COMMAND-001N-R9C-A1"
    root = json.loads((base / "SYNTHETIC_R9C_A1_ROOT_SENSITIVE_COMPARISON.json").read_text())
    continuation = json.loads(
        (base / "SYNTHETIC_R9C_A1_CONTINUATION_SENSITIVE_COMPARISON.json").read_text()
    )

    assert root["artifact_semantic_sha256"] == (
        "f5ed1f8b64eb0270cca1a08de20bbbef67839de8d4d79d75f72cdab17a568cc1"
    )
    assert continuation["artifact_semantic_sha256"] == (
        "24583b60a8d047c59c0f5895ba923cb41904ed965b548bfefd58644b0f45f726"
    )
