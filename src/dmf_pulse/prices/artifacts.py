"""Stage-13 semantic sealing on top of the accepted Stage-12 artifact infrastructure."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from dmf_pulse.evaluation.artifacts import (
    load_verified_artifact,
    persist_artifact,
    seal,
    verify_sealed,
)
from dmf_pulse.prices.models import (
    ArtifactReceipt,
    CompetingLogitArtifact,
    EarlyTransferDecision,
    ExternalPredictorObservation,
    PriceCalibrationArtifact,
    PriceObservation,
    PricePathDistribution,
    PriceProjection,
)


def seal_observation(value: PriceObservation) -> PriceObservation:
    return seal(value, "semantic_hash")


def seal_external_observation(
    value: ExternalPredictorObservation,
) -> ExternalPredictorObservation:
    return seal(value, "semantic_hash")


def seal_competing_logit(value: CompetingLogitArtifact) -> CompetingLogitArtifact:
    return seal(value, "artifact_sha256")


def seal_price_calibration(value: PriceCalibrationArtifact) -> PriceCalibrationArtifact:
    return seal(value, "artifact_sha256")


def seal_path_distribution(value: PricePathDistribution) -> PricePathDistribution:
    return seal(value, "distribution_sha256")


def seal_projection(value: PriceProjection) -> PriceProjection:
    return seal(value, "projection_sha256")


def seal_early_transfer_decision(value: EarlyTransferDecision) -> EarlyTransferDecision:
    return seal(value, "decision_sha256")


def persist_price_artifact[PriceArtifactT: BaseModel](
    value: PriceArtifactT,
    *,
    hash_field: str,
    artifact_root: Path,
    category: str,
    identity: str,
) -> ArtifactReceipt:
    """Verify semantic identity, then use Stage 12's write-once content addressing."""

    verify_sealed(value, hash_field)
    path = persist_artifact(
        value,
        artifact_root=artifact_root,
        category=f"prices-{category}",
        identity=identity,
    )
    return ArtifactReceipt(
        artifact_path=path.as_posix(),
        artifact_sha256=path.stem,
        semantic_sha256=getattr(value, hash_field),
    )


def load_price_artifact[PriceArtifactT: BaseModel](
    path: Path,
    model_type: type[PriceArtifactT],
    *,
    hash_field: str,
) -> PriceArtifactT:
    return load_verified_artifact(path, model_type, hash_field=hash_field)
