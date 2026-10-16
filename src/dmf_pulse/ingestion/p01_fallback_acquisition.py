"""One-attempt, rights/review-gated public P01 acquisition; no raw-body storage."""

from __future__ import annotations

import http.client
import os
import ssl
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol, Self

from pydantic import Field, model_validator

from dmf_pulse.assurance.canonical import pretty_json, sha256_file
from dmf_pulse.evaluation.p01_fallback_context import (
    CONTEXT_SHA,
    ROUTES,
    authenticate_p01,
    load_context,
    require_openligadb_rights,
    strict_json,
)
from dmf_pulse.evaluation.p01_fallback_store import persist_fallback
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    SHA,
    FrozenEvidence,
    SealedEvidence,
    StrengthEvidenceError,
    authenticate,
)
from dmf_pulse.ingestion.p01_fallback import (
    PublicP01FallbackOutcomesV1,
    admit_final_facts,
    project_final_facts,
    regulation_type,
    require_d_plus_2,
    source_receipt,
)

REVIEWED_PATHS = (
    "config/evaluation/team_strength_p01_fallback_a02.json",
    "config/rights/openligadb_p01_fallback.json",
    "src/dmf_pulse/evaluation/p01_fallback_context.py",
    "src/dmf_pulse/evaluation/p01_frozen_view.py",
    "src/dmf_pulse/evaluation/p01_fallback.py",
    "src/dmf_pulse/evaluation/p01_fallback_store.py",
    "src/dmf_pulse/evaluation/team_strength_prospective.py",
    "src/dmf_pulse/ingestion/p01_fallback.py",
    "src/dmf_pulse/ingestion/p01_fallback_acquisition.py",
    "src/dmf_pulse/cli/p01_fallback.py",
    "src/dmf_pulse/cli/team_strength.py",
    "scripts/run_p01_fallback_a02.py",
    "scripts/verify_p01_fallback_a02_wheel.py",
    "tests/unit/evaluation/test_p01_fallback_a02.py",
    "tests/fixtures/evaluation/a02_legacy_score_oracle.json",
    "pyproject.toml",
    ".github/workflows/ci.yml",
    "tickets/CURRENT-TEAM-STRENGTH-001V-P01-FALLBACK-A02/CONTRACT.md",
)


class ReviewedFile(FrozenEvidence):
    path: str
    byte_sha256: SHA


class P01IndependentReview(SealedEvidence):
    schema_version: Literal["public-team-strength-p01-a02-independent-review-v1"] = (
        "public-team-strength-p01-a02-independent-review-v1"
    )
    context_sha256: Literal["6bb80a9c0b17b673044be5b5c53a2eda6c4e4110ef09f7a586e87e0d8432c259"]
    reviewer_identity: str = Field(min_length=1)
    reviewed_at: datetime
    verdict: Literal["CLEAR_FOR_P01_OPENLIGADB_DESCRIPTIVE_SCORING"]
    unresolved_p0_p1: Literal[0] = 0
    no_live_labels_acquired: Literal[True] = True
    no_p01_performance_metrics_inspected: Literal[True] = True
    files: tuple[ReviewedFile, ...]
    assessment: tuple[str, ...] = Field(min_length=8)

    @model_validator(mode="after")
    def review_scope(self) -> Self:
        if tuple(row.path for row in self.files) != REVIEWED_PATHS:
            raise ValueError("independent review file scope differs")
        return self


def authenticate_review(
    path: Path, *, expected_sha256: str, implementation_root: Path
) -> P01IndependentReview:
    data = path.read_bytes()
    strict_json(data)
    review = authenticate(P01IndependentReview.model_validate_json(data), expected_sha256)
    context = load_context()
    if review.reviewed_at < context.amended_at or review.context_sha256 != CONTEXT_SHA:
        raise StrengthEvidenceError("independent review predates A02 authority")
    root = implementation_root.resolve()
    for item in review.files:
        candidate = root / item.path
        if (
            candidate.is_symlink()
            or not candidate.resolve().is_relative_to(root)
            or sha256_file(candidate) != item.byte_sha256
        ):
            raise StrengthEvidenceError("implementation changed after independent review")
    return review


class OpenLigaTransport(Protocol):
    def get(self, url: str) -> bytes: ...


