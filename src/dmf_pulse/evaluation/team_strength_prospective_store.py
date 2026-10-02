"""Explicit content-addressed public-team evidence storage; no private surface."""

import os
import tempfile
from pathlib import Path

from dmf_pulse.assurance.canonical import pretty_json
from dmf_pulse.evaluation.team_strength_prospective import (
    PrivateProspectiveStorageDenied,
    PublicTeamStrengthForecastV1,
    require_public_prospective_storage,
)
from dmf_pulse.ingestion.openfootball.team_strength_data import StrengthEvidenceError, authenticate


def persist_public_forecast(value: PublicTeamStrengthForecastV1, *, artifact_root: Path) -> Path:
    if type(value) is not PublicTeamStrengthForecastV1:
        raise PrivateProspectiveStorageDenied("only the public team forecast schema may persist")
    require_public_prospective_storage(value.data_class)
    value = authenticate(value)
    if artifact_root.is_symlink():
        raise StrengthEvidenceError("public forecast root must not be a symbolic link")
    root = artifact_root.resolve()
    destination = root / "public-team-strength-prospective" / f"{value.semantic_sha256}.json"
    if destination.is_symlink() or not destination.resolve().is_relative_to(root):
        raise StrengthEvidenceError("public forecast path escapes explicit root")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink() or not destination.resolve().is_relative_to(root):
        raise StrengthEvidenceError("public forecast destination changed")
    payload = pretty_json(value).encode("utf-8")
    if destination.exists():
        if destination.read_bytes() != payload:
            raise StrengthEvidenceError("immutable forecast identity collision")
        return destination
    handle, name = tempfile.mkstemp(prefix=".public-forecast-", dir=destination.parent)
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
                raise StrengthEvidenceError("immutable forecast publication collision") from None
    finally:
        temporary.unlink()
    return destination


def load_public_forecast(
    path: Path, *, expected_forecast_sha256: str
) -> PublicTeamStrengthForecastV1:
    return authenticate(
        PublicTeamStrengthForecastV1.model_validate_json(path.read_bytes()),
        expected_forecast_sha256,
    )
