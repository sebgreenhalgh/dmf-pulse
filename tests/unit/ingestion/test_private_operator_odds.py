"""Actual client/parser with owned installed authority; no real permission or provider."""

from datetime import timedelta

import pytest

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.models import CapabilityValue, RightsCapability, RightsProfileStatus
from dmf_pulse.ingestion.odds.client import OddsClient, OddsHttpResponse
from dmf_pulse.ingestion.odds.config import effective_config_sha256, rights_config_sha256
from dmf_pulse.ingestion.odds.current import _rights_state
from dmf_pulse.ingestion.odds.private_operator import (
    PRIVATE_OPERATOR_PROFILE_ID,
    require_private_operator_input,
)
from dmf_pulse.ingestion.odds.transient import CurrentOddsTransientService
from dmf_pulse.operation import enrollment
from dmf_pulse.operation.enrollment import InstalledEnrollment
from tests.unit.ingestion.odds_private_test_support import (
    NOW,
    owned_body,
    owned_profile,
    owned_registry,
)

pytestmark = pytest.mark.unit


def acquisition(
    monkeypatch, repository_root, *, profile=None, registry=None, quota=None, **options
):
    default_registry, profile, default_quota = owned_registry(profile=profile)
    selected = default_registry if registry is None else registry
    monkeypatch.setattr(enrollment, "installed_enrollment", lambda: selected)
    counters = {"credentials": 0, "constructed": 0, "transports": 0, "parameters": None}

    class Credentials:
        def get_credential(self):
            counters["credentials"] += 1
            return "owned-placeholder-odds-key"

    class Transport:
        transport_id = "injected"

        def send(self, request, credential):
            assert credential == "owned-placeholder-odds-key"
            counters["transports"] += 1
            counters["parameters"] = request.safe_parameters
            return OddsHttpResponse(
                200,
                "application/json",
                {"x-requests-remaining": "498", "x-requests-used": "2", "x-requests-last": "2"},
                owned_body(repository_root),
            )

    def transport():
        counters["constructed"] += 1
        return Transport()

    def client(profile, **kwargs):
        return OddsClient(profile, transport_factory=transport, **kwargs)

    service = CurrentOddsTransientService(
        rights_profile=profile,
        credential_provider=Credentials(),
        client_factory=client,
        quota=default_quota if quota is None else quota,
        clock=lambda: NOW,
        **{"require_known_quota": True, "maximum_attempts": 1, **options},
    )
    return service, counters, selected, profile, default_quota


def fetch(service):
    return service.acquire(information_cutoff=NOW, commence_to=NOW + timedelta(days=20))


def test_new_purpose_reaches_actual_client_parser_with_truthful_new_lineage(
    monkeypatch, repository_root
):
    service, counters, _, profile, _ = acquisition(monkeypatch, repository_root)
    result = fetch(service)
    assert counters["credentials"] == counters["constructed"] == counters["transports"] == 1
    assert counters["parameters"][:4] == (
        ("regions", "uk"),
        ("markets", "h2h,totals"),
        ("oddsFormat", "decimal"),
        ("dateFormat", "iso"),
    )
    assert result.rights.rights_profile_id == PRIVATE_OPERATOR_PROFILE_ID
    assert result.rights == _rights_state(profile, NOW)
    assert result.rights.raw_storage_declared == result.rights.model_training_declared == "DENY"
    assert result.provenance.rights_config_sha256 != rights_config_sha256()
    assert result.provenance.effective_config_sha256 != effective_config_sha256()
    assert result.provenance.attempt_count == result.provenance.transport_call_count == 1
    assert result.quota.remaining == 498 and result.quota.provider_last_request_cost == 2
    assert require_private_operator_input(result)[0] == profile


@pytest.mark.parametrize(
    "changes",
    [
        {"status": RightsProfileStatus.DRAFT},
        {"approved_purpose": "consumed-older-purpose"},
        {"account_scope": "another-account"},
        {"geography_scope": "private UK analytical use"},
        {"terms_source": "unverified-terms"},
        {"unresolved_rights": ("unresolved-owner-claim",)},
        {"retention_seconds": None, "retention_reason": "broader unused permission"},
        {"termination_deletion_required": False},
        {"approved_at": NOW + timedelta(seconds=1)},
        {"checked_at": NOW + timedelta(seconds=1)},
        {"rights_profile_id": "the_odds_api_private_operator_recommendations_v2"},
    ],
)
def test_changed_or_unsupported_profile_refuses_before_key_and_transport(
    monkeypatch, repository_root, changes
):
    profile = owned_profile(**changes)
    service, counters, *_ = acquisition(monkeypatch, repository_root, profile=profile)
    with pytest.raises(IngestionError) as error:
        fetch(service)
    assert error.value.code == "RIGHTS_BLOCKED"
    assert counters["credentials"] == counters["constructed"] == counters["transports"] == 0


