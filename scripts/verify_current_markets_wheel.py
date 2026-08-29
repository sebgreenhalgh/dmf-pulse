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
from datetime import timedelta
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

from dmf_pulse.ingestion.current_state import (
    CurrentUnifiedStateBundle,
    current_unified_state_semantic_sha256,
)
from dmf_pulse.ingestion.odds.current import current_odds_market_semantic_sha256
from dmf_pulse.ingestion.odds.identity import current_odds_identity_semantic_sha256
from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.markets.current import (
    CurrentMarketCanonicalIdentityView,
    CurrentMarketConstraintError,
    CurrentMarketConstraintService,
    bind_current_market_constraint_request,
    current_market_identity_view_sha256,
    current_odds_rights_sha256,
    current_odds_temporal_sha256,
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
assert request.odds_temporal_sha256 == current_odds_temporal_sha256(source)
assert request.odds_rights_sha256 == current_odds_rights_sha256(source)
assert result.lineage.odds_temporal_sha256 == request.odds_temporal_sha256
assert result.lineage.odds_rights_sha256 == request.odds_rights_sha256
assert result.runtime.persistence_performed is False
assert result.runtime.database_write_performed is False
assert result.runtime.network_called is False
assert "NO_ACCEPTED_CURRENT_SCORE_PRIOR" in result.limitations

temporal = source.odds_input.temporal.model_copy(
    update={
        "request_started_at": source.odds_input.temporal.request_started_at
        - timedelta(seconds=1)
    }
)
temporal_source = source.model_copy(
    update={"odds_input": source.odds_input.model_copy(update={"temporal": temporal})}
)
try:
    service.build(request, source=temporal_source, identity_view=view)
except CurrentMarketConstraintError as error:
    assert error.code == "SOURCE_MISMATCH"
else:
    raise AssertionError("installed wheel accepted a stale temporal request")
temporal_request = bind_current_market_constraint_request(temporal_source, view)
temporal_result = service.build(
    temporal_request,
    source=temporal_source,
    identity_view=view,
)
assert temporal_request.odds_temporal_sha256 != request.odds_temporal_sha256
assert temporal_result.semantic_sha256 != result.semantic_sha256

wrong_rights = source.odds_input.rights.model_copy(
    update={"rights_profile_id": "synthetic_unapproved_profile"}
)
rights_source = source.model_copy(
    update={"odds_input": source.odds_input.model_copy(update={"rights": wrong_rights})}
)
rights_request = bind_current_market_constraint_request(rights_source, view)
try:
    service.build(rights_request, source=rights_source, identity_view=view)
except CurrentMarketConstraintError as error:
    assert error.code == "RIGHTS_BLOCKED"
    assert "synthetic_unapproved_profile" not in str(error)
    assert "synthetic_unapproved_profile" not in repr(error)
    assert "synthetic_unapproved_profile" not in json.dumps(error.as_error_object())
else:
    raise AssertionError("installed wheel accepted an unapproved rights profile")

def rehash_market_source(changed_odds):
    provisional_odds = changed_odds.model_copy(update={"market_semantic_sha256": "0" * 64})
    checked_odds = provisional_odds.model_copy(
        update={
            "market_semantic_sha256": current_odds_market_semantic_sha256(provisional_odds)
        }
    )
    lineage = source.lineage.model_copy(
        update={
            "odds_market_semantic_sha256": checked_odds.market_semantic_sha256,
            "odds_identity_semantic_sha256": current_odds_identity_semantic_sha256(
                checked_odds
            ),
        }
    )
    provisional_source = source.model_copy(
        update={
            "odds_input": checked_odds,
            "lineage": lineage,
            "semantic_sha256": "0" * 64,
        }
    )
    return provisional_source.model_copy(
        update={
            "semantic_sha256": current_unified_state_semantic_sha256(provisional_source)
        }
    )

events = list(source.odds_input.events)
event = events[0]
books = list(event.bookmakers)
for index, book in enumerate(books):
    market = book.markets[0]
    swapped = tuple(
        outcome.model_copy(
            update={
                "provider_name": (
                    event.provider_away_team
                    if outcome.outcome == "HOME"
                    else event.provider_home_team
                    if outcome.outcome == "AWAY"
                    else outcome.provider_name
                )
            }
        )
        for outcome in market.outcomes
    )
    books[index] = book.model_copy(
        update={"markets": (market.model_copy(update={"outcomes": swapped}),)}
    )
events[0] = event.model_copy(
    update={
        "provider_home_team": event.provider_away_team,
        "provider_away_team": event.provider_home_team,
        "bookmakers": tuple(books),
    }
)
orientation_source = rehash_market_source(
    source.odds_input.model_copy(update={"events": tuple(events)})
)
orientation_request = bind_current_market_constraint_request(orientation_source, view)
try:
    service.build(orientation_request, source=orientation_source, identity_view=view)
except CurrentMarketConstraintError as error:
    assert error.code == "SOURCE_INVALID"
else:
    raise AssertionError("installed wheel accepted a coherent cross-source orientation swap")

first_operator, second_operator = view.operators
aliased_second = second_operator.model_copy(
    update={
        "canonical_operator_id": first_operator.canonical_operator_id,
        "canonical_operator_key": first_operator.canonical_operator_key,
    }
)
alias_provisional = view.model_copy(
    update={
        "operators": (first_operator, aliased_second),
        "semantic_sha256": "0" * 64,
    }
)
alias_view = alias_provisional.model_copy(
    update={"semantic_sha256": current_market_identity_view_sha256(alias_provisional)}
)
events = list(source.odds_input.events)
event = events[0]
books = list(event.bookmakers)
valid_at = source.odds_input.temporal.received_at - timedelta(seconds=1)
future_at = source.odds_input.temporal.received_at + timedelta(seconds=1)
books[0] = books[0].model_copy(
    update={
        "markets": (
            books[0].markets[0].model_copy(update={"provider_last_update": future_at}),
        )
    }
)
books[1] = books[1].model_copy(
    update={
        "markets": (
            books[1].markets[0].model_copy(update={"provider_last_update": valid_at}),
        )
    }
)
events[0] = event.model_copy(update={"bookmakers": tuple(books)})
h2h_receipt_source = rehash_market_source(
    source.odds_input.model_copy(update={"events": tuple(events)})
)
h2h_receipt_request = bind_current_market_constraint_request(h2h_receipt_source, alias_view)
h2h_receipt_result = service.build(
    h2h_receipt_request,
    source=h2h_receipt_source,
    identity_view=alias_view,
)
target_mapping = source.identity_map.fixture(event.provider_event_id)
target_fixture = alias_view.fixture(target_mapping.official_fpl_fixture_id)
h2h_receipt_fixture = next(
    item
    for item in h2h_receipt_result.fixtures
    if item.canonical_fixture_id == target_fixture.canonical_fixture_id
)
assert h2h_receipt_fixture.h2h_consensus is not None
assert h2h_receipt_fixture.h2h_consensus.operator_count == 1
assert h2h_receipt_fixture.h2h_consensus.operator_markets[0].observed_at == valid_at
assert any(
    item.reason == "FUTURE_OBSERVATION" and item.count >= 1
    for item in h2h_receipt_fixture.exclusion_counts
)

operator = view.operators[0]
target_events = {
    mapping.provider_event_id for mapping in source.identity_map.fixture_mappings
}
earliest_occurrence = min(
    event.commence_time
    for event in source.odds_input.events
    if event.provider_event_id in target_events
    for bookmaker in event.bookmakers
    if bookmaker.bookmaker_key == operator.bookmaker_key
)
earliest_only_digest = canonical_sha256(
    {
        "bookmaker_key": operator.bookmaker_key,
        "contract_version": "current-market-operator-applicability-v1",
        "target_occurrence_times": [earliest_occurrence.isoformat()],
    }
)
earliest_operator = operator.model_copy(
    update={"target_occurrence_times_sha256": earliest_only_digest}
)
earliest_provisional = view.model_copy(
    update={
        "operators": (earliest_operator, *view.operators[1:]),
        "semantic_sha256": "0" * 64,
    }
)
earliest_view = earliest_provisional.model_copy(
    update={"semantic_sha256": current_market_identity_view_sha256(earliest_provisional)}
)
earliest_request = bind_current_market_constraint_request(source, earliest_view)
try:
    service.build(earliest_request, source=source, identity_view=earliest_view)
except CurrentMarketConstraintError as error:
    assert error.code == "CANONICAL_IDENTITY_UNAVAILABLE"
else:
    raise AssertionError("installed wheel accepted earliest-only operator applicability")

events = list(source.odds_input.events)
event = events[0]
books = list(event.bookmakers)
totals = list(books[0].totals_markets)
totals[1] = totals[1].model_copy(
    update={
        "provider_last_update": source.odds_input.temporal.received_at
        + timedelta(seconds=1)
    }
)
books[0] = books[0].model_copy(update={"totals_markets": tuple(totals)})
events[0] = event.model_copy(update={"bookmakers": tuple(books)})
receipt_source = rehash_market_source(
    source.odds_input.model_copy(update={"events": tuple(events)})
)
receipt_request = bind_current_market_constraint_request(receipt_source, view)
receipt_result = service.build(receipt_request, source=receipt_source, identity_view=view)
receipt_fixture = next(
    item
    for item in receipt_result.fixtures
    if any(total.line == Decimal("2.5") for total in item.totals_consensuses)
)
receipt_total = next(
    item for item in receipt_fixture.totals_consensuses if item.line == Decimal("2.5")
)
assert receipt_total.eligible_operator_count == 1
assert any(
    item.reason == "FUTURE_OBSERVATION" and item.count >= 1
    for item in receipt_fixture.exclusion_counts
)
assert not attempts
print(json.dumps({
    "fixture_count": summary.fixture_count,
    "market_ready_count": summary.market_ready_count,
    "module_path": __import__("dmf_pulse").__file__,
    "network_requests": len(attempts),
    "orientation_attack": "BLOCKED",
    "operator_earliest_only_attack": "BLOCKED",
    "post_receipt_h2h_alias": "VALID_OLDER_RETAINED",
    "post_receipt_totals": "EXCLUDED",
    "rights_attack": "BLOCKED",
    "semantic_sha256": result.semantic_sha256,
    "status": "PASS",
    "temporal_attack": "BLOCKED",
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
