from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest

from dmf_pulse.fpl_points.models import MonteCarloPolicy
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.current import CurrentFplInputService
from dmf_pulse.ingestion.fpl.manager_current import CurrentManagerStateService
from dmf_pulse.ingestion.openfootball.config import (
    APPROVED_PROFILE_ID,
    load_rights_profiles,
)
from dmf_pulse.ingestion.openfootball.service import (
    CurrentScorePriorBuildRequest,
    CurrentScorePriorService,
    build_current_score_prior_bundle,
)
from dmf_pulse.markets.current import (
    CurrentMarketCanonicalIdentityView,
    current_market_identity_view_sha256,
)
from dmf_pulse.private_v1.errors import PrivateV1Error
from dmf_pulse.private_v1.live import (
    PrivateLivePriorFallbackInput,
    PrivateV1LiveTransientRequest,
    PrivateV1LiveTransientService,
)
from dmf_pulse.private_v1.models import (
    PrivateCandidateActionPolicy,
    PrivateCanonicalPlayerIdentityMap,
    PrivateCurrentOwnership,
    PrivateCurrentOwnershipMember,
    PrivateFixtureScorePrior,
    seal_candidate_action_policy,
    seal_canonical_player_identity_map,
    seal_current_ownership,
    seal_fixture_score_prior,
)
from dmf_pulse.private_v1.service import load_packaged_event_allocation_config
from dmf_pulse.rules.capabilities import compile_capability_artifact
from dmf_pulse.rules.compiler import compile_ruleset
from dmf_pulse.rules.models import (
    CapabilityArtifact,
    CompiledRuleset,
    RuleCapability,
    RulesetStatus,
)
from dmf_pulse.rules.private_transient import (
    PrivateTransientRulesAuthority,
    seal_private_transient_rules_authority,
)
from tests.unit.ingestion.openfootball.conftest import (
    FakeTransport,
    synthetic_snapshot,
    ticking_clock,
)
from tests.unit.markets.current_market_test_support import build_from_context, recompose
from tests.unit.private_v1.e2e_test_support import (
    _identity_map,
    _manual_inputs,
    _unified_context,
)

_CAPTURED = datetime(2026, 8, 30, 8, 45, tzinfo=UTC)
_CUTOFF = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)
_COMPETITION_ID = UUID("30000000-0000-7000-8000-000000000001")


def test_prior_fallback_declaration_requires_aware_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        PrivateLivePriorFallbackInput(declared_at=datetime(2026, 8, 30, 9, 34))


def _boundary_request(**updates: object) -> PrivateV1LiveTransientRequest:
    values: dict[str, object] = {
        "bootstrap_path": Path("operator-bootstrap.json"),
        "fixtures_path": Path("operator-fixtures.json"),
        "manager_declaration_path": Path("operator-manager.json"),
        "target_gameweek": 1,
        "captured_at": _CAPTURED,
        "information_cutoff": _CUTOFF,
        "prior_fallbacks": None,
        "score_priors": (SimpleNamespace(source_class="CURRENT_SCORE_PRIOR_BUNDLE"),),
        "player_identity_map": SimpleNamespace(source_class="DAT_003_OPERATOR_EXPORT"),
        "market_identity_view": SimpleNamespace(authority="DAT_003_READ_ONLY"),
        "event_allocation_config": SimpleNamespace(source_tag="CURRENT_FPL_RULES"),
    }
    values.update(updates)
    return cast(PrivateV1LiveTransientRequest, SimpleNamespace(**values))


class _UnexpectedFplRead:
    def compile(self, request: object) -> None:
        del request
        raise AssertionError("operator-owned FPL source must not be read")


@pytest.mark.parametrize(
    ("updates", "expected_code"),
    [
        ({"target_gameweek": 2}, "PLAYER_PRIOR_POLICY_MISSING"),
        ({"prior_fallbacks": SimpleNamespace()}, "PLAYER_PRIOR_POLICY_INVALID"),
        (
            {"score_priors": (SimpleNamespace(source_class="REPOSITORY_OWNED_SYNTHETIC"),)},
            "SCORE_PRIOR_SOURCE_INVALID",
        ),
        (
            {"player_identity_map": SimpleNamespace(source_class="TEST_SYNTHETIC")},
            "PLAYER_IDENTITY_SOURCE_INVALID",
        ),
        (
            {"market_identity_view": SimpleNamespace(authority="OPERATOR_SYNTHETIC")},
            "MARKET_IDENTITY_SOURCE_INVALID",
        ),
        (
            {"event_allocation_config": SimpleNamespace(source_tag="TEST_SYNTHETIC")},
            "STAGE9_POLICY_INVALID",
        ),
    ],
)
def test_live_boundary_rejects_disallowed_authority_before_fpl_read(
    updates: dict[str, object], expected_code: str
) -> None:
    service = PrivateV1LiveTransientService(fpl_service=_UnexpectedFplRead())  # type: ignore[arg-type]

    with pytest.raises(PrivateV1Error) as caught:
        service.run(_boundary_request(**updates))

    assert caught.value.code == expected_code


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        (IngestionError("RIGHTS_BLOCKED", "sensitive source detail"), "RIGHTS_BLOCKED"),
        (ValueError("sensitive source detail"), "LIVE_TRANSIENT_INPUT_INVALID"),
    ],
)
def test_live_boundary_redacts_upstream_failures(failure: Exception, expected_code: str) -> None:
    class _FailingFplRead:
        def compile(self, request: object) -> None:
            del request
            raise failure

    service = PrivateV1LiveTransientService(fpl_service=_FailingFplRead())  # type: ignore[arg-type]

    with pytest.raises(PrivateV1Error) as caught:
        service.run(_boundary_request())

    assert caught.value.code == expected_code
    assert "sensitive source detail" not in str(caught.value)


