"""Ticket-specific remote authorization seal; never a production control plane."""

from __future__ import annotations

import base64
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from dmf_pulse.assurance.canonical import pretty_json
from dmf_pulse.evaluation.p01_a03_authority import (
    AUTHORITY_SHA,
    BRANCH,
    CONSUMED_REF,
    D1_SHA,
    REPOSITORY,
    A03ReviewBinding,
)
from dmf_pulse.evaluation.p01_fallback_context import strict_json
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    SHA,
    SealedEvidence,
    authenticate,
    seal,
)
from dmf_pulse.ingestion.p01_fallback_diagnostics import FailureReason, ReasonFailure

REVIEW_PATH = "evidence/tickets/CURRENT-TEAM-STRENGTH-001V-P01-FALLBACK-A03/INDEPENDENT-REVIEW.json"
EXPECTED_JOBS = frozenset(
    {"Pre-flight", "Combined coverage gate", "Post-coverage acceptance", "Python 3.13 / Ubuntu"}
    | {f"Coverage shard {index} of 16" for index in range(16)}
)


class A03ConsumptionReceipt(SealedEvidence):
    schema_version: Literal["public-team-strength-p01-a03-consumption-v1"] = (
        "public-team-strength-p01-a03-consumption-v1"
    )
    authority_sha256: SHA
    implementation_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    exact_sha_review_binding_sha256: SHA
    independent_review_sha256: SHA
    consumed_at: datetime
    consumed: Literal[True] = True
    attempt_number: Literal[1] = 1
    maximum_attempts: Literal[1] = 1
    retry_permitted: Literal[False] = False
    source_switch_permitted: Literal[False] = False
    source: Literal["OpenLigaDB"] = "OpenLigaDB"
    provider_requests_before_seal: Literal[0] = 0
    production_active: Literal[False] = False


class RemoteConsumptionSeal(SealedEvidence):
    schema_version: Literal["public-team-strength-p01-a03-remote-consumption-seal-v1"] = (
        "public-team-strength-p01-a03-remote-consumption-seal-v1"
    )
    repository: Literal["sebgreenhalgh/dmf-pulse"] = "sebgreenhalgh/dmf-pulse"
    ref: Literal["refs/heads/evidence/CURRENT-TEAM-STRENGTH-001V-P01-FALLBACK-A03-consumed"] = (
        "refs/heads/evidence/CURRENT-TEAM-STRENGTH-001V-P01-FALLBACK-A03-consumed"
    )
    commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    receipt: A03ConsumptionReceipt


