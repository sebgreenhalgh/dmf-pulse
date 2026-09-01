"""Unified private transient source state for one current FPL decision context.

This module composes already-compiled in-memory inputs. It performs no acquisition, file I/O,
network access, database access, persistence, market normalisation, modelling, or optimisation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.current import CurrentFplInputBundle
from dmf_pulse.ingestion.fpl.manager_current import (
    CurrentManagerStateBundle,
    CurrentManagerStateService,
    current_fpl_catalogue_view_sha256,
)
from dmf_pulse.ingestion.odds.current import (
    OddsProviderCurrentInput,
    current_odds_market_semantic_sha256,
)
from dmf_pulse.ingestion.odds.identity import (
    FplOddsIdentityMap,
    bind_current_fixture_resolution_request,
    bind_current_team_resolution_request,
    current_fpl_identity_view_sha256,
    current_odds_identity_semantic_sha256,
    current_odds_provider_provenance_sha256,
    resolve_current_fixture_identities,
    resolve_current_team_identities,
)
from dmf_pulse.rules.models import CapabilityArtifact, CompiledRuleset
from dmf_pulse.rules.private_transient import PrivateTransientRulesAuthority

CURRENT_UNIFIED_STATE_CONTRACT_VERSION: Literal["current-unified-state-v1"] = (
    "current-unified-state-v1"
)

_LIMITATIONS = (
    "MANAGER_STATE_HUMAN_ATTESTED_NOT_PROVIDER_VERIFIED",
    "OFFICIAL_FPL_INPUT_MANUAL_TRANSIENT_ONLY",
    "CURRENT_FREE_HIT_REMAINS_SUBJECT_TO_MANAGER_STATE_BLOCK",
    "NO_AVAILABILITY_OR_MINUTES_MODEL",
    "NO_MARKET_CONSENSUS_OR_NORMALISATION",
    "NO_FOOTBALL_EVENT_PROBABILITIES",
    "NO_FPL_POINTS_PROJECTIONS",
    "NO_OPTIMISATION",
    "NO_DECISION_BUNDLE",
    "NO_PRODUCTION_ACTIVATION",
)
_PROVIDER_LIMITATIONS = (
    *(
        item
        for item in _LIMITATIONS
        if item
        not in {
            "MANAGER_STATE_HUMAN_ATTESTED_NOT_PROVIDER_VERIFIED",
            "OFFICIAL_FPL_INPUT_MANUAL_TRANSIENT_ONLY",
        }
    ),
    "MANAGER_STATE_PROVIDER_OBSERVED_PRIVATE_TRANSIENT",
    "OFFICIAL_FPL_OPERATOR_INITIATED_DIRECT_READ",
)


def _limitations(manager: CurrentManagerStateBundle) -> tuple[str, ...]:
    return _LIMITATIONS if manager.source_class == "OPERATOR_DECLARED" else _PROVIDER_LIMITATIONS


def _normalize_utc(value: datetime, *, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)


Sha256 = str


def current_fpl_full_representation_sha256(value: CurrentFplInputBundle) -> str:
    """Bind the complete materialized 001A object supplied to this 001D boundary.

    This local integrity digest neither authenticates official FPL nor replaces 001A's
    acquisition/source semantic digest. The accepted 001A catalogues are identity-keyed, so their
    construction order is non-semantic and is normalized before canonical hashing.
    """

    payload = value.model_dump(mode="json")
    payload["events"] = sorted(payload["events"], key=lambda item: item["provider_event_id"])
    payload["teams"] = sorted(payload["teams"], key=lambda item: item["provider_team_id"])
    payload["positions"] = sorted(
        payload["positions"],
        key=lambda item: (item["canonical_position"], item["provider_element_type_id"]),
    )
    payload["players"] = sorted(payload["players"], key=lambda item: item["provider_element_id"])
    payload["fixtures"] = sorted(payload["fixtures"], key=lambda item: item["provider_fixture_id"])
    return canonical_sha256(
        {
            "contract_version": "current-unified-state-fpl-full-representation-v1",
            "fpl_input": payload,
        }
    )


class CurrentUnifiedStateRequest(_FrozenModel):
    """Path-free binding of every accepted source needed by the composition."""

    contract_version: Literal["current-unified-state-v1"] = CURRENT_UNIFIED_STATE_CONTRACT_VERSION
    target_gameweek: int = Field(gt=0)
    information_cutoff: datetime
    fpl_input_semantic_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    fpl_full_representation_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    fpl_identity_view_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    fpl_catalogue_view_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    odds_market_semantic_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    odds_identity_semantic_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    odds_provider_provenance_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    fpl_odds_identity_map_semantic_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    manager_state_semantic_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    manager_declaration_semantic_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    ruleset_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    full_season_capability_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("information_cutoff")
    @classmethod
    def normalize_cutoff(cls, value: datetime) -> datetime:
        return _normalize_utc(value, label="unified state information cutoff")


class CurrentUnifiedStateLineage(_FrozenModel):
    fpl_input_semantic_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    fpl_full_representation_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    fpl_identity_view_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    fpl_catalogue_view_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    fpl_provider_config_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    fpl_rights_config_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    target_gameweek_identity_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    odds_market_semantic_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    odds_identity_semantic_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    odds_provider_provenance_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    odds_provider_config_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    odds_rights_config_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    fpl_odds_identity_map_semantic_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    fpl_odds_identity_map_source_lineage_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    manager_state_semantic_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    manager_declaration_semantic_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    ruleset_id: str = Field(min_length=1, max_length=100)
    ruleset_version: str = Field(min_length=1, max_length=100)
    ruleset_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    full_season_capability_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    selling_price_rule_semantic_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    chip_bundle_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    chip_inventory_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")


class CurrentUnifiedRightsBoundary(_FrozenModel):
    """Conservative whole-bundle rights while retaining distinct source access rights."""

    official_fpl_automated_access: Literal["ALLOW", "DENY"] = "DENY"
    odds_automated_access: Literal["ALLOW"] = "ALLOW"
    private_internal_use: Literal["ALLOW"] = "ALLOW"
    transient_processing: Literal["ALLOW"] = "ALLOW"
    persistent_storage: Literal["DENY"] = "DENY"
    derived_storage: Literal["DENY"] = "DENY"
    raw_storage: Literal["DENY"] = "DENY"
    cache: Literal["DENY"] = "DENY"
    backup: Literal["DENY"] = "DENY"
    public_display: Literal["DENY"] = "DENY"
    redistribution: Literal["DENY"] = "DENY"


class CurrentUnifiedRuntimeBoundary(_FrozenModel):
    storage_mode: Literal["TRANSIENT_IN_MEMORY"] = "TRANSIENT_IN_MEMORY"
    persistence_performed: Literal[False] = False
    database_accessed: Literal[False] = False
    network_called: Literal[False] = False


class CurrentUnifiedStateSummary(_FrozenModel):
    """Disclosure-minimized representation safe for ordinary logs and evidence."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    contract: Literal["CURRENT_UNIFIED_STATE_SUMMARY"] = "CURRENT_UNIFIED_STATE_SUMMARY"
    status: Literal["USABLE"] = "USABLE"
    season_code: Literal["2026/27"] = "2026/27"
    target_gameweek: int = Field(gt=0)
    target_deadline_at: datetime
    information_cutoff: datetime
    decision_information_at: datetime
    fpl_team_count: int = Field(gt=0)
    fpl_player_count: int = Field(gt=0)
    target_fpl_fixture_count: int = Field(gt=0)
    odds_event_count: int = Field(gt=0)
    mapped_target_fixture_count: int = Field(gt=0)
    manager_squad_count: int = Field(gt=0)
    identity_coverage: Literal["COMPLETE"] = "COMPLETE"
    manager_source_class: Literal["OPERATOR_DECLARED", "PROVIDER_OBSERVED"] = "OPERATOR_DECLARED"
    manager_attestation_status: Literal["HUMAN_ATTESTED", "PROVIDER_OBSERVED"] = "HUMAN_ATTESTED"
    manager_provider_verification: Literal["NOT_PROVIDER_VERIFIED", "PROVIDER_VERIFIED"] = (
        "NOT_PROVIDER_VERIFIED"
    )
    lineage: CurrentUnifiedStateLineage
    rights: CurrentUnifiedRightsBoundary
    runtime: CurrentUnifiedRuntimeBoundary
    unified_state_semantic_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("target_deadline_at", "information_cutoff", "decision_information_at")
    @classmethod
    def normalize_times(cls, value: datetime) -> datetime:
        return _normalize_utc(value, label="unified state summary timestamp")


