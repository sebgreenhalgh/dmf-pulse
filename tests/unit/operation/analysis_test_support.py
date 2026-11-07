"""Complete owned analytical fixture; fresh engine parity belongs to integration."""

import hashlib
from pathlib import Path

from dmf_pulse.operation.analysis_models import AnalysisSnapshot

FIXTURE = (
    Path(__file__).resolve().parents[3] / "fixtures/operation/analysis/owned_full_snapshot_v1.json"
)
FIXTURE_SHA256 = "83b899584c6629e74838dfb55015dd2b8ccc7ef4f4f1361249004868da9cd83a"
SNAPSHOT_SHA256 = "74c90cd4a0afcf0dc24520b17c3416561dae7f725768079690e60f091db95eb9"


def load_owned_snapshot(path: Path = FIXTURE) -> AnalysisSnapshot:
    """Validate exact owned bytes and return a fresh instance for each consumer."""
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != FIXTURE_SHA256:
        raise ValueError("OWNED_ANALYSIS_FIXTURE_BYTES_CHANGED")
    snapshot = AnalysisSnapshot.model_validate_json(body)
    if (
        snapshot.semantic_sha256 != SNAPSHOT_SHA256
        or snapshot.provenance_class != "OWNED_SYNTHETIC"
        or snapshot.permission_origin != "OWNED_FIXTURE"
        or snapshot.view.catalogue_count != 121
        or snapshot.view.projected_count != 120
    ):
        raise ValueError("OWNED_ANALYSIS_FIXTURE_BINDING_CHANGED")
    return snapshot
