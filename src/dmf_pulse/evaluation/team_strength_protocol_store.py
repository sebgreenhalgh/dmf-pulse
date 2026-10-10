"""Exclusive content-addressed protocol/ledger retention under public rights."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from dmf_pulse.assurance.canonical import pretty_json
from dmf_pulse.evaluation.team_strength_prospective import require_public_prospective_storage
from dmf_pulse.evaluation.team_strength_protocol import (
    CampaignLedgerV1,
    ProspectiveProtocolV1,
    initial_campaign_ledger,
    protocol_summary,
)
from dmf_pulse.ingestion.openfootball.team_strength_data import StrengthEvidenceError, authenticate

type Retained = ProspectiveProtocolV1 | CampaignLedgerV1


def persist_protocol_evidence(value: Retained, *, artifact_root: Path) -> Path:
    if type(value) not in {ProspectiveProtocolV1, CampaignLedgerV1}:
        raise StrengthEvidenceError("only public protocol/campaign evidence may persist")
    require_public_prospective_storage(value.data_class)
    value = authenticate(value)
    if artifact_root.is_symlink():
        raise StrengthEvidenceError("retained root must not be a symbolic link")
    root = artifact_root.resolve()
    folder = (
        "public-team-strength-protocol"
        if isinstance(value, ProspectiveProtocolV1)
        else "public-team-strength-campaign"
    )
    destination = root / folder / f"{value.semantic_sha256}.json"
    if destination.is_symlink() or not destination.resolve().is_relative_to(root):
        raise StrengthEvidenceError("protocol/ledger destination escapes root")
    if isinstance(value, CampaignLedgerV1):
        if value.predecessor_sha256 is None:
            if value != initial_campaign_ledger():
                raise StrengthEvidenceError("unpinned or truncated campaign genesis")
        else:
            prior_path = root / folder / f"{value.predecessor_sha256}.json"
            previous = load_campaign(prior_path, expected_sha256=value.predecessor_sha256)
            _check_edge(previous, value)
    payload = pretty_json(
        protocol_summary(value) if isinstance(value, ProspectiveProtocolV1) else value
    ).encode()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink() or not destination.resolve().is_relative_to(root):
        raise StrengthEvidenceError("retained path changed")
    handle, name = tempfile.mkstemp(prefix=".public-protocol-", dir=destination.parent)
    temporary = Path(name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if destination.is_symlink() or destination.read_bytes() != payload:
                raise StrengthEvidenceError(
                    "immutable protocol/ledger identity collision"
                ) from None
    finally:
        temporary.unlink()
    return destination


def load_protocol_evidence(path: Path, *, expected_sha256: str) -> ProspectiveProtocolV1:
    return authenticate(
        ProspectiveProtocolV1.model_validate_json(path.read_bytes()), expected_sha256
    )


def load_campaign(path: Path, *, expected_sha256: str) -> CampaignLedgerV1:
    top = authenticate(CampaignLedgerV1.model_validate_json(path.read_bytes()), expected_sha256)
    current = top
    seen: set[str] = set()
    while current.predecessor_sha256 is not None:
        if current.semantic_sha256 in seen:
            raise StrengthEvidenceError("campaign ancestry cycle")
        seen.add(current.semantic_sha256)
        predecessor_path = path.parent / f"{current.predecessor_sha256}.json"
        if predecessor_path.is_symlink() or not predecessor_path.resolve().is_relative_to(
            path.parent.resolve()
        ):
            raise StrengthEvidenceError("unsafe campaign predecessor")
        previous = authenticate(
            CampaignLedgerV1.model_validate_json(predecessor_path.read_bytes()),
            current.predecessor_sha256,
        )
        _check_edge(previous, current)
        current = previous
    if current != initial_campaign_ledger():
        raise StrengthEvidenceError("unpinned or truncated campaign genesis")
    return top


def _check_edge(previous: CampaignLedgerV1, current: CampaignLedgerV1) -> None:
    append_only = (
        current.protocol == previous.protocol
        and current.protocol_history == previous.protocol_history
        and current.events[: len(previous.events)] == previous.events
        and len(current.events) == len(previous.events) + 1
    )
    amendment = (
        current.protocol.predecessor_protocol_sha256 == previous.protocol.semantic_sha256
        and current.protocol_history == (*previous.protocol_history, previous.protocol)
        and current.events == previous.events
        and current.protocol.evaluation_epoch != previous.protocol.evaluation_epoch
    )
    if not (append_only or amendment) or current.created_at < previous.created_at:
        raise StrengthEvidenceError(
            "ledger must append immutable evidence or an explicit new-epoch amendment"
        )