def _authority(
    ruleset: CompiledRuleset, capability: CapabilityArtifact
) -> PrivateTransientRulesAuthority:
    return seal_private_transient_rules_authority(
        PrivateTransientRulesAuthority.model_construct(
            ruleset_id=ruleset.ruleset_id,
            ruleset_version=ruleset.ruleset_version,
            ruleset_sha256=ruleset.ruleset_hash,
            capability_sha256=capability.capability_hash,
            operator_approval_reference="PRIVATE-V1-LIVE-TRANSIENT-001A-current-like-test",
            operator_approved_at=_CAPTURED + timedelta(minutes=4),
            attestation_sha256="0" * 64,
        )
    )


def _dat003_player_map(
    value: PrivateCanonicalPlayerIdentityMap,
) -> PrivateCanonicalPlayerIdentityMap:
    return seal_canonical_player_identity_map(
        PrivateCanonicalPlayerIdentityMap.model_construct(
            source_class="DAT_003_OPERATOR_EXPORT",
            resolved_at=value.resolved_at,
            information_cutoff=value.information_cutoff,
            teams=value.teams,
            players=value.players,
            semantic_sha256="0" * 64,
        )
    )


def _dat003_market_view(
    value: CurrentMarketCanonicalIdentityView,
) -> CurrentMarketCanonicalIdentityView:
    provisional = CurrentMarketCanonicalIdentityView.model_construct(
        authority="DAT_003_READ_ONLY",
        resolved_at=value.resolved_at,
        resolution_cutoff=value.resolution_cutoff,
        database_read_performed=True,
        provider_id=value.provider_id,
        fixtures=value.fixtures,
        operators=value.operators,
        semantic_sha256="0" * 64,
    )
    payload = provisional.model_dump(mode="python")
    payload["semantic_sha256"] = current_market_identity_view_sha256(provisional)
    return CurrentMarketCanonicalIdentityView.model_validate(payload)


