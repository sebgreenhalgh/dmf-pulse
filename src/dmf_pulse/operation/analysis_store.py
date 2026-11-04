"""Durable derived read model. SQLite never grants operational authorization."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any, Literal

from dmf_pulse.operation.analysis_models import AnalysisSnapshot
from dmf_pulse.operation.analysis_paths import protect_owner_path
from dmf_pulse.operation.diagnostics import DiagnosticReport
from dmf_pulse.operation.models import ChargedQuotaStatus

AnalysisStorageError = sqlite3.Error
_MAX_SNAPSHOT_BYTES = 32 * 1024 * 1024

_SCHEMA = """
CREATE TABLE snapshots (
 run_id TEXT PRIMARY KEY, digest TEXT NOT NULL UNIQUE, payload TEXT NOT NULL CHECK(json_valid(payload))
);
CREATE TABLE publications (
 run_id TEXT PRIMARY KEY REFERENCES snapshots(run_id), digest TEXT NOT NULL,
 canonical_sha256 TEXT NOT NULL, confirmed_at TEXT NOT NULL
);
CREATE TABLE failed_attempts (
 attempt_id TEXT PRIMARY KEY, recorded_at TEXT NOT NULL, error_code TEXT NOT NULL
);
CREATE TABLE failure_evidence (
 attempt_id TEXT PRIMARY KEY REFERENCES failed_attempts(attempt_id),
 derived_json TEXT NOT NULL CHECK(json_valid(derived_json))
);
CREATE VIEW runs AS SELECT s.run_id, s.digest, p.canonical_sha256, p.confirmed_at,
 'COMPLETE' AS run_status, 'HISTORICAL_AS_OF' AS temporal_status,
 json_extract(payload,'$.provenance_class') AS provenance_class,
 json_extract(payload,'$.validation') AS validation,
 json_extract(payload,'$.rights') AS rights,
 json_extract(payload,'$.permission_origin') AS permission_origin,
 json_extract(payload,'$.view.generated_at') AS generated_at,
 json_extract(payload,'$.view.information_cutoff') AS information_cutoff,
 json_extract(payload,'$.view.source_captured_at') AS source_captured_at,
 json_extract(payload,'$.view.gameweeks[0]') AS gameweek,
 json_extract(payload,'$.source_commit') AS source_commit,
 json_extract(payload,'$.implementation_sha') AS implementation_sha,
 json_extract(payload,'$.policy_sha256') AS policy_sha256,
 json_extract(payload,'$.wheel_sha256') AS wheel_sha256,
 json_extract(payload,'$.view.team') AS manager_decision_json,
 json_extract(payload,'$.view.source_vintages') AS source_vintages_json,
 json_extract(payload,'$.view.market_quota_receipt') AS observed_quota_json,
 json_extract(payload,'$.captaincy_explanation') AS captaincy_explanation,
 json_extract(payload,'$.view.restrictions') AS restrictions_json
 FROM snapshots s JOIN publications p ON s.run_id=p.run_id AND s.digest=p.digest;
CREATE VIEW player_forecasts AS SELECT s.run_id,
 json_extract(j.value,'$.catalogue.official_id') AS official_id,
 json_extract(j.value,'$.catalogue.player_id') AS player_id,
 json_extract(j.value,'$.catalogue.name') AS name,
 json_extract(j.value,'$.catalogue.team') AS team,
 json_extract(j.value,'$.catalogue.position') AS position,
 json_extract(j.value,'$.catalogue.price_tenths') AS price_tenths,
 json_extract(j.value,'$.expected_points') AS expected_points,
 json_extract(j.value,'$.median_points') AS median,
 json_extract(j.value,'$.points_p10') AS p10,
 json_extract(j.value,'$.points_p90') AS p90,
 json_extract(j.value,'$.points_standard_deviation') AS standard_deviation,
 json_extract(j.value,'$.monte_carlo_mean_se') AS mean_se,
 json_extract(j.value,'$.expected_minutes') AS expected_minutes,
 json_extract(j.value,'$.p_start') AS p_start,
 json_extract(j.value,'$.p_60_plus') AS p_60_plus,
 json_extract(j.value,'$.confidence') AS confidence,
 json_extract(j.value,'$.fallback') AS fallback, j.value AS derived_json
 FROM snapshots s JOIN runs r ON r.run_id=s.run_id, json_each(payload,'$.view.players') j;
CREATE VIEW manager_squad AS SELECT s.run_id, j.key AS squad_order, j.value AS player_id,
 json_extract(payload,'$.view.team.current_bank_tenths') AS bank_tenths,
 json_extract(payload,'$.view.team.current_team_value_tenths') AS team_value_tenths
 FROM snapshots s JOIN runs r ON r.run_id=s.run_id,
 json_each(payload,'$.view.team.current_squad') j;
