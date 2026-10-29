"""Narrow new injection seam preserves legacy defaults without source access."""

from datetime import UTC, datetime, timedelta

import pytest

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.models import RightsProfileStatus
from dmf_pulse.ingestion.odds.config import load_rights_profiles
from dmf_pulse.ingestion.odds.credentials import EnvironmentOddsCredentialProvider
from dmf_pulse.ingestion.odds.models import QuotaSource, QuotaState
from dmf_pulse.ingestion.odds.transient import CurrentOddsTransientService

pytestmark = pytest.mark.unit
NOW = datetime(2026, 10, 29, 12, tzinfo=UTC)


def _quota(remaining=2):
    return QuotaState(
        remaining=remaining,
        used=2,
        last_cost=2,
        observed_at=NOW,
        source=QuotaSource.SYNTHETIC_FIXTURE,
    )


@pytest.mark.parametrize(
    "quota,code", [(None, "QUOTA_EVIDENCE_REQUIRED"), (_quota(1), "QUOTA_EXHAUSTED")]
)
def test_known_quota_refusal_precedes_credential_and_factory(quota, code):
    class Credentials(EnvironmentOddsCredentialProvider):
        def _configured(self):
            raise AssertionError("credential lookup must follow quota preflight")

    def factory(*args, **kwargs):
        raise AssertionError("client factory must follow quota preflight")

    service = CurrentOddsTransientService(
        credential_provider=Credentials(environment={}),
        client_factory=factory,
        quota=quota,
        require_known_quota=True,
    )
    with pytest.raises(IngestionError) as caught:
        service.acquire(information_cutoff=NOW, commence_to=NOW + timedelta(days=1))
    assert caught.value.code == code


def test_injected_denied_profile_precedes_credential_lookup():
    profile = load_rights_profiles()["the_odds_api_private_analytics_v1"].model_copy(
        update={"status": RightsProfileStatus.BLOCKED}
    )

    class Credentials(EnvironmentOddsCredentialProvider):
        def _configured(self):
            raise AssertionError("credential lookup must follow rights preflight")

    service = CurrentOddsTransientService(
        credential_provider=Credentials(environment={}),
        rights_profile=profile,
        quota=_quota(),
        require_known_quota=True,
        clock=lambda: NOW,
    )
    with pytest.raises(IngestionError) as caught:
        service.acquire(information_cutoff=NOW, commence_to=NOW + timedelta(days=1))
    assert caught.value.code == "RIGHTS_BLOCKED"


def test_single_attempt_and_known_quota_are_forwarded_to_existing_client():
    seen = {}
    profile = load_rights_profiles()["the_odds_api_private_analytics_v1"]

    class Client:
        def __init__(self, selected_profile, **kwargs):
            seen["profile"] = selected_profile
            seen["construction"] = kwargs

        def fetch(self, **kwargs):
            seen["fetch"] = kwargs
            raise IngestionError("SOURCE_UNAVAILABLE", "owned injected source failed")

    service = CurrentOddsTransientService(
        credential_provider=EnvironmentOddsCredentialProvider(
            environment={"THE_ODDS_API_KEY": "placeholder"}
        ),
        client_factory=Client,
        rights_profile=profile,
        quota=_quota(),
        maximum_attempts=1,
        require_known_quota=True,
        clock=lambda: NOW,
    )
    with pytest.raises(IngestionError, match="owned injected source failed"):
        service.acquire(information_cutoff=NOW, commence_to=NOW + timedelta(days=1))
    assert seen["profile"] == profile
    assert seen["construction"]["maximum_attempts"] == 1
    assert seen["fetch"]["quota"] == _quota()


def test_legacy_defaults_preserve_exact_existing_client_and_fetch_arguments():
    seen = {}
    credentials = EnvironmentOddsCredentialProvider(environment={"THE_ODDS_API_KEY": "placeholder"})

    def clock():
        return NOW

    class Client:
        def __init__(self, selected_profile, **kwargs):
            seen["profile"] = selected_profile
            seen["construction"] = kwargs

        def fetch(self, **kwargs):
            seen["fetch"] = kwargs
            raise IngestionError("SOURCE_UNAVAILABLE", "owned default compatibility sentinel")

    service = CurrentOddsTransientService(
        credential_provider=credentials, client_factory=Client, clock=clock
    )
    with pytest.raises(IngestionError, match="owned default compatibility sentinel"):
        service.acquire(information_cutoff=NOW, commence_to=NOW + timedelta(days=1))
    assert seen["profile"] == load_rights_profiles()["the_odds_api_private_analytics_v1"]
    assert seen["construction"] == {"credential_provider": credentials, "clock": clock}
    assert seen["fetch"] == {"commence_from": NOW, "commence_to": NOW + timedelta(days=1)}


@pytest.mark.parametrize("attempts", [0, 2, True])
def test_new_seam_never_expands_retry_policy(attempts):
    with pytest.raises(ValueError, match="single-attempt"):
        CurrentOddsTransientService(maximum_attempts=attempts)