@pytest.mark.parametrize("capability", list(RightsCapability))
def test_every_capability_is_bound_before_key(monkeypatch, repository_root, capability):
    profile = owned_profile()
    capabilities = dict(profile.capabilities)
    capabilities[capability] = (
        CapabilityValue.DENY
        if capabilities[capability] is CapabilityValue.ALLOW
        else CapabilityValue.ALLOW
    )
    profile = profile.model_copy(update={"capabilities": capabilities})
    service, counters, *_ = acquisition(monkeypatch, repository_root, profile=profile)
    with pytest.raises(IngestionError) as error:
        fetch(service)
    assert error.value.code == "RIGHTS_BLOCKED" and counters["credentials"] == 0


@pytest.mark.parametrize(
    "attack", ["absent", "duplicate", "expired", "country", "approval", "quota", "stale"]
)
def test_missing_qualification_account_or_freshness_refuses_before_transport(
    monkeypatch, repository_root, attack
):
    registry, profile, quota = owned_registry()
    row = registry.qualifications[0]
    if attack == "absent":
        registry = InstalledEnrollment()
    elif attack == "duplicate":
        registry = registry.model_copy(
            update={
                "qualifications": (
                    row,
                    row.model_copy(update={"qualification_id": "owned-duplicate"}),
                )
            }
        )
    elif attack == "expired":
        registry = registry.model_copy(
            update={"qualifications": (row.model_copy(update={"valid_until": NOW}),)}
        )
    elif attack == "country":
        registry = registry.model_copy(
            update={"qualifications": (row.model_copy(update={"operator_country": "DE"}),)}
        )
    elif attack == "approval":
        registry = registry.model_copy(update={"approvals": ()})
    elif attack == "quota":
        quota = quota.model_copy(update={"evidence_sha256": "0" * 64})
    else:
        observed = NOW - timedelta(seconds=301)
        approval = registry.approvals[0]
        plan = approval.plan_quota.model_copy(update={"observed_at": observed})
        registry = registry.model_copy(
            update={"approvals": (approval.model_copy(update={"plan_quota": plan}),)}
        )
        quota = quota.model_copy(update={"observed_at": observed})
    service, counters, *_ = acquisition(
        monkeypatch, repository_root, registry=registry, profile=profile, quota=quota
    )
    with pytest.raises(IngestionError) as error:
        fetch(service)
    assert error.value.code in {"RIGHTS_BLOCKED", "QUOTA_EVIDENCE_REQUIRED"}
    assert counters["credentials"] == counters["constructed"] == counters["transports"] == 0


@pytest.mark.parametrize("options", [{"maximum_attempts": None}, {"require_known_quota": False}])
def test_new_purpose_cannot_inherit_legacy_retry_or_unknown_quota_defaults(
    monkeypatch, repository_root, options
):
    service, counters, *_ = acquisition(monkeypatch, repository_root, **options)
    with pytest.raises(IngestionError) as error:
        fetch(service)
    assert error.value.code == "RIGHTS_BLOCKED" and counters["credentials"] == 0


def test_resealed_new_input_cannot_borrow_legacy_rights_fields_or_config(
    monkeypatch, repository_root
):
    service, *_ = acquisition(monkeypatch, repository_root)
    result = fetch(service)
    attacks = (
        result.model_copy(
            update={
                "rights": result.rights.model_copy(update={"model_training_declared": "UNKNOWN"})
            }
        ),
        result.model_copy(
            update={
                "provenance": result.provenance.model_copy(
                    update={"rights_config_sha256": rights_config_sha256()}
                )
            }
        ),
        result.model_copy(
            update={
                "provenance": result.provenance.model_copy(
                    update={"effective_config_sha256": effective_config_sha256()}
                )
            }
        ),
    )
    for changed in attacks:
        with pytest.raises(IngestionError) as error:
            require_private_operator_input(changed)
        assert error.value.code == "RIGHTS_BLOCKED"
