"""Complete rights gate -> fixture joins -> feature report -> command acceptance."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

import pytest
import typer
from typer.testing import CliRunner

from dmf_pulse.cli.player_evidence import player_evidence_app
from dmf_pulse.player_evidence import demo, features, qualification
from dmf_pulse.player_evidence.contracts import EvidenceError

pytestmark = pytest.mark.integration


def test_complete_owned_pipeline_is_reproducible_without_writes_or_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dmf_pulse.availability.pipeline as accepted_pipeline

    def denied(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("descriptive evidence performed a write or invoked a model")

    monkeypatch.setattr(Path, "write_bytes", denied)
    monkeypatch.setattr(Path, "write_text", denied)
    monkeypatch.setattr(accepted_pipeline, "fit_projection_artifact", denied)
    monkeypatch.setattr(accepted_pipeline, "predict_minutes_baseline", denied)
    original = demo.owned_demo()
    later = demo.owned_demo(datetime(2026, 10, 12, 12, tzinfo=UTC))
    assert original == demo.owned_demo()
    assert original.semantic_sha256 != later.semantic_sha256
    assert len(original.players) == len(later.players) == 6
    assert original.mode == later.mode == "SYNTHETIC"
    assert original.source.payload_sha256 == qualification.OWNED_PAYLOAD_SHA256
    assert original.production_activation is False
    assert original.status == "EVIDENCE_ONLY_NOT_MODEL_INPUT"
    assert original.predictive_uncertainty_status == "NOT_ESTIMATED_EMPIRICAL_SUPPORT_ONLY"
    assert original.request == demo.owned_request()
    assert original.source.purpose == "DESCRIPTIVE_EVIDENCE"


@pytest.mark.parametrize("revised", [False, True])
def test_registered_cli_runs_same_authenticated_service(revised: bool) -> None:
    app = typer.Typer()
    app.add_typer(player_evidence_app, name="player-evidence")
    command = ["player-evidence", "demo", *(["--revised"] if revised else [])]
    response = CliRunner().invoke(app, command)
    assert response.exit_code == 0, response.output
    body = json.loads(response.stdout)
    expected = demo.owned_demo(datetime(2026, 10, 12, 12, tzinfo=UTC) if revised else None)
    assert body.pop("semantic_sha256") == expected.semantic_sha256
    assert body == expected.model_dump(mode="json")
    assert body["mode"] == "SYNTHETIC"
    assert body["production_activation"] is False
    assert "NOT_REAL_PLAYER_HISTORY" in " ".join(body["limitations"])


def test_unsupported_source_rejected_before_resource_or_parser_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = qualification.owned_source().model_copy(update={"provider_id": "official_fpl"})

    def denied(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("unqualified source reached acquisition or parsing")

    monkeypatch.setattr(qualification, "owned_body", denied)
    monkeypatch.setattr(features, "decode_dataset", denied)
    with pytest.raises(EvidenceError, match="SOURCE_NOT_QUALIFIED"):
        features.build_features(
            b"unqualified raw body", source=source, request=demo.owned_request()
        )


def test_cli_failure_is_typed_and_does_not_claim_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(_cutoff: datetime | None = None) -> NoReturn:
        raise EvidenceError("SOURCE_BYTES_NOT_AUTHENTICATED")

    monkeypatch.setattr(demo, "owned_demo", denied)
    app = typer.Typer()
    app.add_typer(player_evidence_app, name="player-evidence")
    response = CliRunner().invoke(app, ["player-evidence", "demo"])
    assert response.exit_code == 2
    assert "SOURCE_BYTES_NOT_AUTHENTICATED" in response.output
    assert "semantic_sha256" not in response.output


def test_imports_do_not_read_resources_or_generate_features(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib.resources

    def denied(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("import accessed evidence resources")

    with monkeypatch.context() as isolated:
        isolated.setattr(importlib.resources, "files", denied)
        for module in (qualification, features, demo):
            importlib.reload(module)
    # Restore the normal explicit-invocation resource function after the import probe.
    importlib.reload(qualification)
    importlib.reload(features)
    importlib.reload(demo)
