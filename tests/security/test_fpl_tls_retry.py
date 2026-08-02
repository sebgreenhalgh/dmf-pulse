"""Mandatory FPL-004 TLS remediation regression proof."""

from __future__ import annotations

import ssl
import urllib.error
import urllib.request

import pytest

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.client import FplClient, UrllibTransport
from dmf_pulse.ingestion.fpl.parser import FplResource
from dmf_pulse.ingestion.models import CapabilityValue, RightsCapability
from dmf_pulse.ingestion.rights import load_rights_profiles

pytestmark = pytest.mark.security


class _FailingOpener:
    def __init__(self, failure: BaseException) -> None:
        self.failure = failure
        self.calls = 0

    def open(self, *_args: object, **_kwargs: object) -> object:
        self.calls += 1
        raise self.failure


@pytest.mark.parametrize(
    "reason",
    (
        ssl.SSLError("synthetic TLS failure"),
        ssl.SSLCertVerificationError("synthetic certificate failure"),
        ssl.CertificateError("synthetic hostname failure"),
    ),
)
def test_urlerror_wrapped_tls_and_certificate_failures_are_nonretryable(
    monkeypatch: pytest.MonkeyPatch,
    reason: BaseException,
) -> None:
    profile = load_rights_profiles()["synthetic_test_v1"]
    capabilities = dict(profile.capabilities)
    capabilities[RightsCapability.AUTOMATED_ACCESS] = CapabilityValue.ALLOW
    automated = profile.model_copy(update={"capabilities": capabilities})
    opener = _FailingOpener(urllib.error.URLError(reason))
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_handlers: opener)

    with pytest.raises(IngestionError) as raised:
        FplClient(automated, UrllibTransport).fetch(FplResource.FIXTURES)

    assert raised.value.code == "TLS_ERROR"
    assert raised.value.retryable is False
    assert opener.calls == 1
    assert "synthetic" not in raised.value.message
