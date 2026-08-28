"""Verify CURRENT-MARKETS-001A from an offline wheel outside the repository."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from tests.unit.markets.current_market_test_support import build_market_context  # noqa: E402


class VerificationError(RuntimeError):
    """A bounded installed-wheel verification failure."""


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    step: str,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            list(command),
            cwd=cwd,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VerificationError(f"{step} could not complete") from exc
    if result.returncode != 0:
        raise VerificationError(
            f"{step} failed with exit {result.returncode}: "
            f"{result.stdout[-500:]} {result.stderr[-500:]}"
        )
    return result


def _python(environment_root: Path) -> Path:
    return (
        environment_root / "Scripts/python.exe"
        if os.name == "nt"
        else environment_root / "bin/python"
    )


def _environment(environment_root: Path | None = None) -> dict[str, str]:
    environment = os.environ.copy()
    for name in (
        "PYTHONPATH",
        "PYTHONHOME",
        "THE_ODDS_API_KEY",
        "ODDS_API_KEY",
        "DMF_ODDS_API_KEY",
        "DATABASE_URL",
        "DMF_DATABASE_URL",
        "DMF_TEST_DATABASE_URL",
    ):
        environment.pop(name, None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["UV_OFFLINE"] = "1"
    environment["HTTP_PROXY"] = "http://127.0.0.1:9"
    environment["HTTPS_PROXY"] = "http://127.0.0.1:9"
    environment["NO_PROXY"] = ""
    if environment_root is not None:
        environment["VIRTUAL_ENV"] = str(environment_root)
    return environment


def _wheel() -> Path:
    matches = sorted((REPOSITORY_ROOT / "dist").glob("dmf_pulse-0.2.0-py3-none-any.whl"))
    if len(matches) != 1:
        raise VerificationError("exactly one current dmf-pulse wheel is required")
    return matches[0].resolve()


def _json_object(output: str) -> dict[str, Any]:
    for line in reversed([item for item in output.splitlines() if item.strip()]):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise VerificationError("installed current-market smoke emitted no JSON result")


_INSTALLED_SMOKE = r"""
import json
import socket
import sys
from decimal import Decimal
from pathlib import Path

attempts = []
def blocked(*args, **kwargs):
    attempts.append((args, kwargs))
    raise AssertionError("installed current-market smoke attempted network access")

socket.create_connection = blocked
socket.getaddrinfo = blocked
socket.socket.connect = blocked
socket.socket.connect_ex = blocked
socket.socket.sendto = blocked

from dmf_pulse.ingestion.current_state import CurrentUnifiedStateBundle
from dmf_pulse.markets.current import (
    CurrentMarketCanonicalIdentityView,
    CurrentMarketConstraintService,
    bind_current_market_constraint_request,
)

source = CurrentUnifiedStateBundle.model_validate_json(Path(sys.argv[1]).read_text(encoding="utf-8"))
view = CurrentMarketCanonicalIdentityView.model_validate_json(
    Path(sys.argv[2]).read_text(encoding="utf-8")
)
request = bind_current_market_constraint_request(source, view)
service = CurrentMarketConstraintService()
result = service.build(request, source=source, identity_view=view)
assert service.verify(result, request, source=source, identity_view=view) == result
assert len(result.fixtures) == 2
assert all(item.readiness.value == "MARKET_READY" for item in result.fixtures)
assert all(item.h2h_consensus is not None for item in result.fixtures)
assert all(len(item.totals_consensuses) == 2 for item in result.fixtures)
assert all(len(item.constraint_set.constraints) == 7 for item in result.fixtures)
assert all(
    sum((outcome.consensus_probability for outcome in totals.outcomes), Decimal(0)) == Decimal(1)
    for fixture in result.fixtures
    for totals in fixture.totals_consensuses
)
summary = result.safe_summary()
assert summary.fixture_count == 2
assert summary.market_ready_count == 2
assert summary.totals_line_count == 4
assert result.runtime.persistence_performed is False
assert result.runtime.database_write_performed is False
assert result.runtime.network_called is False
assert "NO_ACCEPTED_CURRENT_SCORE_PRIOR" in result.limitations
assert not attempts
print(json.dumps({
    "fixture_count": summary.fixture_count,
    "market_ready_count": summary.market_ready_count,
    "module_path": __import__("dmf_pulse").__file__,
    "network_requests": len(attempts),
    "semantic_sha256": result.semantic_sha256,
    "status": "PASS",
    "totals_line_count": summary.totals_line_count,
}, sort_keys=True))
"""


def verify() -> dict[str, Any]:
    uv = shutil.which("uv")
    if uv is None:
        raise VerificationError("uv is unavailable")
    wheel = _wheel()
    with tempfile.TemporaryDirectory(prefix="dmf-current-markets-wheel-") as temporary:
        temporary_root = Path(temporary).resolve()
        repository_root = REPOSITORY_ROOT.resolve()
        if temporary_root == repository_root or repository_root in temporary_root.parents:
            raise VerificationError("clean environment is inside the repository")
        context, view, _request, _result = build_market_context(
            repository_root,
            temporary_root / "synthetic-source",
        )
        source_path = temporary_root / "source.json"
        view_path = temporary_root / "identity-view.json"
        source_path.write_text(context.bundle.model_dump_json(), encoding="utf-8")
        view_path.write_text(view.model_dump_json(), encoding="utf-8")
        environment_root = temporary_root / "venv"
        base_environment = _environment()
        _run(
            [uv, "venv", "--python", "3.13", "--no-project", str(environment_root)],
            cwd=temporary_root,
            environment=base_environment,
            step="clean virtual environment creation",
        )
        environment = _environment(environment_root)
        _run(
            [
                uv,
                "sync",
                "--frozen",
                "--offline",
                "--no-dev",
                "--no-install-project",
                "--active",
            ],
            cwd=repository_root,
            environment=environment,
            step="locked runtime dependency installation",
        )
        python = _python(environment_root)
        _run(
            [
                uv,
                "pip",
                "install",
                "--offline",
                "--no-deps",
                "--python",
                str(python),
                str(wheel),
            ],
            cwd=temporary_root,
            environment=environment,
            step="wheel installation",
        )
        smoke = _run(
            [str(python), "-c", _INSTALLED_SMOKE, str(source_path), str(view_path)],
            cwd=temporary_root,
            environment=environment,
            step="installed current-market smoke",
        )
        report = _json_object(smoke.stdout)
        module_path = Path(str(report["module_path"])).resolve()
        if module_path == repository_root or repository_root in module_path.parents:
            raise VerificationError("installed smoke imported repository source")
        report["clean_environment_outside_repository"] = True
        report["wheel"] = wheel.name
        return report


def main() -> int:
    try:
        report = verify()
    except VerificationError as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, sort_keys=True))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
