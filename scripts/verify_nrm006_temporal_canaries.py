"""Run the frozen NRM-006 temporal and HTTP 429 canaries without live I/O."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from sqlalchemy.engine import make_url

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CANARY_ROOT = REPOSITORY_ROOT / "fixtures/odds/NRM-006"
TEST_MODULES = (
    "tests/security/test_odds_429_retry_policy.py",
    "tests/integration/ingestion/odds/test_odds_temporal_publication_mapping.py",
)
EXPECTED_HASHES = {
    "fixtures/odds/NRM-006/future_mapping_canaries.json": (
        "471dd13ac95f27f0e34b6352e50253ea5139bdbc1b202ba4c43278282f217b7c"
    ),
    "fixtures/odds/NRM-006/processing_crosses_cutoff.json": (
        "e70a03b0d1d3195ae83a97ce2671d94abb15b4765e34bb210a5cbb33a8aba715"
    ),
    "fixtures/odds/NRM-006/rate_limit_retry.json": (
        "f5e85faa12fd1655f70b405c3ddd0cc801edca27c1b0607c5838af6bdeeb68e6"
    ),
    "fixtures/odds/NRM-006/expected_outputs/future_mapping_canaries.json": (
        "ac17153205e345694b883e1d9dfe7e80351299a3bfe5c457bd3935aa714cfc89"
    ),
    "fixtures/odds/NRM-006/expected_outputs/processing_crosses_cutoff.json": (
        "638f01644ec20302cfab2749fff4df5d22179174d7f6e7aedbb554f0f4290f9a"
    ),
    "fixtures/odds/NRM-006/expected_outputs/rate_limit_retry.json": (
        "72431b449f943b3980cea059a98201c92e38b4f9f315de245b3aa1bcd0291fd6"
    ),
}


class VerificationError(Exception):
    """A bounded failure whose message contains no URL, body, or credential."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise VerificationError("CANARY_UNAVAILABLE", "a frozen canary is unavailable") from exc
    return digest.hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda constant: (_ for _ in ()).throw(ValueError(constant)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise VerificationError("CANARY_INVALID", "a frozen canary is invalid") from exc
    if not isinstance(value, dict):
        raise VerificationError("CANARY_INVALID", "a frozen canary is invalid")
    return value


def _verify_frozen_canaries() -> dict[str, object]:
    manifest = _read_object(CANARY_ROOT / "manifest.json")
    entries = manifest.get("entries")
    if manifest.get("fixture_manifest_version") != "nrm-006-fixtures-v1.1" or not isinstance(
        entries, list
    ):
        raise VerificationError("CANARY_INVALID", "the NRM-006 fixture manifest is invalid")
    manifest_hashes: dict[str, str] = {}
    for entry in entries:
        if (
            isinstance(entry, dict)
            and isinstance(entry.get("path"), str)
            and isinstance(entry.get("sha256"), str)
        ):
            manifest_hashes[entry["path"]] = entry["sha256"]
    for relative_path, expected_hash in EXPECTED_HASHES.items():
        path = REPOSITORY_ROOT / relative_path
        if _sha256(path) != expected_hash:
            raise VerificationError("CANARY_HASH_MISMATCH", "a frozen canary hash differs")
        if (
            "/expected_outputs/" not in relative_path
            and manifest_hashes.get(relative_path) != expected_hash
        ):
            raise VerificationError(
                "CANARY_MANIFEST_MISMATCH",
                "the NRM-006 fixture manifest differs",
            )
    rate_limit = _read_object(CANARY_ROOT / "rate_limit_retry.json")
    if rate_limit.get("real_sleep_allowed") is not False:
        raise VerificationError("CANARY_INVALID", "the rate-limit canary permits real sleep")
    for relative_path in TEST_MODULES:
        if not (REPOSITORY_ROOT / relative_path).is_file():
            raise VerificationError("TEST_UNAVAILABLE", "a required canary test is unavailable")
    return {
        "fixture_manifest_version": manifest["fixture_manifest_version"],
        "verified_file_count": len(EXPECTED_HASHES),
    }


def _test_environment() -> dict[str, str]:
    if os.environ.get("DMF_ENVIRONMENT", "").casefold() != "test":
        raise VerificationError(
            "DATABASE_CONFIGURATION_INVALID",
            "DMF_ENVIRONMENT must select TEST",
        )
    raw_url = os.environ.get("DMF_TEST_DATABASE_URL")
    if not raw_url:
        raise VerificationError(
            "DATABASE_CONFIGURATION_INVALID",
            "DMF_TEST_DATABASE_URL is required",
        )
    try:
        parsed = make_url(raw_url)
    except Exception as exc:
        raise VerificationError(
            "DATABASE_CONFIGURATION_INVALID",
            "the disposable test database configuration is invalid",
        ) from exc
    if (
        parsed.drivername not in {"postgresql", "postgresql+psycopg"}
        or parsed.host not in {"127.0.0.1", "localhost", "::1"}
        or parsed.database != "dmf_pulse_test"
    ):
        raise VerificationError(
            "DATABASE_CONFIGURATION_INVALID",
            "the verifier requires the disposable local PostgreSQL test database",
        )
    environment = os.environ.copy()
    environment["DMF_ENVIRONMENT"] = "TEST"
    environment["PYTHONNOUSERSITE"] = "1"
    for name in ("THE_ODDS_API_KEY", "ODDS_API_KEY", "DMF_ODDS_API_KEY"):
        environment.pop(name, None)
    return environment


def _run_canaries(environment: dict[str, str]) -> None:
    command = [sys.executable, "-m", "pytest", "-q", *TEST_MODULES]
    try:
        completed = subprocess.run(
            command,
            cwd=REPOSITORY_ROOT,
            env=environment,
            capture_output=True,
            check=False,
            encoding="utf-8",
            errors="replace",
            shell=False,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired as exc:
        raise VerificationError("CANARY_TIMEOUT", "NRM-006 canary verification timed out") from exc
    except OSError as exc:
        raise VerificationError("CANARY_START_FAILED", "NRM-006 canaries could not start") from exc
    if completed.returncode != 0:
        raise VerificationError("CANARY_FAILED", "one or more NRM-006 canaries failed")


def _emit(value: dict[str, object]) -> None:
    print(json.dumps(value, sort_keys=True, separators=(",", ":")))


def main() -> int:
    try:
        frozen = _verify_frozen_canaries()
        environment = _test_environment()
        _run_canaries(environment)
    except VerificationError as exc:
        _emit(
            {
                "error": {"code": exc.code, "message": str(exc)},
                "status": "FAIL",
                "ticket_id": "NRM-006",
            }
        )
        return 1
    except Exception:
        _emit(
            {
                "error": {
                    "code": "VERIFIER_INTERNAL_ERROR",
                    "message": "NRM-006 canary verification failed safely",
                },
                "status": "FAIL",
                "ticket_id": "NRM-006",
            }
        )
        return 1
    _emit(
        {
            "database_scope": "DISPOSABLE_LOCAL_POSTGRESQL",
            "external_network_calls": 0,
            "frozen_canaries": frozen,
            "real_sleep_calls": 0,
            "status": "PASS",
            "test_modules": list(TEST_MODULES),
            "ticket_id": "NRM-006",
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
