"""Explicit reviewed score source reaches the existing one-command request, with owned inputs."""

from datetime import timedelta

import pytest

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.direct import DirectFplClient, DirectFplCredentialProvider
from dmf_pulse.ingestion.openfootball.service import PRIVATE_OPERATOR_PROFILE_ID
from dmf_pulse.private_v1.errors import PrivateV1Error
from dmf_pulse.private_v1.one_command import OneCommandRequest, PrivateV1OneCommandService
from tests.unit.private_v1.test_one_command import (
    RUN_AT,
    _DirectTransport,
    _odds_input,
    _OddsService,
    _provider_sources,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "selected", ["openfootball_football_json_score_prior_v1", PRIVATE_OPERATOR_PROFILE_ID]
)
def test_one_command_builds_exact_selected_score_profile_request(repository_root, selected):
    bodies, _ = _provider_sources(repository_root)
    direct = _DirectTransport(bodies)
    captured = []

    def direct_factory(attestation):
        return DirectFplClient(
            attestation,
            transport=direct,
            credential_provider=DirectFplCredentialProvider(
                {"DMF_FPL_BEARER_TOKEN": "placeholder"}
            ),
            pace_seconds=0,
            sleeper=lambda _: None,
        )

    class CaptureScore:
        def build(self, request):
            captured.append(request)
            # Stop before modeling; this test proves routing and grants no source qualification.
            raise IngestionError("RIGHTS_BLOCKED", "owned stop before model")

    service = PrivateV1OneCommandService(
        direct_client_factory=direct_factory,
        odds_service_factory=lambda _: _OddsService(_odds_input(repository_root)),
        score_service_factory=lambda _: CaptureScore(),
        score_prior_rights_profile_id=selected,
        clock=lambda: RUN_AT,
    )
    with pytest.raises(PrivateV1Error, match="RIGHTS_BLOCKED"):
        service.run(
            OneCommandRequest(
                entry_id=42,
                code_sha="a" * 40,
                run_at=RUN_AT,
                operator_approved_at=RUN_AT - timedelta(minutes=1),
            )
        )
    assert len(captured) == 1
    assert captured[0].rights_profile_id == selected
    assert captured[0].information_cutoff == RUN_AT


def test_arbitrary_score_profile_rejected_before_acquisition():
    def forbidden(_):
        pytest.fail("invalid source reached acquisition")

    with pytest.raises(ValueError, match="unsupported score-prior source profile"):
        PrivateV1OneCommandService(
            direct_client_factory=forbidden,
            score_prior_rights_profile_id="unreviewed-generic-id",
        )
