"""Numerical parity and one-capture handoff through unchanged accepted kernels."""

from datetime import timedelta
from pathlib import Path

import pytest

from dmf_pulse.ingestion.fpl.direct import (
    DirectFplClient,
    DirectFplCredentialProvider,
    DirectFplRunAttestation,
)
from dmf_pulse.ingestion.fpl.direct_payloads import acquire_direct_fpl_snapshot
from dmf_pulse.ingestion.openfootball.config import load_rights_profiles
from dmf_pulse.ingestion.openfootball.service import (
    CurrentScorePriorBuildRequest,
    CurrentScorePriorService,
)
from dmf_pulse.operation.diagnostic_pipeline import (
    assemble_diagnostic_execution,
    inherited_monte_carlo_policy,
    prepare_diagnostic_fpl,
    run_diagnostic_kernel,
)
from dmf_pulse.operation.models import OperationError
from dmf_pulse.private_v1.models import PrivateV1ExecutionInput
from dmf_pulse.private_v1.one_command import OneCommandRequest, PrivateV1OneCommandService
from dmf_pulse.private_v1.progress import ProgressSink
from dmf_pulse.private_v1.service import PrivateV1RecommendationService, PrivateV1RunResult
from tests.unit.ingestion.openfootball.conftest import FakeTransport as ScoreTransport
from tests.unit.ingestion.openfootball.conftest import synthetic_snapshot
from tests.unit.private_v1.test_one_command import (
    RUN_AT,
    _DirectTransport,
    _odds_input,
    _OddsService,
    _provider_sources,
)


class CaptureAcceptedInput(PrivateV1RecommendationService):
    execution: PrivateV1ExecutionInput | None = None

    def run(
        self, value: PrivateV1ExecutionInput, *, progress: ProgressSink | None = None
    ) -> PrivateV1RunResult:
        self.execution = value
        return super().run(value, progress=progress)


def test_same_typed_snapshot_matches_existing_one_command_numerically(
    repository_root: Path,
) -> None:
    bodies, _ = _provider_sources(repository_root)
    reference_transport = _DirectTransport(bodies)
    transport = _DirectTransport(bodies)
    odds = _odds_input(repository_root)
    config, score_bodies = synthetic_snapshot()

    def client(attestation: DirectFplRunAttestation, selected: _DirectTransport) -> DirectFplClient:
        return DirectFplClient(
            attestation,
            transport=selected,
            credential_provider=DirectFplCredentialProvider(
                {"DMF_FPL_BEARER_TOKEN": "owned-synthetic-placeholder"}
            ),
            clock=lambda: RUN_AT,
            sleeper=lambda _: None,
            pace_seconds=0,
        )

    def score() -> CurrentScorePriorService:
        return CurrentScorePriorService(
            provider_config=config,
            rights_profiles=load_rights_profiles(),
            transport=ScoreTransport(score_bodies),
            clock=lambda: RUN_AT,
            provider_config_identity="a" * 64,
            rights_config_identity="b" * 64,
        )

    request = OneCommandRequest(
        entry_id=42,
        code_sha="a" * 40,
        run_at=RUN_AT,
        operator_approved_at=RUN_AT - timedelta(minutes=1),
        scenario_count=32,
        root_seed=42,
    )
    capture = CaptureAcceptedInput()
    reference = PrivateV1OneCommandService(
        direct_client_factory=lambda attestation: client(attestation, reference_transport),
        odds_service_factory=lambda clock: _OddsService(odds),  # type: ignore[arg-type,return-value]
        score_service_factory=lambda clock: score(),
        recommendation_service=capture,
        clock=lambda: RUN_AT,
    ).run(request)
    snapshot = acquire_direct_fpl_snapshot(
        client(DirectFplRunAttestation(attested_at=request.operator_approved_at), transport),
        entry_id=42,
        captured_at=RUN_AT,
        clock=lambda: RUN_AT,
    )
    prepared = prepare_diagnostic_fpl(
        snapshot, approved_at=RUN_AT - timedelta(minutes=1), observed_at=RUN_AT
    )
    prior = score().build(
        CurrentScorePriorBuildRequest(
            information_cutoff=RUN_AT, rights_profile_id="openfootball_football_json_score_prior_v1"
        )
    )
    execution = assemble_diagnostic_execution(prepared, odds, prior, request, resolved_at=RUN_AT)
    assert capture.execution is not None
    assert execution.model_dump(mode="json") == capture.execution.model_dump(mode="json")
    controlled = run_diagnostic_kernel(execution, controlled=True)
    assert controlled.result.decision.model_dump(mode="json") == reference.decision.model_dump(
        mode="json"
    )
    assert len(reference_transport.requests) == len(transport.requests) == 8
    assert not transport.bodies
    # Reassembly/controlled calculation uses typed objects, never the transport again.
    repeated = assemble_diagnostic_execution(prepared, odds, prior, request, resolved_at=RUN_AT)
    assert repeated.semantic_sha256 == execution.semantic_sha256 and len(transport.requests) == 8
    proof = controlled.controlled_proof()
    assert proof["classification"] == "REAL_FPL_CONTROLLED_MARKET_ENGINEERING"
    assert proof["real_recommendation_publication"] is False
    assert proof["paid_provider_gets_in_controlled_computation"] == 0
    with pytest.raises(OperationError, match="PROVENANCE_CLASS_MISMATCH"):
        run_diagnostic_kernel(execution, controlled=False)


def test_inherited_policy_uses_accepted_literal_source_configuration() -> None:
    policy = inherited_monte_carlo_policy()
    assert policy.minimum_effective_scenarios == 1.0
    assert policy.maximum_mean_mcse == 100.0
    assert policy.quantiles == (0.1, 0.5, 0.9)
