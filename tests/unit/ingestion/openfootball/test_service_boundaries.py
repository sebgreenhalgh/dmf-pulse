from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.models import CapabilityValue, RightsCapability, RightsProfile
from dmf_pulse.ingestion.openfootball.client import (
    OpenFootballHttpRequest,
    OpenFootballHttpResponse,
)
from dmf_pulse.ingestion.openfootball.config import (
    APPROVED_PROFILE_ID,
    OpenFootballProviderConfig,
    load_rights_profiles,
)
from dmf_pulse.ingestion.openfootball.service import (
    CurrentScorePriorBuildRequest,
    CurrentScorePriorProvenance,
    CurrentScorePriorService,
)

from .conftest import FakeTransport, ticking_clock

_START = datetime(2026, 8, 30, 9, 0, tzinfo=UTC)
_CUTOFF = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)


def _service(
    config: OpenFootballProviderConfig,
    transport: object,
    *,
    profiles: Mapping[str, RightsProfile] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> CurrentScorePriorService:
    return CurrentScorePriorService(
        provider_config=config,
        rights_profiles=profiles or load_rights_profiles(),
        transport=transport,  # type: ignore[arg-type]
        clock=clock or ticking_clock(_START),
        provider_config_identity="c" * 64,
        rights_config_identity="d" * 64,
    )


def _request(
    cutoff: datetime = _CUTOFF, profile_id: str = APPROVED_PROFILE_ID
) -> CurrentScorePriorBuildRequest:
    return CurrentScorePriorBuildRequest(
        information_cutoff=cutoff,
        rights_profile_id=profile_id,
    )


@pytest.mark.security
def test_unknown_profile_is_zero_call_with_default_packaged_configuration() -> None:
    service = CurrentScorePriorService(transport=FakeTransport({}))

    with pytest.raises(IngestionError) as caught:
        service.build(_request(datetime(2100, 1, 1, tzinfo=UTC), "unknown"))

    assert caught.value.code == "RIGHTS_BLOCKED"
    assert caught.value.details["transport_call_count"] == 0


@pytest.mark.security
def test_denied_required_capability_is_zero_call(
    approved_snapshot: tuple[OpenFootballProviderConfig, dict[str, bytes]],
) -> None:
    config, bodies = approved_snapshot
    approved = load_rights_profiles()[APPROVED_PROFILE_ID]
    capabilities = dict(approved.capabilities)
    capabilities[RightsCapability.AUTOMATED_ACCESS] = CapabilityValue.DENY
    blocked = approved.model_copy(update={"capabilities": capabilities})
    transport = FakeTransport(bodies)

    with pytest.raises(IngestionError) as caught:
        _service(config, transport, profiles={APPROVED_PROFILE_ID: blocked}).build(_request())

    assert caught.value.code == "RIGHTS_BLOCKED"
    assert caught.value.details["transport_call_count"] == 0
    assert transport.requests == []


@pytest.mark.security
def test_naive_runtime_clock_is_rejected_before_transport(
    approved_snapshot: tuple[OpenFootballProviderConfig, dict[str, bytes]],
) -> None:
    config, bodies = approved_snapshot
    transport = FakeTransport(bodies)

    with pytest.raises(IngestionError) as caught:
        _service(config, transport, clock=lambda: datetime(2026, 8, 30, 9, 0)).build(_request())

    assert caught.value.code == "INTERNAL_INVARIANT"
    assert transport.requests == []


class _EnvelopeTransport(FakeTransport):
    def __init__(
        self,
        bodies: Mapping[str, bytes],
        *,
        status: int = 200,
        content_type: str = "application/json",
        oversized: bool = False,
    ) -> None:
        super().__init__(bodies)
        self._status = status
        self._content_type = content_type
        self._oversized = oversized

    def send(self, request: OpenFootballHttpRequest) -> OpenFootballHttpResponse:
        normal = super().send(request)
        body = normal.body
        if self._oversized:
            body = b"x" * (request.max_response_bytes + 1)
        return OpenFootballHttpResponse(
            status_code=self._status,
            content_type=self._content_type,
            headers={},
            body=body,
        )


@pytest.mark.parametrize(
    ("transport_kwargs", "code"),
    [
        ({"status": 500}, "SOURCE_UNAVAILABLE"),
        ({"content_type": "text/html"}, "SOURCE_UNAVAILABLE"),
        ({"oversized": True}, "PAYLOAD_TOO_LARGE"),
    ],
)
def test_service_rechecks_transport_response_envelope(
    approved_snapshot: tuple[OpenFootballProviderConfig, dict[str, bytes]],
    transport_kwargs: dict[str, object],
    code: str,
) -> None:
    config, bodies = approved_snapshot
    transport = _EnvelopeTransport(bodies, **transport_kwargs)  # type: ignore[arg-type]

    with pytest.raises(IngestionError) as caught:
        _service(config, transport).build(_request())

    assert caught.value.code == code
    assert caught.value.details["transport_call_count"] == 1


def test_resource_receipt_after_cutoff_is_rejected(
    approved_snapshot: tuple[OpenFootballProviderConfig, dict[str, bytes]],
) -> None:
    config, bodies = approved_snapshot
    values = iter((_START, _CUTOFF + timedelta(seconds=1)))
    transport = FakeTransport(bodies)

    with pytest.raises(IngestionError) as caught:
        _service(config, transport, clock=lambda: next(values)).build(_request())

    assert caught.value.code == "POST_CUTOFF"
    assert caught.value.details["transport_call_count"] == 1


def test_final_usable_time_after_cutoff_is_rejected(
    approved_snapshot: tuple[OpenFootballProviderConfig, dict[str, bytes]],
) -> None:
    config, bodies = approved_snapshot
    values = iter(
        (
            _START,
            _START + timedelta(seconds=1),
            _START + timedelta(seconds=2),
            _START + timedelta(seconds=3),
            _START + timedelta(seconds=4),
            _START + timedelta(seconds=5),
            _CUTOFF + timedelta(seconds=1),
        )
    )

    with pytest.raises(IngestionError) as caught:
        _service(config, FakeTransport(bodies), clock=lambda: next(values)).build(_request())

    assert caught.value.code == "POST_CUTOFF"
    assert caught.value.details["transport_call_count"] == 4


def test_nonmonotonic_receipt_lineage_is_rejected(
    approved_snapshot: tuple[OpenFootballProviderConfig, dict[str, bytes]],
) -> None:
    config, bodies = approved_snapshot
    values = iter(
        (
            _START,
            _START - timedelta(seconds=1),
            _START + timedelta(seconds=2),
            _START + timedelta(seconds=3),
            _START + timedelta(seconds=4),
            _START + timedelta(seconds=5),
            _START + timedelta(seconds=6),
        )
    )

    with pytest.raises(IngestionError) as caught:
        _service(config, FakeTransport(bodies), clock=lambda: next(values)).build(_request())

    assert caught.value.code == "LIFECYCLE_INVARIANT"
    assert caught.value.details["transport_call_count"] == 4


def test_aggregate_rate_mismatch_is_quality_blocked(
    approved_snapshot: tuple[OpenFootballProviderConfig, dict[str, bytes]],
) -> None:
    config, bodies = approved_snapshot
    drifted = config.model_copy(update={"expected_home_goal_rate": config.expected_away_goal_rate})

    with pytest.raises(IngestionError) as caught:
        _service(drifted, FakeTransport(bodies)).build(_request())

    assert caught.value.code == "QUALITY_BLOCKED"
    assert caught.value.details["transport_call_count"] == 4


def test_provenance_rejects_approval_commit_and_resource_order_drift(
    approved_snapshot: tuple[OpenFootballProviderConfig, dict[str, bytes]],
) -> None:
    config, bodies = approved_snapshot
    result = _service(config, FakeTransport(bodies)).build(_request())
    raw = result.provenance.model_dump()

    for update in (
        {"approved_at": raw["request_started_at"] + timedelta(seconds=1)},
        {"source_commit_timestamp": raw["resources"][0]["received_at"] + timedelta(seconds=1)},
        {
            "resources": (
                {**raw["resources"][0], "resource_kind": "SEASON"},
                *raw["resources"][1:],
            )
        },
    ):
        with pytest.raises(ValidationError):
            CurrentScorePriorProvenance.model_validate({**raw, **update})