class GitHubA03Control:
    """Create-only fixed ref; no secrets read, retries, force, reset or ref deletion."""

    def __init__(self, implementation_root: Path) -> None:
        self.root = implementation_root.resolve()
        self._verified: A03ReviewBinding | None = None
        self._used = False

    def _git(self, *arguments: str) -> bytes:
        try:
            result = subprocess.run(
                ["git", *arguments], cwd=self.root, capture_output=True, timeout=60, check=True
            )
        except (OSError, subprocess.SubprocessError):
            raise ReasonFailure(FailureReason.REVIEW_INVALID) from None
        return result.stdout

    def _api(
        self, endpoint: str, *, payload: dict[str, object] | None = None, absent_ok: bool = False
    ) -> dict[str, Any] | None:
        command = ["gh", "api", "--include", "repos/" + REPOSITORY + "/" + endpoint]
        if payload is not None:
            command += ["--method", "POST", "--input", "-"]
        try:
            result = subprocess.run(
                command,
                cwd=self.root,
                input=None if payload is None else json.dumps(payload).encode(),
                capture_output=True,
                timeout=60,
                check=False,
            )
            raw = result.stdout.replace(b"\r\n", b"\n")
            header, body = raw.split(b"\n\n", 1)
            first = header.splitlines()[0].split()
            if not first[0].startswith(b"HTTP/"):
                raise ValueError
            status = int(first[1])
            if status == 404 and absent_ok:
                return None
            if result.returncode or status not in {200, 201}:
                raise ValueError
            value = strict_json(body)
            if not isinstance(value, dict):
                raise ValueError
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            raise ReasonFailure(FailureReason.MARKER_PERSISTENCE_FAILED) from None
        return value

    def verify(self, binding: A03ReviewBinding, *, expected_review_bytes: bytes) -> None:
        binding = authenticate(binding)
        if (
            self._git("rev-parse", "HEAD").decode().strip() != binding.implementation_sha
            or self._git("rev-parse", "HEAD^").decode().strip() != D1_SHA
            or self._git("status", "--porcelain").strip()
            or self._git("show", binding.implementation_sha + ":" + REVIEW_PATH)
            != expected_review_bytes
        ):
            raise ReasonFailure(FailureReason.REVIEW_INVALID)
        branch = self._api("git/ref/heads/" + BRANCH)
        run = self._api("actions/runs/" + str(binding.ci_run_id))
        jobs = self._api("actions/runs/" + str(binding.ci_run_id) + "/jobs?per_page=100")
        if branch is None or run is None or jobs is None:
            raise ReasonFailure(FailureReason.REVIEW_INVALID)
        rows = jobs.get("jobs", [])
        if (
            branch.get("object", {}).get("sha") != binding.implementation_sha
            or run.get("head_sha") != binding.implementation_sha
            or run.get("status") != "completed"
            or run.get("conclusion") != "success"
            or jobs.get("total_count") != 20
            or len(rows) != 20
            or {row.get("name") for row in rows} != EXPECTED_JOBS
            or any(
                row.get("status") != "completed" or row.get("conclusion") != "success"
                for row in rows
            )
        ):
            raise ReasonFailure(FailureReason.REVIEW_INVALID)
        self._verified = binding

    def consume(self, receipt: A03ConsumptionReceipt) -> RemoteConsumptionSeal:
        # Set before any remote operation: ambiguous outcomes never allow reuse.
        if self._used:
            raise ReasonFailure(FailureReason.ONE_ATTEMPT_ALREADY_CONSUMED)
        self._used = True
        receipt = authenticate(receipt)
        binding = self._verified
        if (
            binding is None
            or receipt.authority_sha256 != AUTHORITY_SHA
            or receipt.implementation_sha != binding.implementation_sha
            or receipt.exact_sha_review_binding_sha256 != binding.semantic_sha256
            or receipt.independent_review_sha256 != binding.file_review_sha256
        ):
            raise ReasonFailure(FailureReason.REVIEW_INVALID)
        endpoint = "git/ref/" + CONSUMED_REF.removeprefix("refs/")
        if self._api(endpoint, absent_ok=True) is not None:
            raise ReasonFailure(FailureReason.ONE_ATTEMPT_ALREADY_CONSUMED)
        text = pretty_json(receipt)
        tree = self._api(
            "git/trees",
            payload={
                "tree": [
                    {
                        "path": "A03-ATTEMPT-CONSUMED.json",
                        "mode": "100644",
                        "type": "blob",
                        "content": text,
                    }
                ]
            },
        )
        if tree is None:
            raise ReasonFailure(FailureReason.MARKER_PERSISTENCE_FAILED)
        commit = self._api(
            "git/commits",
            payload={
                "message": "Seal the single human-authorized P01 A03 attempt",
                "tree": tree["sha"],
                "parents": [],
            },
        )
        if commit is None:
            raise ReasonFailure(FailureReason.MARKER_PERSISTENCE_FAILED)
        # GitHub create-ref is atomic and refuses an existing reference, including
        # the same target commit. Never use update-ref or a force push here.
        created = self._api("git/refs", payload={"ref": CONSUMED_REF, "sha": commit["sha"]})
        observed = self._api(endpoint)
        blob = self._api("contents/A03-ATTEMPT-CONSUMED.json?ref=" + commit["sha"])
        if (
            created is None
            or observed is None
            or blob is None
            or created.get("ref") != CONSUMED_REF
            or created.get("object", {}).get("sha") != commit["sha"]
            or observed.get("object", {}).get("sha") != commit["sha"]
            or blob.get("encoding") != "base64"
            or base64.b64decode(blob.get("content", "")) != text.encode()
        ):
            raise ReasonFailure(FailureReason.MARKER_PERSISTENCE_FAILED)
        return seal(RemoteConsumptionSeal, commit_sha=commit["sha"], receipt=receipt)


def consumption_receipt(
    binding: A03ReviewBinding, *, at: datetime | None = None
) -> A03ConsumptionReceipt:
    return seal(
        A03ConsumptionReceipt,
        authority_sha256=AUTHORITY_SHA,
        implementation_sha=binding.implementation_sha,
        exact_sha_review_binding_sha256=binding.semantic_sha256,
        independent_review_sha256=binding.file_review_sha256,
        consumed_at=at or datetime.now(UTC),
    )
