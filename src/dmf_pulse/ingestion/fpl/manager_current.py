"""Private transient compilation of operator-declared current manager state.

The operator declaration is human-attested and explicitly not provider verified.  This module
does not authenticate, call a provider, access a database, or persist either source or derived
state.  It resolves catalogue-owned facts through the accepted CURRENT-FPL-STATE-001A bundle and
compiles every rule-owned fact from one ACTIVE FULL_SEASON ruleset.  A separate explicit private
transient authority may admit one exact VERIFIED ruleset without changing the ordinary contract.
"""

from __future__ import annotations

import json
import os
import stat
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, Self

from pydantic import (
    BaseModel,
    Field,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.chips.compiler import compile_optimisation_chip_rules
from dmf_pulse.chips.definitions import CompiledChipBundle
from dmf_pulse.chips.errors import ChipError
from dmf_pulse.chips.inventory import (
    ChipInventory,
    TokenStatus,
    activate_token,
    advance_inventory,
    build_chip_inventory,
    select_token,
    validate_chip_inventory,
)
from dmf_pulse.fpl_points.models import PlayerPosition, ProjectionMode
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.current import (
    CurrentFplIdentity,
    CurrentFplInputBundle,
    CurrentFplPositionDefinition,
)
from dmf_pulse.ingestion.models import FrozenModel
from dmf_pulse.optimisation.manager_state import selling_price_tenths
from dmf_pulse.optimisation.models import OneGameweekRulesView
from dmf_pulse.optimisation.multi_gameweek_models import TransferRules
from dmf_pulse.rules.capabilities import compile_capability_artifact
from dmf_pulse.rules.chips import build_chip_rules_view
from dmf_pulse.rules.compiler import ensure_compiled_ruleset_integrity
from dmf_pulse.rules.errors import RulesError
from dmf_pulse.rules.models import (
    CapabilityArtifact,
    CompiledRuleset,
    FPLPosition,
    RuleCapability,
    RulesetStatus,
)
from dmf_pulse.rules.multi_gameweek import build_multi_gameweek_transfer_rules
from dmf_pulse.rules.one_gameweek import build_one_gameweek_rules_view
from dmf_pulse.rules.private_transient import (
    PrivateTransientRulesAuthority,
    validate_private_transient_rules_authority,
)

if TYPE_CHECKING:
    from dmf_pulse.ingestion.fpl.manager_provider import ProviderCurrentTeam

CURRENT_MANAGER_CONTRACT_VERSION: Literal["current-manager-state-v1"] = "current-manager-state-v1"
MAX_MANAGER_DECLARATION_BYTES = 262_144
SUPPORTED_FPL_SEASON_CODE: Literal["2026/27"] = "2026/27"
SUPPORTED_RULES_SEASON_CODE: Literal["2026/2027"] = "2026/2027"

Sha256 = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
DeclaredTokenStatus = Literal[
    "UNAVAILABLE",
    "AVAILABLE",
    "PENDING_CANCELLABLE",
    "ACTIVE",
    "USED",
    "EXPIRED",
]

_LIMITATIONS = (
    "MANAGER_FACTS_HUMAN_ATTESTED_NOT_PROVIDER_VERIFIED",
    "NO_AUTOMATED_FPL_MANAGER_ACQUISITION",
    "NO_ACCOUNT_CREDENTIALS_OR_IDENTIFIERS",
    "NO_PERSISTENCE_CACHE_BACKUP_OR_DATABASE",
    "OPTIONAL_POINTS_AND_RANK_MAY_BE_ABSENT",
    "ACTIVE_OR_PENDING_FREE_HIT_REQUIRES_UNAVAILABLE_RESTORATION_STATE",
    "CLUB_QUOTA_GRANDFATHERING_NOT_INFERRED",
    "NOT_THE_UNIFIED_CURRENT_FPL_STATE_001D_BUNDLE",
    "NO_DOWNSTREAM_OPTIMISATION_EXECUTED",
)
_PROVIDER_LIMITATIONS = (
    "MANAGER_FACTS_PROVIDER_OBSERVED_AT_INFORMATION_CUTOFF",
    "OFFICIAL_FPL_RESPONSE_MEMORY_ONLY",
    "NO_PERSISTENCE_CACHE_BACKUP_OR_DATABASE",
    "ACTIVE_OR_PENDING_FREE_HIT_REQUIRES_UNAVAILABLE_RESTORATION_STATE",
    "CLUB_QUOTA_GRANDFATHERING_NOT_INFERRED",
    "NOT_THE_UNIFIED_CURRENT_FPL_STATE_001D_BUNDLE",
    "NO_DOWNSTREAM_OPTIMISATION_EXECUTED",
)


def _normalize_utc(value: datetime, *, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


class CurrentManagerAttestation(FrozenModel):
    """Explicit human attestation without an account identity or credential."""

    declaration_method: Literal["OPERATOR_DECLARED", "PROVIDER_OBSERVED"] = "OPERATOR_DECLARED"
    attestation_status: Literal["HUMAN_ATTESTED", "PROVIDER_OBSERVED"] = "HUMAN_ATTESTED"
    provider_verification: Literal["NOT_PROVIDER_VERIFIED", "PROVIDER_VERIFIED"] = (
        "NOT_PROVIDER_VERIFIED"
    )
    declared_at: datetime
    attested_at: datetime
    operator_reference: StrictStr = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
    )

    @field_validator("declared_at", "attested_at")
    @classmethod
    def normalize_times(cls, value: datetime) -> datetime:
        return _normalize_utc(value, label="current manager attestation timestamp")

    @model_validator(mode="after")
    def chronology_is_valid(self) -> Self:
        if self.attested_at < self.declared_at:
            raise ValueError("manager attestation cannot precede declaration")
        expected = (
            ("OPERATOR_DECLARED", "HUMAN_ATTESTED", "NOT_PROVIDER_VERIFIED")
            if self.declaration_method == "OPERATOR_DECLARED"
            else ("PROVIDER_OBSERVED", "PROVIDER_OBSERVED", "PROVIDER_VERIFIED")
        )
        if (
            self.declaration_method,
            self.attestation_status,
            self.provider_verification,
        ) != expected:
            raise ValueError("manager attestation source labels are inconsistent")
        return self


class CurrentManagerPlayerDeclaration(FrozenModel):
    """Only manager-specific player facts that the 001A catalogue cannot derive."""

    official_fpl_element_id: PositiveInt
    purchase_price_tenths: PositiveInt
    observed_selling_price_tenths: PositiveInt | None = None


class CurrentManagerLineupDeclaration(FrozenModel):
    """Submitted lineup; starting-XI order is non-semantic, bench order is semantic."""

    starting_xi_element_ids: tuple[PositiveInt, ...] = Field(min_length=1)
    bench_goalkeeper_element_id: PositiveInt
    bench_outfield_element_ids: tuple[PositiveInt, ...] = Field(min_length=1)
    captain_element_id: PositiveInt
    vice_captain_element_id: PositiveInt


class CurrentManagerChipDeclaration(FrozenModel):
    """One declaration for one deterministic configured chip token."""

    token_id: StrictStr = Field(min_length=1, max_length=240)
    status: DeclaredTokenStatus
    selected_at_gameweek: PositiveInt | None = None
    active_from_gameweek: PositiveInt | None = None
    used_at_gameweek: PositiveInt | None = None

    @model_validator(mode="after")
    def metadata_matches_status(self) -> Self:
        if self.status == "PENDING_CANCELLABLE":
            if self.selected_at_gameweek is None or any(
                value is not None for value in (self.active_from_gameweek, self.used_at_gameweek)
            ):
                raise ValueError("pending chip declaration metadata is inconsistent")
        elif self.status == "ACTIVE":
            if self.active_from_gameweek is None or any(
                value is not None for value in (self.selected_at_gameweek, self.used_at_gameweek)
            ):
                raise ValueError("active chip declaration metadata is inconsistent")
        elif self.status == "USED":
            if self.used_at_gameweek is None or any(
                value is not None
                for value in (self.selected_at_gameweek, self.active_from_gameweek)
            ):
                raise ValueError("used chip declaration metadata is inconsistent")
        elif any(
            value is not None
            for value in (
                self.selected_at_gameweek,
                self.active_from_gameweek,
                self.used_at_gameweek,
            )
        ):
            raise ValueError("inactive chip declaration cannot contain transition metadata")
        return self


class CurrentManagerDeclaration(FrozenModel):
    """Strict operator-owned declaration parsed from one bounded local JSON object."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    source_class: Literal["OPERATOR_DECLARED", "PROVIDER_OBSERVED"] = "OPERATOR_DECLARED"
    season_code: Literal["2026/27"] = SUPPORTED_FPL_SEASON_CODE
    target_gameweek: PositiveInt
    information_cutoff: datetime
    attestation: CurrentManagerAttestation
    squad: tuple[CurrentManagerPlayerDeclaration, ...] = Field(min_length=1)
    bank_tenths: NonNegativeInt
    free_transfers: NonNegativeInt
    lineup: CurrentManagerLineupDeclaration
    chip_tokens: tuple[CurrentManagerChipDeclaration, ...] = Field(min_length=1)
    overall_points: NonNegativeInt | None = None
    overall_rank: PositiveInt | None = None

    @field_validator("information_cutoff")
    @classmethod
    def normalize_cutoff(cls, value: datetime) -> datetime:
        return _normalize_utc(value, label="current manager information cutoff")

    @model_validator(mode="after")
    def declarations_are_unique(self) -> Self:
        element_ids = tuple(item.official_fpl_element_id for item in self.squad)
        if len(element_ids) != len(set(element_ids)):
            raise ValueError("manager squad declarations must be unique")
        token_ids = tuple(item.token_id for item in self.chip_tokens)
        if len(token_ids) != len(set(token_ids)):
            raise ValueError("manager chip-token declarations must be unique")
        if self.source_class != self.attestation.declaration_method:
            raise ValueError("manager declaration and attestation sources differ")
        return self


def canonical_current_manager_declaration(
    value: CurrentManagerDeclaration,
) -> CurrentManagerDeclaration:
    """Canonicalise only the declaration collections whose order has no meaning."""

    lineup = value.lineup.model_copy(
        update={
            "starting_xi_element_ids": tuple(sorted(value.lineup.starting_xi_element_ids)),
        }
    )
    return value.model_copy(
        update={
            "squad": tuple(sorted(value.squad, key=lambda item: item.official_fpl_element_id)),
            "lineup": lineup,
            "chip_tokens": tuple(sorted(value.chip_tokens, key=lambda item: item.token_id)),
        }
    )


def current_manager_declaration_semantic_sha256(value: CurrentManagerDeclaration) -> str:
    canonical = canonical_current_manager_declaration(value)
    return canonical_sha256(canonical.model_dump(mode="json"))


class CurrentManagerStateRequest(FrozenModel):
    """Hash-bound request; the machine-specific declaration path is not semantic output."""

    declaration_path: Path
    target_gameweek: PositiveInt
    information_cutoff: datetime
    fpl_input_semantic_sha256: Sha256
    fpl_catalogue_view_sha256: Sha256
    ruleset_sha256: Sha256
    full_season_capability_sha256: Sha256

    @field_validator("information_cutoff")
    @classmethod
    def normalize_cutoff(cls, value: datetime) -> datetime:
        return _normalize_utc(value, label="bound current manager cutoff")


class CurrentManagerSquadMember(FrozenModel):
    """Catalogue-resolved current member without fabricated ownership history."""

    season_code: Literal["2026/27"] = SUPPORTED_FPL_SEASON_CODE
    official_fpl_element_id: PositiveInt
    player_identity: CurrentFplIdentity
    team_identity: CurrentFplIdentity
    position: FPLPosition
    purchase_price_tenths: PositiveInt
    current_price_tenths: PositiveInt
    selling_price_tenths: PositiveInt
    source_semantic_sha256: Sha256

    @model_validator(mode="after")
    def identities_match_member(self) -> Self:
        if (
            self.player_identity.entity_type != "PLAYER"
            or self.player_identity.external_id_text != str(self.official_fpl_element_id)
            or self.player_identity.season_code != self.season_code
            or self.team_identity.entity_type != "TEAM"
            or self.team_identity.season_code != self.season_code
        ):
            raise ValueError("current manager member identity is inconsistent")
        return self


class CurrentManagerLineup(FrozenModel):
    starting_xi_element_ids: tuple[PositiveInt, ...]
    bench_goalkeeper_element_id: PositiveInt
    bench_outfield_element_ids: tuple[PositiveInt, ...]
    captain_element_id: PositiveInt
    vice_captain_element_id: PositiveInt

    @model_validator(mode="after")
    def designations_are_distinct(self) -> Self:
        if self.starting_xi_element_ids != tuple(sorted(self.starting_xi_element_ids)):
            raise ValueError("starting XI must be canonical")
        partition = (
            *self.starting_xi_element_ids,
            self.bench_goalkeeper_element_id,
            *self.bench_outfield_element_ids,
        )
        if len(partition) != len(set(partition)):
            raise ValueError("lineup and bench must form a unique partition")
        if (
            self.captain_element_id not in self.starting_xi_element_ids
            or self.vice_captain_element_id not in self.starting_xi_element_ids
            or self.captain_element_id == self.vice_captain_element_id
        ):
            raise ValueError("captain and vice-captain must be distinct starters")
        return self


class CurrentManagerStateLineage(FrozenModel):
    fpl_input_semantic_sha256: Sha256
    fpl_catalogue_view_sha256: Sha256
    manager_declaration_semantic_sha256: Sha256
    target_gameweek_identity_sha256: Sha256
    ruleset_id: StrictStr = Field(min_length=1, max_length=100)
    ruleset_version: StrictStr = Field(min_length=1, max_length=100)
    ruleset_sha256: Sha256
    full_season_capability_sha256: Sha256
    tactical_rules_semantic_sha256: Sha256
    transfer_rules_semantic_sha256: Sha256
    selling_price_rule_semantic_sha256: Sha256
    chip_bundle_sha256: Sha256
    chip_inventory_sha256: Sha256


class CurrentManagerRuntimeBoundary(FrozenModel):
    manual_import: Literal["ALLOW", "DENY"] = "ALLOW"
    transient_processing: Literal["ALLOW"] = "ALLOW"
    private_internal_use: Literal["ALLOW"] = "ALLOW"
    automated_access: Literal["ALLOW", "DENY"] = "DENY"
    raw_storage: Literal["DENY"] = "DENY"
    derived_storage: Literal["DENY"] = "DENY"
    cache: Literal["DENY"] = "DENY"
    backup: Literal["DENY"] = "DENY"
    storage_mode: Literal["TRANSIENT_IN_MEMORY"] = "TRANSIENT_IN_MEMORY"
    persistence_performed: Literal[False] = False
    database_accessed: Literal[False] = False
    network_called: bool = False

    @model_validator(mode="after")
    def acquisition_is_exact(self) -> Self:
        if self.network_called != (self.automated_access == "ALLOW"):
            raise ValueError("manager network and automated-access flags differ")
        if self.manual_import == self.automated_access:
            raise ValueError("manager acquisition must be exactly manual or direct")
        return self


class CurrentManagerStateSummary(FrozenModel):
    """Disclosure-minimized representation safe for ordinary logs and evidence."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    contract: Literal["CURRENT_MANAGER_STATE_SUMMARY"] = "CURRENT_MANAGER_STATE_SUMMARY"
    status: Literal["VALID"] = "VALID"
    source_class: Literal["OPERATOR_DECLARED", "PROVIDER_OBSERVED"] = "OPERATOR_DECLARED"
    attestation_status: Literal["HUMAN_ATTESTED", "PROVIDER_OBSERVED"] = "HUMAN_ATTESTED"
    provider_verification: Literal["NOT_PROVIDER_VERIFIED", "PROVIDER_VERIFIED"] = (
        "NOT_PROVIDER_VERIFIED"
    )
    season_code: Literal["2026/27"] = SUPPORTED_FPL_SEASON_CODE
    target_gameweek: PositiveInt
    declared_at: datetime
    attested_at: datetime
    received_at: datetime
    usable_at: datetime
    information_cutoff: datetime
    squad_count: PositiveInt
    starter_count: PositiveInt
    bench_count: PositiveInt
    chip_state_counts: dict[StrictStr, NonNegativeInt]
    selected_chip_count: NonNegativeInt
    manager_declaration_semantic_sha256: Sha256
    manager_state_semantic_sha256: Sha256
    fpl_input_semantic_sha256: Sha256
    ruleset_sha256: Sha256
    chip_bundle_sha256: Sha256
    storage_mode: Literal["TRANSIENT_IN_MEMORY"] = "TRANSIENT_IN_MEMORY"
    persistence_performed: Literal[False] = False
    database_accessed: Literal[False] = False
    network_called: bool = False


class CurrentManagerStateBundle(FrozenModel):
    """Complete private current manager facts proven by 001C and no historical claims."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    contract: Literal["CURRENT_MANAGER_STATE_BUNDLE"] = "CURRENT_MANAGER_STATE_BUNDLE"
    current_contract_version: Literal["current-manager-state-v1"] = CURRENT_MANAGER_CONTRACT_VERSION
    status: Literal["VALID"] = "VALID"
    source_class: Literal["OPERATOR_DECLARED", "PROVIDER_OBSERVED"] = "OPERATOR_DECLARED"
    attestation_status: Literal["HUMAN_ATTESTED", "PROVIDER_OBSERVED"] = "HUMAN_ATTESTED"
    provider_verification: Literal["NOT_PROVIDER_VERIFIED", "PROVIDER_VERIFIED"] = (
        "NOT_PROVIDER_VERIFIED"
    )
    season_code: Literal["2026/27"] = SUPPORTED_FPL_SEASON_CODE
    target_gameweek: PositiveInt
    as_of: datetime
    received_at: datetime
    usable_at: datetime
    information_cutoff: datetime
    declaration: CurrentManagerDeclaration
    squad: tuple[CurrentManagerSquadMember, ...]
    bank_tenths: NonNegativeInt
    free_transfers: NonNegativeInt
    lineup: CurrentManagerLineup
    chip_inventory: ChipInventory
    selected_chip_token_id: StrictStr | None = None
    overall_points: NonNegativeInt | None = None
    overall_rank: PositiveInt | None = None
    attestation: CurrentManagerAttestation
    lineage: CurrentManagerStateLineage
    runtime: CurrentManagerRuntimeBoundary
    limitations: tuple[StrictStr, ...]
    semantic_sha256: Sha256

    @field_validator("as_of", "received_at", "usable_at", "information_cutoff")
    @classmethod
    def normalize_times(cls, value: datetime) -> datetime:
        return _normalize_utc(value, label="current manager bundle timestamp")

    @model_validator(mode="after")
    def bundle_is_internally_sealed(self) -> Self:
        if self.declaration != canonical_current_manager_declaration(self.declaration):
            raise ValueError("embedded manager declaration is not canonical")
        if self.squad != tuple(sorted(self.squad, key=lambda item: item.official_fpl_element_id)):
            raise ValueError("current manager squad is not canonical")
        member_ids = tuple(item.official_fpl_element_id for item in self.squad)
        if len(member_ids) != len(set(member_ids)):
            raise ValueError("current manager squad contains duplicate members")
        partition = {
            *self.lineup.starting_xi_element_ids,
            self.lineup.bench_goalkeeper_element_id,
            *self.lineup.bench_outfield_element_ids,
        }
        if partition != set(member_ids):
            raise ValueError("current manager lineup does not partition the squad")
        selected = tuple(
            token.token_id
            for token in self.chip_inventory.tokens
            if token.status in {TokenStatus.PENDING_CANCELLABLE, TokenStatus.ACTIVE}
        )
        if selected != (
            () if self.selected_chip_token_id is None else (self.selected_chip_token_id,)
        ):
            raise ValueError("selected chip identity is inconsistent")
        if (
            self.target_gameweek != self.declaration.target_gameweek
            or self.target_gameweek != self.chip_inventory.current_gameweek
            or self.season_code != self.declaration.season_code
            or self.information_cutoff != self.declaration.information_cutoff
            or self.as_of != self.attestation.declared_at
            or self.attestation != self.declaration.attestation
            or self.attestation_status != self.attestation.attestation_status
            or self.provider_verification != self.attestation.provider_verification
            or self.bank_tenths != self.declaration.bank_tenths
            or self.free_transfers != self.declaration.free_transfers
            or self.overall_points != self.declaration.overall_points
            or self.overall_rank != self.declaration.overall_rank
            or self.lineup
            != CurrentManagerLineup.model_validate(self.declaration.lineup.model_dump())
            or self.lineage.manager_declaration_semantic_sha256
            != current_manager_declaration_semantic_sha256(self.declaration)
            or self.lineage.chip_inventory_sha256 != self.chip_inventory.inventory_hash
            or self.source_class != self.declaration.source_class
            or self.runtime.network_called != (self.source_class == "PROVIDER_OBSERVED")
            or self.limitations
            != (_LIMITATIONS if self.source_class == "OPERATOR_DECLARED" else _PROVIDER_LIMITATIONS)
        ):
            raise ValueError("current manager bundle lineage is inconsistent")
        if not (
            self.as_of
            <= self.attestation.attested_at
            <= self.received_at
            <= self.usable_at
            <= self.information_cutoff
        ):
            raise ValueError("current manager bundle timestamps are out of order")
        declarations = {item.official_fpl_element_id: item for item in self.declaration.squad}
        for member in self.squad:
            declared = declarations.get(member.official_fpl_element_id)
            if (
                declared is None
                or declared.purchase_price_tenths != member.purchase_price_tenths
                or (
                    declared.observed_selling_price_tenths is not None
                    and declared.observed_selling_price_tenths != member.selling_price_tenths
                )
            ):
                raise ValueError("derived squad differs from its declaration")
        declared_tokens = {item.token_id: item.status for item in self.declaration.chip_tokens}
        resolved_tokens = {item.token_id: item.status.value for item in self.chip_inventory.tokens}
        if declared_tokens != resolved_tokens:
            raise ValueError("derived chip inventory differs from its declaration")
        if self.semantic_sha256 != current_manager_state_semantic_sha256(self):
            raise ValueError("current manager bundle semantic hash does not match")
        return self

    def safe_summary(self) -> CurrentManagerStateSummary:
        counts = Counter(token.status.value for token in self.chip_inventory.tokens)
        return CurrentManagerStateSummary(
            source_class=self.source_class,
            attestation_status=self.attestation_status,
            provider_verification=self.provider_verification,
            target_gameweek=self.target_gameweek,
            declared_at=self.attestation.declared_at,
            attested_at=self.attestation.attested_at,
            received_at=self.received_at,
            usable_at=self.usable_at,
            information_cutoff=self.information_cutoff,
            squad_count=len(self.squad),
            starter_count=len(self.lineup.starting_xi_element_ids),
            bench_count=1 + len(self.lineup.bench_outfield_element_ids),
            chip_state_counts=dict(sorted(counts.items())),
            selected_chip_count=0 if self.selected_chip_token_id is None else 1,
            manager_declaration_semantic_sha256=(self.lineage.manager_declaration_semantic_sha256),
            manager_state_semantic_sha256=self.semantic_sha256,
            fpl_input_semantic_sha256=self.lineage.fpl_input_semantic_sha256,
            ruleset_sha256=self.lineage.ruleset_sha256,
            chip_bundle_sha256=self.lineage.chip_bundle_sha256,
            network_called=self.runtime.network_called,
        )


def current_manager_state_semantic_sha256(value: CurrentManagerStateBundle) -> str:
    payload = value.model_dump(mode="json", exclude={"semantic_sha256"})
    return canonical_sha256(payload)


def current_fpl_catalogue_view_sha256(value: CurrentFplInputBundle) -> str:
    """Hash every 001A catalogue fact consumed by current manager resolution."""

    return canonical_sha256(
        {
            "fpl_input_semantic_sha256": value.semantic_sha256,
            "season_code": value.season_code,
            "target_gameweek": value.target_gameweek,
            "target_gameweek_identity_sha256": value.target_event.identity.canonical_lookup_sha256,
            "target_deadline_at": value.target_event.deadline_at.isoformat(),
            "bootstrap_source_semantic_sha256": value.provenance.bootstrap_semantic_sha256,
            "positions": [
                {
                    "canonical_position": item.canonical_position.value,
                    "provider_element_type_id": item.provider_element_type_id,
                    "source_semantic_sha256": item.source_semantic_sha256,
                    "squad_max_play": item.squad_max_play,
                    "squad_min_play": item.squad_min_play,
                    "squad_select": item.squad_select,
                }
                for item in sorted(
                    value.positions, key=lambda child: child.canonical_position.value
                )
            ],
            "teams": [
                {
                    "identity": item.identity.model_dump(mode="json"),
                    "provider_team_id": item.provider_team_id,
                    "source_semantic_sha256": item.source_semantic_sha256,
                }
                for item in sorted(value.teams, key=lambda child: child.provider_team_id)
            ],
            "players": [
                {
                    "current_price_tenths": item.current_price_tenths,
                    "identity": item.identity.model_dump(mode="json"),
                    "position": item.position.value,
                    "provider_element_id": item.provider_element_id,
                    "source_semantic_sha256": item.source_semantic_sha256,
                    "team_identity": item.team_identity.model_dump(mode="json"),
                }
                for item in sorted(value.players, key=lambda child: child.provider_element_id)
            ],
        }
    )


def _rules_view_sha256(value: BaseModel) -> str:
    return canonical_sha256(value.model_dump(mode="json"))


def bind_current_manager_state_request(
    declaration_path: Path,
    fpl_input: CurrentFplInputBundle,
    ruleset: CompiledRuleset,
    capability: CapabilityArtifact,
) -> CurrentManagerStateRequest:
    """Bind accepted sources before any operator declaration is read."""

    return CurrentManagerStateRequest(
        declaration_path=declaration_path,
        target_gameweek=fpl_input.target_gameweek,
        information_cutoff=fpl_input.provenance.information_cutoff,
        fpl_input_semantic_sha256=fpl_input.semantic_sha256,
        fpl_catalogue_view_sha256=current_fpl_catalogue_view_sha256(fpl_input),
        ruleset_sha256=ruleset.ruleset_hash,
        full_season_capability_sha256=capability.capability_hash,
    )


@dataclass(frozen=True)
class _OpenedDeclaration:
    descriptor: int
    metadata: os.stat_result


def _open_flags() -> int:
    flags = os.O_RDONLY
    for name in ("O_BINARY", "O_CLOEXEC", "O_NOINHERIT", "O_NOFOLLOW"):
        flags |= int(getattr(os, name, 0))
    return flags


def _is_regular(metadata: os.stat_result) -> bool:
    return not stat.S_ISLNK(metadata.st_mode) and stat.S_ISREG(metadata.st_mode)


@contextmanager
def _open_verified_declaration(path: Path) -> Iterator[_OpenedDeclaration]:
    descriptor: int | None = None
    try:
        before = os.lstat(path)
        if not _is_regular(before):
            raise OSError("declaration is not a regular file")
        descriptor = os.open(path, _open_flags())
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(before, opened):
            raise OSError("opened declaration differs from validated path")
        after = os.lstat(path)
        if not _is_regular(after) or not os.path.samestat(after, opened):
            raise OSError("declaration path changed while opening")
        yield _OpenedDeclaration(descriptor=descriptor, metadata=opened)
    except OSError:
        raise IngestionError(
            "SOURCE_UNAVAILABLE", "current manager declaration is unavailable"
        ) from None
    finally:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)


def _read_declaration(path: Path) -> bytes:
    with _open_verified_declaration(path) as source:
        if source.metadata.st_size > MAX_MANAGER_DECLARATION_BYTES:
            raise IngestionError(
                "PAYLOAD_TOO_LARGE", "current manager declaration exceeds the byte limit"
            )
        chunks: list[bytes] = []
        remaining = MAX_MANAGER_DECLARATION_BYTES + 1
        while remaining:
            chunk = os.read(source.descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        body = b"".join(chunks)
    if len(body) > MAX_MANAGER_DECLARATION_BYTES:
        raise IngestionError(
            "PAYLOAD_TOO_LARGE", "current manager declaration exceeds the byte limit"
        )
    return body


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise IngestionError(
                "DUPLICATE_JSON_KEY", "current manager declaration contains duplicate keys"
            )
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    del value
    raise IngestionError("MALFORMED_JSON", "current manager declaration is not strict JSON")


def _parse_declaration(body: bytes) -> CurrentManagerDeclaration:
    try:
        text = body.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise IngestionError(
            "MALFORMED_JSON", "current manager declaration is not valid UTF-8"
        ) from None
    try:
        parsed = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_json_constant,
        )
    except IngestionError:
        raise
    except (json.JSONDecodeError, UnicodeError, ValueError):
        raise IngestionError(
            "MALFORMED_JSON", "current manager declaration is not strict JSON"
        ) from None
    if not isinstance(parsed, dict):
        raise IngestionError(
            "VALIDATION_FAILED", "current manager declaration must be a JSON object"
        )
    try:
        return canonical_current_manager_declaration(
            CurrentManagerDeclaration.model_validate_json(body)
        )
    except ValidationError:
        raise IngestionError(
            "VALIDATION_FAILED", "current manager declaration failed schema validation"
        ) from None


def _revalidate_fpl_input(value: CurrentFplInputBundle) -> None:
    try:
        CurrentFplInputBundle.model_validate(value.model_dump(mode="python"))
    except ValidationError:
        raise IngestionError(
            "MAPPING_CONFLICT", "accepted current FPL input failed structural revalidation"
        ) from None
    direct = value.rights.rights_profile_id == "fpl_official_private_operator_initiated_read_v1"
    expected_decisions = (
        (
            ("automated_access", "ALLOW"),
            ("transient_processing", "ALLOW"),
            ("private_internal_use", "ALLOW"),
            ("raw_storage", "DENY"),
            ("derived_storage", "DENY"),
        )
        if direct
        else (
            ("manual_import", "ALLOW"),
            ("transient_processing", "ALLOW"),
            ("private_internal_use", "ALLOW"),
            ("automated_access", "DENY"),
            ("raw_storage", "DENY"),
            ("derived_storage", "DENY"),
        )
    )
    decisions = tuple((str(item.capability), item.decision) for item in value.rights.decisions)
    if (
        value.provider != "official_fpl"
        or value.competition_key != "PL"
        or value.season_code != SUPPORTED_FPL_SEASON_CODE
        or value.semantic_sha256 != value.provenance.input_bundle_semantic_sha256
        or value.target_event.provider_event_id != value.target_gameweek
        or value.target_event not in value.events
        or value.provenance.information_cutoff > value.target_event.deadline_at
    ):
        raise IngestionError("MAPPING_CONFLICT", "current FPL source context is inconsistent")
    rights = value.rights
    if (
        decisions != expected_decisions
        or rights.rights_profile_id
        not in {
            "fpl_official_private_manual_v1",
            "fpl_official_private_operator_initiated_read_v1",
        }
        or rights.rights_profile_version != "1.0.0"
        or rights.automated_access_profile_value != ("ALLOW" if direct else "DENY")
        or rights.raw_storage_profile_value != "DENY"
        or rights.derived_storage_profile_value not in {"UNKNOWN", "DENY"}
        or rights.automated_access != ("ALLOW" if direct else "DENY")
        or rights.raw_storage != "DENY"
        or rights.derived_storage != "DENY"
        or rights.cache != "DENY"
        or rights.backup != "DENY"
        or rights.database_accessed is not False
        or rights.raw_storage_performed is not False
        or rights.derived_storage_performed is not False
        or rights.operator_delete_required is not (not direct)
        or rights.disclosure_mode != "SAFE_SUMMARY_ONLY"
        or value.provenance.transport_called is not direct
        or value.provenance.database_accessed is not False
        or value.provenance.raw_storage_performed is not False
        or value.provenance.derived_storage_performed is not False
    ):
        raise IngestionError("RIGHTS_BLOCKED", "current manager use violates FPL source rights")

    team_identities = {team.identity.canonical_lookup_sha256 for team in value.teams}
    player_ids: set[int] = set()
    player_identity_hashes: set[str] = set()
    for player in value.players:
        if (
            player.provider_element_id in player_ids
            or player.identity.canonical_lookup_sha256 in player_identity_hashes
            or player.source_semantic_sha256 != value.provenance.bootstrap_semantic_sha256
            or player.team_identity.canonical_lookup_sha256 not in team_identities
            or player.current_price_tenths <= 0
        ):
            raise IngestionError("MAPPING_CONFLICT", "current FPL player catalogue is inconsistent")
        player_ids.add(player.provider_element_id)
        player_identity_hashes.add(player.identity.canonical_lookup_sha256)
    if not player_ids:
        raise IngestionError("MAPPING_CONFLICT", "current FPL player catalogue is empty")


@dataclass(frozen=True)
class _ActiveRules:
    tactical: OneGameweekRulesView
    transfers: TransferRules
    chips: CompiledChipBundle


def _compile_active_rules(
    ruleset: CompiledRuleset,
    capability: CapabilityArtifact,
    *,
    private_rules_authority: PrivateTransientRulesAuthority | None = None,
    information_cutoff: datetime,
) -> _ActiveRules:
    try:
        checked_ruleset = CompiledRuleset.model_validate(ruleset.model_dump(mode="python"))
        checked_capability = CapabilityArtifact.model_validate(capability.model_dump(mode="python"))
        ensure_compiled_ruleset_integrity(checked_ruleset)
        expected_capability = compile_capability_artifact(
            checked_ruleset, RuleCapability.FULL_SEASON
        )
        if checked_capability != expected_capability:
            raise IngestionError(
                "MAPPING_CONFLICT", "FULL_SEASON capability differs from the active ruleset"
            )
        is_active = checked_ruleset.status is RulesetStatus.ACTIVE
        is_private_verified = private_rules_authority is not None
        if private_rules_authority is not None:
            if checked_ruleset.status is not RulesetStatus.VERIFIED:
                raise IngestionError(
                    "CONFIGURATION_INVALID",
                    "private transient rules authority applies only to VERIFIED rules",
                )
            validate_private_transient_rules_authority(
                private_rules_authority,
                ruleset=checked_ruleset,
                capability=checked_capability,
                information_cutoff=information_cutoff,
            )
        if (
            not (is_active or is_private_verified)
            or not checked_ruleset.production_eligible
            or checked_ruleset.schema_version != "1.1"
            or checked_ruleset.season_code != SUPPORTED_RULES_SEASON_CODE
            or checked_capability.capability is not RuleCapability.FULL_SEASON
            or not checked_capability.source_backed
            or not checked_capability.production_eligible
            or checked_capability.blockers
        ):
            raise IngestionError(
                "CONFIGURATION_INVALID",
                "current manager state requires ACTIVE target FULL_SEASON rules or exact "
                "private transient VERIFIED authority",
            )
        projection_mode = ProjectionMode.PRODUCTION if is_active else ProjectionMode.REPLAY
        tactical = build_one_gameweek_rules_view(
            checked_ruleset,
            projection_mode=projection_mode,
            capability=checked_capability if is_active else None,
        )
        transfers = build_multi_gameweek_transfer_rules(
            checked_ruleset,
            projection_mode=projection_mode,
            capability=checked_capability if is_active else None,
        )
        chips = compile_optimisation_chip_rules(build_chip_rules_view(checked_ruleset))
    except IngestionError:
        raise
    except (RulesError, ValidationError, ValueError, KeyError, TypeError):
        raise IngestionError(
            "CONFIGURATION_INVALID", "current manager target rules are invalid"
        ) from None
    identities = {
        (tactical.ruleset_id, tactical.ruleset_version, tactical.ruleset_hash),
        (transfers.ruleset_id, transfers.ruleset_version, transfers.ruleset_hash),
        (chips.ruleset_id, chips.ruleset_version, chips.ruleset_hash),
    }
    if (
        len(identities) != 1
        or (
            ruleset.status is RulesetStatus.ACTIVE
            and tactical.manager_capability_hash != capability.capability_hash
        )
        or (
            ruleset.status is RulesetStatus.ACTIVE
            and transfers.capability_hash != capability.capability_hash
        )
        or (
            ruleset.status is RulesetStatus.VERIFIED
            and (
                tactical.manager_capability_hash is not None
                or transfers.capability_hash is not None
            )
        )
    ):
        raise IngestionError("MAPPING_CONFLICT", "compiled current manager rule lineage differs")
    return _ActiveRules(tactical=tactical, transfers=transfers, chips=chips)


def _require_request_bindings(
    request: CurrentManagerStateRequest,
    fpl_input: CurrentFplInputBundle,
    ruleset: CompiledRuleset,
    capability: CapabilityArtifact,
) -> None:
    checks = (
        (request.target_gameweek, fpl_input.target_gameweek),
        (request.information_cutoff, fpl_input.provenance.information_cutoff),
        (request.fpl_input_semantic_sha256, fpl_input.semantic_sha256),
        (request.fpl_catalogue_view_sha256, current_fpl_catalogue_view_sha256(fpl_input)),
        (request.ruleset_sha256, ruleset.ruleset_hash),
        (request.full_season_capability_sha256, capability.capability_hash),
    )
    if any(observed != expected for observed, expected in checks):
        raise IngestionError("MAPPING_CONFLICT", "bound current manager source hash differs")


def _require_rules_match_catalogue(
    fpl_input: CurrentFplInputBundle,
    active: _ActiveRules,
) -> None:
    tactical = active.tactical
    transfers = active.transfers
    if (
        tactical.squad_size != transfers.squad_size
        or tactical.position_squad_quota != transfers.position_squad_quota
        or tactical.max_players_per_club != transfers.max_players_per_club
        or tactical.starting_size + tactical.bench_size != tactical.squad_size
        or tactical.initial_budget_tenths is None
    ):
        raise IngestionError("CONFIGURATION_INVALID", "current manager rule views are inconsistent")
    definitions: dict[PlayerPosition, CurrentFplPositionDefinition] = {}
    for item in fpl_input.positions:
        position = PlayerPosition(item.canonical_position.value)
        if position in definitions or item.source_semantic_sha256 != (
            fpl_input.provenance.bootstrap_semantic_sha256
        ):
            raise IngestionError(
                "MAPPING_CONFLICT", "current FPL position catalogue is inconsistent"
            )
        definitions[position] = item
    if set(definitions) != set(PlayerPosition):
        raise IngestionError("MAPPING_CONFLICT", "current FPL position catalogue is incomplete")
    for position, item in definitions.items():
        if (
            item.squad_select != tactical.position_squad_quota[position]
            or item.squad_min_play != tactical.lineup_min[position]
            or item.squad_max_play != tactical.lineup_max[position]
        ):
            raise IngestionError(
                "MAPPING_CONFLICT", "current FPL positions differ from active target rules"
            )


def _resolve_squad(
    declaration: CurrentManagerDeclaration,
    fpl_input: CurrentFplInputBundle,
    active: _ActiveRules,
) -> tuple[CurrentManagerSquadMember, ...]:
    rules = active.transfers
    if len(declaration.squad) != rules.squad_size:
        raise IngestionError("VALIDATION_FAILED", "declared current squad has the wrong size")
    catalogue = {item.provider_element_id: item for item in fpl_input.players}
    if len(catalogue) != len(fpl_input.players):
        raise IngestionError("MAPPING_CONFLICT", "current FPL player identity is ambiguous")
    initial_budget = active.tactical.initial_budget_tenths
    if initial_budget is None:
        raise IngestionError("CONFIGURATION_INVALID", "active rules omit the FPL price unit")

    members: list[CurrentManagerSquadMember] = []
    for declared in declaration.squad:
        player = catalogue.get(declared.official_fpl_element_id)
        if player is None:
            raise IngestionError("MAPPING_CONFLICT", "declared squad contains an unknown player")
        if (
            player.source_semantic_sha256 != fpl_input.provenance.bootstrap_semantic_sha256
            or player.identity.season_code != fpl_input.season_code
            or player.current_price_tenths <= 0
        ):
            raise IngestionError("MAPPING_CONFLICT", "declared player catalogue binding differs")
        if (
            declared.purchase_price_tenths > initial_budget
            or player.current_price_tenths > initial_budget
        ):
            raise IngestionError("VALIDATION_FAILED", "declared player price is implausible")
        selling = selling_price_tenths(
            purchase_price_tenths=declared.purchase_price_tenths,
            current_price_tenths=player.current_price_tenths,
            rule=rules.selling_price_rule,
        )
        if (
            declared.observed_selling_price_tenths is not None
            and declared.observed_selling_price_tenths != selling
        ):
            raise IngestionError(
                "VALIDATION_FAILED", "declared selling price differs from active rules"
            )
        members.append(
            CurrentManagerSquadMember(
                official_fpl_element_id=player.provider_element_id,
                player_identity=player.identity,
                team_identity=player.team_identity,
                position=player.position,
                purchase_price_tenths=declared.purchase_price_tenths,
                current_price_tenths=player.current_price_tenths,
                selling_price_tenths=selling,
                source_semantic_sha256=player.source_semantic_sha256,
            )
        )
    ordered = tuple(sorted(members, key=lambda item: item.official_fpl_element_id))
    if Counter(PlayerPosition(item.position.value) for item in ordered) != Counter(
        rules.position_squad_quota
    ):
        raise IngestionError("VALIDATION_FAILED", "declared squad violates position quotas")
    clubs = Counter(item.team_identity.canonical_lookup_sha256 for item in ordered)
    if clubs and max(clubs.values()) > rules.max_players_per_club:
        raise IngestionError("VALIDATION_FAILED", "declared squad violates the club quota")
    return ordered


def _resolve_lineup(
    declaration: CurrentManagerDeclaration,
    members: tuple[CurrentManagerSquadMember, ...],
    rules: OneGameweekRulesView,
) -> CurrentManagerLineup:
    declared = declaration.lineup
    starters = tuple(sorted(declared.starting_xi_element_ids))
    bench_outfield = declared.bench_outfield_element_ids
    if len(starters) != rules.starting_size or len(set(starters)) != len(starters):
        raise IngestionError("VALIDATION_FAILED", "declared starting XI is invalid")
    if len(bench_outfield) != rules.bench_size - 1 or len(set(bench_outfield)) != len(
        bench_outfield
    ):
        raise IngestionError("VALIDATION_FAILED", "declared bench order is invalid")
    member_by_id = {item.official_fpl_element_id: item for item in members}
    partition = (
        *starters,
        declared.bench_goalkeeper_element_id,
        *bench_outfield,
    )
    if len(partition) != len(set(partition)) or set(partition) != set(member_by_id):
        raise IngestionError(
            "VALIDATION_FAILED", "declared lineup does not partition the current squad"
        )
    bench_goalkeeper = member_by_id[declared.bench_goalkeeper_element_id]
    if bench_goalkeeper.position is not FPLPosition.GK or any(
        member_by_id[element_id].position is FPLPosition.GK for element_id in bench_outfield
    ):
        raise IngestionError("VALIDATION_FAILED", "declared bench goalkeeper role is invalid")
    counts = Counter(
        PlayerPosition(member_by_id[element_id].position.value) for element_id in starters
    )
    if any(
        counts[position] < rules.lineup_min[position]
        or counts[position] > rules.lineup_max[position]
        for position in PlayerPosition
    ):
        raise IngestionError("VALIDATION_FAILED", "declared starting formation is illegal")
    if (
        declared.captain_element_id not in starters
        or declared.vice_captain_element_id not in starters
        or declared.captain_element_id == declared.vice_captain_element_id
    ):
        raise IngestionError("VALIDATION_FAILED", "declared captaincy is invalid")
    return CurrentManagerLineup(
        starting_xi_element_ids=starters,
        bench_goalkeeper_element_id=declared.bench_goalkeeper_element_id,
        bench_outfield_element_ids=bench_outfield,
        captain_element_id=declared.captain_element_id,
        vice_captain_element_id=declared.vice_captain_element_id,
    )


def _resolve_chip_inventory(
    declaration: CurrentManagerDeclaration,
    bundle: CompiledChipBundle,
) -> tuple[ChipInventory, str | None]:
    current_gameweek = declaration.target_gameweek
    base_current = build_chip_inventory(bundle, current_gameweek=current_gameweek)
    declared = {item.token_id: item for item in declaration.chip_tokens}
    expected_ids = {item.token_id for item in base_current.tokens}
    if set(declared) != expected_ids:
        raise IngestionError(
            "VALIDATION_FAILED", "declared chip tokens differ from configured inventory"
        )
    token_by_id = {item.token_id: item for item in base_current.tokens}
    selected = tuple(
        item for item in declaration.chip_tokens if item.status in {"PENDING_CANCELLABLE", "ACTIVE"}
    )
    if len(selected) > 1:
        raise IngestionError("VALIDATION_FAILED", "multiple chip tokens are selected")
    if selected and token_by_id[selected[0].token_id].chip_key == "FREE_HIT":
        raise IngestionError(
            "USAGE_INVALID",
            "active or pending Free Hit requires unavailable restoration state",
        )

    commands: list[tuple[int, str, str]] = []
    for item in declaration.chip_tokens:
        inventory_item = token_by_id[item.token_id]
        definition = bundle.definition_for(inventory_item.chip_key).definition
        if item.status == "USED":
            assert item.used_at_gameweek is not None
            activation_gameweek = item.used_at_gameweek - definition.duration_gameweeks + 1
            if activation_gameweek <= 0:
                raise IngestionError("VALIDATION_FAILED", "declared chip use time is invalid")
            commands.append((activation_gameweek, "ACTIVATE", item.token_id))
        elif item.status == "ACTIVE":
            assert item.active_from_gameweek is not None
            commands.append((item.active_from_gameweek, "ACTIVATE", item.token_id))
        elif item.status == "PENDING_CANCELLABLE":
            assert item.selected_at_gameweek is not None
            commands.append((item.selected_at_gameweek, "SELECT", item.token_id))

    inventory = build_chip_inventory(bundle, current_gameweek=1)
    try:
        for gameweek, action, token_id in sorted(commands):
            if gameweek > current_gameweek:
                raise IngestionError("VALIDATION_FAILED", "declared chip event is in the future")
            inventory = advance_inventory(inventory, to_gameweek=gameweek)
            if action == "ACTIVATE":
                inventory = activate_token(inventory, bundle, token_id=token_id)
            else:
                inventory = select_token(inventory, bundle, token_id=token_id)
        inventory = advance_inventory(inventory, to_gameweek=current_gameweek)
        inventory = validate_chip_inventory(inventory, bundle)
    except IngestionError:
        raise
    except ChipError:
        raise IngestionError(
            "VALIDATION_FAILED", "declared chip inventory is not rule-valid"
        ) from None

    resolved = {item.token_id: item for item in inventory.tokens}
    for item in declaration.chip_tokens:
        inventory_item = resolved[item.token_id]
        if inventory_item.status.value != item.status:
            raise IngestionError(
                "VALIDATION_FAILED", "declared chip status differs from configured inventory"
            )
        if item.status == "USED" and inventory_item.used_at_gameweek != item.used_at_gameweek:
            raise IngestionError("VALIDATION_FAILED", "declared chip use time is inconsistent")
        if (
            item.status == "ACTIVE"
            and inventory_item.active_from_gameweek != item.active_from_gameweek
        ):
            raise IngestionError("VALIDATION_FAILED", "declared active chip time is inconsistent")
        if (
            item.status == "PENDING_CANCELLABLE"
            and inventory_item.selected_at_gameweek != item.selected_at_gameweek
        ):
            raise IngestionError("VALIDATION_FAILED", "declared pending chip time is inconsistent")
    return inventory, selected[0].token_id if selected else None


def _require_temporal_context(
    declaration: CurrentManagerDeclaration,
    fpl_input: CurrentFplInputBundle,
    *,
    received_at: datetime,
    usable_at: datetime,
) -> None:
    cutoff = fpl_input.provenance.information_cutoff
    if (
        declaration.target_gameweek != fpl_input.target_gameweek
        or declaration.season_code != fpl_input.season_code
        or declaration.information_cutoff != cutoff
    ):
        raise IngestionError(
            "MAPPING_CONFLICT", "manager declaration and current FPL context differ"
        )
    if any(
        value > cutoff
        for value in (
            declaration.attestation.declared_at,
            declaration.attestation.attested_at,
            received_at,
            usable_at,
        )
    ):
        raise IngestionError("POST_CUTOFF", "current manager state is post-cutoff")
    if not (
        fpl_input.provenance.usable_at
        <= declaration.attestation.declared_at
        <= declaration.attestation.attested_at
        <= received_at
        <= usable_at
    ):
        raise IngestionError("VALIDATION_FAILED", "current manager timestamps are out of order")


def _build_bundle(
    declaration: CurrentManagerDeclaration,
    fpl_input: CurrentFplInputBundle,
    active: _ActiveRules,
    capability: CapabilityArtifact,
    *,
    received_at: datetime,
    usable_at: datetime,
) -> CurrentManagerStateBundle:
    canonical_declaration = canonical_current_manager_declaration(declaration)
    if canonical_declaration.free_transfers > active.transfers.maximum_free_transfers:
        raise IngestionError(
            "VALIDATION_FAILED", "declared free transfers exceed the configured maximum"
        )
    _require_temporal_context(
        canonical_declaration,
        fpl_input,
        received_at=received_at,
        usable_at=usable_at,
    )
    members = _resolve_squad(canonical_declaration, fpl_input, active)
    lineup = _resolve_lineup(canonical_declaration, members, active.tactical)
    inventory, selected_token = _resolve_chip_inventory(canonical_declaration, active.chips)
    declaration_hash = current_manager_declaration_semantic_sha256(canonical_declaration)
    lineage = CurrentManagerStateLineage(
        fpl_input_semantic_sha256=fpl_input.semantic_sha256,
        fpl_catalogue_view_sha256=current_fpl_catalogue_view_sha256(fpl_input),
        manager_declaration_semantic_sha256=declaration_hash,
        target_gameweek_identity_sha256=fpl_input.target_event.identity.canonical_lookup_sha256,
        ruleset_id=active.transfers.ruleset_id,
        ruleset_version=active.transfers.ruleset_version,
        ruleset_sha256=active.transfers.ruleset_hash,
        full_season_capability_sha256=capability.capability_hash,
        tactical_rules_semantic_sha256=_rules_view_sha256(active.tactical),
        transfer_rules_semantic_sha256=_rules_view_sha256(active.transfers),
        selling_price_rule_semantic_sha256=_rules_view_sha256(active.transfers.selling_price_rule),
        chip_bundle_sha256=active.chips.bundle_hash,
        chip_inventory_sha256=inventory.inventory_hash,
    )
    provisional = CurrentManagerStateBundle.model_construct(
        source_class=canonical_declaration.source_class,
        attestation_status=canonical_declaration.attestation.attestation_status,
        provider_verification=canonical_declaration.attestation.provider_verification,
        target_gameweek=canonical_declaration.target_gameweek,
        as_of=canonical_declaration.attestation.declared_at,
        received_at=received_at,
        usable_at=usable_at,
        information_cutoff=canonical_declaration.information_cutoff,
        declaration=canonical_declaration,
        squad=members,
        bank_tenths=canonical_declaration.bank_tenths,
        free_transfers=canonical_declaration.free_transfers,
        lineup=lineup,
        chip_inventory=inventory,
        selected_chip_token_id=selected_token,
        overall_points=canonical_declaration.overall_points,
        overall_rank=canonical_declaration.overall_rank,
        attestation=canonical_declaration.attestation,
        lineage=lineage,
        runtime=CurrentManagerRuntimeBoundary(
            manual_import=(
                "ALLOW" if canonical_declaration.source_class == "OPERATOR_DECLARED" else "DENY"
            ),
            automated_access=(
                "DENY" if canonical_declaration.source_class == "OPERATOR_DECLARED" else "ALLOW"
            ),
            network_called=canonical_declaration.source_class == "PROVIDER_OBSERVED",
        ),
        limitations=(
            _LIMITATIONS
            if canonical_declaration.source_class == "OPERATOR_DECLARED"
            else _PROVIDER_LIMITATIONS
        ),
        semantic_sha256="0" * 64,
    )
    payload = provisional.model_dump(mode="python")
    payload["semantic_sha256"] = current_manager_state_semantic_sha256(provisional)
    return CurrentManagerStateBundle.model_validate(payload)


class CurrentManagerStateService:
    """Compile and independently verify one private transient current manager bundle."""

    def __init__(self, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._clock = clock

    def _clock_utc(self) -> datetime:
        try:
            return _normalize_utc(self._clock(), label="current manager service clock")
        except ValueError:
            raise IngestionError(
                "INTERNAL_INVARIANT", "current manager service clock must be timezone-aware"
            ) from None

    def compile(
        self,
        request: CurrentManagerStateRequest,
        *,
        fpl_input: CurrentFplInputBundle,
        ruleset: CompiledRuleset,
        capability: CapabilityArtifact,
        private_rules_authority: PrivateTransientRulesAuthority | None = None,
    ) -> CurrentManagerStateBundle:
        received_at = self._clock_utc()
        _revalidate_fpl_input(fpl_input)
        _require_request_bindings(request, fpl_input, ruleset, capability)
        active = _compile_active_rules(
            ruleset,
            capability,
            private_rules_authority=private_rules_authority,
            information_cutoff=fpl_input.provenance.information_cutoff,
        )
        _require_rules_match_catalogue(fpl_input, active)
        declaration = _parse_declaration(_read_declaration(request.declaration_path))
        usable_at = self._clock_utc()
        if usable_at < received_at:
            raise IngestionError(
                "INTERNAL_INVARIANT", "current manager service clock moved backwards"
            )
        return _build_bundle(
            declaration,
            fpl_input,
            active,
            capability,
            received_at=received_at,
            usable_at=usable_at,
        )

    def compile_provider_observed(
        self,
        declaration: CurrentManagerDeclaration,
        *,
        fpl_input: CurrentFplInputBundle,
        ruleset: CompiledRuleset,
        capability: CapabilityArtifact,
        private_rules_authority: PrivateTransientRulesAuthority | None = None,
    ) -> CurrentManagerStateBundle:
        """Compile an authenticated memory-only provider observation."""

        if declaration.source_class != "PROVIDER_OBSERVED":
            raise IngestionError(
                "VALIDATION_FAILED", "provider manager declaration has the wrong source label"
            )
        received_at = self._clock_utc()
        _revalidate_fpl_input(fpl_input)
        active = _compile_active_rules(
            ruleset,
            capability,
            private_rules_authority=private_rules_authority,
            information_cutoff=fpl_input.provenance.information_cutoff,
        )
        _require_rules_match_catalogue(fpl_input, active)
        usable_at = self._clock_utc()
        if usable_at < received_at:
            raise IngestionError(
                "INTERNAL_INVARIANT", "current manager service clock moved backwards"
            )
        return _build_bundle(
            declaration,
            fpl_input,
            active,
            capability,
            received_at=received_at,
            usable_at=usable_at,
        )

    def compile_provider_snapshot(
        self,
        source: ProviderCurrentTeam,
        *,
        fpl_input: CurrentFplInputBundle,
        ruleset: CompiledRuleset,
        capability: CapabilityArtifact,
        observed_at: datetime,
        overall_points: int | None = None,
        overall_rank: int | None = None,
        private_rules_authority: PrivateTransientRulesAuthority | None = None,
    ) -> CurrentManagerStateBundle:
        """Adapt and compile one authenticated current-team provider response."""

        from dmf_pulse.ingestion.fpl.manager_provider import (
            provider_current_manager_declaration,
        )

        _revalidate_fpl_input(fpl_input)
        active = _compile_active_rules(
            ruleset,
            capability,
            private_rules_authority=private_rules_authority,
            information_cutoff=fpl_input.provenance.information_cutoff,
        )
        declaration = provider_current_manager_declaration(
            source,
            fpl_input,
            active.chips,
            observed_at=observed_at,
            overall_points=overall_points,
            overall_rank=overall_rank,
        )
        return self.compile_provider_observed(
            declaration,
            fpl_input=fpl_input,
            ruleset=ruleset,
            capability=capability,
            private_rules_authority=private_rules_authority,
        )

    def verify(
        self,
        value: CurrentManagerStateBundle,
        *,
        fpl_input: CurrentFplInputBundle,
        ruleset: CompiledRuleset,
        capability: CapabilityArtifact,
        private_rules_authority: PrivateTransientRulesAuthority | None = None,
    ) -> CurrentManagerStateBundle:
        try:
            checked = CurrentManagerStateBundle.model_validate(value.model_dump(mode="python"))
        except ValidationError:
            raise IngestionError(
                "MAPPING_CONFLICT", "current manager bundle failed structural revalidation"
            ) from None
        _revalidate_fpl_input(fpl_input)
        active = _compile_active_rules(
            ruleset,
            capability,
            private_rules_authority=private_rules_authority,
            information_cutoff=fpl_input.provenance.information_cutoff,
        )
        _require_rules_match_catalogue(fpl_input, active)
        expected = _build_bundle(
            checked.declaration,
            fpl_input,
            active,
            capability,
            received_at=checked.received_at,
            usable_at=checked.usable_at,
        )
        if expected != checked:
            raise IngestionError(
                "MAPPING_CONFLICT", "current manager bundle differs from its bound sources"
            )
        return checked


__all__ = [
    "CURRENT_MANAGER_CONTRACT_VERSION",
    "MAX_MANAGER_DECLARATION_BYTES",
    "CurrentManagerAttestation",
    "CurrentManagerChipDeclaration",
    "CurrentManagerDeclaration",
    "CurrentManagerLineup",
    "CurrentManagerLineupDeclaration",
    "CurrentManagerPlayerDeclaration",
    "CurrentManagerRuntimeBoundary",
    "CurrentManagerSquadMember",
    "CurrentManagerStateBundle",
    "CurrentManagerStateLineage",
    "CurrentManagerStateRequest",
    "CurrentManagerStateService",
    "CurrentManagerStateSummary",
    "bind_current_manager_state_request",
    "canonical_current_manager_declaration",
    "current_fpl_catalogue_view_sha256",
    "current_manager_declaration_semantic_sha256",
    "current_manager_state_semantic_sha256",
]