class CurrentUnifiedStateBundle(_FrozenModel):
    """One immutable, private and transient current decision-source composition."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    contract: Literal["CURRENT_UNIFIED_STATE_BUNDLE"] = "CURRENT_UNIFIED_STATE_BUNDLE"
    contract_version: Literal["current-unified-state-v1"] = CURRENT_UNIFIED_STATE_CONTRACT_VERSION
    status: Literal["USABLE"] = "USABLE"
    competition_key: Literal["PL"] = "PL"
    season_code: Literal["2026/27"] = "2026/27"
    target_gameweek: int = Field(gt=0)
    target_gameweek_identity_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    target_deadline_at: datetime
    information_cutoff: datetime
    decision_information_at: datetime
    fpl_input: CurrentFplInputBundle
    odds_input: OddsProviderCurrentInput
    identity_map: FplOddsIdentityMap
    manager_state: CurrentManagerStateBundle
    lineage: CurrentUnifiedStateLineage
    rights: CurrentUnifiedRightsBoundary
    runtime: CurrentUnifiedRuntimeBoundary
    limitations: tuple[str, ...]
    semantic_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("target_deadline_at", "information_cutoff", "decision_information_at")
    @classmethod
    def normalize_times(cls, value: datetime) -> datetime:
        return _normalize_utc(value, label="unified state timestamp")

    @model_validator(mode="after")
    def composition_is_internally_sealed(self) -> Self:
        fpl = self.fpl_input
        odds = self.odds_input
        identity_map = self.identity_map
        manager = self.manager_state
        expected_decision_time = max(
            fpl.provenance.usable_at,
            odds.temporal.usable_at,
            identity_map.mapping_decided_at,
            manager.usable_at,
        )
        if (
            self.competition_key != fpl.competition_key
            or self.season_code != fpl.season_code
            or self.target_gameweek != fpl.target_gameweek
            or self.target_gameweek_identity_sha256
            != fpl.target_event.identity.canonical_lookup_sha256
            or self.target_deadline_at != fpl.target_event.deadline_at
            or self.information_cutoff != fpl.provenance.information_cutoff
            or self.information_cutoff != odds.temporal.information_cutoff
            or self.information_cutoff != identity_map.information_cutoff
            or self.information_cutoff != manager.information_cutoff
            or self.information_cutoff > self.target_deadline_at
            or self.decision_information_at != expected_decision_time
            or self.decision_information_at > self.information_cutoff
            or self.lineage != _build_lineage(fpl, odds, identity_map, manager)
            or self.limitations != _limitations(manager)
            or self.rights.official_fpl_automated_access
            != ("ALLOW" if manager.source_class == "PROVIDER_OBSERVED" else "DENY")
            or self.semantic_sha256 != current_unified_state_semantic_sha256(self)
        ):
            raise ValueError("unified current state composition is inconsistent")
        return self

    def safe_summary(self) -> CurrentUnifiedStateSummary:
        return CurrentUnifiedStateSummary(
            target_gameweek=self.target_gameweek,
            target_deadline_at=self.target_deadline_at,
            information_cutoff=self.information_cutoff,
            decision_information_at=self.decision_information_at,
            fpl_team_count=len(self.fpl_input.teams),
            fpl_player_count=len(self.fpl_input.players),
            target_fpl_fixture_count=self.identity_map.coverage.target_fpl_fixture_count,
            odds_event_count=len(self.odds_input.events),
            mapped_target_fixture_count=self.identity_map.coverage.mapped_event_count,
            manager_squad_count=len(self.manager_state.squad),
            manager_source_class=self.manager_state.source_class,
            manager_attestation_status=self.manager_state.attestation_status,
            manager_provider_verification=self.manager_state.provider_verification,
            lineage=self.lineage,
            rights=self.rights,
            runtime=self.runtime,
            unified_state_semantic_sha256=self.semantic_sha256,
        )


def _build_lineage(
    fpl_input: CurrentFplInputBundle,
    odds_input: OddsProviderCurrentInput,
    identity_map: FplOddsIdentityMap,
    manager_state: CurrentManagerStateBundle,
) -> CurrentUnifiedStateLineage:
    manager_lineage = manager_state.lineage
    return CurrentUnifiedStateLineage(
        fpl_input_semantic_sha256=fpl_input.semantic_sha256,
        fpl_full_representation_sha256=current_fpl_full_representation_sha256(fpl_input),
        fpl_identity_view_sha256=current_fpl_identity_view_sha256(fpl_input),
        fpl_catalogue_view_sha256=current_fpl_catalogue_view_sha256(fpl_input),
        fpl_provider_config_sha256=fpl_input.provenance.provider_config_sha256,
        fpl_rights_config_sha256=fpl_input.provenance.rights_config_sha256,
        target_gameweek_identity_sha256=fpl_input.target_event.identity.canonical_lookup_sha256,
        odds_market_semantic_sha256=odds_input.market_semantic_sha256,
        odds_identity_semantic_sha256=current_odds_identity_semantic_sha256(odds_input),
        odds_provider_provenance_sha256=current_odds_provider_provenance_sha256(odds_input),
        odds_provider_config_sha256=odds_input.provenance.provider_config_sha256,
        odds_rights_config_sha256=odds_input.provenance.rights_config_sha256,
        fpl_odds_identity_map_semantic_sha256=identity_map.semantic_sha256,
        fpl_odds_identity_map_source_lineage_sha256=identity_map.source_lineage_sha256,
        manager_state_semantic_sha256=manager_state.semantic_sha256,
        manager_declaration_semantic_sha256=(manager_lineage.manager_declaration_semantic_sha256),
        ruleset_id=manager_lineage.ruleset_id,
        ruleset_version=manager_lineage.ruleset_version,
        ruleset_sha256=manager_lineage.ruleset_sha256,
        full_season_capability_sha256=manager_lineage.full_season_capability_sha256,
        selling_price_rule_semantic_sha256=(manager_lineage.selling_price_rule_semantic_sha256),
        chip_bundle_sha256=manager_lineage.chip_bundle_sha256,
        chip_inventory_sha256=manager_lineage.chip_inventory_sha256,
    )


def current_unified_state_semantic_sha256(value: CurrentUnifiedStateBundle) -> str:
    """Hash only canonical composition identity, never embedded paths or incidental ordering."""

    return canonical_sha256(
        {
            "contract": value.contract,
            "contract_version": value.contract_version,
            "schema_version": value.schema_version,
            "status": value.status,
            "competition_key": value.competition_key,
            "season_code": value.season_code,
            "target_gameweek": value.target_gameweek,
            "target_gameweek_identity_sha256": value.target_gameweek_identity_sha256,
            "target_deadline_at": value.target_deadline_at.isoformat(),
            "information_cutoff": value.information_cutoff.isoformat(),
            "decision_information_at": value.decision_information_at.isoformat(),
            "lineage": value.lineage.model_dump(mode="json"),
            "rights": value.rights.model_dump(mode="json"),
            "runtime": value.runtime.model_dump(mode="json"),
            "limitations": list(value.limitations),
        }
    )


def bind_current_unified_state_request(
    fpl_input: CurrentFplInputBundle,
    odds_input: OddsProviderCurrentInput,
    identity_map: FplOddsIdentityMap,
    manager_state: CurrentManagerStateBundle,
    ruleset: CompiledRuleset,
    capability: CapabilityArtifact,
) -> CurrentUnifiedStateRequest:
    """Bind exact in-memory source identities before composition."""

    return CurrentUnifiedStateRequest(
        target_gameweek=fpl_input.target_gameweek,
        information_cutoff=fpl_input.provenance.information_cutoff,
        fpl_input_semantic_sha256=fpl_input.semantic_sha256,
        fpl_full_representation_sha256=current_fpl_full_representation_sha256(fpl_input),
        fpl_identity_view_sha256=current_fpl_identity_view_sha256(fpl_input),
        fpl_catalogue_view_sha256=current_fpl_catalogue_view_sha256(fpl_input),
        odds_market_semantic_sha256=odds_input.market_semantic_sha256,
        odds_identity_semantic_sha256=current_odds_identity_semantic_sha256(odds_input),
        odds_provider_provenance_sha256=current_odds_provider_provenance_sha256(odds_input),
        fpl_odds_identity_map_semantic_sha256=identity_map.semantic_sha256,
        manager_state_semantic_sha256=manager_state.semantic_sha256,
        manager_declaration_semantic_sha256=(
            manager_state.lineage.manager_declaration_semantic_sha256
        ),
        ruleset_sha256=ruleset.ruleset_hash,
        full_season_capability_sha256=capability.capability_hash,
    )


def _revalidate_models(
    fpl_input: CurrentFplInputBundle,
    odds_input: OddsProviderCurrentInput,
    identity_map: FplOddsIdentityMap,
    manager_state: CurrentManagerStateBundle,
    ruleset: CompiledRuleset,
    capability: CapabilityArtifact,
) -> tuple[
    CurrentFplInputBundle,
    OddsProviderCurrentInput,
    FplOddsIdentityMap,
    CurrentManagerStateBundle,
    CompiledRuleset,
    CapabilityArtifact,
]:
    try:
        return (
            CurrentFplInputBundle.model_validate(fpl_input.model_dump(mode="python")),
            OddsProviderCurrentInput.model_validate(odds_input.model_dump(mode="python")),
            FplOddsIdentityMap.model_validate(identity_map.model_dump(mode="python")),
            CurrentManagerStateBundle.model_validate(manager_state.model_dump(mode="python")),
            CompiledRuleset.model_validate(ruleset.model_dump(mode="python")),
            CapabilityArtifact.model_validate(capability.model_dump(mode="python")),
        )
    except ValidationError:
        raise IngestionError(
            "MAPPING_CONFLICT", "unified current source failed structural revalidation"
        ) from None


def _require_request_bindings(
    request: CurrentUnifiedStateRequest,
    fpl_input: CurrentFplInputBundle,
    odds_input: OddsProviderCurrentInput,
    identity_map: FplOddsIdentityMap,
    manager_state: CurrentManagerStateBundle,
    ruleset: CompiledRuleset,
    capability: CapabilityArtifact,
) -> None:
    expected = bind_current_unified_state_request(
        fpl_input, odds_input, identity_map, manager_state, ruleset, capability
    )
    if request != expected:
        raise IngestionError("MAPPING_CONFLICT", "unified state request bindings are inconsistent")
    if odds_input.market_semantic_sha256 != current_odds_market_semantic_sha256(odds_input):
        raise IngestionError(
            "MAPPING_CONFLICT", "current Odds market semantic hash is inconsistent"
        )


def _verify_identity_map(
    identity_map: FplOddsIdentityMap,
    fpl_input: CurrentFplInputBundle,
    odds_input: OddsProviderCurrentInput,
) -> None:
    try:
        team_plan = identity_map.team_alias_plan
        team_request = bind_current_team_resolution_request(
            fpl_input,
            odds_input,
            team_plan,
            mapping_decided_at=identity_map.mapping_decided_at,
        )
        team_map = resolve_current_team_identities(fpl_input, odds_input, team_plan, team_request)
        fixture_plan = identity_map.fixture_mapping_plan
        fixture_request = bind_current_fixture_resolution_request(
            fpl_input,
            odds_input,
            team_plan,
            team_map,
            fixture_plan,
            mapping_decided_at=identity_map.mapping_decided_at,
        )
        expected = resolve_current_fixture_identities(
            fpl_input,
            odds_input,
            team_plan,
            team_map,
            fixture_plan,
            fixture_request,
        )
    except IngestionError:
        raise IngestionError(
            "MAPPING_CONFLICT", "FPL/Odds identity reconstruction failed"
        ) from None
    if identity_map != expected:
        raise IngestionError(
            "MAPPING_CONFLICT", "FPL/Odds identity map differs from its exact current sources"
        )


def _verify_manager_catalogue(
    manager_state: CurrentManagerStateBundle,
    fpl_input: CurrentFplInputBundle,
) -> None:
    players = {player.provider_element_id: player for player in fpl_input.players}
    if len(players) != len(fpl_input.players):
        raise IngestionError("MAPPING_CONFLICT", "current FPL player identities are ambiguous")
    for member in manager_state.squad:
        player = players.get(member.official_fpl_element_id)
        if (
            player is None
            or member.player_identity != player.identity
            or member.team_identity != player.team_identity
            or member.position != player.position
            or member.current_price_tenths != player.current_price_tenths
            or member.source_semantic_sha256 != player.source_semantic_sha256
        ):
            raise IngestionError(
                "MAPPING_CONFLICT", "current manager squad differs from the supplied FPL catalogue"
            )


def _verify_external_family(
    request: CurrentUnifiedStateRequest,
    fpl_input: CurrentFplInputBundle,
    odds_input: OddsProviderCurrentInput,
    identity_map: FplOddsIdentityMap,
    manager_state: CurrentManagerStateBundle,
    ruleset: CompiledRuleset,
    capability: CapabilityArtifact,
    private_rules_authority: PrivateTransientRulesAuthority | None,
) -> None:
    _require_request_bindings(
        request, fpl_input, odds_input, identity_map, manager_state, ruleset, capability
    )
    _verify_identity_map(identity_map, fpl_input, odds_input)
    try:
        checked_manager = CurrentManagerStateService().verify(
            manager_state,
            fpl_input=fpl_input,
            ruleset=ruleset,
            capability=capability,
            private_rules_authority=private_rules_authority,
        )
    except IngestionError:
        raise IngestionError("MAPPING_CONFLICT", "current manager reconstruction failed") from None
    _verify_manager_catalogue(checked_manager, fpl_input)
    cutoff = request.information_cutoff
    if not (
        cutoff
        == fpl_input.provenance.information_cutoff
        == odds_input.temporal.information_cutoff
        == identity_map.information_cutoff
        == manager_state.information_cutoff
    ):
        raise IngestionError("MAPPING_CONFLICT", "unified source cutoffs are not identical")
    if cutoff > fpl_input.target_event.deadline_at:
        raise IngestionError("POST_CUTOFF", "unified source cutoff exceeds the target deadline")
    expected_manager_provenance = (
        ("OPERATOR_DECLARED", "HUMAN_ATTESTED", "NOT_PROVIDER_VERIFIED")
        if fpl_input.provenance.acquisition_mode == "MANUAL_OPERATOR_CAPTURE"
        else ("PROVIDER_OBSERVED", "PROVIDER_OBSERVED", "PROVIDER_VERIFIED")
    )
    if (
        manager_state.source_class,
        manager_state.attestation_status,
        manager_state.provider_verification,
    ) != expected_manager_provenance:
        raise IngestionError("MAPPING_CONFLICT", "manager verification class is inconsistent")


class CurrentUnifiedStateService:
    """Compose and independently verify one coherent in-memory current source family."""

    def compose(
        self,
        request: CurrentUnifiedStateRequest,
        *,
        fpl_input: CurrentFplInputBundle,
        odds_input: OddsProviderCurrentInput,
        identity_map: FplOddsIdentityMap,
        manager_state: CurrentManagerStateBundle,
        ruleset: CompiledRuleset,
        capability: CapabilityArtifact,
        private_rules_authority: PrivateTransientRulesAuthority | None = None,
    ) -> CurrentUnifiedStateBundle:
        fpl, odds, bridge, manager, checked_ruleset, checked_capability = _revalidate_models(
            fpl_input, odds_input, identity_map, manager_state, ruleset, capability
        )
        _verify_external_family(
            request,
            fpl,
            odds,
            bridge,
            manager,
            checked_ruleset,
            checked_capability,
            private_rules_authority,
        )
        decision_information_at = max(
            fpl.provenance.usable_at,
            odds.temporal.usable_at,
            bridge.mapping_decided_at,
            manager.usable_at,
        )
        if decision_information_at > request.information_cutoff:
            raise IngestionError("POST_CUTOFF", "required source was not usable by the cutoff")
        provisional = CurrentUnifiedStateBundle.model_construct(
            target_gameweek=fpl.target_gameweek,
            target_gameweek_identity_sha256=fpl.target_event.identity.canonical_lookup_sha256,
            target_deadline_at=fpl.target_event.deadline_at,
            information_cutoff=request.information_cutoff,
            decision_information_at=decision_information_at,
            fpl_input=fpl,
            odds_input=odds,
            identity_map=bridge,
            manager_state=manager,
            lineage=_build_lineage(fpl, odds, bridge, manager),
            rights=CurrentUnifiedRightsBoundary(
                official_fpl_automated_access=(
                    "ALLOW" if manager.source_class == "PROVIDER_OBSERVED" else "DENY"
                )
            ),
            runtime=CurrentUnifiedRuntimeBoundary(),
            limitations=_limitations(manager),
            semantic_sha256="0" * 64,
        )
        payload = provisional.model_dump(mode="python")
        payload["semantic_sha256"] = current_unified_state_semantic_sha256(provisional)
        return CurrentUnifiedStateBundle.model_validate(payload)

    def verify(
        self,
        value: CurrentUnifiedStateBundle,
        request: CurrentUnifiedStateRequest,
        *,
        fpl_input: CurrentFplInputBundle,
        odds_input: OddsProviderCurrentInput,
        identity_map: FplOddsIdentityMap,
        manager_state: CurrentManagerStateBundle,
        ruleset: CompiledRuleset,
        capability: CapabilityArtifact,
        private_rules_authority: PrivateTransientRulesAuthority | None = None,
    ) -> CurrentUnifiedStateBundle:
        try:
            checked = CurrentUnifiedStateBundle.model_validate(value.model_dump(mode="python"))
        except ValidationError:
            raise IngestionError(
                "MAPPING_CONFLICT", "unified current state failed structural revalidation"
            ) from None
        expected = self.compose(
            request,
            fpl_input=fpl_input,
            odds_input=odds_input,
            identity_map=identity_map,
            manager_state=manager_state,
            ruleset=ruleset,
            capability=capability,
            private_rules_authority=private_rules_authority,
        )
        if checked != expected:
            raise IngestionError(
                "MAPPING_CONFLICT", "unified current state differs from its exact source family"
            )
        return checked


__all__ = [
    "CURRENT_UNIFIED_STATE_CONTRACT_VERSION",
    "CurrentUnifiedRightsBoundary",
    "CurrentUnifiedRuntimeBoundary",
    "CurrentUnifiedStateBundle",
    "CurrentUnifiedStateLineage",
    "CurrentUnifiedStateRequest",
    "CurrentUnifiedStateService",
    "CurrentUnifiedStateSummary",
    "bind_current_unified_state_request",
    "current_fpl_full_representation_sha256",
    "current_unified_state_semantic_sha256",
]