CREATE VIEW fixture_projections AS SELECT s.run_id, j.value AS derived_json,
 json_extract(j.value,'$.fixture_id') AS fixture_id,
 json_extract(j.value,'$.official_fixture_id') AS official_fixture_id,
 json_extract(j.value,'$.gameweek') AS gameweek
 FROM snapshots s JOIN runs r ON r.run_id=s.run_id,
 json_each(payload,'$.presentation.fixtures') j;
CREATE VIEW gameweek_projections AS SELECT s.run_id,j.value AS derived_json
 FROM snapshots s JOIN runs r ON r.run_id=s.run_id,
 json_each(payload,'$.presentation.gameweeks') j;
CREATE VIEW optimizer_evidence AS SELECT s.run_id,
 json_extract(payload,'$.optimizer_evidence.optimiser_result') AS derived_json,
 json_extract(payload,'$.optimizer_evidence.optimiser_result.result_sha256') AS optimizer_sha256,
 json_extract(payload,'$.optimizer_evidence.optimiser_result.recommended_plan') AS recommended_plan_json,
 json_extract(payload,'$.optimizer_evidence.optimiser_result.conservative_plan') AS conservative_plan_json,
 json_extract(payload,'$.optimizer_evidence.optimiser_result.high_upside_plan') AS high_upside_plan_json,
 json_extract(payload,'$.optimizer_evidence.optimiser_result.root_action_counterfactual_plan') AS root_counterfactual_json,
 json_extract(payload,'$.optimizer_evidence.optimiser_result.marginal_value_of_each_move') AS move_attribution_json
 FROM snapshots s JOIN runs r ON r.run_id=s.run_id;
CREATE VIEW transfer_plans AS SELECT s.run_id,j.value AS derived_json,
 json_extract(j.value,'$.transfer_count') AS transfer_count
 FROM snapshots s JOIN runs r ON r.run_id=s.run_id,
 json_each(payload,'$.view.team.decision.transfer_frontier.points') j;
CREATE VIEW tactics AS SELECT s.run_id,
 json_extract(payload,'$.view.team.decision.tactics') AS recommended_json,
 json_extract(payload,'$.view.team.decision.no_transfer_tactics') AS hold_json,
 json_extract(payload,'$.view.team.decision.paired_comparison') AS paired_comparison_json
 FROM snapshots s JOIN runs r ON r.run_id=s.run_id;
CREATE VIEW captaincy_evidence AS SELECT s.run_id,
 json_extract(payload,'$.view.team.decision.tactics.captain') AS captain,
 json_extract(payload,'$.view.team.decision.tactics.vice_captain') AS vice_captain,
 json_extract(payload,'$.view.team.decision.tactics') AS actual_tactics_json,
 json_extract(payload,'$.view.team.decision.no_transfer_tactics') AS actual_hold_tactics_json,
 json_extract(payload,'$.view.team.decision.action_space_disclosure') AS objective_disclosure,
 json_extract(payload,'$.captaincy_explanation') AS explanation_availability,
 NULL AS captain_only_counterfactual_json, NULL AS captain_only_joint_outcomes_json
 FROM snapshots s JOIN runs r ON r.run_id=s.run_id;
CREATE VIEW acquisition_evidence AS SELECT s.run_id,j.value AS derived_json
 FROM snapshots s JOIN runs r ON r.run_id=s.run_id,
 json_each(payload,'$.diagnostics.requests') j;
CREATE VIEW analysis_attempts AS SELECT s.run_id AS attempt_id,
 CASE WHEN p.run_id IS NULL THEN 'PENDING_UNCONFIRMED' ELSE 'COMPLETE' END AS run_status,
 json_extract(payload,'$.recorded_at') AS recorded_at,NULL AS error_code
 FROM snapshots s LEFT JOIN publications p ON s.run_id=p.run_id
 UNION ALL SELECT attempt_id,'FAILED',recorded_at,error_code FROM failed_attempts;
CREATE VIEW run_player_changes AS SELECT a.run_id AS old_run_id,b.run_id AS new_run_id,
 a.official_id,b.expected_points-a.expected_points AS expected_points_delta
 FROM player_forecasts a JOIN player_forecasts b ON a.official_id=b.official_id
 WHERE a.run_id<>b.run_id;
