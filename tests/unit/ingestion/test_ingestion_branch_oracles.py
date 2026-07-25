"""Independent negative controls for otherwise defensive ingestion branches."""

from __future__ import annotations

import hashlib
import json
import urllib.request
from datetime import UTC, datetime
from decimal import Decimal
from email.message import Message
from pathlib import Path
from uuid import UUID

import pytest

from dmf_pulse.ingestion import fixtures as fixture_module
from dmf_pulse.ingestion import rights as rights_module
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fixtures import approve_synthetic_fixture
from dmf_pulse.ingestion.fpl import parser as parser_module
from dmf_pulse.ingestion.fpl import persistence as persistence_module
from dmf_pulse.ingestion.fpl.adapter import FplReferenceAdapter
from dmf_pulse.ingestion.fpl.client import HttpRequest, HttpResponse, UrllibTransport
from dmf_pulse.ingestion.fpl.parser import FplResource, parse_fpl_payload
from dmf_pulse.ingestion.fpl.persistence import FplPersistence
from dmf_pulse.ingestion.models import (
    CapabilityValue,
    ProviderResourceResult,
    QualityReport,
    RightsCapability,
    RightsDecision,
    SourceBundleMember,
    SourceBundleSummary,
)
from dmf_pulse.ingestion.rights import load_rights_profiles

pytestmark = pytest.mark.unit


def _write_manifest(root: Path, value: object) -> Path:
    path = root / "fixtures/manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    path.write_bytes(encoded)
    return path


def _fixture_case(root: Path) -> tuple[Path, dict[str, object]]:
    body = b'{"synthetic":true}'
    target = root / "fixtures/case/payload.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(body)
    entry: dict[str, object] = {
        "bytes": len(body),
        "path": "fixtures/case/payload.json",
        "rights_profile": "synthetic_test_v1",
        "sha256": hashlib.sha256(body).hexdigest(),
        "synthetic": True,
    }
    return target, {
        "manifest_version": "1.0.0",
        "pack_id": "FPL-004",
        "fixture_count": 1,
        "entries": [entry],
    }


@pytest.mark.parametrize("fault", ["entries", "header", "missing", "bytes"])
def test_trusted_fixture_manifest_rejects_each_structural_false_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    target, value = _fixture_case(tmp_path)
    if fault == "entries":
        value["entries"] = {}
    elif fault == "header":
        value["pack_id"] = "OTHER"
    elif fault == "missing":
        entries = value["entries"]
        assert isinstance(entries, list) and isinstance(entries[0], dict)
        entries[0]["path"] = "fixtures/case/other.json"
    else:
        entries = value["entries"]
        assert isinstance(entries, list) and isinstance(entries[0], dict)
        entries[0]["bytes"] = 1
    manifest = _write_manifest(tmp_path, value)
    monkeypatch.setattr(
        fixture_module, "TRUSTED_MANIFEST_SHA256", hashlib.sha256(manifest.read_bytes()).hexdigest()
    )
    with pytest.raises(IngestionError) as caught:
        approve_synthetic_fixture(target, profile_id="synthetic_test_v1")
    assert caught.value.code == "FIXTURE_NOT_APPROVED"


def test_adapter_success_delegates_to_authorized_transport(repository_root: Path) -> None:
    profile = load_rights_profiles()["synthetic_test_v1"]
    capabilities = dict(profile.capabilities)
    capabilities[RightsCapability.AUTOMATED_ACCESS] = CapabilityValue.ALLOW
    automated = profile.model_copy(update={"capabilities": capabilities})

    class Transport:
        def send(self, _request: HttpRequest) -> HttpResponse:
            return HttpResponse(200, "application/json", b'{"synthetic":true}')

    assert (
        FplReferenceAdapter(automated, Transport).fetch(FplResource.BOOTSTRAP)
        == b'{"synthetic":true}'
    )


def test_transport_rejects_invalid_timeout_contract() -> None:
    request = HttpRequest(
        method="GET",
        host="fantasy.premierleague.com",
        path="/api/bootstrap-static/",
        headers={},
        connect_timeout_seconds=0,
        read_timeout_seconds=10,
        total_timeout_seconds=15,
    )
    with pytest.raises(IngestionError) as caught:
        UrllibTransport().send(request)
    assert caught.value.code == "CONFIGURATION_INVALID"


def test_transport_applies_read_timeout_to_available_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timeouts: list[float] = []

    class Socket:
        def settimeout(self, value: float) -> None:
            timeouts.append(value)

    class Response:
        status = 200
        fp = type("Fp", (), {"raw": type("Raw", (), {"_sock": Socket()})()})()
        headers = Message()

        def __init__(self) -> None:
            self.served = False

        def __enter__(self) -> Response:
            self.headers["Content-Type"] = "application/json"
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, _limit: int) -> bytes:
            if self.served:
                return b""
            self.served = True
            return b"{}"

    class Opener:
        def open(self, _request: object, *, timeout: float) -> Response:
            assert timeout == 3.0
            return Response()

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_handlers: Opener())
    request = HttpRequest(
        method="GET",
        host="fantasy.premierleague.com",
        path="/api/bootstrap-static/",
        headers={},
        connect_timeout_seconds=3,
        read_timeout_seconds=10,
        total_timeout_seconds=15,
    )
    assert UrllibTransport().send(request).body == b"{}"
    assert timeouts == [10, 10]


