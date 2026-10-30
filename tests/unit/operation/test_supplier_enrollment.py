"""Installed source closure precedes reservation, credential and native transport."""

from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from dmf_pulse.dashboard import authorization as auth
from dmf_pulse.dashboard.current_sources import GuardedFplTransport
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.direct import (
    DirectFplClient,
    DirectFplResource,
    DirectFplRunAttestation,
    DirectUrllibTransport,
)
from dmf_pulse.ingestion.rights import load_rights_profiles
from dmf_pulse.operation import enrollment
from dmf_pulse.operation.enrollment import (
    InstalledEnrollment,
    SourceQualification,
    rights_fingerprint,
)
from dmf_pulse.operation.models import OperationError
from tests.unit.dashboard.test_live_authorization import NOW, setup
from tests.unit.ingestion.test_fpl_direct_transport import _request

pytestmark = pytest.mark.unit


def qualification():
    profile = load_rights_profiles()["fpl_official_private_operator_initiated_read_v1"].model_copy(
        update={
            "rights_profile_id": "owned_supplier_permission_example_v1",
            "human_approval_id": "owned-permission-example",
            "approved_purpose": "PRIVATE_OPERATOR_FPL_RECOMMENDATIONS",
        }
    )
    scope = auth.SourceScope(
        provider="FPL",
        account_ref="owned-manager-account",
        profile_id=profile.rights_profile_id,
        profile_sha256=rights_fingerprint(profile),
        source_kind="RIGHTS_QUALIFIED_PRIVATE",
        routes=(
            auth.RouteBudget(
                host="fantasy.premierleague.com", path="/api/my-team/17/", maximum_calls=1
            ),
        ),
    )
    return SourceQualification(
        qualification_id="owned-fpl-permission",
        scope=scope,
        profile=profile,
        purpose="PRIVATE_OPERATOR_FPL_RECOMMENDATIONS",
        permission_basis="SUPPLIER_WRITTEN_PERMISSION",
        permission_evidence_sha256="a" * 64,
        independent_review_sha256="b" * 64,
        decision_ref="owned-review",
        operator_country="DE",
        qualified_at=NOW - timedelta(hours=1),
        valid_until=NOW + timedelta(hours=1),
        control_metadata_retention_approved=True,
    )


def test_empty_fixed_registry_has_no_source_closure_or_release_authority():
    registry = enrollment.installed_enrollment()
    assert registry == InstalledEnrollment()
    with pytest.raises(OperationError, match="FPL_SUPPLIER_PERMISSION_REQUIRED"):
        enrollment.require_fpl_route(
            "GET", "fantasy.premierleague.com", "/api/my-team/17/", now=NOW
        )


@pytest.mark.parametrize(
    "resource", [DirectFplResource.MY_TEAM, DirectFplResource.BOOTSTRAP, DirectFplResource.FIXTURES]
)
def test_default_client_denies_before_credential_or_request_construction(monkeypatch, resource):
    client = DirectFplClient(DirectFplRunAttestation(attested_at=NOW), clock=lambda: NOW)
    monkeypatch.setattr(
        client._credential_provider, "get", lambda: pytest.fail("supplier refusal read token")
    )
    monkeypatch.setattr(
        client, "_request", lambda *args: pytest.fail("supplier refusal built outbound request")
    )
    with pytest.raises(IngestionError, match="Supplier permission") as caught:
        client.fetch(resource, entry_id=17 if resource == DirectFplResource.MY_TEAM else None)
    assert caught.value.code == "FPL_SUPPLIER_PERMISSION_REQUIRED" and client.request_count == 0


def test_native_transport_denies_before_opener(monkeypatch):
    import urllib.request

    monkeypatch.setattr(
        urllib.request, "build_opener", lambda *args: pytest.fail("unqualified native opener")
    )
    with pytest.raises(IngestionError, match="Supplier permission"):
        DirectUrllibTransport().send(_request())


