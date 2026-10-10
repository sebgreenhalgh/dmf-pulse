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
    if isinstance(value, CampaignLedgerV1) and value.predecessor_sha256 is not None:
        prior_path = root / folder / f"{value.predecessor_sha256}.json"
        previous = load_campaign(prior_path, expected_sha256=value.predecessor_sha256)
        if (
            value.protocol != previous.protocol
            or value.events[: len(previous.events)] != previous.events
            or len(value.events) != len(previous.events) + 1
        ):
            raise StrengthEvidenceError(
                "ledger must append exactly one event to immutable predecessor"
            )
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
    return authenticate(CampaignLedgerV1.model_validate_json(path.read_bytes()), expected_sha256)