def test_current_like_verified_live_transient_full_stack_has_zero_persistence(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    working = tmp_path / "operator-owned-live-input"
    context = _unified_context(
        repository_root,
        working,
        target_gameweek=2,
        captured_at=_CAPTURED,
        information_cutoff=_CUTOFF,
    )
    context = recompose(context, context.odds_input)
    synthetic_view, _market_request, _markets = build_from_context(context)
    market_view = _dat003_market_view(synthetic_view)
    identities = _dat003_player_map(
        _identity_map(context, captured_at=_CAPTURED, information_cutoff=_CUTOFF)
    )
    manual = _manual_inputs(
        context,
        identities,
        market_view,
        captured_at=_CAPTURED,
        information_cutoff=_CUTOFF,
    )
    manual_by_fixture = {item.fixture_id: item for item in manual}

    config, bodies = synthetic_snapshot()
    score_source = CurrentScorePriorService(
        provider_config=config,
        rights_profiles=load_rights_profiles(),
        transport=FakeTransport(bodies),
        clock=ticking_clock(datetime(2026, 8, 30, 9, 0, tzinfo=UTC)),
        provider_config_identity="a" * 64,
        rights_config_identity="b" * 64,
    ).build(
        CurrentScorePriorBuildRequest(
            information_cutoff=_CUTOFF,
            rights_profile_id=APPROVED_PROFILE_ID,
        )
    )
    score_priors = tuple(
        seal_fixture_score_prior(
            PrivateFixtureScorePrior.model_construct(
                source_class="CURRENT_SCORE_PRIOR_BUNDLE",
                fixture_id=item.canonical_fixture_id,
                competition_id=_COMPETITION_ID,
                home_team_id=UUID(manual_by_fixture[str(item.canonical_fixture_id)].home_team_id),
                away_team_id=UUID(manual_by_fixture[str(item.canonical_fixture_id)].away_team_id),
                as_of=_CUTOFF,
                score_prior_request=score_source.score_prior_request,
                current_bundle=build_current_score_prior_bundle(
                    score_source,
                    fixture_id=item.canonical_fixture_id,
                    competition_id=_COMPETITION_ID,
                    home_team_id=UUID(
                        manual_by_fixture[str(item.canonical_fixture_id)].home_team_id
                    ),
                    away_team_id=UUID(
                        manual_by_fixture[str(item.canonical_fixture_id)].away_team_id
                    ),
                    as_of=_CUTOFF,
                ),
                semantic_sha256="0" * 64,
            )
        )
        for item in sorted(market_view.fixtures, key=lambda value: str(value.canonical_fixture_id))
    )
    squad_ids = tuple(sorted(item.official_fpl_element_id for item in context.manager_state.squad))
    ownership = seal_current_ownership(
        PrivateCurrentOwnership.model_construct(
            source_class="OPERATOR_DECLARED_PRIVATE_TRANSIENT",
            attestation_status="HUMAN_ATTESTED",
            provider_verification="NOT_PROVIDER_VERIFIED",
            target_gameweek=2,
            declared_at=_CAPTURED + timedelta(minutes=47),
            attested_at=_CAPTURED + timedelta(minutes=48),
            information_cutoff=_CUTOFF,
            members=tuple(
                PrivateCurrentOwnershipMember(official_fpl_element_id=item, acquired_gameweek=1)
                for item in squad_ids
            ),
            semantic_sha256="0" * 64,
        )
    )
    squad = set(squad_ids)
    incoming = next(
        item.provider_element_id
        for item in sorted(context.fpl_input.players, key=lambda value: value.provider_element_id)
        if item.position.value == "GK"
        and int(item.team_identity.external_id_text) == 1
        and item.provider_element_id not in squad
    )
    candidates = seal_candidate_action_policy(
        PrivateCandidateActionPolicy.model_construct(
            allowed_transfer_in_element_ids=(incoming,),
            maximum_transfers=1,
            rationale="One explicit current-like incoming goalkeeper candidate.",
            semantic_sha256="0" * 64,
        )
    )
    ruleset = compile_ruleset(repository_root / "config/rules/fpl-2026-27")
    assert ruleset.status is RulesetStatus.VERIFIED
    capability = compile_capability_artifact(ruleset, RuleCapability.FULL_SEASON)
    authority = _authority(ruleset, capability)
    mc_policy = MonteCarloPolicy(
        minimum_effective_scenarios=1.0,
        maximum_mean_mcse=100.0,
        maximum_probability_se=1.0,
        maximum_quantile_span=100,
        quantiles=(0.1, 0.5, 0.9),
        thresholds=(5, 10, 15),
        batch_count=2,
    )
    before = {
        path.relative_to(working): path.read_bytes()
        for path in working.rglob("*")
        if path.is_file()
    }
    fpl_times = iter((_CAPTURED + timedelta(minutes=5), _CAPTURED + timedelta(minutes=6)))
    manager_times = iter((_CAPTURED + timedelta(minutes=12), _CAPTURED + timedelta(minutes=13)))
    result = PrivateV1LiveTransientService(
        fpl_service=CurrentFplInputService(clock=lambda: next(fpl_times)),
        manager_service=CurrentManagerStateService(clock=lambda: next(manager_times)),
    ).run(
        PrivateV1LiveTransientRequest(
            run_id="PRIVATE_V1_CURRENT_LIKE_TRANSIENT",
            code_sha="b" * 40,
            bootstrap_path=working / "bootstrap.json",
            fixtures_path=working / "fixtures.json",
            manager_declaration_path=working / "manager.json",
            target_gameweek=2,
            captured_at=_CAPTURED,
            information_cutoff=_CUTOFF,
            ruleset=ruleset,
            full_season_capability=capability,
            private_rules_authority=authority,
            odds_input=context.odds_input,
            team_alias_plan=context.identity_map.team_alias_plan,
            fixture_mapping_plan=context.identity_map.fixture_mapping_plan,
            mapping_decided_at=context.identity_map.mapping_decided_at,
            market_identity_view=market_view,
            player_identity_map=identities,
            score_priors=score_priors,
            manual_minutes=manual,
            ownership=ownership,
            candidate_action_policy=candidates,
            prior_fallbacks=PrivateLivePriorFallbackInput(
                declared_at=_CAPTURED + timedelta(minutes=49), assignments=()
            ),
            root_seed=1,
            scenario_count=1,
            stage9_monte_carlo_policy=mc_policy,
            event_allocation_config=load_packaged_event_allocation_config(),
        )
    )

    after = {
        path.relative_to(working): path.read_bytes()
        for path in working.rglob("*")
        if path.is_file()
    }
    assert before == after
    assert result.execution_status == "REAL_PRIVATE_TRANSIENT_RECOMMENDATION"
    assert result.replay_retention == "FORBIDDEN_BY_CURRENT_RIGHTS_PROFILE"
    assert result.persistent_artifacts_created == 0
    assert result.decision.target_gameweek == 2
    assert result.decision.player_prior_status == (
        "PRIVATE_CURRENT_GW_STALE_PRIOR_CARRY_FORWARD_V1"
    )
    assert result.decision.player_prior_fallback_player_ids == ()
    assert result.decision.tactics.captain in result.decision.tactics.starting_xi
    assert result.decision.tactics.vice_captain in result.decision.tactics.starting_xi
    assert "TRANSIENT PRIVATE DECISION" in result.report
    assert "NOT REPLAYABLE UNDER CURRENT RIGHTS PROFILE" in result.report
    assert "Persistent artifacts created by live-transient: 0" in result.report