def test_wrapper_cannot_hide_native_supplier_requirement():
    class Guard:
        def __getattr__(self, name):
            return lambda *args: pytest.fail("unqualified wrapper reached grant operation")

    wrapped = GuardedFplTransport(Guard(), DirectUrllibTransport())
    client = DirectFplClient(
        DirectFplRunAttestation(attested_at=NOW), transport=wrapped, clock=lambda: NOW
    )
    with pytest.raises(IngestionError) as caught:
        client.fetch(DirectFplResource.MY_TEAM, entry_id=17)
    assert caught.value.code == "FPL_SUPPLIER_PERMISSION_REQUIRED"


@pytest.mark.parametrize(
    "attack", ["risk_profile", "vendor_terms", "country", "window", "scope_hash", "retention"]
)
def test_source_qualification_rejects_risk_or_incoherent_closure(attack):
    row = qualification()
    values = {name: getattr(row, name) for name in type(row).model_fields}
    if attack == "risk_profile":
        profile = load_rights_profiles()["fpl_official_private_operator_initiated_read_v1"]
        values.update(
            profile=profile,
            scope=row.scope.model_copy(
                update={
                    "profile_id": profile.rights_profile_id,
                    "profile_sha256": rights_fingerprint(profile),
                }
            ),
        )
    elif attack == "vendor_terms":
        values["permission_basis"] = "VENDOR_TERMS_AND_ACCOUNT"
    elif attack == "country":
        values["operator_country"] = "uk"
    elif attack == "window":
        values["valid_until"] = row.qualified_at
    elif attack == "scope_hash":
        values["scope"] = row.scope.model_copy(update={"profile_sha256": "f" * 64})
    else:
        values["control_metadata_retention_approved"] = 1
    with pytest.raises(ValidationError):
        SourceQualification.model_validate(values)


def test_installed_owned_permission_is_exact_and_expires(monkeypatch):
    row = qualification()
    monkeypatch.setattr(
        enrollment, "installed_enrollment", lambda: InstalledEnrollment(qualifications=(row,))
    )
    enrollment.require_source_closure((row.scope,), now=NOW)
    enrollment.require_fpl_route(
        "GET",
        "fantasy.premierleague.com",
        "/api/my-team/17/",
        now=NOW,
        profile_sha256=row.scope.profile_sha256,
    )
    for method, host, path, at in (
        ("POST", "fantasy.premierleague.com", "/api/my-team/17/", NOW),
        ("GET", "fantasy.premierleague.com", "/api/my-team/18/", NOW),
        ("GET", "fantasy.premierleague.com", "/api/my-team/17/", row.valid_until),
    ):
        with pytest.raises(OperationError, match="FPL_SUPPLIER_PERMISSION_REQUIRED"):
            enrollment.require_fpl_route(
                method, host, path, now=at, profile_sha256=row.scope.profile_sha256
            )


def test_populated_qualification_and_registry_semantic_json_roundtrip():
    row = qualification()
    assert SourceQualification.model_validate_json(row.model_dump_json()) == row
    registry = InstalledEnrollment(qualifications=(row,))
    restored = InstalledEnrollment.model_validate_json(registry.model_dump_json())
    assert restored == registry and restored.semantic_sha256 == registry.semantic_sha256


def test_private_complete_approval_cannot_waive_missing_supplier_permission(tmp_path, monkeypatch):
    _, owned, request, _ = setup(tmp_path)
    private = owned.model_copy(
        update={
            "classification": "PRIVATE_CURRENT",
            "ledger_backend": "POSTGRES",
            "qualified_deadline_at": request.deadline_at,
            "source_scopes": tuple(
                row.model_copy(update={"source_kind": "RIGHTS_QUALIFIED_PRIVATE"})
                for row in owned.source_scopes
            ),
        }
    )
    private_request = request.model_copy(update={"source_scopes": private.source_scopes})
    monkeypatch.setattr(auth, "production_approvals", lambda: (private,))
    with pytest.raises(auth.AuthorizationError, match="FPL_SUPPLIER_PERMISSION_REQUIRED"):
        auth._approved_expiry(private, private_request, NOW)


def test_legacy_v1_resource_never_invents_qualifications(monkeypatch):
    class Resource:
        def joinpath(self, name):
            return self

        def read_bytes(self):
            return b'{"schema_version":"trusted-refresh-enrollments-v1","approvals":[]}'

    monkeypatch.setattr(enrollment, "files", lambda package: Resource())
    assert enrollment.installed_enrollment() == InstalledEnrollment()