"""


class AnalysisStore:
    """Explicit open/migrate/write; no mutable latest pointer or historical overwrite."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        protect_owner_path(self.path.parent)
        if self.path.exists():
            protect_owner_path(self.path)
        with closing(sqlite3.connect(self.path, timeout=5)) as connection:
            protect_owner_path(self.path)
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA synchronous=FULL")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in {0, 1}:
                raise ValueError("ANALYSIS_SCHEMA_VERSION_UNSUPPORTED")
            if version == 0:
                if connection.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]:
                    raise ValueError("ANALYSIS_UNKNOWN_SCHEMA")
                triggers = "\n".join(
                    f"CREATE TRIGGER {table}_{action} BEFORE {action} ON {table} "
                    "BEGIN SELECT RAISE(ABORT,'IMMUTABLE_ANALYSIS_RECORD'); END;"
                    for table in (
                        "snapshots",
                        "publications",
                        "failed_attempts",
                        "failure_evidence",
                    )
                    for action in ("UPDATE", "DELETE")
                )
                connection.executescript(
                    "BEGIN IMMEDIATE;\n" + _SCHEMA + triggers + "\nPRAGMA user_version=1; COMMIT;"
                )
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("ANALYSIS_DATABASE_CORRUPT")

    def _connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        mode = "ro" if readonly else "rw"
        connection = sqlite3.connect(
            self.path.resolve().as_uri() + f"?mode={mode}",
            uri=True,
            timeout=5,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        # A full 760-player result with optimizer outcomes exceeds 16 MiB.
        # Query output remains independently bounded to 16 MiB below.
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, _MAX_SNAPSHOT_BYTES + 65_536)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        if readonly:
            connection.execute("PRAGMA query_only=ON")
        if connection.execute("PRAGMA user_version").fetchone()[0] != 1:
            connection.close()
            raise ValueError("ANALYSIS_SCHEMA_VERSION_UNSUPPORTED")
        return connection

    def stage(self, snapshot: AnalysisSnapshot) -> str:
        body = snapshot.model_dump_json()
        snapshot = AnalysisSnapshot.model_validate_json(body)
        if len(body.encode()) > _MAX_SNAPSHOT_BYTES:
            raise ValueError("ANALYSIS_SNAPSHOT_TOO_LARGE")
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT digest FROM snapshots WHERE run_id=?", (snapshot.run_id,)
            ).fetchone()
            if existing is not None:
                if existing[0] != snapshot.semantic_sha256:
                    raise ValueError("ANALYSIS_RUN_ID_CONFLICT")
            else:
                connection.execute(
                    "INSERT INTO snapshots VALUES (?,?,?)",
                    (snapshot.run_id, snapshot.semantic_sha256, body),
                )
        return snapshot.semantic_sha256

    def confirm(self, run_id: str, digest: str, canonical_sha256: str, *, at: datetime) -> None:
        if len(canonical_sha256) != 64 or any(
            c not in "0123456789abcdef" for c in canonical_sha256
        ):
            raise ValueError("ANALYSIS_PUBLICATION_ID_INVALID")
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("ANALYSIS_UTC_REQUIRED")
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT digest,payload FROM snapshots WHERE run_id=?", (run_id,)
            ).fetchone()
            if (
                row is None
                or row[0] != digest
                or AnalysisSnapshot.model_validate_json(row[1]).semantic_sha256 != digest
            ):
                raise ValueError("ANALYSIS_PUBLICATION_BINDING_INVALID")
            old = connection.execute(
                "SELECT digest,canonical_sha256 FROM publications WHERE run_id=?", (run_id,)
            ).fetchone()
            if old is not None:
                if tuple(old) != (digest, canonical_sha256):
                    raise ValueError("ANALYSIS_PUBLICATION_CONFLICT")
            else:
                connection.execute(
                    "INSERT INTO publications VALUES (?,?,?,?)",
                    (run_id, digest, canonical_sha256, at.astimezone(UTC).isoformat()),
                )

    def snapshot(
        self, run_id: str | None = None, *, include_pending: bool = False
    ) -> AnalysisSnapshot | None:
        if include_pending and run_id is None:
            raise ValueError("ANALYSIS_EXACT_PENDING_RUN_REQUIRED")
        with closing(self._connect(readonly=True)) as connection:
            row = connection.execute(
                "SELECT s.payload,s.digest FROM snapshots s "
                + ("" if include_pending else "JOIN runs r ON s.run_id=r.run_id ")
                + (
                    "WHERE s.run_id=?"
                    if run_id is not None
                    else "ORDER BY r.generated_at DESC,r.run_id DESC LIMIT 1"
                ),
                () if run_id is None else (run_id,),
            ).fetchone()
        if row is None:
            return None
        value = AnalysisSnapshot.model_validate_json(row[0])
        if value.semantic_sha256 != row[1]:
            raise ValueError("ANALYSIS_SNAPSHOT_DIGEST_MISMATCH")
        return value

    def history(self) -> list[dict[str, Any]]:
        return self.query(
            "SELECT run_id,digest,canonical_sha256,confirmed_at,run_status,temporal_status,"
            "provenance_class,validation,rights,permission_origin,generated_at,"
            "information_cutoff,source_captured_at,gameweek,source_commit,"
            "implementation_sha,policy_sha256,wheel_sha256 "
            "FROM runs ORDER BY generated_at DESC,run_id DESC"
        )

    def failure(
        self,
        attempt_id: str,
        code: str,
        *,
        at: datetime,
        diagnostics: DiagnosticReport | None = None,
        quota: ChargedQuotaStatus | None = None,
        provenance: Literal["NORMAL_STANDING", "OWNED_SYNTHETIC"] = "NORMAL_STANDING",
    ) -> None:
        from dmf_pulse.current_failures import CURRENT_FAILURE_CODES
        from dmf_pulse.operation.failures import OPERATOR_FAILURE_ACTIONS

        credential_codes = {
            "CREDENTIAL_JWT_INVALID",
            "CREDENTIAL_EXPIRED",
            "CREDENTIAL_BACKEND_UNAVAILABLE",
            "CREDENTIAL_JWT_LIFETIME_INVALID",
        }
        safe = (
            code
            if code in CURRENT_FAILURE_CODES
            or code in OPERATOR_FAILURE_ACTIONS
            or code in credential_codes
            else "CURRENT_TYPED_FAILURE_UNRECOGNIZED"
        )
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("ANALYSIS_UTC_REQUIRED")
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            payload = json.dumps(
                {
                    "provenance_class": provenance,
                    "validation": "UNVALIDATED",
                    "diagnostics": None
                    if diagnostics is None
                    else diagnostics.model_dump(mode="json"),
                    "quota": None if quota is None else quota.model_dump(mode="json"),
                },
                sort_keys=True,
            )
            old = connection.execute(
                "SELECT f.error_code,e.derived_json FROM failed_attempts f LEFT JOIN failure_evidence e USING(attempt_id) WHERE f.attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if old is not None:
                if tuple(old) != (safe, payload):
                    raise ValueError("ANALYSIS_FAILED_ATTEMPT_CONFLICT")
                return
            connection.execute(
                "INSERT INTO failed_attempts VALUES (?,?,?)",
                (attempt_id, at.astimezone(UTC).isoformat(), safe),
            )
            connection.execute("INSERT INTO failure_evidence VALUES (?,?)", (attempt_id, payload))

    def query(self, sql: str, *, limit: int = 10000) -> list[dict[str, Any]]:
        """Read-only SQLite authorizer, bounded runtime and rows; no operational imports."""
        if len(sql) > 16384 or not 1 <= limit <= 10000:
            raise ValueError("ANALYSIS_QUERY_BOUND_EXCEEDED")
        allowed = {
            sqlite3.SQLITE_SELECT,
            sqlite3.SQLITE_READ,
            sqlite3.SQLITE_FUNCTION,
            sqlite3.SQLITE_RECURSIVE,
        }
        started = monotonic()
        with closing(self._connect(readonly=True)) as connection:
            connection.enable_load_extension(False)
            connection.set_authorizer(
                lambda action, first, second, db, source: (
                    sqlite3.SQLITE_OK
                    if action in allowed
                    and (second or "").lower() not in {"load_extension", "writefile", "readfile"}
                    else sqlite3.SQLITE_DENY
                )
            )
            connection.set_progress_handler(lambda: int(monotonic() - started > 5), 10000)
            result: list[dict[str, Any]] = []
            output_bytes = 2
            for row in connection.execute(sql):
                if len(result) >= limit:
                    raise ValueError("ANALYSIS_QUERY_ROW_LIMIT_EXCEEDED")
                item = dict(row)
                try:
                    output_bytes += len(json.dumps(item, ensure_ascii=False).encode()) + 2
                except TypeError:
                    raise ValueError("ANALYSIS_QUERY_BINARY_OUTPUT_REJECTED") from None
                if output_bytes > 16_777_216:
                    raise ValueError("ANALYSIS_QUERY_OUTPUT_LIMIT_EXCEEDED")
                result.append(item)
            return result

    def export_json(self, run_id: str | None = None) -> str:
        value = self.snapshot(run_id)
        if value is None:
            raise ValueError("ANALYSIS_RUN_UNAVAILABLE")
        return json.dumps(
            value.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, indent=2
        )
