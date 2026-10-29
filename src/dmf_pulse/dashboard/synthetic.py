"""Executable offline demonstration through the actual private application chain."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from typing import Literal

from dmf_pulse.ingestion.fpl.direct import (
    DirectFplClient,
    DirectFplCredentialProvider,
    DirectFplRunAttestation,
    DirectHttpRequest,
    DirectHttpResponse,
)
from dmf_pulse.ingestion.odds.current import OddsProviderCurrentInput
from dmf_pulse.ingestion.odds.transient import CurrentOddsTransientService
from dmf_pulse.ingestion.openfootball.client import (
    OpenFootballHttpRequest,
    OpenFootballHttpResponse,
)
from dmf_pulse.ingestion.openfootball.config import OpenFootballProviderConfig, load_rights_profiles
from dmf_pulse.ingestion.openfootball.service import CurrentScorePriorService
from dmf_pulse.private_v1.one_command import (
    OneCommandRequest,
    OneCommandResult,
    PrivateV1OneCommandService,
)
from dmf_pulse.private_v1.progress import ProgressSink

DEMO_TIME = datetime(2026, 9, 1, 12, tzinfo=UTC)


def demo_inputs() -> dict[str, bytes]:
    root = files("dmf_pulse.dashboard.resources").joinpath("demo")
    manifest = json.loads(root.joinpath("manifest.json").read_text(encoding="utf-8"))
    result = {}
    for name, expected in manifest["files"].items():
        if "/" in name or "\\" in name or ".." in name:
            raise ValueError("synthetic resource path invalid")
        body = root.joinpath(name).read_bytes()
        if hashlib.sha256(body).hexdigest() != expected:
            raise ValueError("synthetic resource identity mismatch")
        result[name] = body
    return result


class _FplTransport:
    def __init__(self, bodies: list[bytes]) -> None:
        self._bodies = bodies

    def send(self, request: DirectHttpRequest) -> DirectHttpResponse:
        del request
        if not self._bodies:
            raise ValueError("synthetic request budget exceeded")
        return DirectHttpResponse(200, "application/json", self._bodies.pop(0))


class _OddsService(CurrentOddsTransientService):
    def __init__(self, body: bytes) -> None:
        self._value = OddsProviderCurrentInput.model_validate_json(body)
        self._used = False

    def acquire(
        self,
        *,
        information_cutoff: datetime,
        commence_to: datetime,
        required_h2h_commence_times: tuple[datetime, ...] | None = None,
    ) -> OddsProviderCurrentInput:
        del commence_to, required_h2h_commence_times
        if self._used or information_cutoff != DEMO_TIME:
            raise ValueError("synthetic odds request invalid")
        self._used = True
        return self._value


class _ScoreTransport:
    transport_id = "accel002_repository_owned_synthetic"

    def __init__(self, bodies: dict[str, bytes]) -> None:
        self._bodies = bodies

    def send(self, request: OpenFootballHttpRequest) -> OpenFootballHttpResponse:
        path = "/".join(request.path.lstrip("/").split("/")[3:])
        content_type = "text/plain" if path == "LICENSE.md" else "application/json"
        return OpenFootballHttpResponse(
            status_code=200, content_type=content_type, headers={}, body=self._bodies[path]
        )


def run_synthetic_recommendation(
    horizon: Literal[1, 3], progress: ProgressSink
) -> OneCommandResult:
    """No credentials/environment/network, no canned decision; run real Stage 7 through 11."""
    root = files("dmf_pulse.dashboard.resources").joinpath("demo")
    manifest = json.loads(root.joinpath("manifest.json").read_text(encoding="utf-8"))
    inputs = demo_inputs()
    direct = _FplTransport([inputs[name] for name in manifest["fpl"]])
    odds = _OddsService(inputs["odds.json"])
    score_config = OpenFootballProviderConfig.model_validate_json(inputs["score-config.json"])
    score_transport = _ScoreTransport(
        {path: inputs[name] for path, name in manifest["score_paths"].items()}
    )

    def direct_factory(attestation: DirectFplRunAttestation) -> DirectFplClient:
        return DirectFplClient(
            attestation,
            transport=direct,
            credential_provider=DirectFplCredentialProvider(
                {"DMF_FPL_BEARER_TOKEN": "repository-owned-synthetic-only"}
            ),
            sleeper=lambda _: None,
            pace_seconds=0,
        )

    def score_factory(clock: Callable[[], datetime]) -> CurrentScorePriorService:
        return CurrentScorePriorService(
            provider_config=score_config,
            rights_profiles=load_rights_profiles(),
            transport=score_transport,
            clock=clock,
            provider_config_identity="a" * 64,
            rights_config_identity="b" * 64,
        )

    return PrivateV1OneCommandService(
        direct_client_factory=direct_factory,
        odds_service_factory=lambda _: odds,
        score_service_factory=score_factory,
        progress=progress,
        clock=lambda: DEMO_TIME,
        collect_presentation=True,
    ).run(
        OneCommandRequest(
            entry_id=42,
            code_sha="a"
            * 40,  # Synthetic request identity; native package authentication stays enabled.
            run_at=DEMO_TIME,
            operator_approved_at=DEMO_TIME - timedelta(minutes=1),
            run_id="ACCEL002_SYNTHETIC_DASHBOARD",
            scenario_count=32 if horizon == 1 else 8,
            root_seed=42 if horizon == 1 else 43,
            horizon_gameweeks=horizon,
        )
    )
