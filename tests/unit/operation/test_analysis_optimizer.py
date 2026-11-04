"""Actual unchanged engine evidence stays bound across IPC and immutable storage."""

from dataclasses import replace
from datetime import timedelta

import pytest

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.dashboard import current
from dmf_pulse.dashboard.authorization import AuthorizationError
from dmf_pulse.dashboard.current import CurrentRefreshSession, CurrentWorkerResult
from dmf_pulse.dashboard.synthetic import DEMO_TIME
from dmf_pulse.dashboard.views import desk_view
from dmf_pulse.operation.analysis_models import AnalysisSnapshot
from dmf_pulse.operation.analysis_optimizer import AnalysisOptimizerEvidence
from dmf_pulse.operation.analysis_store import AnalysisStore
from dmf_pulse.private_v1.progress import NullProgress
from dmf_pulse.private_v1.service import PrivateV1RecommendationService


@pytest.fixture(scope="module")
def actual_evidence(tmp_path_factory):
    session = CurrentRefreshSession.owned(tmp_path_factory.mktemp("optimizer") / "usage")
    launch = session.prepare(1)
    outputs = []
    original = PrivateV1RecommendationService.run

    def capture(self, *args, **kwargs):
        value = original(self, *args, **kwargs)
        outputs.append(value)
        return value

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(PrivateV1RecommendationService, "run", capture)
        result = current.run_current_recommendation(launch, NullProgress())
    assert len(outputs) == 1
    evidence = AnalysisOptimizerEvidence(
        decision_sha256=result.decision.semantic_sha256,
        optimiser_result=outputs[0].optimiser_result,
    )
    evidence.require_bound_to(result.decision)
    digest = canonical_sha256(result.presentation.model_dump(mode="json"))
    envelope = CurrentWorkerResult(
        result,
        launch.grant.semantic_sha256,
        digest,
        current._result_authentication(launch, result, digest, evidence),
        evidence,
    )
    current.validate_current_result(envelope, launch)
    return launch, envelope


def test_standing_worker_cannot_omit_optimizer_even_with_matching_legacy_mac(actual_evidence):
    launch, envelope = actual_evidence
    standing = replace(
        launch,
        grant=launch.grant.model_copy(
            update={
                "request": launch.grant.request.model_copy(
                    update={"authorization_id": "OPR001-OWNED-OMISSION-TEST"}
                )
            }
        ),
    )
    missing = replace(
        envelope,
        grant_sha256=standing.grant.semantic_sha256,
        optimizer_evidence=None,
        authentication_sha256=current._result_authentication(
            standing, envelope.result, envelope.presentation_sha256
        ),
    )
    with pytest.raises(AuthorizationError, match="WORKER_RESULT_BINDING_INVALID"):
        current.validate_current_result(missing, standing)


@pytest.mark.parametrize("attack", ["stripped", "tampered", "resealed_tamper", "decision"])
def test_ipc_rejects_stripped_tampered_and_rebound_optimizer(actual_evidence, attack):
    launch, envelope = actual_evidence
    evidence = envelope.optimizer_evidence
    if attack == "stripped":
        altered = replace(envelope, optimizer_evidence=None)
    else:
        evidence = evidence.model_copy(
            update={"decision_sha256": "0" * 64}
            if attack == "decision"
            else {
                "optimiser_result": evidence.optimiser_result.model_copy(
                    update={"result_sha256": "0" * 64}
                )
            }
        )
        altered = replace(envelope, optimizer_evidence=evidence)
        if attack in {"resealed_tamper", "decision"}:
            altered = replace(
                altered,
                authentication_sha256=current._result_authentication(
                    launch, altered.result, altered.presentation_sha256, evidence
                ),
            )
    with pytest.raises(AuthorizationError, match="WORKER_RESULT_BINDING_INVALID"):
        current.validate_current_result(altered, launch)


def test_complete_optimizer_round_trip_and_missing_normal_evidence_refusal(
    actual_evidence, tmp_path
):
    _, envelope = actual_evidence
    result, evidence = envelope.result, envelope.optimizer_evidence
    view = desk_view(
        result,
        job_id="owned-optimizer",
        mode="SYNTHETIC_CURRENT_MODE",
        generated_at=DEMO_TIME,
        expires_at=DEMO_TIME + timedelta(minutes=15),
    )
    snapshot = AnalysisSnapshot(
        run_id=view.job_id,
        provenance_class="OWNED_SYNTHETIC",
        permission_origin="OWNED_FIXTURE",
        implementation_sha="a" * 40,
        policy_sha256="b" * 64,
        wheel_sha256="c" * 64,
        recorded_at=DEMO_TIME,
        view=view,
        presentation=result.presentation,
        optimizer_evidence=evidence,
    )
    store = AnalysisStore(tmp_path / "derived" / "optimizer.sqlite")
    store.initialize()
    digest = store.stage(snapshot)
    store.confirm(snapshot.run_id, digest, "d" * 64, at=DEMO_TIME)
    restored = AnalysisSnapshot.model_validate_json(store.export_json())
    assert restored == snapshot
    assert restored.optimizer_evidence.optimiser_result == evidence.optimiser_result
    rows = store.query("SELECT optimizer_sha256,derived_json FROM optimizer_evidence")
    assert rows[0]["optimizer_sha256"] == evidence.optimiser_result.result_sha256
    assert rows[0]["derived_json"]
    missing = snapshot.model_dump()
    missing.update(provenance_class="NORMAL_STANDING", optimizer_evidence=None)
    with pytest.raises(ValueError, match="ANALYSIS_OPTIMIZER_EVIDENCE_REQUIRED"):
        AnalysisSnapshot.model_validate(missing)
