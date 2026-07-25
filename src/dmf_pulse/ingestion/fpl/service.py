"""Rights-gated, resumable FPL reference ingestion service."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import Engine, func, insert, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from dmf_pulse import __version__
from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.data_model.models import require_utc
from dmf_pulse.data_model.tables import data_quality_issue, source_processing_event, source_snapshot
from dmf_pulse.database.engine import (
    create_database_engine,
    resolve_test_database_url,
    session_factory,
)
from dmf_pulse.database.errors import DatabaseError
from dmf_pulse.database.models import DatabaseSettings
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fixtures import ApprovedFixture, approve_synthetic_fixture
from dmf_pulse.ingestion.fpl.adapter import FplReferenceAdapter
from dmf_pulse.ingestion.fpl.client import Transport, UrllibTransport
from dmf_pulse.ingestion.fpl.config import (
    effective_config_sha256,
    load_provider_config,
    provider_config_sha256,
)
from dmf_pulse.ingestion.fpl.parser import (
    CONTRACT_VERSION,
    BootstrapPayload,
    FixturePayload,
    FplResource,
    ParsedFplResource,
    parse_fpl_payload,
    parsed_artifact,
)
from dmf_pulse.ingestion.fpl.persistence import (
    FplMappingPlan,
    FplPersistence,
    ensure_official_provider,
    ensure_synthetic_provider,
)
from dmf_pulse.ingestion.models import (
    DriftClassification,
    FplValidationResult,
    MissingnessValue,
    ProviderResourceResult,
    ProviderSnapshotResult,
    QualityIssue,
    QualityReport,
    RightsCapability,
    RightsDecision,
    RightsProfile,
    SourceBundleSummary,
)
from dmf_pulse.ingestion.repository import (
    append_processing_event_idempotent,
    get_or_create_raw_content,
    get_or_create_raw_storage_object,
    lifecycle_state,
    received_context,
    record_ingestion_run,
    record_received_snapshot,
    record_rights_decision,
    register_rights_profile,
)
from dmf_pulse.ingestion.rights import (
    decide_rights,
    load_rights_profiles,
    require_rights,
    rights_config_sha256,
)

DATABASE_REF = "env:DMF_TEST_DATABASE_URL"
TARGET_REVISION = "20260724_0002"
DEFAULT_CAPTURED_AT = datetime(2026, 8, 21, 17, 0, tzinfo=UTC)
DEFAULT_INFORMATION_CUTOFF = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)
VOLATILE_ROOT_NAME = "dmf-fpl004-volatile"
VOLATILE_OPERATION_PATTERN = re.compile(
    r"^(?:preparing|active)-(?P<pid>[1-9][0-9]*)-(?P<token>[0-9a-f]{32})$"
)
STAGE_INDEX = {
    "ENVELOPE_ONLY": 0,
    "RECEIVED": 1,
    "STORED": 2,
    "RAW_DISCARDED": 2,
    "PARSED": 3,
    "VALIDATED": 4,
    "MAPPED": 5,
    "PROMOTED": 6,
    "QUALITY_PASSED": 7,
    "USABLE": 8,
}


@dataclass(frozen=True, slots=True)
class FplImportRequest:
    bootstrap_path: Path
    fixtures_path: Path
    competition_key: str
    season_code: str
    captured_at: datetime
    information_cutoff: datetime
    rights_profile_id: str
    database_url_ref: str = DATABASE_REF
    halt_after_stage: str | None = None


@dataclass(frozen=True, slots=True)
class FplReplayRequest:
    fixture_set: Path
    scenario: str
    information_cutoff: datetime = DEFAULT_INFORMATION_CUTOFF
    rights_profile_id: str = "synthetic_test_v1"
    database_url_ref: str = DATABASE_REF
    competition_key: str = "SYNTHETIC_PL"
    season_code: str = "2026/27"
    halt_after_stage: str | None = None


@dataclass(frozen=True, slots=True)
class FplOperationOutcome:
    result: ProviderSnapshotResult
    exit_code: int = 0


class IngestionInterrupted(RuntimeError):
    """Deterministic synthetic fault used to prove restart safety."""

    def __init__(self, stage: str, snapshot_ids: tuple[UUID, UUID]) -> None:
        super().__init__(f"synthetic interruption after {stage}")
        self.stage = stage
        self.snapshot_ids = snapshot_ids


def resolve_database_reference(reference: str) -> str:
    """Resolve the one sanctioned test reference without accepting a URL value."""

    if reference != DATABASE_REF or "://" in reference or "@" in reference:
        raise IngestionError(
            "DATABASE_REFERENCE_INVALID",
            "database reference must name the sanctioned TEST environment variable",
        )
    try:
        return resolve_test_database_url(environment=os.environ.get("DMF_ENVIRONMENT", ""))
    except DatabaseError as exc:
        raise IngestionError("DATABASE_REFERENCE_INVALID", exc.message) from exc


def _validate_database_reference(reference: str | None) -> None:
    if reference is None:
        return
    try:
        DatabaseSettings(url_secret_ref=reference)
    except ValueError:
        raise IngestionError(
            "DATABASE_REFERENCE_INVALID",
            "database reference must name the sanctioned TEST environment variable",
        ) from None
    if reference != DATABASE_REF:
        raise IngestionError(
            "DATABASE_REFERENCE_INVALID",
            "database reference must name the sanctioned TEST environment variable",
        )


def _validate_synthetic_context(request: FplImportRequest, profile: RightsProfile) -> None:
    if profile.rights_profile_id == "synthetic_test_v1" and (
        request.competition_key != "SYNTHETIC_PL" or request.season_code != "2026/27"
    ):
        raise IngestionError(
            "USAGE_INVALID",
            "synthetic fixtures require the fixed SYNTHETIC_PL 2026/27 context",
        )


def _engine(reference: str) -> Engine:
    url = resolve_database_reference(reference)
    settings = DatabaseSettings(
        url_secret_ref=DATABASE_REF,
        connect_timeout_seconds=5,
        application_name="dmf-pulse-fpl004",
    )
    try:
        engine = create_database_engine(url, settings)
        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        if revision != TARGET_REVISION:
            engine.dispose()
            raise IngestionError("DATABASE_SCHEMA_BEHIND", "database migration is not current")
        return engine
    except IngestionError:
        raise
    except (DatabaseError, SQLAlchemyError) as exc:
        raise _database_error(exc) from None


def _database_error(exc: BaseException) -> IngestionError:
    """Translate PostgreSQL failures without exposing driver messages or values."""

    if isinstance(exc, DatabaseError):
        if exc.code == "DATABASE_RETRYABLE":
            return IngestionError(
                "DATABASE_RETRYABLE",
                "database transaction must be retried",
                retryable=True,
            )
        if exc.code in {
            "DATABASE_CONSTRAINT_VIOLATION",
            "ENTITY_TYPE_MISMATCH",
            "TEMPORAL_OVERLAP",
            "TEMPORAL_RANGE_INVALID",
            "TEMPORAL_SUPERSESSION_CONFLICT",
        }:
            return IngestionError(
                "DATABASE_CONSTRAINT",
                "database constraint rejected the operation",
                details={"source_code": exc.code},
            )
        return IngestionError("DATABASE_UNAVAILABLE", "database is unavailable")
    original = getattr(exc, "orig", exc)
    sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    if sqlstate in {"40001", "40P01", "55P03"}:
        return IngestionError(
            "DATABASE_RETRYABLE",
            "database transaction must be retried",
            retryable=True,
            details={"sqlstate": sqlstate},
        )
    if isinstance(sqlstate, str) and sqlstate.startswith("23"):
        return IngestionError(
            "DATABASE_CONSTRAINT",
            "database constraint rejected the operation",
            details={"sqlstate": sqlstate},
        )
    return IngestionError("DATABASE_UNAVAILABLE", "database is unavailable")


def _read_bounded(path: Path) -> bytes:
    maximum = load_provider_config().max_response_bytes
    try:
        if path.is_symlink() or not path.is_file():
            raise OSError("input must be a nonsymlink regular file")
        with path.open("rb") as handle:
            body = handle.read(maximum + 1)
    except OSError as exc:
        raise IngestionError("USAGE_INVALID", "input file is unavailable") from exc
    if len(body) > maximum:
        raise IngestionError("PAYLOAD_TOO_LARGE", "payload exceeds the configured byte limit")
    return body


def _volatile_root() -> Path:
    return Path(tempfile.gettempdir()).resolve() / VOLATILE_ROOT_NAME


def _pid_is_running(pid: int) -> bool:
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _remove_volatile_directory(path: Path, root: Path) -> None:
    try:
        if path.is_symlink() or path.resolve(strict=True).parent != root:
            raise OSError("volatile directory escaped its service-owned root")
        shutil.rmtree(path)
    except OSError as exc:
        raise IngestionError(
            "RIGHTS_BLOCKED", "volatile input cleanup could not be verified"
        ) from exc


def _cleanup_orphan_volatile_directories(root: Path) -> None:
    """Remove only service-owned directories whose creating process has ended."""

    try:
        candidates = tuple(root.iterdir()) if root.exists() else ()
    except OSError as exc:
        raise IngestionError(
            "RIGHTS_BLOCKED", "volatile input cleanup could not be verified"
        ) from exc
    for candidate in candidates:
        match = VOLATILE_OPERATION_PATTERN.fullmatch(candidate.name)
        if match is None or candidate.is_symlink() or not candidate.is_dir():
            continue
        if _pid_is_running(int(match.group("pid"))):
            continue
        _remove_volatile_directory(candidate, root)


def _read_through_volatile_pair(bootstrap_path: Path, fixtures_path: Path) -> tuple[bytes, bytes]:
    """Read caller files through isolated service-owned copies, then destroy the copies."""

    sources = (bootstrap_path, fixtures_path)
    try:
        resolved = tuple(path.resolve(strict=True) for path in sources)
    except OSError:
        raise IngestionError("USAGE_INVALID", "input file is unavailable") from None
    if resolved[0] == resolved[1]:
        raise IngestionError("USAGE_INVALID", "bootstrap and fixtures inputs must differ")
    bodies = (_read_bounded(sources[0]), _read_bounded(sources[1]))
    root = _volatile_root()
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        root.chmod(0o700)
    except OSError as exc:
        raise IngestionError(
            "RIGHTS_BLOCKED", "volatile input storage could not be restricted"
        ) from exc
    _cleanup_orphan_volatile_directories(root)

    token = uuid4().hex
    preparing = root / f"preparing-{os.getpid()}-{token}"
    active = root / f"active-{os.getpid()}-{token}"
    current = preparing
    cleanup_required = False
    try:
        preparing.mkdir(mode=0o700)
        cleanup_required = True
        for name, body in zip(("bootstrap.json", "fixtures.json"), bodies, strict=True):
            target = preparing / name
            with target.open("xb") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            target.chmod(0o600)
        preparing.replace(active)
        current = active
        readback = (
            _read_bounded(active / "bootstrap.json"),
            _read_bounded(active / "fixtures.json"),
        )
        if tuple(hashlib.sha256(item).digest() for item in readback) != tuple(
            hashlib.sha256(item).digest() for item in bodies
        ):
            raise IngestionError("RIGHTS_BLOCKED", "volatile input read-back verification failed")
        return readback
    except IngestionError:
        raise
    except OSError as exc:
        raise IngestionError(
            "RIGHTS_BLOCKED", "volatile input handling could not be completed"
        ) from exc
    finally:
        if cleanup_required and current.exists():
            _remove_volatile_directory(current, root)


def _profile(profile_id: str) -> RightsProfile:
    profile = load_rights_profiles().get(profile_id)
    if profile is None:
        raise IngestionError("CONFIGURATION_INVALID", "rights profile is not configured")
    return profile


def _stage_time(captured_at: datetime, stage_number: int) -> datetime:
    return require_utc(captured_at) + timedelta(microseconds=stage_number)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _clean_quality() -> QualityReport:
    return QualityReport(status="PASS", warning_count=0, blocker_count=0, issues=())


def _merge_effect_counts(
    *values: dict[str, dict[str, int]],
) -> dict[str, dict[str, int]]:
    merged: dict[str, dict[str, int]] = {"changed": {}, "created": {}, "reused": {}}
    for value in values:
        for state in merged:
            for category, count in value.get(state, {}).items():
                merged[state][category] = merged[state].get(category, 0) + count
    return {state: dict(sorted(counts.items())) for state, counts in merged.items()}


def _quality_issue(
    *,
    severity: Literal["P0", "P1", "P2", "P3"],
    code: str,
    subject_scope: str,
    message: str,
    observed_at: datetime,
    safe_details: dict[str, object],
    missingness: MissingnessValue | None = None,
) -> QualityIssue:
    return QualityIssue(
        severity=severity,
        code=code,
        stage="VALIDATION",
        subject_scope=subject_scope,
        message=message,
        observed_at=require_utc(observed_at),
        evidence_sha256=canonical_sha256(safe_details),
        decision_impact=("BLOCKING" if severity in {"P0", "P1"} else "NONBLOCKING"),
        missingness=missingness,
        safe_details=safe_details,
    )


def _drift_quality(
    parsed: tuple[ParsedFplResource, ...], *, observed_at: datetime = DEFAULT_CAPTURED_AT
) -> QualityReport:
    issues: list[QualityIssue] = []
    for item in parsed:
        if item.drift.classification is DriftClassification.ADDITIVE_UNKNOWN:
            issues.append(
                _quality_issue(
                    severity="P3",
                    code="ADDITIVE_UNKNOWN",
                    subject_scope=f"SOURCE_SNAPSHOT:{item.resource.value}",
                    message="provider payload contains additive unknown fields",
                    observed_at=observed_at,
                    safe_details={"unknown_paths": list(item.drift.unknown_paths)},
                )
            )
        if item.drift.missing_optional_paths:
            issues.append(
                _quality_issue(
                    severity="P3",
                    code="OPTIONAL_FIELD_ABSENT",
                    subject_scope=f"SOURCE_SNAPSHOT:{item.resource.value}",
                    message="provider payload omits optional fields",
                    observed_at=observed_at,
                    safe_details={"paths": list(item.drift.missing_optional_paths)},
                    missingness=MissingnessValue.NOT_PUBLISHED,
                )
            )
        issues.append(
            _quality_issue(
                severity="P3",
                code="PROVIDER_SOURCE_TIME_ABSENT",
                subject_scope=f"SOURCE_SNAPSHOT:{item.resource.value}",
                message="provider source time was not published",
                observed_at=observed_at,
                safe_details={"resource": item.resource.value},
                missingness=MissingnessValue.SOURCE_UNAVAILABLE,
            )
        )
    bootstrap = next(
        (item.payload for item in parsed if isinstance(item.payload, BootstrapPayload)), None
    )
    if isinstance(bootstrap, BootstrapPayload):
        aliases = [item.name.casefold() for item in bootstrap.teams]
        aliases.extend(item.web_name.casefold() for item in bootstrap.elements)
        duplicates = sorted({alias for alias in aliases if aliases.count(alias) > 1})
        if duplicates:
            issues.append(
                _quality_issue(
                    severity="P3",
                    code="NONCRITICAL_DUPLICATED_ALIAS",
                    subject_scope="SOURCE_SNAPSHOT:bootstrap",
                    message="provider payload contains a noncritical duplicated alias",
                    observed_at=observed_at,
                    safe_details={"duplicate_count": len(duplicates)},
                )
            )
    return QualityReport(
        status="PASS_WITH_WARNINGS" if issues else "PASS",
        warning_count=len(issues),
        blocker_count=0,
        issues=tuple(issues),
    )


def _blocked_quality(code: str, *, observed_at: datetime = DEFAULT_CAPTURED_AT) -> QualityReport:
    missingness = {
        "MAPPING_CONFLICT": MissingnessValue.MAPPING_FAILED,
        "POST_CUTOFF": MissingnessValue.POST_CUTOFF,
        "RIGHTS_BLOCKED": MissingnessValue.RIGHTS_BLOCKED,
    }.get(code, MissingnessValue.UNKNOWN)
    issue = _quality_issue(
        severity="P1",
        code=code,
        subject_scope="GLOBAL_SYSTEM",
        message="source pair did not satisfy the governed ingestion contract",
        observed_at=observed_at,
        safe_details={"code": code},
        missingness=missingness,
    )
    return QualityReport(status="BLOCKED", warning_count=0, blocker_count=1, issues=(issue,))


def _quality_with_blocker(
    quality: QualityReport,
    code: str,
    *,
    observed_at: datetime,
) -> QualityReport:
    blocker = _blocked_quality(code, observed_at=observed_at)
    return QualityReport(
        status="BLOCKED",
        warning_count=quality.warning_count,
        blocker_count=blocker.blocker_count,
        issues=(*quality.issues, *blocker.issues),
    )


def _cross_validate(
    bootstrap: ParsedFplResource,
    fixtures: ParsedFplResource,
) -> None:
    if not isinstance(bootstrap.payload, BootstrapPayload) or not isinstance(
        fixtures.payload, FixturePayload
    ):
        raise IngestionError("INTERNAL_INVARIANT", "resource pair has invalid payload types")
    team_ids = {item.id for item in bootstrap.payload.teams}
    event_ids = {item.id for item in bootstrap.payload.events}
    for fixture in fixtures.payload.fixtures:
        if fixture.team_h not in team_ids or fixture.team_a not in team_ids:
            raise IngestionError("MAPPING_CONFLICT", "fixture references an unresolved team")
        if fixture.event is not None and fixture.event not in event_ids:
            raise IngestionError("MAPPING_CONFLICT", "fixture references an unresolved Gameweek")


def _relative_fixture_path(approved: ApprovedFixture) -> str:
    if not approved.relative_path.startswith("fixtures/"):
        raise IngestionError("FIXTURE_NOT_APPROVED", "fixture manifest path is invalid")
    return approved.relative_path


def _verified_fixture_storage(approved: ApprovedFixture, expected_body: bytes) -> str:
    relative_path = _relative_fixture_path(approved)
    try:
        resolved = approved.path.resolve(strict=True)
    except OSError:
        raise IngestionError(
            "FIXTURE_NOT_APPROVED", "durable fixture content is unavailable"
        ) from None
    digest = hashlib.sha256(expected_body).hexdigest()
    if (
        approved.path.is_symlink()
        or not resolved.is_file()
        or _read_bounded(resolved) != expected_body
        or approved.sha256 != digest
    ):
        raise IngestionError(
            "FIXTURE_NOT_APPROVED", "durable fixture read-back verification failed"
        )
    portable = relative_path.replace("\\", "/")
    return f"repository://{portable}#sha256={digest}"


def _pair_context(
    request: FplImportRequest,
    bootstrap: ApprovedFixture,
    fixtures: ApprovedFixture,
    profile: RightsProfile,
) -> tuple[str, dict[str, object]]:
    captured = require_utc(request.captured_at)
    cutoff = require_utc(request.information_cutoff)
    common: dict[str, object] = {
        "bootstrap_path": _relative_fixture_path(bootstrap),
        "captured_at": captured.isoformat().replace("+00:00", "Z"),
        "competition_key": request.competition_key,
        "fixtures_path": _relative_fixture_path(fixtures),
        "information_cutoff": cutoff.isoformat().replace("+00:00", "Z"),
        "profile_id": request.rights_profile_id,
        "profile_version": profile.profile_version,
        "retrieval_pair_id": str(uuid4()),
        "rights_config_sha256": rights_config_sha256(),
        "provider_config_sha256": provider_config_sha256(),
        "effective_config_sha256": effective_config_sha256(),
        "contract_version": CONTRACT_VERSION,
        "season_code": request.season_code,
    }
    pair_key = canonical_sha256(common)
    common["pair_key"] = pair_key
    return pair_key, common


def _right_blocked_result(
    profile: RightsProfile,
    decision: RightsDecision,
    *,
    operation: str,
    transport_call_count: int = 0,
    extra_effects: dict[str, object] | None = None,
    resources: tuple[ProviderResourceResult, ...] = (),
    observed_at: datetime = DEFAULT_CAPTURED_AT,
) -> FplOperationOutcome:
    return FplOperationOutcome(
        result=ProviderSnapshotResult(
            status="RIGHTS_BLOCKED",
            provider=profile.provider_key,
            resources=resources,
            rights=decision,
            quality=_blocked_quality("RIGHTS_BLOCKED", observed_at=observed_at),
            canonical_effects={
                "code_version": __version__,
                "contract_version": CONTRACT_VERSION,
                "error_code": "RIGHTS_BLOCKED",
                "next_action": "obtain an explicit approved capability before retrying",
                "operation": operation,
                "outcome": "RIGHTS_BLOCKED",
                "transport_call_count": transport_call_count,
                **(extra_effects or {}),
            },
            source_bundle=None,
        ),
        exit_code=4,
    )


class FplIngestionService:
    """Execute FPL-004 operations without hidden network or database resolution."""

    def __init__(
        self,
        *,
        repository_root: Path | None = None,
        transport_factory: Callable[[], Transport] = UrllibTransport,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.repository_root = (repository_root or Path.cwd()).resolve()
        self.transport_factory = transport_factory
        self.clock = clock

    def _operation_time(self, captured_at: datetime) -> datetime:
        captured = require_utc(captured_at)
        current = require_utc(self.clock())
        return max(captured, current)

    def validate(
        self,
        resource: FplResource,
        input_path: Path,
        *,
        contract_version: str = CONTRACT_VERSION,
    ) -> FplValidationResult:
        parsed = FplReferenceAdapter(contract_version=contract_version).validate(
            resource, _read_bounded(input_path)
        )
        quality = _drift_quality((parsed, parsed))
        if quality.warning_count:
            first = quality.issues[0]
            quality = QualityReport(
                status="PASS_WITH_WARNINGS",
                warning_count=1,
                blocker_count=0,
                issues=(first,),
            )
        return FplValidationResult(
            status="VALID_WITH_WARNINGS" if quality.warning_count else "VALID",
            provider="official_fpl_shape",
            resource=resource.value,
            contract_version=contract_version,
            payload_semantic_sha256=parsed.semantic_sha256,
            drift=parsed.drift,
            quality=quality,
            next_action="eligible for a separately rights-gated import",
        )

    def snapshot(
        self,
        *,
        resource: str,
        competition_key: str,
        season_code: str,
        rights_profile_id: str,
        database_url_ref: str | None = None,
    ) -> FplOperationOutcome:
        del competition_key, season_code
        _validate_database_reference(database_url_ref)
        profile = _profile(rights_profile_id)
        decision = decide_rights(
            profile,
            RightsCapability.AUTOMATED_ACCESS,
            checked_at=require_utc(self.clock()),
        )
        if decision.decision != "ALLOW":
            return _right_blocked_result(profile, decision, operation="snapshot")
        requested = (
            (FplResource.BOOTSTRAP, FplResource.FIXTURES)
            if resource == "all"
            else (FplResource(resource),)
        )
        adapter = FplReferenceAdapter(profile, self.transport_factory)
        for item in requested:
            adapter.fetch(item)
        raise IngestionError(
            "RIGHTS_BLOCKED",
            "live snapshot persistence is not approved for FPL-004",
        )

    def import_pair(self, request: FplImportRequest) -> FplOperationOutcome:
        _validate_database_reference(request.database_url_ref)
        profile = _profile(request.rights_profile_id)
        _validate_synthetic_context(request, profile)
        operation_at = self._operation_time(request.captured_at)
        manual = require_rights(
            profile,
            RightsCapability.MANUAL_IMPORT,
            checked_at=operation_at,
        )
        require_rights(
            profile,
            RightsCapability.TRANSIENT_PROCESSING,
            checked_at=operation_at,
        )
        if profile.rights_profile_id != "synthetic_test_v1":
            raw_decision = decide_rights(
                profile,
                RightsCapability.RAW_STORAGE,
                checked_at=operation_at,
            )
            bodies = _read_through_volatile_pair(request.bootstrap_path, request.fixtures_path)
            engine = _engine(request.database_url_ref)
            try:
                factory = session_factory(engine)
                pair_key, context = self._manual_pair_context(request, profile, bodies)
                manual_snapshots = self._create_manual_envelopes(
                    factory,
                    request,
                    profile,
                    context,
                    bodies,
                    manual,
                    raw_decision,
                    operation_at,
                )
                try:
                    parsed = (
                        parse_fpl_payload(FplResource.BOOTSTRAP, bodies[0]),
                        parse_fpl_payload(FplResource.FIXTURES, bodies[1]),
                    )
                    _cross_validate(*parsed)
                except IngestionError as exc:
                    self._quarantine(
                        factory,
                        operation_at,
                        manual_snapshots,
                        exc,
                        pair_key=pair_key,
                    )
                    return self._quarantined_result(
                        factory,
                        profile,
                        manual_snapshots,
                        exc,
                        raw_retention="RAW_DISCARDED",
                    )
                decision = decide_rights(
                    profile,
                    RightsCapability.DERIVED_STORAGE,
                    checked_at=operation_at,
                )
                self._finish_manual_validation_with_retry(
                    factory,
                    request,
                    manual_snapshots,
                    pair_key,
                    parsed,
                    decision,
                    operation_at,
                )
                resources = self._manual_resource_results(factory, manual_snapshots, parsed)
                return _right_blocked_result(
                    profile,
                    decision,
                    operation="import",
                    extra_effects={
                        "raw_retention": "RAW_DISCARDED",
                        "raw_storage_decision": raw_decision.decision,
                        "volatile_cleanup": "COMPLETED",
                    },
                    resources=resources,
                    observed_at=request.captured_at,
                )
            except IngestionError:
                raise
            except DatabaseError as exc:
                raise _database_error(exc) from None
            except SQLAlchemyError as exc:
                raise _database_error(exc) from None
            finally:
                engine.dispose()

        raw_decision = require_rights(
            profile,
            RightsCapability.RAW_STORAGE,
            checked_at=operation_at,
        )
        derived_decision = require_rights(
            profile,
            RightsCapability.DERIVED_STORAGE,
            checked_at=operation_at,
        )
        bootstrap_fixture = approve_synthetic_fixture(
            request.bootstrap_path, profile_id=profile.rights_profile_id
        )
        fixtures_fixture = approve_synthetic_fixture(
            request.fixtures_path, profile_id=profile.rights_profile_id
        )
        pair_key, context = _pair_context(request, bootstrap_fixture, fixtures_fixture, profile)
        bodies = (
            _read_bounded(bootstrap_fixture.path),
            _read_bounded(fixtures_fixture.path),
        )
        engine = _engine(request.database_url_ref)
        factory = session_factory(engine)
        snapshots: tuple[UUID, UUID] | None = None
        try:
            snapshots = self._create_envelopes(
                factory,
                request,
                profile,
                pair_key,
                context,
                bodies,
                (bootstrap_fixture, fixtures_fixture),
                raw_decision,
                derived_decision,
                manual,
                operation_at,
            )
            self._maybe_interrupt(request.halt_after_stage, "STORED", snapshots)
            return self._continue_pair(
                factory,
                request,
                profile,
                snapshots,
                pair_key=pair_key,
                bodies=bodies,
                operation_at=operation_at,
            )
        except IngestionInterrupted:
            raise
        except IngestionError as exc:
            if exc.retryable and snapshots is not None:
                with suppress(IngestionError, DatabaseError, SQLAlchemyError):
                    self._record_retryable_failure(factory, operation_at, snapshots, pair_key, exc)
            raise
        except DatabaseError as exc:
            error = _database_error(exc)
            if error.retryable and snapshots is not None:
                with suppress(IngestionError, DatabaseError, SQLAlchemyError):
                    self._record_retryable_failure(
                        factory, operation_at, snapshots, pair_key, error
                    )
            raise error from None
        except SQLAlchemyError as exc:
            error = _database_error(exc)
            if error.retryable and snapshots is not None:
                with suppress(IngestionError, DatabaseError, SQLAlchemyError):
                    self._record_retryable_failure(
                        factory, operation_at, snapshots, pair_key, error
                    )
            raise error from None
        finally:
            engine.dispose()

    def replay(self, request: FplReplayRequest) -> FplOperationOutcome:
        scenario_aliases = {
            "happy": "happy_path",
            "changed": "changed_snapshot",
            "drift": "unknown_additive",
            "invalid": "missing_required",
        }
        scenario = scenario_aliases.get(request.scenario, request.scenario)
        halt_after = request.halt_after_stage
        if scenario.startswith("resume-"):
            halt_after = scenario.removeprefix("resume-").replace("_", "-").upper()
            scenario = "happy_path"
        scenario_root = request.fixture_set / scenario
        captured = DEFAULT_CAPTURED_AT
        if scenario == "changed_snapshot":
            captured = datetime(2026, 8, 21, 17, 10, tzinfo=UTC)
        elif scenario == "post_cutoff":
            captured = datetime(2026, 8, 21, 17, 31, tzinfo=UTC)
        return self.import_pair(
            FplImportRequest(
                bootstrap_path=scenario_root / "bootstrap.json",
                fixtures_path=scenario_root / "fixtures.json",
                competition_key=request.competition_key,
                season_code=request.season_code,
                captured_at=captured,
                information_cutoff=require_utc(request.information_cutoff),
                rights_profile_id=request.rights_profile_id,
                database_url_ref=request.database_url_ref,
                halt_after_stage=halt_after,
            )
        )

    def resume(self, snapshot_id: UUID, *, database_url_ref: str) -> FplOperationOutcome:
        engine = _engine(database_url_ref)
        factory = session_factory(engine)
        snapshots: tuple[UUID, UUID] | None = None
        pair_key: str | None = None
        captured_at = DEFAULT_CAPTURED_AT
        operation_at = DEFAULT_CAPTURED_AT
        try:
            parsed: tuple[ParsedFplResource, ParsedFplResource] | None = None
            bodies: tuple[bytes, bytes] | None = None
            with factory.begin() as session:
                context = received_context(session, snapshot_id)
                raw_pair_key = context.get("pair_key")
                if not isinstance(raw_pair_key, str):
                    raise IngestionError(
                        "LIFECYCLE_INVARIANT", "snapshot pair context is unavailable"
                    )
                pair_key = raw_pair_key
                self._lock_pair(session, pair_key)
                rows = (
                    session.execute(
                        select(
                            source_snapshot.c.source_snapshot_id,
                            source_snapshot.c.resource,
                            source_snapshot.c.body_sha256,
                            source_snapshot.c.rights_profile_key,
                            source_snapshot.c.rights_profile_version,
                            source_snapshot.c.rights_profile_record_id,
                            source_snapshot.c.adapter_version,
                            source_snapshot.c.contract_version,
                        )
                        .join(
                            source_processing_event,
                            source_processing_event.c.source_snapshot_id
                            == source_snapshot.c.source_snapshot_id,
                        )
                        .where(
                            source_processing_event.c.stage == "RECEIVED",
                            source_processing_event.c.safe_details["pair_key"].as_string()
                            == pair_key,
                        )
                    )
                    .mappings()
                    .all()
                )
                by_resource = {str(row["resource"]): row for row in rows}
                if len(rows) != 2 or set(by_resource) != {"bootstrap", "fixtures"}:
                    raise IngestionError("LIFECYCLE_INVARIANT", "snapshot pair is incomplete")
                bootstrap_path = self._safe_resume_path(context.get("bootstrap_path"))
                fixtures_path = self._safe_resume_path(context.get("fixtures_path"))
                profile_id = context.get("profile_id")
                if not isinstance(profile_id, str):
                    raise IngestionError("LIFECYCLE_INVARIANT", "rights context is unavailable")
                profile = _profile(profile_id)
                captured_at = self._context_time(context, "captured_at")
                operation_at = self._operation_time(captured_at)
                if (
                    context.get("profile_version") != profile.profile_version
                    or context.get("rights_config_sha256") != rights_config_sha256()
                    or context.get("provider_config_sha256") != provider_config_sha256()
                    or context.get("effective_config_sha256") != effective_config_sha256()
                    or context.get("contract_version") != CONTRACT_VERSION
                ):
                    raise IngestionError(
                        "RIGHTS_BLOCKED", "resume rights authority differs from the envelope"
                    )
                pair_material = {
                    key: value
                    for key, value in context.items()
                    if key not in {"pair_key", "resource_role"}
                }
                if canonical_sha256(pair_material) != pair_key:
                    raise IngestionError(
                        "LIFECYCLE_INVARIANT", "snapshot pair context hash is invalid"
                    )
                profile_record_id = register_rights_profile(session, profile)
                require_rights(
                    profile,
                    RightsCapability.DERIVED_STORAGE,
                    checked_at=operation_at,
                )
                if any(
                    row["rights_profile_key"] != profile.rights_profile_id
                    or row["rights_profile_version"] != profile.profile_version
                    or row["rights_profile_record_id"] != profile_record_id
                    or row["adapter_version"] != CONTRACT_VERSION
                    or row["contract_version"] != CONTRACT_VERSION
                    for row in rows
                ):
                    raise IngestionError(
                        "RIGHTS_BLOCKED", "resume envelope authority could not be verified"
                    )
                snapshots = (
                    UUID(str(by_resource["bootstrap"]["source_snapshot_id"])),
                    UUID(str(by_resource["fixtures"]["source_snapshot_id"])),
                )
                states = self._pair_state(session, snapshots)
                if states[0] in {
                    "QUARANTINED",
                    "REJECTED",
                    "CANCELLED",
                    "FAILED_PERMANENT",
                }:
                    raise IngestionError(
                        "LIFECYCLE_INVARIANT", "terminal snapshots cannot be resumed"
                    )
                current_index = STAGE_INDEX.get(states[0], -1)
                if current_index >= STAGE_INDEX["PARSED"]:
                    parsed = self._load_parsed_artifacts(session, snapshots)
                else:
                    approved_bootstrap = approve_synthetic_fixture(
                        bootstrap_path, profile_id=profile_id
                    )
                    approved_fixtures = approve_synthetic_fixture(
                        fixtures_path, profile_id=profile_id
                    )
                    bodies = (
                        _read_bounded(approved_bootstrap.path),
                        _read_bounded(approved_fixtures.path),
                    )
                    for resource, body in zip(("bootstrap", "fixtures"), bodies, strict=True):
                        if hashlib.sha256(body).hexdigest() != by_resource[resource]["body_sha256"]:
                            raise IngestionError("LIFECYCLE_INVARIANT", "resume input hash changed")
                request = FplImportRequest(
                    bootstrap_path=bootstrap_path,
                    fixtures_path=fixtures_path,
                    competition_key=self._context_string(context, "competition_key"),
                    season_code=self._context_string(context, "season_code"),
                    captured_at=captured_at,
                    information_cutoff=self._context_time(context, "information_cutoff"),
                    rights_profile_id=profile_id,
                    database_url_ref=database_url_ref,
                )
                captured_at = request.captured_at
            return self._continue_pair(
                factory,
                request,
                profile,
                snapshots,
                pair_key=pair_key,
                bodies=bodies,
                parsed=parsed,
                operation_at=operation_at,
            )
        except IngestionError as exc:
            if exc.retryable and snapshots is not None and pair_key is not None:
                with suppress(IngestionError, DatabaseError, SQLAlchemyError):
                    self._record_retryable_failure(factory, operation_at, snapshots, pair_key, exc)
            raise
        except DatabaseError as exc:
            error = _database_error(exc)
            if error.retryable and snapshots is not None and pair_key is not None:
                with suppress(IngestionError, DatabaseError, SQLAlchemyError):
                    self._record_retryable_failure(
                        factory, operation_at, snapshots, pair_key, error
                    )
            raise error from None
        except SQLAlchemyError as exc:
            error = _database_error(exc)
            if error.retryable and snapshots is not None and pair_key is not None:
                with suppress(IngestionError, DatabaseError, SQLAlchemyError):
                    self._record_retryable_failure(
                        factory, operation_at, snapshots, pair_key, error
                    )
            raise error from None
        finally:
            engine.dispose()

    def show_bundle(self, bundle_id: UUID, *, database_url_ref: str) -> SourceBundleSummary:
        engine = _engine(database_url_ref)
        try:
            factory = session_factory(engine)
            with factory() as session:
                row = session.execute(
                    select(source_snapshot.c.source_snapshot_id).limit(1)
                ).scalar_one_or_none()
                if row is None:
                    raise IngestionError("NO_USABLE_BUNDLE", "source bundle was not found")
                persistence = FplPersistence(
                    session,
                    captured_at=DEFAULT_CAPTURED_AT,
                    competition_key="SYNTHETIC_PL",
                    season_code="2026/27",
                    bootstrap_snapshot_id=UUID(str(row)),
                    fixtures_snapshot_id=UUID(str(row)),
                )
                return persistence.bundle_summary(bundle_id)
        except IngestionError:
            raise
        except DatabaseError as exc:
            raise _database_error(exc) from None
        except SQLAlchemyError as exc:
            raise _database_error(exc) from None
        finally:
            engine.dispose()

    @staticmethod
    def _manual_pair_context(
        request: FplImportRequest,
        profile: RightsProfile,
        bodies: tuple[bytes, bytes],
    ) -> tuple[str, dict[str, object]]:
        context: dict[str, object] = {
            "bootstrap_body_sha256": hashlib.sha256(bodies[0]).hexdigest(),
            "captured_at": require_utc(request.captured_at).isoformat().replace("+00:00", "Z"),
            "competition_key": request.competition_key,
            "contract_version": CONTRACT_VERSION,
            "fixtures_body_sha256": hashlib.sha256(bodies[1]).hexdigest(),
            "information_cutoff": require_utc(request.information_cutoff)
            .isoformat()
            .replace("+00:00", "Z"),
            "profile_id": profile.rights_profile_id,
            "profile_version": profile.profile_version,
            "retrieval_pair_id": str(uuid4()),
            "rights_config_sha256": rights_config_sha256(),
            "provider_config_sha256": provider_config_sha256(),
            "effective_config_sha256": effective_config_sha256(),
            "season_code": request.season_code,
        }
        pair_key = canonical_sha256(context)
        context["pair_key"] = pair_key
        return pair_key, context

    def _create_manual_envelopes(
        self,
        factory: sessionmaker[Session],
        request: FplImportRequest,
        profile: RightsProfile,
        common_context: dict[str, object],
        bodies: tuple[bytes, bytes],
        manual_decision: RightsDecision,
        raw_decision: RightsDecision,
        operation_at: datetime,
    ) -> tuple[UUID, UUID]:
        snapshot_ids: list[UUID] = []
        operation_id = uuid4()
        transient_decision = decide_rights(
            profile,
            RightsCapability.TRANSIENT_PROCESSING,
            checked_at=operation_at,
        )
        with factory.begin() as session:
            provider_id, _created = ensure_official_provider(session)
            profile_record_id = register_rights_profile(session, profile)
            run_id = record_ingestion_run(
                session,
                provider_id=provider_id,
                pair_key=str(common_context["pair_key"]),
                started_at=operation_at,
            )
            for index, (resource, body) in enumerate(
                zip(("bootstrap", "fixtures"), bodies, strict=True)
            ):
                context = {**common_context, "resource_role": resource.upper()}
                snapshot_id = record_received_snapshot(
                    session,
                    provider_id=provider_id,
                    ingestion_run_id=run_id,
                    attempt_number=1,
                    resource=resource,
                    captured_at=request.captured_at,
                    body=body,
                    raw_blob_id=None,
                    raw_storage_object_id=None,
                    rights_profile_record_id=profile_record_id,
                    profile=profile,
                    sanitized_target=f"manual:{resource}",
                    context=context,
                    raw_storage_policy="FORBIDDEN",
                )
                snapshot_ids.append(snapshot_id)
                for decision in (manual_decision, transient_decision, raw_decision):
                    record_rights_decision(
                        session,
                        rights_profile_record_id=profile_record_id,
                        source_snapshot_id=snapshot_id,
                        decision=decision,
                        context={"operation": "transient_manual_import", "resource": resource},
                    )
                append_processing_event_idempotent(
                    session,
                    snapshot_id=snapshot_id,
                    stage="RAW_DISCARDED",
                    event_at=_stage_time(operation_at, 1 + index),
                    input_sha256=hashlib.sha256(body).hexdigest(),
                    output_sha256=hashlib.sha256(body).hexdigest(),
                    safe_details={"deletion": "VERIFIED", "raw_retention": "ZERO"},
                    operation_id=operation_id,
                )
        return snapshot_ids[0], snapshot_ids[1]

    def _finish_manual_validation(
        self,
        factory: sessionmaker[Session],
        request: FplImportRequest,
        snapshots: tuple[UUID, UUID],
        pair_key: str,
        parsed: tuple[ParsedFplResource, ParsedFplResource],
        derived_decision: RightsDecision,
        operation_at: datetime,
    ) -> None:
        operation_id = uuid4()
        with factory.begin() as session:
            self._lock_pair(session, pair_key)
            states = tuple(
                str(lifecycle_state(session, snapshot_id)["current_state"])
                for snapshot_id in snapshots
            )
            if states == ("REJECTED", "REJECTED"):
                return
            if states[0] != states[1]:
                raise IngestionError(
                    "LIFECYCLE_INVARIANT", "manual source pair lifecycle state diverged"
                )
            self._append_pair_stage_in_session(
                session,
                snapshots,
                "PARSED",
                _stage_time(operation_at, 4),
                (parsed[0].payload_sha256, parsed[1].payload_sha256),
                (parsed[0].semantic_sha256, parsed[1].semantic_sha256),
                (
                    {"classification": parsed[0].drift.classification.value},
                    {"classification": parsed[1].drift.classification.value},
                ),
                operation_id=operation_id,
            )
            self._append_pair_stage_in_session(
                session,
                snapshots,
                "VALIDATED",
                _stage_time(operation_at, 5),
                (parsed[0].semantic_sha256, parsed[1].semantic_sha256),
                (parsed[0].drift.schema_fingerprint, parsed[1].drift.schema_fingerprint),
                ({"contract": CONTRACT_VERSION}, {"contract": CONTRACT_VERSION}),
                operation_id=operation_id,
            )
            profile_record_id = session.scalar(
                select(source_snapshot.c.rights_profile_record_id).where(
                    source_snapshot.c.source_snapshot_id == snapshots[0]
                )
            )
            if not isinstance(profile_record_id, UUID):
                raise IngestionError("LIFECYCLE_INVARIANT", "rights record is unavailable")
            for index, snapshot_id in enumerate(snapshots):
                record_rights_decision(
                    session,
                    rights_profile_record_id=profile_record_id,
                    source_snapshot_id=snapshot_id,
                    decision=derived_decision,
                    context={"operation": "promotion_gate", "resource_index": index},
                )
                append_processing_event_idempotent(
                    session,
                    snapshot_id=snapshot_id,
                    stage="REJECTED",
                    event_at=self._next_event_time(
                        session, snapshot_id, _stage_time(operation_at, 6 + index)
                    ),
                    safe_details={
                        "derived_storage": derived_decision.decision,
                        "raw_retention": "RAW_DISCARDED",
                    },
                    error_code="RIGHTS_BLOCKED",
                    operation_id=operation_id,
                )

    def _finish_manual_validation_with_retry(
        self,
        factory: sessionmaker[Session],
        request: FplImportRequest,
        snapshots: tuple[UUID, UUID],
        pair_key: str,
        parsed: tuple[ParsedFplResource, ParsedFplResource],
        derived_decision: RightsDecision,
        operation_at: datetime,
    ) -> None:
        last_error: IngestionError | None = None
        for _attempt in range(3):
            try:
                self._finish_manual_validation(
                    factory,
                    request,
                    snapshots,
                    pair_key,
                    parsed,
                    derived_decision,
                    operation_at,
                )
                return
            except IngestionError as exc:
                if not exc.retryable:
                    raise
                last_error = exc
            except (DatabaseError, SQLAlchemyError) as exc:
                last_error = _database_error(exc)
                if not last_error.retryable:
                    raise last_error from None
        if last_error is None:
            raise IngestionError("DATABASE_RETRYABLE", "manual validation retry failed")
        self._record_manual_permanent_failure(
            factory,
            operation_at,
            snapshots,
            pair_key,
            last_error,
        )
        raise last_error

    def _record_manual_permanent_failure(
        self,
        factory: sessionmaker[Session],
        captured_at: datetime,
        snapshots: tuple[UUID, UUID],
        pair_key: str,
        error: IngestionError,
    ) -> None:
        operation_id = uuid4()
        with factory.begin() as session:
            self._lock_pair(session, pair_key)
            for index, snapshot_id in enumerate(snapshots):
                state = str(lifecycle_state(session, snapshot_id)["current_state"])
                if state in {"REJECTED", "FAILED_PERMANENT"}:
                    continue
                append_processing_event_idempotent(
                    session,
                    snapshot_id=snapshot_id,
                    stage="FAILED_PERMANENT",
                    event_at=self._next_event_time(
                        session,
                        snapshot_id,
                        _stage_time(captured_at, 20 + index),
                    ),
                    safe_details={
                        "error_code": error.code,
                        "raw_retention": "RAW_DISCARDED",
                        "retry_exhausted": True,
                    },
                    error_code=error.code,
                    operation_id=operation_id,
                )

    @staticmethod
    def _manual_resource_results(
        factory: sessionmaker[Session],
        snapshots: tuple[UUID, UUID],
        parsed: tuple[ParsedFplResource, ParsedFplResource],
    ) -> tuple[ProviderResourceResult, ProviderResourceResult]:
        with factory() as session:
            values = tuple(
                ProviderResourceResult(
                    resource="bootstrap" if index == 0 else "fixtures",
                    source_snapshot_id=snapshot_id,
                    lifecycle_state=str(lifecycle_state(session, snapshot_id)["current_state"]),
                    drift=parsed[index].drift.classification.value,
                    raw_retention="RAW_DISCARDED",
                )
                for index, snapshot_id in enumerate(snapshots)
            )
        return values[0], values[1]

    def _create_envelopes(
        self,
        factory: sessionmaker[Session],
        request: FplImportRequest,
        profile: RightsProfile,
        pair_key: str,
        common_context: dict[str, object],
        bodies: tuple[bytes, bytes],
        approved_fixtures: tuple[ApprovedFixture, ApprovedFixture],
        raw_decision: RightsDecision,
        derived_decision: RightsDecision,
        manual_decision: RightsDecision,
        operation_at: datetime,
    ) -> tuple[UUID, UUID]:
        del pair_key
        captured = require_utc(request.captured_at)
        snapshot_ids: list[UUID] = []
        with factory.begin() as session:
            provider_id, _ = ensure_synthetic_provider(session)
            profile_record_id = register_rights_profile(session, profile)
            run_id = record_ingestion_run(
                session,
                provider_id=provider_id,
                pair_key=str(common_context["pair_key"]),
                started_at=operation_at,
            )
            for index, (resource, body, approved_fixture) in enumerate(
                zip(("bootstrap", "fixtures"), bodies, approved_fixtures, strict=True)
            ):
                storage_uri = _verified_fixture_storage(approved_fixture, body)
                raw_blob_id, body_sha256 = get_or_create_raw_content(session, body)
                storage_id = get_or_create_raw_storage_object(
                    session,
                    raw_blob_id=raw_blob_id,
                    rights_profile_record_id=profile_record_id,
                    body_sha256=body_sha256,
                    storage_uri=storage_uri,
                    content_type="application/json",
                    retention_seconds=profile.retention_seconds,
                    access_allowed=True,
                    export_allowed=True,
                    backup_allowed=True,
                )
                context = {**common_context, "resource_role": resource.upper()}
                snapshot_id = record_received_snapshot(
                    session,
                    provider_id=provider_id,
                    ingestion_run_id=run_id,
                    attempt_number=1,
                    resource=resource,
                    captured_at=captured,
                    body=body,
                    raw_blob_id=raw_blob_id,
                    raw_storage_object_id=storage_id,
                    rights_profile_record_id=profile_record_id,
                    profile=profile,
                    sanitized_target=f"fixture:{resource}",
                    context=context,
                )
                snapshot_ids.append(snapshot_id)
                for decision in (manual_decision, raw_decision, derived_decision):
                    record_rights_decision(
                        session,
                        rights_profile_record_id=profile_record_id,
                        source_snapshot_id=snapshot_id,
                        decision=decision,
                        context={"resource": resource, "operation": "synthetic_import"},
                    )
                append_processing_event_idempotent(
                    session,
                    snapshot_id=snapshot_id,
                    stage="STORED",
                    event_at=_stage_time(operation_at, 1 + index),
                    input_sha256=body_sha256,
                    output_sha256=body_sha256,
                    safe_details={"retention": "ALLOWED"},
                )
        return snapshot_ids[0], snapshot_ids[1]

    def _continue_pair(
        self,
        factory: sessionmaker[Session],
        request: FplImportRequest,
        profile: RightsProfile,
        snapshots: tuple[UUID, UUID],
        *,
        pair_key: str,
        bodies: tuple[bytes, bytes] | None = None,
        parsed: tuple[ParsedFplResource, ParsedFplResource] | None = None,
        operation_at: datetime,
    ) -> FplOperationOutcome:
        current = "STORED"
        operation_id = uuid4()
        try:
            with factory.begin() as session:
                self._lock_pair(session, pair_key)
                current = self._pair_state(session, snapshots)[0]
                if STAGE_INDEX.get(current, -1) < STAGE_INDEX["PARSED"]:
                    if bodies is None:
                        raise IngestionError(
                            "LIFECYCLE_INVARIANT", "stored payload artifacts are unavailable"
                        )
                    try:
                        parsed = (
                            parse_fpl_payload(FplResource.BOOTSTRAP, bodies[0]),
                            parse_fpl_payload(FplResource.FIXTURES, bodies[1]),
                        )
                    except IngestionError:
                        raise
                    artifacts = (parsed_artifact(parsed[0]), parsed_artifact(parsed[1]))
                    self._append_pair_stage_in_session(
                        session,
                        snapshots,
                        "PARSED",
                        _stage_time(operation_at, 4),
                        (parsed[0].payload_sha256, parsed[1].payload_sha256),
                        (parsed[0].semantic_sha256, parsed[1].semantic_sha256),
                        (
                            {
                                "artifact": artifacts[0],
                                "artifact_sha256": canonical_sha256(artifacts[0]),
                                "classification": parsed[0].drift.classification.value,
                            },
                            {
                                "artifact": artifacts[1],
                                "artifact_sha256": canonical_sha256(artifacts[1]),
                                "classification": parsed[1].drift.classification.value,
                            },
                        ),
                        operation_id=operation_id,
                    )
                    current = "PARSED"
                elif parsed is None:
                    parsed = self._load_parsed_artifacts(session, snapshots)
            self._maybe_interrupt(request.halt_after_stage, "PARSED", snapshots)

            if parsed is None:
                raise IngestionError("LIFECYCLE_INVARIANT", "parsed artifacts are unavailable")
            with factory.begin() as session:
                self._lock_pair(session, pair_key)
                current = self._pair_state(session, snapshots)[0]
                if STAGE_INDEX.get(current, -1) < STAGE_INDEX["VALIDATED"]:
                    _cross_validate(*parsed)
                    self._append_pair_stage_in_session(
                        session,
                        snapshots,
                        "VALIDATED",
                        _stage_time(operation_at, 5),
                        (parsed[0].semantic_sha256, parsed[1].semantic_sha256),
                        (parsed[0].drift.schema_fingerprint, parsed[1].drift.schema_fingerprint),
                        ({"contract": CONTRACT_VERSION}, {"contract": CONTRACT_VERSION}),
                        operation_id=operation_id,
                    )
                    current = "VALIDATED"
                else:
                    self._verify_validated_artifacts(session, snapshots, parsed)
            self._maybe_interrupt(request.halt_after_stage, "VALIDATED", snapshots)

            mapping_input_sha256 = canonical_sha256(
                {
                    "competition_key": request.competition_key,
                    "resources": [item.semantic_sha256 for item in parsed],
                    "season_code": request.season_code,
                }
            )
            with factory.begin() as session:
                self._lock_pair(session, pair_key)
                current = self._pair_state(session, snapshots)[0]
                mapping_persistence = FplPersistence(
                    session,
                    captured_at=request.captured_at,
                    system_at=operation_at,
                    competition_key=request.competition_key,
                    season_code=request.season_code,
                    bootstrap_snapshot_id=snapshots[0],
                    fixtures_snapshot_id=snapshots[1],
                )
                if STAGE_INDEX.get(current, -1) < STAGE_INDEX["MAPPED"]:
                    mapping_plan = mapping_persistence.stage_mapping(*parsed)
                    mapping_artifact = mapping_plan.model_dump(mode="json")
                    mapping_hash = canonical_sha256(mapping_artifact)
                    mapping_details: dict[str, object] = {
                        "mapping_input_sha256": mapping_input_sha256,
                        "mapping_plan": mapping_artifact,
                        "mapping_plan_sha256": mapping_hash,
                    }
                    self._append_pair_stage_in_session(
                        session,
                        snapshots,
                        "MAPPED",
                        _stage_time(operation_at, 6),
                        (mapping_input_sha256, mapping_input_sha256),
                        (mapping_hash, mapping_hash),
                        (mapping_details, mapping_details),
                        operation_id=operation_id,
                    )
                else:
                    mapping_plan, mapping_hash = self._mapping_plan(
                        session,
                        snapshots,
                        expected_input_sha256=mapping_input_sha256,
                    )
                    mapping_persistence.verify_mapping_plan(mapping_plan)
            self._maybe_interrupt(request.halt_after_stage, "MAPPED", snapshots)

            with factory.begin() as session:
                self._lock_pair(session, pair_key)
                current = self._pair_state(session, snapshots)[0]
                promoted_persistence = FplPersistence(
                    session,
                    captured_at=request.captured_at,
                    system_at=operation_at,
                    competition_key=request.competition_key,
                    season_code=request.season_code,
                    bootstrap_snapshot_id=snapshots[0],
                    fixtures_snapshot_id=snapshots[1],
                )
                promoted_persistence.verify_mapping_plan(mapping_plan)
                if STAGE_INDEX.get(current, -1) < STAGE_INDEX["PROMOTED"]:
                    if current != "MAPPED":
                        raise IngestionError(
                            "LIFECYCLE_INVARIANT", "source pair is not ready for promotion"
                        )
                    competition_id, season_id = promoted_persistence.promote(*parsed, mapping_plan)
                    preflight_persistence = FplPersistence(
                        session,
                        captured_at=request.captured_at,
                        system_at=operation_at,
                        competition_key=request.competition_key,
                        season_code=request.season_code,
                        bootstrap_snapshot_id=snapshots[0],
                        fixtures_snapshot_id=snapshots[1],
                    )
                    preflight_persistence.preflight_observation_conflicts(
                        parsed[0], parsed[1], mapping_plan
                    )
                    promotion_details: dict[str, object] = {
                        "competition_id": str(competition_id),
                        "effect_counts": promoted_persistence.counts.as_dict(),
                        "mapping_plan_sha256": mapping_hash,
                        "promotion": "CANONICAL_COMMITTED",
                        "season_id": str(season_id),
                    }
                    promotion_sha256 = canonical_sha256(promotion_details)
                    self._append_pair_stage_in_session(
                        session,
                        snapshots,
                        "PROMOTED",
                        _stage_time(operation_at, 7),
                        (mapping_hash, mapping_hash),
                        (promotion_sha256, promotion_sha256),
                        (promotion_details, promotion_details),
                        operation_id=operation_id,
                    )
                else:
                    competition_id, season_id, _ = self._verify_promoted_artifacts(
                        session, snapshots, mapping_hash
                    )
                _, _, promotion_counts = self._verify_promoted_artifacts(
                    session, snapshots, mapping_hash
                )
            self._maybe_interrupt(request.halt_after_stage, "PROMOTED", snapshots)

            persistence = FplPersistence(
                self._new_session(factory),
                captured_at=request.captured_at,
                system_at=operation_at,
                competition_key=request.competition_key,
                season_code=request.season_code,
                bootstrap_snapshot_id=snapshots[0],
                fixtures_snapshot_id=snapshots[1],
            )
            unit_of_work = persistence.session
            try:
                quality = _drift_quality(parsed, observed_at=request.captured_at)
                result_quality = quality
                bundle: SourceBundleSummary | None
                outcome = "BUNDLE_CREATED"
                exit_code = 0
                with unit_of_work.begin():
                    self._lock_pair(unit_of_work, pair_key)
                    current = self._pair_state(unit_of_work, snapshots)[0]
                    if STAGE_INDEX.get(current, -1) < STAGE_INDEX["PROMOTED"]:
                        raise IngestionError(
                            "LIFECYCLE_INVARIANT", "source pair lacks canonical promotion"
                        )
                    verified_competition_id, verified_season_id, verified_counts = (
                        self._verify_promoted_artifacts(unit_of_work, snapshots, mapping_hash)
                    )
                    if (
                        verified_competition_id != competition_id
                        or verified_season_id != season_id
                        or verified_counts != promotion_counts
                    ):
                        raise IngestionError(
                            "LIFECYCLE_INVARIANT", "promotion artifact identity changed"
                        )
                    persistence.verify_mapping_plan(mapping_plan)
                    resolved_mapping_sha256 = persistence.mapping_identity_sha256(
                        season_id, parsed[0], parsed[1]
                    )
                    usable_at = self._finish_quality(
                        unit_of_work,
                        operation_at,
                        snapshots,
                        quality,
                        mapping_identity_sha256=resolved_mapping_sha256,
                        mapping_plan_sha256=mapping_hash,
                        operation_id=operation_id,
                    )
                    persistence.record_observations(
                        parsed[0],
                        parsed[1],
                        mapping_plan,
                        bootstrap_usable_at=usable_at[0],
                        fixtures_usable_at=usable_at[1],
                    )
                    try:
                        bundle = persistence.freeze_bundle(
                            competition_id=competition_id,
                            season_id=season_id,
                            information_cutoff=request.information_cutoff,
                            bootstrap=parsed[0],
                            fixtures=parsed[1],
                            profile_id=profile.rights_profile_id,
                            profile_version=profile.profile_version,
                            config_sha256=effective_config_sha256(),
                            mapping_plan_sha256=mapping_hash,
                            quality_status=quality.status,
                        )
                    except IngestionError as exc:
                        if exc.code != "POST_CUTOFF":
                            raise
                        bundle = None
                        outcome = "OBSERVED_NOT_BUNDLE_ELIGIBLE"
                        exit_code = 2
                        result_quality = _quality_with_blocker(
                            quality, "POST_CUTOFF", observed_at=request.captured_at
                        )
                        self._record_bundle_eligibility_issues(
                            unit_of_work,
                            snapshots,
                            result_quality,
                        )
                resources = self._resource_results(factory, snapshots, parsed)
                effect_counts = _merge_effect_counts(
                    promotion_counts,
                    persistence.counts.as_dict(),
                )
                surfaced_warnings = any(
                    issue.code in {"ADDITIVE_UNKNOWN", "NONCRITICAL_DUPLICATED_ALIAS"}
                    for issue in result_quality.issues
                )
                result = ProviderSnapshotResult(
                    status="USABLE_WITH_WARNINGS" if surfaced_warnings else "USABLE",
                    provider=profile.provider_key,
                    resources=resources,
                    rights=decide_rights(
                        profile,
                        RightsCapability.DERIVED_STORAGE,
                        checked_at=operation_at,
                    ),
                    quality=result_quality,
                    canonical_effects={
                        "changed": effect_counts["changed"],
                        "code_version": __version__,
                        "config_sha256": effective_config_sha256(),
                        "contract_version": CONTRACT_VERSION,
                        "created": effect_counts["created"],
                        "information_cutoff": require_utc(request.information_cutoff)
                        .isoformat()
                        .replace("+00:00", "Z"),
                        "next_action": (
                            "consume the immutable source bundle"
                            if bundle is not None
                            else "select an information cutoff after the usable timestamps"
                        ),
                        "outcome": outcome,
                        "reused": effect_counts["reused"],
                    },
                    source_bundle=bundle,
                )
                return FplOperationOutcome(result=result, exit_code=exit_code)
            finally:
                persistence.session.close()
        except IngestionError as exc:
            if exc.code in {
                "VALIDATION_FAILED",
                "MALFORMED_JSON",
                "PAYLOAD_TOO_LARGE",
                "PAYLOAD_TOO_DEEP",
                "DUPLICATE_JSON_KEY",
                "MAPPING_CONFLICT",
                "SEMANTIC_CONTRADICTION",
            }:
                self._quarantine(factory, operation_at, snapshots, exc, pair_key=pair_key)
                return self._quarantined_result(factory, profile, snapshots, exc)
            raise

    @staticmethod
    def _new_session(factory: sessionmaker[Session]) -> Session:
        return factory()

    @staticmethod
    def _lock_pair(session: Session, pair_key: str) -> None:
        session.execute(text("SET LOCAL lock_timeout = '5s'"))
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": f"fpl-pair:{pair_key}"},
        )

    @staticmethod
    def _pair_state(session: Session, snapshots: tuple[UUID, UUID]) -> tuple[str, str]:
        effective: list[str] = []
        for snapshot_id in snapshots:
            state = str(lifecycle_state(session, snapshot_id)["current_state"])
            if state == "FAILED_RETRYABLE":
                prior = session.scalar(
                    select(source_processing_event.c.stage)
                    .where(
                        source_processing_event.c.source_snapshot_id == snapshot_id,
                        source_processing_event.c.stage != "FAILED_RETRYABLE",
                    )
                    .order_by(source_processing_event.c.sequence_number.desc())
                    .limit(1)
                )
                if not isinstance(prior, str):
                    raise IngestionError(
                        "LIFECYCLE_INVARIANT", "retryable lifecycle has no successful prefix"
                    )
                state = prior
            effective.append(state)
        states = (effective[0], effective[1])
        if states[0] != states[1]:
            raise IngestionError("LIFECYCLE_INVARIANT", "source pair lifecycle state diverged")
        return states[0], states[1]

    @staticmethod
    def _next_event_time(session: Session, snapshot_id: UUID, planned: datetime) -> datetime:
        candidate = require_utc(planned)
        previous = session.scalar(
            select(func.max(source_processing_event.c.event_at)).where(
                source_processing_event.c.source_snapshot_id == snapshot_id
            )
        )
        if isinstance(previous, datetime) and candidate <= require_utc(previous):
            return require_utc(previous) + timedelta(microseconds=1)
        return candidate

    def _record_retryable_failure(
        self,
        factory: sessionmaker[Session],
        captured_at: datetime,
        snapshots: tuple[UUID, UUID],
        pair_key: str,
        error: IngestionError,
    ) -> None:
        operation_id = uuid4()
        with factory.begin() as session:
            self._lock_pair(session, pair_key)
            self._pair_state(session, snapshots)
            for index, snapshot_id in enumerate(snapshots):
                append_processing_event_idempotent(
                    session,
                    snapshot_id=snapshot_id,
                    stage="FAILED_RETRYABLE",
                    event_at=self._next_event_time(
                        session, snapshot_id, _stage_time(captured_at, 20 + index)
                    ),
                    safe_details={"error_code": error.code, "retryable": True},
                    error_code=error.code,
                    operation_id=operation_id,
                )

    @staticmethod
    def _load_parsed_artifacts(
        session: Session,
        snapshots: tuple[UUID, UUID],
    ) -> tuple[ParsedFplResource, ParsedFplResource]:
        rows = (
            session.execute(
                select(
                    source_processing_event.c.source_snapshot_id,
                    source_processing_event.c.input_sha256,
                    source_processing_event.c.output_sha256,
                    source_processing_event.c.safe_details,
                    source_snapshot.c.body_sha256,
                )
                .join(
                    source_snapshot,
                    source_snapshot.c.source_snapshot_id
                    == source_processing_event.c.source_snapshot_id,
                )
                .where(
                    source_processing_event.c.source_snapshot_id.in_(snapshots),
                    source_processing_event.c.stage == "PARSED",
                )
            )
            .mappings()
            .all()
        )
        artifacts = {UUID(str(row["source_snapshot_id"])): row for row in rows}
        if set(artifacts) != set(snapshots):
            raise IngestionError("LIFECYCLE_INVARIANT", "parsed stage artifacts are incomplete")
        parsed: list[ParsedFplResource] = []
        for index, snapshot_id in enumerate(snapshots):
            row = artifacts[snapshot_id]
            details = row["safe_details"]
            artifact = details.get("artifact") if isinstance(details, dict) else None
            artifact_sha256 = details.get("artifact_sha256") if isinstance(details, dict) else None
            if not isinstance(artifact, dict) or artifact_sha256 != canonical_sha256(artifact):
                raise IngestionError("LIFECYCLE_INVARIANT", "parsed stage artifact is unavailable")
            try:
                value = ParsedFplResource.model_validate_json(
                    json.dumps(artifact, sort_keys=True, separators=(",", ":"))
                )
            except (TypeError, ValueError):
                raise IngestionError(
                    "LIFECYCLE_INVARIANT", "parsed stage artifact is invalid"
                ) from None
            expected_resource = FplResource.BOOTSTRAP if index == 0 else FplResource.FIXTURES
            if (
                value.resource is not expected_resource
                or value.payload_sha256 != row["body_sha256"]
                or value.payload_sha256 != row["input_sha256"]
                or value.semantic_sha256 != row["output_sha256"]
            ):
                raise IngestionError("LIFECYCLE_INVARIANT", "parsed stage artifact hash is invalid")
            parsed.append(value)
        return parsed[0], parsed[1]

    @staticmethod
    def _mapping_plan(
        session: Session,
        snapshots: tuple[UUID, UUID],
        *,
        expected_input_sha256: str,
    ) -> tuple[FplMappingPlan, str]:
        rows = (
            session.execute(
                select(
                    source_processing_event.c.source_snapshot_id,
                    source_processing_event.c.input_sha256,
                    source_processing_event.c.output_sha256,
                    source_processing_event.c.safe_details,
                ).where(
                    source_processing_event.c.source_snapshot_id.in_(snapshots),
                    source_processing_event.c.stage == "MAPPED",
                )
            )
            .mappings()
            .all()
        )
        if len(rows) != 2:
            raise IngestionError("LIFECYCLE_INVARIANT", "mapping artifacts are incomplete")
        plans: list[FplMappingPlan] = []
        hashes: set[str] = set()
        for row in rows:
            details = row["safe_details"]
            artifact = details.get("mapping_plan") if isinstance(details, dict) else None
            try:
                plan = FplMappingPlan.model_validate(artifact)
            except (TypeError, ValueError):
                raise IngestionError(
                    "LIFECYCLE_INVARIANT", "mapping plan artifact is invalid"
                ) from None
            value = canonical_sha256(plan.model_dump(mode="json"))
            if (
                row["input_sha256"] != expected_input_sha256
                or row["output_sha256"] != value
                or details.get("mapping_input_sha256") != expected_input_sha256
                or details.get("mapping_plan_sha256") != value
            ):
                raise IngestionError("LIFECYCLE_INVARIANT", "mapping artifact hash is invalid")
            plans.append(plan)
            hashes.add(value)
        if len(hashes) != 1 or plans[0] != plans[1]:
            raise IngestionError("LIFECYCLE_INVARIANT", "mapping artifacts conflict")
        return plans[0], hashes.pop()

    @staticmethod
    def _verify_validated_artifacts(
        session: Session,
        snapshots: tuple[UUID, UUID],
        parsed: tuple[ParsedFplResource, ParsedFplResource],
    ) -> None:
        rows = (
            session.execute(
                select(
                    source_processing_event.c.source_snapshot_id,
                    source_processing_event.c.input_sha256,
                    source_processing_event.c.output_sha256,
                    source_processing_event.c.safe_details,
                ).where(
                    source_processing_event.c.source_snapshot_id.in_(snapshots),
                    source_processing_event.c.stage == "VALIDATED",
                )
            )
            .mappings()
            .all()
        )
        by_snapshot = {UUID(str(row["source_snapshot_id"])): row for row in rows}
        if len(by_snapshot) != 2 or any(
            by_snapshot[snapshot_id]["input_sha256"] != parsed[index].semantic_sha256
            or by_snapshot[snapshot_id]["output_sha256"] != parsed[index].drift.schema_fingerprint
            for index, snapshot_id in enumerate(snapshots)
        ):
            raise IngestionError("LIFECYCLE_INVARIANT", "validated stage artifact hash is invalid")

    @staticmethod
    def _verify_promoted_artifacts(
        session: Session,
        snapshots: tuple[UUID, UUID],
        mapping_hash: str,
    ) -> tuple[UUID, UUID, dict[str, dict[str, int]]]:
        rows = (
            session.execute(
                select(
                    source_processing_event.c.source_snapshot_id,
                    source_processing_event.c.input_sha256,
                    source_processing_event.c.output_sha256,
                    source_processing_event.c.safe_details,
                ).where(
                    source_processing_event.c.source_snapshot_id.in_(snapshots),
                    source_processing_event.c.stage == "PROMOTED",
                )
            )
            .mappings()
            .all()
        )
        if len(rows) != 2 or not all(isinstance(row["safe_details"], dict) for row in rows):
            raise IngestionError("LIFECYCLE_INVARIANT", "promotion artifact hash is invalid")
        details = dict(rows[0]["safe_details"])
        if dict(rows[1]["safe_details"]) != details:
            raise IngestionError("LIFECYCLE_INVARIANT", "promotion artifacts conflict")
        promotion_sha256 = canonical_sha256(details)
        if (
            any(
                row["input_sha256"] != mapping_hash or row["output_sha256"] != promotion_sha256
                for row in rows
            )
            or details.get("mapping_plan_sha256") != mapping_hash
            or details.get("promotion") != "CANONICAL_COMMITTED"
        ):
            raise IngestionError("LIFECYCLE_INVARIANT", "promotion artifact hash is invalid")
        raw_counts = details.get("effect_counts")
        if not isinstance(raw_counts, dict) or set(raw_counts) != {
            "changed",
            "created",
            "reused",
        }:
            raise IngestionError("LIFECYCLE_INVARIANT", "promotion counts are invalid")
        counts: dict[str, dict[str, int]] = {}
        for state, raw_state in raw_counts.items():
            if (
                not isinstance(state, str)
                or not isinstance(raw_state, dict)
                or any(
                    not isinstance(category, str)
                    or not isinstance(count, int)
                    or isinstance(count, bool)
                    or count <= 0
                    for category, count in raw_state.items()
                )
            ):
                raise IngestionError("LIFECYCLE_INVARIANT", "promotion counts are invalid")
            counts[state] = dict(raw_state)
        try:
            competition_id = UUID(str(details["competition_id"]))
            season_id = UUID(str(details["season_id"]))
        except (KeyError, ValueError, TypeError):
            raise IngestionError("LIFECYCLE_INVARIANT", "promotion identity is invalid") from None
        return competition_id, season_id, counts

    def _append_pair_stage_in_session(
        self,
        session: Session,
        snapshots: tuple[UUID, UUID],
        stage: str,
        event_at: datetime,
        input_hashes: tuple[str, str],
        output_hashes: tuple[str, str],
        details: tuple[dict[str, object], dict[str, object]],
        *,
        operation_id: UUID,
    ) -> None:
        for index, snapshot_id in enumerate(snapshots):
            state = str(lifecycle_state(session, snapshot_id)["current_state"])
            if STAGE_INDEX.get(state, -1) >= STAGE_INDEX[stage]:
                continue
            append_processing_event_idempotent(
                session,
                snapshot_id=snapshot_id,
                stage=stage,
                event_at=self._next_event_time(
                    session, snapshot_id, event_at + timedelta(microseconds=index)
                ),
                input_sha256=input_hashes[index],
                output_sha256=output_hashes[index],
                safe_details=details[index],
                operation_id=operation_id,
            )

    def _finish_quality(
        self,
        session: Session,
        operation_at: datetime,
        snapshots: tuple[UUID, UUID],
        quality: QualityReport,
        *,
        mapping_identity_sha256: str,
        mapping_plan_sha256: str,
        operation_id: UUID,
    ) -> tuple[datetime, datetime]:
        for index, snapshot_id in enumerate(snapshots):
            state = str(lifecycle_state(session, snapshot_id)["current_state"])
            if STAGE_INDEX.get(state, -1) < STAGE_INDEX["QUALITY_PASSED"]:
                resource = "bootstrap" if index == 0 else "fixtures"
                for issue in quality.issues:
                    if issue.subject_scope.endswith(resource):
                        issue_details = issue.model_dump(mode="json")
                        session.execute(
                            insert(data_quality_issue).values(
                                source_snapshot_id=snapshot_id,
                                issue_type=issue.code,
                                severity=issue.severity,
                                status="OPEN",
                                detected_at=_stage_time(operation_at, 9 + index),
                                decision_impact=issue.decision_impact,
                                details=issue_details,
                                subject_scope="SOURCE_SNAPSHOT",
                                stage=issue.stage,
                                message=issue.message or issue.code,
                                owner=issue.owner,
                                review_at=issue.review_at,
                            )
                        )
                append_processing_event_idempotent(
                    session,
                    snapshot_id=snapshot_id,
                    stage="QUALITY_PASSED",
                    event_at=self._next_event_time(
                        session, snapshot_id, _stage_time(operation_at, 9 + index)
                    ),
                    output_sha256=canonical_sha256(
                        {
                            "mapping_identity_sha256": mapping_identity_sha256,
                            "mapping_plan_sha256": mapping_plan_sha256,
                            "quality": quality.model_dump(mode="json"),
                        }
                    ),
                    safe_details={
                        "mapping_identity_sha256": mapping_identity_sha256,
                        "mapping_plan_sha256": mapping_plan_sha256,
                        "quality_status": quality.status,
                    },
                    operation_id=operation_id,
                )
        usable_times: list[datetime] = []
        for index, snapshot_id in enumerate(snapshots):
            state = str(lifecycle_state(session, snapshot_id)["current_state"])
            if STAGE_INDEX.get(state, -1) < STAGE_INDEX["USABLE"]:
                append_processing_event_idempotent(
                    session,
                    snapshot_id=snapshot_id,
                    stage="USABLE",
                    event_at=self._next_event_time(
                        session, snapshot_id, _stage_time(operation_at, 11 + index)
                    ),
                    output_sha256=canonical_sha256(
                        {
                            "mapping_identity_sha256": mapping_identity_sha256,
                            "mapping_plan_sha256": mapping_plan_sha256,
                            "quality_status": quality.status,
                            "snapshot": str(snapshot_id),
                        }
                    ),
                    safe_details={
                        "eligibility": "DERIVED_STORAGE_ALLOWED",
                        "mapping_identity_sha256": mapping_identity_sha256,
                        "mapping_plan_sha256": mapping_plan_sha256,
                    },
                    operation_id=operation_id,
                )
            usable_at = lifecycle_state(session, snapshot_id)["usable_at"]
            if not isinstance(usable_at, datetime):
                raise IngestionError("LIFECYCLE_INVARIANT", "usable lifecycle time is unavailable")
            usable_times.append(require_utc(usable_at))
        return usable_times[0], usable_times[1]

    @staticmethod
    def _record_bundle_eligibility_issues(
        session: Session,
        snapshots: tuple[UUID, UUID],
        quality: QualityReport,
    ) -> None:
        blockers = [issue for issue in quality.issues if issue.code == "POST_CUTOFF"]
        if len(blockers) != 1:
            raise IngestionError("INTERNAL_INVARIANT", "post-cutoff quality evidence is incomplete")
        issue = blockers[0]
        for snapshot_id in snapshots:
            exists = session.scalar(
                select(func.count())
                .select_from(data_quality_issue)
                .where(
                    data_quality_issue.c.source_snapshot_id == snapshot_id,
                    data_quality_issue.c.issue_type == "POST_CUTOFF",
                    data_quality_issue.c.stage == "BUNDLE_SELECTION",
                )
            )
            if exists:
                continue
            session.execute(
                insert(data_quality_issue).values(
                    source_snapshot_id=snapshot_id,
                    issue_type=issue.code,
                    severity=issue.severity,
                    status="OPEN",
                    detected_at=issue.observed_at,
                    decision_impact=issue.decision_impact,
                    details=issue.model_dump(mode="json"),
                    subject_scope="SOURCE_SNAPSHOT",
                    stage="BUNDLE_SELECTION",
                    message="usable source snapshot is after the requested cutoff",
                    owner=issue.owner,
                    review_at=issue.review_at,
                )
            )

    def _quarantine(
        self,
        factory: sessionmaker[Session],
        captured_at: datetime,
        snapshots: tuple[UUID, UUID],
        error: IngestionError,
        *,
        pair_key: str,
    ) -> None:
        operation_id = uuid4()
        with factory.begin() as session:
            self._lock_pair(session, pair_key)
            for index, snapshot_id in enumerate(snapshots):
                state = str(lifecycle_state(session, snapshot_id)["current_state"])
                if state in {"QUARANTINED", "REJECTED", "CANCELLED", "FAILED_PERMANENT"}:
                    continue
                last_event_at = session.execute(
                    select(func.max(source_processing_event.c.event_at)).where(
                        source_processing_event.c.source_snapshot_id == snapshot_id
                    )
                ).scalar_one()
                event_at = _stage_time(captured_at, 13 + index)
                if isinstance(last_event_at, datetime) and event_at <= require_utc(last_event_at):
                    event_at = require_utc(last_event_at) + timedelta(microseconds=1)
                missingness = (
                    MissingnessValue.MAPPING_FAILED
                    if error.code == "MAPPING_CONFLICT"
                    else MissingnessValue.UNKNOWN
                )
                details: dict[str, object] = {
                    "classification": str(error.details.get("classification", "")),
                    "error_code": error.code,
                    "missingness": missingness.value,
                }
                details["evidence_sha256"] = canonical_sha256(details)
                session.execute(
                    insert(data_quality_issue).values(
                        source_snapshot_id=snapshot_id,
                        issue_type=error.code,
                        severity="P1",
                        status="OPEN",
                        detected_at=event_at,
                        decision_impact="BLOCKING",
                        details=details,
                        subject_scope="SOURCE_SNAPSHOT",
                        stage="MAPPING" if error.code == "MAPPING_CONFLICT" else "VALIDATION",
                        message="source resource was quarantined by a governed blocker",
                    )
                )
                append_processing_event_idempotent(
                    session,
                    snapshot_id=snapshot_id,
                    stage="QUARANTINED",
                    event_at=event_at,
                    input_sha256=None,
                    output_sha256=None,
                    safe_details=details,
                    error_code=error.code,
                    operation_id=operation_id,
                )

    def _quarantined_result(
        self,
        factory: sessionmaker[Session],
        profile: RightsProfile,
        snapshots: tuple[UUID, UUID],
        error: IngestionError,
        *,
        raw_retention: str = "ALLOWED",
    ) -> FplOperationOutcome:
        with factory() as session:
            resources = tuple(
                ProviderResourceResult(
                    resource="bootstrap" if index == 0 else "fixtures",
                    source_snapshot_id=snapshot_id,
                    lifecycle_state=str(lifecycle_state(session, snapshot_id)["current_state"]),
                    drift=str(error.details.get("classification", "MALFORMED")),
                    raw_retention=raw_retention,
                )
                for index, snapshot_id in enumerate(snapshots)
            )
        return FplOperationOutcome(
            result=ProviderSnapshotResult(
                status="QUARANTINED",
                provider=profile.provider_key,
                resources=resources,
                rights=decide_rights(profile, RightsCapability.DERIVED_STORAGE),
                quality=_blocked_quality(error.code),
                canonical_effects={
                    "code_version": __version__,
                    "contract_version": CONTRACT_VERSION,
                    "error_code": error.code,
                    "next_action": "inspect the typed drift report and provide a valid payload",
                    "outcome": "QUARANTINED",
                },
                source_bundle=None,
            ),
            exit_code=2,
        )

    def _resource_results(
        self,
        factory: sessionmaker[Session],
        snapshots: tuple[UUID, UUID],
        parsed: tuple[ParsedFplResource, ParsedFplResource],
    ) -> tuple[ProviderResourceResult, ProviderResourceResult]:
        values: list[ProviderResourceResult] = []
        with factory() as session:
            for index, snapshot_id in enumerate(snapshots):
                lifecycle = lifecycle_state(session, snapshot_id)
                usable_at = lifecycle.get("usable_at")
                values.append(
                    ProviderResourceResult(
                        resource="bootstrap" if index == 0 else "fixtures",
                        source_snapshot_id=snapshot_id,
                        lifecycle_state=str(lifecycle["current_state"]),
                        drift=parsed[index].drift.classification.value,
                        raw_retention="ALLOWED",
                        usable_at=(
                            require_utc(usable_at) if isinstance(usable_at, datetime) else None
                        ),
                    )
                )
        return values[0], values[1]

    def _safe_resume_path(self, value: object) -> Path:
        if not isinstance(value, str) or not value.startswith("fixtures/"):
            raise IngestionError("LIFECYCLE_INVARIANT", "resume fixture path is invalid")
        candidate = (self.repository_root / Path(value)).resolve()
        try:
            candidate.relative_to(self.repository_root)
        except ValueError as exc:
            raise IngestionError(
                "LIFECYCLE_INVARIANT", "resume fixture path escapes repository"
            ) from exc
        return candidate

    @staticmethod
    def _context_string(context: dict[str, object], key: str) -> str:
        value = context.get(key)
        if not isinstance(value, str) or not value:
            raise IngestionError("LIFECYCLE_INVARIANT", "resume context is incomplete")
        return value

    @staticmethod
    def _context_time(context: dict[str, object], key: str) -> datetime:
        value = FplIngestionService._context_string(context, key)
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise IngestionError("LIFECYCLE_INVARIANT", "resume time is invalid") from exc
        return require_utc(parsed)

    @staticmethod
    def _maybe_interrupt(
        requested: str | None,
        completed: str,
        snapshots: tuple[UUID, UUID],
    ) -> None:
        if requested is not None and requested.replace("-", "_").upper() in {
            completed,
            "STORED_OR_RAW_DISCARDED" if completed == "STORED" else completed,
        }:
            raise IngestionInterrupted(completed, snapshots)


__all__ = [
    "DATABASE_REF",
    "FplImportRequest",
    "FplIngestionService",
    "FplOperationOutcome",
    "FplReplayRequest",
    "IngestionInterrupted",
    "resolve_database_reference",
]
