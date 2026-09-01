from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.manager_current import (
    CurrentManagerStateService,
    bind_current_manager_state_request,
)
from dmf_pulse.rules.capabilities import compile_capability_artifact
from dmf_pulse.rules.compiler import compile_ruleset
from dmf_pulse.rules.errors import RulesValidationError
from dmf_pulse.rules.models import (
    CapabilityArtifact,
    CompiledRuleset,
    RuleCapability,
    RulesetStatus,
)
from dmf_pulse.rules.private_transient import (
    PrivateTransientRulesAuthority,
    seal_private_transient_rules_authority,
    validate_private_transient_rules_authority,
)
from tests.unit.ingestion.current_manager_test_support import (
    ATTESTED,
    MANAGER_RECEIVED,
    MANAGER_USABLE,
    build_context,
    write_declaration,
)


def _authority(
    ruleset: CompiledRuleset, capability: CapabilityArtifact
) -> PrivateTransientRulesAuthority:
    provisional = PrivateTransientRulesAuthority.model_construct(
        ruleset_id=ruleset.ruleset_id,
        ruleset_version=ruleset.ruleset_version,
        ruleset_sha256=ruleset.ruleset_hash,
        capability_sha256=capability.capability_hash,
        operator_approval_reference="PRIVATE-V1-LIVE-TRANSIENT-001A-test",
        operator_approved_at=ATTESTED,
        attestation_sha256="0" * 64,
    )
    return seal_private_transient_rules_authority(provisional)


def test_verified_rules_require_exact_private_authority(
    repository_root: Path, tmp_path: Path
) -> None:
    context = build_context(repository_root, tmp_path)
    verified = compile_ruleset(repository_root / "config/rules/fpl-2026-27")
    assert verified.status is RulesetStatus.VERIFIED
    capability = compile_capability_artifact(verified, RuleCapability.FULL_SEASON)
    path = write_declaration(context, context.declaration)
    request = bind_current_manager_state_request(path, context.fpl_input, verified, capability)

    def service() -> CurrentManagerStateService:
        times = iter((MANAGER_RECEIVED, MANAGER_USABLE))
        return CurrentManagerStateService(clock=lambda: next(times))

    with pytest.raises(IngestionError, match="ACTIVE target FULL_SEASON"):
        service().compile(
            request,
            fpl_input=context.fpl_input,
            ruleset=verified,
            capability=capability,
        )

    authority = _authority(verified, capability)
    result = service().compile(
        request,
        fpl_input=context.fpl_input,
        ruleset=verified,
        capability=capability,
        private_rules_authority=authority,
    )
    assert result.lineage.ruleset_sha256 == verified.ruleset_hash
    assert result.runtime.persistence_performed is False

    wrong = seal_private_transient_rules_authority(
        PrivateTransientRulesAuthority.model_construct(
            **{
                **authority.model_dump(
                    mode="python", exclude={"ruleset_sha256", "attestation_sha256"}
                ),
                "ruleset_sha256": "f" * 64,
                "attestation_sha256": "0" * 64,
            }
        )
    )
    with pytest.raises(IngestionError, match="target rules are invalid"):
        service().compile(
            request,
            fpl_input=context.fpl_input,
            ruleset=verified,
            capability=capability,
            private_rules_authority=wrong,
        )
    assert verified.status is RulesetStatus.VERIFIED


def test_active_manager_path_is_unchanged(repository_root: Path, tmp_path: Path) -> None:
    context = build_context(repository_root, tmp_path)
    path = write_declaration(context, context.declaration)
    request = bind_current_manager_state_request(
        path, context.fpl_input, context.ruleset, context.capability
    )
    times = iter((MANAGER_RECEIVED, MANAGER_USABLE))
    result = CurrentManagerStateService(clock=lambda: next(times)).compile(
        request,
        fpl_input=context.fpl_input,
        ruleset=context.ruleset,
        capability=context.capability,
    )
    assert result.lineage.ruleset_sha256 == context.ruleset.ruleset_hash
    assert context.ruleset.status is RulesetStatus.ACTIVE

    times = iter((MANAGER_RECEIVED, MANAGER_USABLE))
    with pytest.raises(IngestionError, match="applies only to VERIFIED"):
        CurrentManagerStateService(clock=lambda: next(times)).compile(
            request,
            fpl_input=context.fpl_input,
            ruleset=context.ruleset,
            capability=context.capability,
            private_rules_authority=_authority(context.ruleset, context.capability),
        )


def test_private_authority_rejects_unsealed_and_naive_times(repository_root: Path) -> None:
    ruleset = compile_ruleset(repository_root / "config/rules/fpl-2026-27")
    capability = compile_capability_artifact(ruleset, RuleCapability.FULL_SEASON)
    authority = _authority(ruleset, capability)

    with pytest.raises(ValidationError, match="attestation hash does not match"):
        PrivateTransientRulesAuthority.model_validate(
            authority.model_dump(mode="python") | {"attestation_sha256": "f" * 64}
        )
    with pytest.raises(ValidationError, match="timezone-aware"):
        PrivateTransientRulesAuthority.model_validate(
            authority.model_dump(mode="python")
            | {
                "operator_approved_at": datetime(2026, 8, 20, 12, 0),
                "attestation_sha256": "f" * 64,
            }
        )


def test_private_authority_validation_fails_closed_on_time_and_integrity(
    repository_root: Path,
) -> None:
    ruleset = compile_ruleset(repository_root / "config/rules/fpl-2026-27")
    capability = compile_capability_artifact(ruleset, RuleCapability.FULL_SEASON)
    authority = _authority(ruleset, capability)

    with pytest.raises(RulesValidationError, match="aware information cutoff"):
        validate_private_transient_rules_authority(
            authority,
            ruleset=ruleset,
            capability=capability,
            information_cutoff=datetime(2026, 8, 21, 17, 30),
        )
    with pytest.raises(RulesValidationError, match="does not bind"):
        validate_private_transient_rules_authority(
            authority,
            ruleset=ruleset,
            capability=capability,
            information_cutoff=authority.operator_approved_at - timedelta(seconds=1),
        )
    with pytest.raises(RulesValidationError, match="integrity validation"):
        validate_private_transient_rules_authority(
            authority,
            ruleset=ruleset.model_copy(update={"ruleset_hash": "f" * 64}),
            capability=capability,
            information_cutoff=datetime(2026, 8, 21, 17, 30, tzinfo=UTC),
        )