def test_parser_private_boundaries_cover_exact_bounded_types(repository_root: Path) -> None:
    with pytest.raises(ValueError, match="RFC3339"):
        parser_module._aware_datetime(1)
    with pytest.raises(ValueError, match="cannot be null"):
        parser_module.Event.parse_deadline(None)
    assert parser_module.PlayerElement.parse_percentage(None) is None
    parser_module._check_depth(r'{"escaped":"a\\b"}')
    with pytest.raises(IngestionError, match="object exceeds"):
        parser_module._check_collection_limits(
            {str(index): index for index in range(parser_module.MAX_COLLECTION_ITEMS + 1)}
        )
    assert parser_module._json_type(Decimal("1.2")) == "decimal"
    assert parser_module._json_type(object()) == "object"
    assert parser_module._contract_projection((Decimal("1.20"),)) == ["1.20"]

    bootstrap = parse_fpl_payload(
        FplResource.BOOTSTRAP,
        (repository_root / "fixtures/fpl/FPL-004/happy_path/bootstrap.json").read_bytes(),
    )
    fixtures = parse_fpl_payload(
        FplResource.FIXTURES,
        (repository_root / "fixtures/fpl/FPL-004/happy_path/fixtures.json").read_bytes(),
    )
    with pytest.raises(IngestionError, match="bootstrap payload"):
        parser_module._validate_semantics(FplResource.BOOTSTRAP, fixtures.payload)
    with pytest.raises(IngestionError, match="fixture payload"):
        parser_module._validate_semantics(FplResource.FIXTURES, bootstrap.payload)


def test_public_models_reject_naive_time_bad_quality_and_bad_bundle_order() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        RightsDecision(
            profile_id="profile",
            profile_version="1.0.0",
            capability="raw_storage",
            decision="ALLOW",
            reason="test",
            checked_at=datetime(2026, 1, 1),
        )
    with pytest.raises(ValueError, match="quality counts"):
        QualityReport(status="PASS", warning_count=1, blocker_count=0, issues=())

    first = UUID(int=1)
    second = UUID(int=2)
    common = {
        "bundle_id": UUID(int=3),
        "competition_id": UUID(int=4),
        "season_id": UUID(int=5),
        "information_cutoff": datetime(2026, 8, 21, 17, 30, tzinfo=UTC),
        "semantic_sha256": "0" * 64,
        "quality_status": "PASS",
    }
    with pytest.raises(ValueError, match="ordered"):
        SourceBundleSummary(
            **common,
            members=(
                SourceBundleMember(
                    role="FIXTURES", source_snapshot_id=first, usable_at=datetime.now(UTC)
                ),
                SourceBundleMember(
                    role="BOOTSTRAP", source_snapshot_id=second, usable_at=datetime.now(UTC)
                ),
            ),
        )
    with pytest.raises(ValueError, match="distinct"):
        SourceBundleSummary(
            **common,
            members=(
                SourceBundleMember(
                    role="BOOTSTRAP", source_snapshot_id=first, usable_at=datetime.now(UTC)
                ),
                SourceBundleMember(
                    role="FIXTURES", source_snapshot_id=first, usable_at=datetime.now(UTC)
                ),
            ),
        )


def test_persistence_helpers_reject_invalid_database_values_and_resource_pair(
    repository_root: Path,
) -> None:
    with pytest.raises(IngestionError, match="invalid identifier"):
        persistence_module._uuid("not-a-uuid")
    with pytest.raises(IngestionError, match="explicit 2026/27"):
        persistence_module._season_dates("2025/26")
    bootstrap = parse_fpl_payload(
        FplResource.BOOTSTRAP,
        (repository_root / "fixtures/fpl/FPL-004/happy_path/bootstrap.json").read_bytes(),
    )
    fixtures = parse_fpl_payload(
        FplResource.FIXTURES,
        (repository_root / "fixtures/fpl/FPL-004/happy_path/fixtures.json").read_bytes(),
    )
    persistence = FplPersistence(
        None,  # type: ignore[arg-type]
        captured_at=datetime.now(UTC),
        competition_key="SYNTHETIC_PL",
        season_code="2026/27",
        bootstrap_snapshot_id=UUID(int=1),
        fixtures_snapshot_id=UUID(int=2),
    )
    with pytest.raises(IngestionError, match="resource types differ"):
        persistence.promote(fixtures, bootstrap, None)  # type: ignore[arg-type]


def test_rights_loader_uses_installed_resource_when_repository_config_is_absent(
    repository_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = (
        Path(rights_module.__file__).resolve().parents[3] / "config/rights/fpl_profiles.json"
    )
    original_is_file = Path.is_file
    monkeypatch.setattr(
        Path,
        "is_file",
        lambda path: False if path == candidate else original_is_file(path),
    )

    class ResourceRoot:
        def joinpath(self, _relative: str) -> Path:
            return repository_root / "config/rights/fpl_profiles.json"

    monkeypatch.setattr(rights_module.resources, "files", lambda _package: ResourceRoot())
    assert set(load_rights_profiles()) == {
        "fpl_official_private_manual_v1",
        "synthetic_test_v1",
    }


def test_provider_resource_model_accepts_aware_time_for_control() -> None:
    value = ProviderResourceResult(
        resource="bootstrap",
        source_snapshot_id=UUID(int=1),
        lifecycle_state="USABLE",
        usable_at=datetime.now(UTC),
    )
    assert value.usable_at is not None
