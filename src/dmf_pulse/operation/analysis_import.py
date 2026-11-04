"""One fixed authenticated GW10 derived import; grants no acquisition authority."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import UTC, datetime
from pathlib import Path

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.dashboard.views import DeskView
from dmf_pulse.operation.analysis_models import AnalysisSnapshot
from dmf_pulse.operation.analysis_store import AnalysisStore
from dmf_pulse.operation.diagnostics import DiagnosticReport

_PINS = {
    "ACTUAL-SESSION006-VERIFIED-VIEW.json": "6b1e2aff6852d3740a111dadb20b541ad5b10a67d6d444f9a8f0a0e3a28cede6",
    "ACTUAL-SESSION006-PLAYER-FORECASTS.csv": "fc440d1c88cf817efa69eaec6bd8878ba81f4ca832f195ace97a4829e34a2b0e",
    "ACTUAL-SESSION006-RECOMMENDATIONS.txt": "294b3eed8867275417820e0391414a96f8da5006db25574519cfd4239ff77846",
    "ACTUAL-SESSION006-OUTPUT-MANIFEST.json": "ecd4f7af85eb9664f6275a65cde9e52688c91092079e5c86efaee70f15675671",
    "ACTUAL-SESSION006-TERMINAL-CUSTODY.json": "eeefb433ee2efabc666ccc6651f5aa56d431d139ef7d8264e98c89cbc8f1b31e",
    "INDEPENDENT-ACTUAL-SESSION006-TERMINAL-REVIEW-151.json": "f6e0fa8cd911e655d86e421aab0cc892795ac23218cf6cb32b5cde75202b6718",
}


def import_gw10(store: AnalysisStore, evidence: Path) -> str:
    authenticated: dict[str, bytes] = {}
    for name, digest in _PINS.items():
        path = evidence / name
        if path.is_symlink() or path.is_junction() or not 0 < path.stat().st_size <= 16_777_216:
            raise ValueError("GW10_IMPORT_EVIDENCE_PATH_INVALID")
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != digest:
            raise ValueError("GW10_IMPORT_EVIDENCE_CHANGED")
        authenticated[name] = body
    view = DeskView.model_validate_json(authenticated["ACTUAL-SESSION006-VERIFIED-VIEW.json"])
    audit = json.loads(authenticated["INDEPENDENT-ACTUAL-SESSION006-TERMINAL-REVIEW-151.json"])
    custody = json.loads(authenticated["ACTUAL-SESSION006-TERMINAL-CUSTODY.json"])
    manifest = json.loads(authenticated["ACTUAL-SESSION006-OUTPUT-MANIFEST.json"])
    terminals = [
        row
        for row in custody["operator_rows"]
        if row["execution_key"] == view.job_id
        and row["payload"]["value"].get("subtype") == "TERMINAL"
    ]
    if (
        len(terminals) != 1
        or audit["outcome"] != "REAL_PUBLICATION"
        or audit["terminal_sha256"] != terminals[0]["sha256"]
        or terminals[0]["payload"]["value"]["view"] != view.model_dump(mode="json")
        or canonical_sha256(view.model_dump(mode="json")) != manifest["view_semantic_sha256"]
        or audit["publication_proof"]["view_sha256"] != manifest["view_semantic_sha256"]
        or view.gameweeks != (10,)
        or view.catalogue_count != 670
        or len(view.players) != 670
    ):
        raise ValueError("GW10_IMPORT_PUBLICATION_MISMATCH")
    rows = list(
        csv.DictReader(
            io.StringIO(authenticated["ACTUAL-SESSION006-PLAYER-FORECASTS.csv"].decode("utf-8"))
        )
    )
    if len(rows) != 670 or {int(row["official_id"]) for row in rows} != {
        p.catalogue.official_id for p in view.players
    }:
        raise ValueError("GW10_IMPORT_PLAYER_MAPPING_INVALID")
    snapshot = AnalysisSnapshot(
        run_id=view.job_id,
        provenance_class="GW10_DIAGNOSTIC",
        permission_origin="OWNER_ATTESTED_NOT_ISSUER_AUTHENTICATED",
        source_commit=audit["source_commit"],
        implementation_sha=view.team.decision.lineage.code_sha,
        policy_sha256=custody["policy_sha256"],
        wheel_sha256=custody["private_wheel_sha256"],
        recorded_at=datetime.now(UTC),
        view=view,
        diagnostics=DiagnosticReport.model_validate_json(
            json.dumps(terminals[0]["payload"]["value"]["diagnostics"])
        ),
        original_artifact_sha256=_PINS["ACTUAL-SESSION006-VERIFIED-VIEW.json"],
    )
    # The authenticated immutable original is the import identity. Re-import
    # returns the existing snapshot, preserving its first analytical import time.
    existing = store.snapshot(view.job_id, include_pending=True)
    if existing is not None:
        if (
            existing.original_artifact_sha256 != snapshot.original_artifact_sha256
            or existing.view != snapshot.view
        ):
            raise ValueError("GW10_IMPORT_EXISTING_RUN_CONFLICT")
        store.confirm(
            existing.run_id,
            existing.semantic_sha256,
            terminals[0]["sha256"],
            at=datetime.fromisoformat(terminals[0]["at"]),
        )
        return existing.semantic_sha256
    digest = store.stage(snapshot)
    store.confirm(
        snapshot.run_id,
        digest,
        terminals[0]["sha256"],
        at=datetime.fromisoformat(terminals[0]["at"]),
    )
    return digest
