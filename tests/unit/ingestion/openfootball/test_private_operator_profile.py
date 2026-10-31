"""Owned installed qualifications and synthetic build parity; no publisher authentication."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from dmf_pulse.dashboard import current_sources
from dmf_pulse.dashboard.authorization import QualifiedPlanQuota, RouteBudget, SourceScope
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.models import CapabilityValue, RightsCapability, RightsProfileStatus
from dmf_pulse.ingestion.openfootball import service
from dmf_pulse.ingestion.openfootball.config import APPROVED_PROFILE_ID, load_provider_config
from dmf_pulse.ingestion.openfootball.config import load_rights_profiles as score_profiles
from dmf_pulse.operation import enrollment
from dmf_pulse.operation.enrollment import (
    InstalledEnrollment,
    SourceQualification,
    rights_fingerprint,
)
from dmf_pulse.operation.models import OperationError

from .conftest import FakeTransport, synthetic_snapshot

pytestmark = pytest.mark.unit
NOW = datetime(2026, 10, 31, 20, tzinfo=UTC)
LICENCE_SHA = "36ffd9dc085d529a7e60e1276d73ae5a030b020313e6c5408593a6ae2af39673"


def owned_profile(**changes):
    original = score_profiles()[APPROVED_PROFILE_ID]
    return original.model_copy(
        update={
            "rights_profile_id": service.PRIVATE_OPERATOR_PROFILE_ID,
            "approved_purpose": "PRIVATE_OPERATOR_FPL_RECOMMENDATIONS",
            "geography_scope": service.PRIVATE_OPERATOR_GEOGRAPHY,
            "human_approval_id": "owned-test-not-real-permission",
            "approved_by": "Owned synthetic reviewer",
            "approved_at": NOW - timedelta(minutes=5),
            "checked_at": NOW - timedelta(minutes=4),
            **changes,
        }
    )


def owned_qualification(profile=None, **changes):
    profile = owned_profile() if profile is None else profile
    config = load_provider_config()
    scope = SourceScope(
        provider="OPENFOOTBALL",
        account_ref="owned-openfootball-public-source",
        profile_id=profile.rights_profile_id,
        profile_sha256=rights_fingerprint(profile),
        source_kind="RIGHTS_QUALIFIED_PRIVATE",
        routes=tuple(
            RouteBudget(host=config.host, path=config.raw_path(resource.path), maximum_calls=1)
            for resource in (config.licence, *config.seasons)
        ),
    )
    return SourceQualification(
        qualification_id="owned-test-only",
        scope=scope,
        profile=profile,
        purpose="PRIVATE_OPERATOR_FPL_RECOMMENDATIONS",
        permission_basis="VENDOR_TERMS_AND_ACCOUNT",
        permission_evidence_sha256=LICENCE_SHA,
        independent_review_sha256="a" * 64,
        decision_ref="owned-test-not-real-permission",
        operator_country="IT",
        qualified_at=NOW - timedelta(minutes=3),
        valid_until=NOW + timedelta(minutes=5),
        control_metadata_retention_approved=True,
        **changes,
    )


def install_owned(monkeypatch, rows):
    registry = InstalledEnrollment(qualifications=tuple(rows))
    monkeypatch.setattr(enrollment, "installed_enrollment", lambda: registry)
    return registry


def build_owned(config, bodies, profile):
    transport = FakeTransport(bodies)
    builder = service.CurrentScorePriorService(
        provider_config=config,
        rights_profiles={profile.rights_profile_id: profile},
        transport=transport,
        clock=lambda: NOW,
    )
    request = service.CurrentScorePriorBuildRequest(
        rights_profile_id=profile.rights_profile_id,
        information_cutoff=NOW + timedelta(seconds=30),
    )
    return builder, request, transport


def test_installed_private_qualification_preserves_synthetic_math_and_actual_profile_lineage(
    monkeypatch,
):
    config, bodies = synthetic_snapshot()
    legacy_builder, legacy_request, _ = build_owned(
        config, bodies, score_profiles()[APPROVED_PROFILE_ID]
    )
    legacy = legacy_builder.build(legacy_request)
    profile = owned_profile()
    install_owned(monkeypatch, (owned_qualification(profile),))
    builder, request, transport = build_owned(config, bodies, profile)
    result = builder.build(request)
    assert result.score_prior_request == legacy.score_prior_request
    assert result.seasons == legacy.seasons
    assert (result.sample_size, result.home_goal_total, result.away_goal_total) == (
        1140,
        1839,
        1567,
    )
    assert result.provenance.rights_profile_id == service.PRIVATE_OPERATOR_PROFILE_ID
    assert result.provenance.human_approval_id == profile.human_approval_id
    assert result.provenance.approved_at == profile.approved_at
    assert result.provenance.rights_config_sha256 != legacy.provenance.rights_config_sha256
    assert result.safe_summary().rights_profile_id == service.PRIVATE_OPERATOR_PROFILE_ID
    assert result.semantic_sha256 != legacy.semantic_sha256
    assert result.provenance.source_mode == "RECONSTRUCTED"
    assert not result.current_team_strength_claim and not result.production_active
    assert len(transport.requests) == 4
    assert all(config.commit_sha in request.path for request in transport.requests)
    # The snapshot deliberately contains invented football bodies, as in the legacy suite.
    assert config.licence.content_sha256 != LICENCE_SHA


@pytest.mark.parametrize(
    "changes",
    [
        {"rights_profile_id": "unlisted-private-profile"},
        {"status": RightsProfileStatus.DRAFT},
        {"approved_purpose": "another-private-purpose"},
        {"account_scope": "another-repository"},
        {"geography_scope": "private UK analytical use"},
        {"terms_source": "another-licence"},
        {"terms_version": "CC-BY-4.0"},
        {"retention_seconds": 0},
        {"retention_reason": "owner-report"},
        {"termination_deletion_required": True},
        {"unresolved_rights": ("owned unresolved right",)},
        {"attribution_required": True, "attribution_text": "another-attribution"},
        {"approved_at": NOW + timedelta(seconds=1)},
        {"checked_at": NOW + timedelta(seconds=1)},
    ],
)
def test_changed_private_profile_blocks_before_transport(monkeypatch, changes):
    profile = owned_profile(**changes)
    install_owned(monkeypatch, (owned_qualification(profile),))
    builder, request, transport = build_owned(*synthetic_snapshot(), profile)
    with pytest.raises(IngestionError) as error:
        builder.build(request)
    assert error.value.code == "RIGHTS_BLOCKED"
    assert error.value.details["transport_call_count"] == 0 and transport.requests == []


@pytest.mark.parametrize("capability", list(RightsCapability))
def test_every_private_capability_remains_explicit(monkeypatch, capability):
    profile = owned_profile()
    capabilities = dict(profile.capabilities)
    capabilities[capability] = (
        CapabilityValue.ALLOW
        if capability in {RightsCapability.PUBLIC_DISPLAY, RightsCapability.REDISTRIBUTION}
        else CapabilityValue.DENY
    )
    profile = profile.model_copy(update={"capabilities": capabilities})
    install_owned(monkeypatch, (owned_qualification(profile),))
    builder, request, transport = build_owned(*synthetic_snapshot(), profile)
    with pytest.raises(IngestionError) as error:
        builder.build(request)
    assert error.value.code == "RIGHTS_BLOCKED"
    assert transport.requests == []


@pytest.mark.parametrize(
    "attack",
    ["missing", "duplicate", "country", "expired", "future", "licence", "route", "route_budget"],
)
def test_private_source_requires_one_exact_current_installed_scope(monkeypatch, attack):
    profile = owned_profile()
    row = owned_qualification(profile)
    if attack == "country":
        row = row.model_copy(update={"operator_country": "DE"})
    elif attack == "expired":
        row = row.model_copy(update={"valid_until": NOW})
    elif attack == "future":
        row = row.model_copy(update={"qualified_at": NOW + timedelta(seconds=1)})
    elif attack == "licence":
        row = row.model_copy(update={"permission_evidence_sha256": "f" * 64})
    elif attack in {"route", "route_budget"}:
        routes = (
            row.scope.routes[:-1]
            if attack == "route"
            else (
                row.scope.routes[0].model_copy(update={"maximum_calls": 2}),
                *row.scope.routes[1:],
            )
        )
        row = row.model_copy(update={"scope": row.scope.model_copy(update={"routes": routes})})
    rows = () if attack == "missing" else (row,)
    if attack == "duplicate":
        rows = (row, row.model_copy(update={"qualification_id": "owned-duplicate"}))
    install_owned(monkeypatch, rows)
    builder, request, transport = build_owned(*synthetic_snapshot(), profile)
    with pytest.raises(IngestionError) as error:
        builder.build(request)
    assert error.value.code == "RIGHTS_BLOCKED"
    assert error.value.details["transport_call_count"] == 0 and transport.requests == []


def test_private_registry_failure_and_withdrawal_are_closed_at_each_resource(monkeypatch):
    profile = owned_profile()
    builder, request, transport = build_owned(*synthetic_snapshot(), profile)

    def unavailable():
        raise OperationError("OWNED_UNAVAILABLE_REGISTRY")

    monkeypatch.setattr(enrollment, "installed_enrollment", unavailable)
    with pytest.raises(IngestionError) as error:
        builder.build(request)
    assert error.value.code == "RIGHTS_BLOCKED"
    assert transport.requests == []
    accepted = InstalledEnrollment(qualifications=(owned_qualification(profile),))
    calls = 0

    def withdraw_after_first_response():
        nonlocal calls
        calls += 1
        return accepted if calls <= 3 else InstalledEnrollment()

    monkeypatch.setattr(enrollment, "installed_enrollment", withdraw_after_first_response)
    with pytest.raises(IngestionError) as error:
        builder.build(request)
    assert error.value.code == "RIGHTS_BLOCKED"
    assert len(transport.requests) == error.value.details["transport_call_count"] == 1


def test_legacy_exact_scope_cannot_inherit_new_private_geography(monkeypatch):
    profile = score_profiles()[APPROVED_PROFILE_ID].model_copy(
        update={"geography_scope": service.PRIVATE_OPERATOR_GEOGRAPHY}
    )
    install_owned(monkeypatch, ())
    builder, request, transport = build_owned(*synthetic_snapshot(), profile)
    with pytest.raises(IngestionError) as error:
        builder.build(request)
    assert error.value.code == "RIGHTS_BLOCKED"
    assert transport.requests == []


def test_provenance_and_summary_do_not_accept_arbitrary_profile_ids(monkeypatch):
    profile = owned_profile()
    install_owned(monkeypatch, (owned_qualification(profile),))
    builder, request, _ = build_owned(*synthetic_snapshot(), profile)
    result = builder.build(request)
    with pytest.raises(ValidationError):
        result.provenance.model_copy(update={"rights_profile_id": "unreviewed-generic-profile"})
    with pytest.raises(ValidationError):
        service.CurrentScorePriorSummary.model_validate(
            {
                **result.safe_summary().model_dump(),
                "rights_profile_id": "unreviewed-generic-profile",
            }
        )


def test_factory_uses_reviewed_profile_and_unchanged_packaged_source_config(monkeypatch):
    profile = owned_profile()
    quota = QualifiedPlanQuota(
        account_ref="owned-account",
        plan_ref="owned-plan",
        evidence_sha256="a" * 64,
        terms_evidence_sha256="b" * 64,
        monthly_plan_credits=2,
        allocated_monthly_credits=2,
        remaining_credits=2,
        observed_at=NOW,
        period_started_at=NOW - timedelta(days=1),
        resets_at=NOW + timedelta(days=1),
    )
    closed = []

    class Guard:
        def finish_acquisition(self):
            closed.append(True)

    factory = current_sources.CurrentSourceFactories(
        guard=Guard(),
        owned=False,
        fpl_profile=profile,
        odds_profile=profile,
        score_profile=profile,
        quota=quota,
        clock=lambda: NOW,
    )
    builder = factory.score(lambda: NOW)
    assert builder._profiles[service.PRIVATE_OPERATOR_PROFILE_ID] == profile
    assert builder._config == load_provider_config()
    install_owned(monkeypatch, ())
    with pytest.raises(IngestionError) as error:
        builder.build(
            service.CurrentScorePriorBuildRequest(
                information_cutoff=NOW,
                rights_profile_id=service.PRIVATE_OPERATOR_PROFILE_ID,
            )
        )
    assert error.value.code == "RIGHTS_BLOCKED"
    assert closed == [True]