class HttpOpenLigaTransport:
    """Explicit TLS host/routes, 20-second total budget, bounded bytes; no redirects."""

    def get(self, url: str) -> bytes:
        if url not in ROUTES:
            raise StrengthEvidenceError("undeclared OpenLigaDB route refused")
        require_openligadb_rights()
        started = time.monotonic()
        connection = http.client.HTTPSConnection(
            "api.openligadb.de", timeout=8, context=ssl.create_default_context()
        )
        try:
            connection.request(
                "GET",
                url.removeprefix("https://api.openligadb.de"),
                headers={
                    "Accept": "application/json",
                    "Connection": "close",
                    "User-Agent": "dmf-pulse/0.2.0",
                },
            )
            response = connection.getresponse()
            if response.status != 200 or response.getheader("Content-Type", "").split(";", 1)[
                0
            ].lower() not in {"application/json", "text/json", "text/plain"}:
                raise StrengthEvidenceError("OpenLigaDB response status/type refused; no retry")
            length = response.getheader("Content-Length")
            if length is not None and (not length.isdecimal() or int(length) > 524288):
                raise StrengthEvidenceError("OpenLigaDB response exceeds bounded acquisition")
            chunks: list[bytes] = []
            count = 0
            while True:
                remaining = 20 - (time.monotonic() - started)
                if remaining <= 0:
                    raise StrengthEvidenceError("OpenLigaDB total timeout; no retry")
                if connection.sock is not None:
                    connection.sock.settimeout(min(8, remaining))
                part = response.read1(min(32768, 524289 - count))
                if not part:
                    break
                count += len(part)
                if count > 524288:
                    raise StrengthEvidenceError("OpenLigaDB response exceeds bounded acquisition")
                chunks.append(part)
            if length is not None and count != int(length):
                raise StrengthEvidenceError("OpenLigaDB truncated response")
            return b"".join(chunks)
        except (OSError, http.client.HTTPException) as exc:
            raise StrengthEvidenceError("OpenLigaDB acquisition unavailable; no retry") from exc
        finally:
            connection.close()


def acquire_p01_once(
    *,
    forecast_path: Path,
    review_path: Path,
    expected_review_sha256: str,
    implementation_root: Path,
    artifact_root: Path,
    transport: OpenLigaTransport | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> PublicP01FallbackOutcomesV1:
    """No provider call can occur until all immutable/review/rights checks pass."""
    context = load_context()
    rights = require_openligadb_rights()
    review = authenticate_review(
        review_path, expected_sha256=expected_review_sha256, implementation_root=implementation_root
    )
    authenticate_p01(forecast_path)
    started = FrozenEvidence.utc_datetimes(clock())
    if started < review.reviewed_at:
        raise StrengthEvidenceError("acquisition predates independent review")
    if artifact_root.is_symlink():
        raise StrengthEvidenceError("acquisition root is a symbolic link")
    root = artifact_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    marker = root / "OPENLIGADB-P01-ONE-ATTEMPT.json"
    marker_payload = {
        "context_sha256": context.semantic_sha256,
        "independent_review_sha256": review.semantic_sha256,
        "forecast_sha256": context.forecast_sha256,
        "forecast_byte_sha256": context.forecast_byte_sha256,
        "source": "OpenLigaDB",
        "started_at": started.isoformat(),
        "source_policy_locked_before_metrics": True,
        "no_metrics_inspected": True,
        "no_retry_or_polling": True,
    }
    try:
        with marker.open("xb") as stream:
            stream.write(pretty_json(marker_payload).encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise StrengthEvidenceError("P01_SOURCE_POLICY_LOCKED_ONE_ATTEMPT_CONSUMED") from exc
    client = transport or HttpOpenLigaTransport()
    bodies: list[bytes] = []  # Transient only; no raw bytes are written or logged.
    receipts = []
    for url in context.allowed_routes[:2]:
        request_start = FrozenEvidence.utc_datetimes(clock())
        body = client.get(url)
        received = FrozenEvidence.utc_datetimes(clock())
        receipts.append(source_receipt(url, body, started=request_start, received=received))
        bodies.append(body)
    result_type = regulation_type(bodies[0], bodies[1])
    bodies.clear()
    url = context.allowed_routes[2]
    request_start = FrozenEvidence.utc_datetimes(clock())
    body = client.get(url)
    received = FrozenEvidence.utc_datetimes(clock())
    receipts.append(source_receipt(url, body, started=request_start, received=received))
    facts = project_final_facts(body, context=context, result_type=result_type)
    bodies.clear()
    validated = FrozenEvidence.utc_datetimes(clock())
    outcomes = admit_final_facts(
        facts,
        context=context,
        retrievals=tuple(receipts),
        result_type=result_type,
        validated_at=validated,
        usable_at=FrozenEvidence.utc_datetimes(clock()),
        attribution=rights.attribution_text or "",
        independent_review_sha256=review.semantic_sha256,
        independently_reviewed_at=review.reviewed_at,
    )
    persist_fallback(outcomes, artifact_root=root)
    require_d_plus_2(outcomes, as_of=FrozenEvidence.utc_datetimes(clock()))
    return outcomes
