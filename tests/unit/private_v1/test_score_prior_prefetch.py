"""R1 regression for cutoff-safe score-prior acquisition before long computation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import NoReturn

import pytest

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.direct import (
    DirectFplClient,
    DirectFplCredentialProvider,
    DirectFplRunAttestation,
    DirectHttpRequest,
    DirectHttpResponse,
)
from dmf_pulse.ingestion.openfootball.config import load_rights_profiles as load_score_rights
from dmf_pulse.ingestion.openfootball.service import CurrentScorePriorService
from dmf_pulse.markets.current import CurrentMarketConstraintError
from dmf_pulse.private_v1 import one_command as one_command_module
from dmf_pulse.private_v1.errors import PrivateV1Error
from dmf_pulse.private_v1.one_command import OneCommandRequest, PrivateV1OneCommandService
from tests.unit.ingestion.openfootball.conftest import FakeTransport as ScoreTransport
from tests.unit.ingestion.openfootball.conftest import synthetic_snapshot
from tests.unit.private_v1.test_one_command import (
    RUN_AT,
    _DirectTransport,
    _odds_input,
    _OddsService,
    _provider_sources,
)

pytestmark = pytest.mark.unit

_APPROVED_AT = RUN_AT - timedelta(minutes=5)
_ACQUIRED_AT = RUN_AT


def _raise(error: Exception) -> NoReturn:
    raise error


@dataclass
class _MutableClock:
    value: datetime

    def __call__(self) -> datetime:
        return self.value


class _RecordingDirectTransport(_DirectTransport):
    def __init__(self, bodies: tuple[bytes, ...], *, clock: _MutableClock, events: list) -> None:
        super().__init__(bodies)
        self._clock = clock
        self._events = events

    def send(self, request: DirectHttpRequest) -> DirectHttpResponse:
        self._events.append(("FPL", self._clock()))
        return super().send(request)


class _RecordingOddsService(_OddsService):
    def __init__(self, value: object, *, clock: _MutableClock, events: list) -> None:
        super().__init__(value)
        self._clock = clock
        self._events = events

    def acquire(self, *, information_cutoff: object, commence_to: object) -> object:
        self._events.append(("ODDS", self._clock()))
        return super().acquire(
            information_cutoff=information_cutoff,
            commence_to=commence_to,
        )


class _RecordingScoreTransport(ScoreTransport):
    def __init__(self, bodies: dict[str, bytes], *, clock: _MutableClock, events: list) -> None:
        super().__init__(bodies)
        self._clock = clock
        self._events = events

    def send(self, request):
        self._events.append(("OPENFOOTBALL", self._clock()))
        return super().send(request)


def test_three_gameweek_prefetch_survives_compute_beyond_five_minute_cutoff(
    monkeypatch: pytest.MonkeyPatch,
    repository_root: Path,
) -> None:
    real_stage7 = one_command_module.build_automatic_rolling_model_minutes
    cached_stage7: list[object] = []

    def run_case(compute_duration: timedelta):
        clock = _MutableClock(_ACQUIRED_AT)
        events: list[tuple[str, datetime]] = []
        direct_bodies, _ = _provider_sources(repository_root)
        direct_transport = _RecordingDirectTransport(direct_bodies, clock=clock, events=events)
        odds_service = _RecordingOddsService(
            _odds_input(repository_root), clock=clock, events=events
        )
        score_config, score_bodies = synthetic_snapshot()
        score_transport = _RecordingScoreTransport(score_bodies, clock=clock, events=events)
        source_results: list[object] = []
        score_factory_calls: list[None] = []
        rolling_inputs: list[object] = []
        marker = "repository-owned-placeholder"

        def direct_factory(attestation: DirectFplRunAttestation) -> DirectFplClient:
            return DirectFplClient(
                attestation,
                transport=direct_transport,
                credential_provider=DirectFplCredentialProvider({"DMF_FPL_BEARER_TOKEN": marker}),
                sleeper=lambda _: None,
                pace_seconds=0,
            )

        def score_factory(source_clock):
            score_factory_calls.append(None)
            service = CurrentScorePriorService(
                provider_config=score_config,
                rights_profiles=load_score_rights(),
                transport=score_transport,
                clock=source_clock,
                provider_config_identity="a" * 64,
                rights_config_identity="b" * 64,
            )

            class CapturingScoreService:
                def build(self, request):
                    result = service.build(request)
                    source_results.append(result)
                    return result

            return CapturingScoreService()

        def timed_stage7(*args, **kwargs):
            assert len(score_factory_calls) == 1
            assert len(score_transport.requests) == 4
            assert len(source_results) == 1
            events.append(("STAGE7_STARTED", clock()))
            if not cached_stage7:
                cached_stage7.append(real_stage7(*args, **kwargs))
            clock.value += compute_duration
            events.append(("STAGE7_COMPLETED", clock()))
            return cached_stage7[0]

        class CapturingRollingService:
            def run(self, value, *, progress):
                del progress
                rolling_inputs.append(value)
                return SimpleNamespace(
                    decision=SimpleNamespace(semantic_sha256=value.semantic_sha256),
                    stage_timings=(),
                )

        monkeypatch.setattr(
            one_command_module,
            "build_automatic_rolling_model_minutes",
            timed_stage7,
        )
        monkeypatch.setattr(
            one_command_module,
            "_display_rolling_report",
            lambda decision, snapshot, player_map: "R1 SYNTHETIC REPORT",
        )
        result = PrivateV1OneCommandService(
            direct_client_factory=direct_factory,
            odds_service_factory=lambda source_clock: odds_service,
            score_service_factory=score_factory,
            rolling_recommendation_service=CapturingRollingService(),  # type: ignore[arg-type]
            clock=clock,
        ).run(
            OneCommandRequest(
                entry_id=42,
                code_sha="c" * 40,
                run_at=RUN_AT,
                operator_approved_at=_APPROVED_AT,
                scenario_count=8,
                root_seed=44,
                horizon_gameweeks=3,
            )
        )

        assert result.status == "REAL_PRIVATE_TRANSIENT_RECOMMENDATION"
        assert result.report == "R1 SYNTHETIC REPORT"
        assert len(score_factory_calls) == 1
        assert len(score_transport.requests) == 4
        assert len(source_results) == 1
        source = source_results[0]
        assert source.provenance.request_started_at == _ACQUIRED_AT
        assert (
            tuple(item.received_at for item in source.provenance.resources) == (_ACQUIRED_AT,) * 4
        )
        assert source.provenance.validation_completed_at == _ACQUIRED_AT
        assert source.provenance.usable_at == _ACQUIRED_AT
        assert source.provenance.information_cutoff == RUN_AT
        assert source.provenance.transport_call_count == 4
        assert clock() > RUN_AT + timedelta(minutes=5)
        assert len(rolling_inputs) == 1
        execution = rolling_inputs[0]
        priors = (
            *execution.current_execution.score_priors,
            *(
                fixture.score_prior
                for gameweek in execution.future_gameweeks
                for fixture in gameweek.fixtures
            ),
        )
        assert len(priors) == 9
        assert {item.current_bundle.source_result_semantic_sha256 for item in priors} == {
            source.semantic_sha256
        }
        assert all(item.current_bundle.source_result == source for item in priors)
        assert all(
            item.current_bundle.source_usable_at <= item.current_bundle.as_of for item in priors
        )
        stage7_index = next(
            index for index, event in enumerate(events) if event[0] == "STAGE7_STARTED"
        )
        provider_events = tuple(
            (index, event)
            for index, event in enumerate(events)
            if event[0] in {"FPL", "ODDS", "OPENFOOTBALL"}
        )
        assert provider_events
        assert all(index < stage7_index for index, _ in provider_events)
        assert all(event[1] <= RUN_AT for _, event in provider_events)
        assert events[-1][0] == "STAGE7_COMPLETED"
        return execution.semantic_sha256

    seven_minute_compute = run_case(timedelta(minutes=7))
    nine_minute_compute = run_case(timedelta(minutes=9))

    assert seven_minute_compute == nine_minute_compute


@pytest.mark.parametrize(
    ("source_error", "expected_code"),
    (
        (PrivateV1Error("SOURCE_FAILURE", "safe failure"), "SOURCE_FAILURE"),
        (IngestionError("POST_CUTOFF", "safe failure"), "POST_CUTOFF"),
        (
            CurrentMarketConstraintError("CURRENT_MARKET_SOURCE_INVALID"),
            "CURRENT_MARKET_SOURCE_INVALID",
        ),
        (ValueError("private source detail"), "ONE_COMMAND_INPUT_INVALID"),
    ),
)
def test_pre_acquisition_failures_remain_typed_and_fail_closed(
    source_error: Exception,
    expected_code: str,
) -> None:
    service = PrivateV1OneCommandService(
        direct_client_factory=lambda _: _raise(source_error),
        clock=lambda: RUN_AT,
    )

    with pytest.raises(PrivateV1Error) as captured:
        service.run(
            OneCommandRequest(
                entry_id=42,
                code_sha="c" * 40,
                run_at=RUN_AT,
                operator_approved_at=_APPROVED_AT,
                scenario_count=8,
                root_seed=44,
                horizon_gameweeks=3,
            )
        )

    assert captured.value.code == expected_code
    if expected_code == "ONE_COMMAND_INPUT_INVALID":
        assert "private source detail" not in str(captured.value)
