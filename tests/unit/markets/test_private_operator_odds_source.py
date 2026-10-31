"""New-purpose source identity and rights through the unchanged market kernel."""

import pytest
from pydantic import ValidationError

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.odds.current import _rights_state
from dmf_pulse.ingestion.odds.private_operator import (
    PRIVATE_OPERATOR_PROFILE_ID,
    require_private_operator_profile,
)
from dmf_pulse.markets.current import (
    CurrentMarketCanonicalIdentityRepository,
    CurrentMarketCanonicalIdentityView,
    CurrentMarketConstraintError,
    CurrentMarketConstraintService,
    bind_current_market_constraint_request,
    build_transient_current_market_identity_view,
)
from dmf_pulse.operation import enrollment
from tests.unit.ingestion.odds_private_test_support import owned_registry
from tests.unit.markets.current_market_test_support import (
    build_source_context,
    recompose,
    rehash_identity_view,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def source_case(repository_root, tmp_path, monkeypatch):
    original = build_source_context(repository_root, tmp_path)
    old = original.odds_input
    registry, profile, _ = owned_registry(at=old.temporal.received_at)
    monkeypatch.setattr(enrollment, "installed_enrollment", lambda: registry)
    identity = require_private_operator_profile(profile, checked_at=old.temporal.received_at)
    provenance = old.provenance.model_copy(
        update={
            "rights_config_sha256": identity,
            "effective_config_sha256": canonical_sha256(
                {
                    "provider_config_sha256": old.provenance.provider_config_sha256,
                    "rights_config_sha256": identity,
                }
            ),
        }
    )
    odds = old.model_copy(
        update={
            "rights": _rights_state(profile, old.temporal.received_at),
            "provenance": provenance,
        }
    )
    context = recompose(original, odds)
    view = build_transient_current_market_identity_view(
        context.bundle, resolved_at=context.identity_map.mapping_decided_at
    )
    return context, view


def test_new_source_binds_actual_profile_provider_and_market_constraints(source_case):
    context, view = source_case
    request = bind_current_market_constraint_request(context.bundle, view)
    result = CurrentMarketConstraintService().build(
        request, source=context.bundle, identity_view=view
    )
    assert view.provider_rights_profile_key == PRIVATE_OPERATOR_PROFILE_ID
    assert view.authority == "OPERATOR_INITIATED_DETERMINISTIC"
    assert not view.database_read_performed
    assert result.fixtures and any(item.constraint_set.constraints for item in result.fixtures)
    assert result.lineage.odds_rights_sha256 == request.odds_rights_sha256
    assert context.bundle.odds_input.rights.rights_profile_id == PRIVATE_OPERATOR_PROFILE_ID


@pytest.mark.parametrize("attack", ["old_profile", "old_provider", "test_authority"])
def test_resealed_identity_cannot_relabel_new_profile_as_legacy(source_case, attack):
    context, view = source_case
    if attack == "old_profile":
        changed = rehash_identity_view(
            view, provider_rights_profile_key="the_odds_api_private_analytics_v1"
        )
    elif attack == "old_provider":
        from uuid import UUID

        changed = rehash_identity_view(view, provider_id=UUID(int=91))
    else:
        changed = rehash_identity_view(view, authority="TEST_ONLY")
    request = bind_current_market_constraint_request(context.bundle, changed)
    with pytest.raises(CurrentMarketConstraintError) as error:
        CurrentMarketConstraintService().build(
            request, source=context.bundle, identity_view=changed
        )
    assert error.value.code in {"CANONICAL_IDENTITY_UNAVAILABLE", "SOURCE_INVALID"}


def test_persistent_identity_repository_refuses_new_source_before_any_sql(source_case):
    context, _ = source_case

    class NoDatabase:
        def execute(self, statement):
            pytest.fail("new transient purpose widened persistent DAT-003 access")

    with pytest.raises(CurrentMarketConstraintError) as error:
        CurrentMarketCanonicalIdentityRepository(NoDatabase()).resolve(
            context.bundle, resolved_at=context.identity_map.mapping_decided_at
        )
    assert error.value.code == "CANONICAL_IDENTITY_UNAVAILABLE"


def test_closed_identity_contract_rejects_unlisted_profile_and_persistent_authority(source_case):
    _, view = source_case
    for changes in (
        {"provider_rights_profile_key": "unlisted-private-profile"},
        {"authority": "DAT_003_READ_ONLY", "database_read_performed": True},
    ):
        with pytest.raises(ValidationError):
            CurrentMarketCanonicalIdentityView.model_validate({**view.model_dump(), **changes})
