"""Explicit locators hash only bounded bodies and never infer freeze custody."""

import hashlib
import json

import pytest
from typer.testing import CliRunner

from dmf_pulse.cli.recovery import recovery_app
from dmf_pulse.player_lab import locator
from dmf_pulse.player_lab.recovery import RecoveryError
from tests.unit.player_lab.real_support import AT

pytestmark = pytest.mark.unit


def test_unknown_json_and_pickle_are_hashed_without_parsing(tmp_path, monkeypatch):
    root = tmp_path / "explicit-approved"
    root.mkdir()
    bodies = {
        "forecast.json": b"this is not JSON",
        "forecast.pickle": b"owned-invalid-pickle-no-execution",
    }
    for name, body in bodies.items():
        (root / name).write_bytes(body)
    value = locator.onboard_locator(root, now=AT)
    assert (
        len(value.artifacts) == 2 and not value.pickle_executed and not value.source_rights_granted
    )
    assert {row.byte_sha256 for row in value.artifacts} == {
        hashlib.sha256(body).hexdigest() for body in bodies.values()
    }
    assert all(
        row.classification == "UNVERIFIED_CUSTODY" and row.original_frozen_at is None
        for row in value.artifacts
    )
    summary = value.public_summary()
    assert "explicit-approved" not in json.dumps(summary) and "forecast.json" not in json.dumps(
        summary
    )
    assert not summary["evaluation_authorized"]


def test_defaults_do_not_descend_and_explicit_depth_is_bounded(tmp_path):
    (tmp_path / "child").mkdir()
    (tmp_path / "child" / "point.json").write_bytes(b"owned")
    assert locator.onboard_locator(tmp_path, now=AT).artifacts == ()
    result = locator.onboard_locator(
        tmp_path, now=AT, bounds=locator.LocatorBounds(maximum_depth=1)
    )
    assert len(result.artifacts) == 1 and result.artifacts[0].relative_locator == "child/point.json"


@pytest.mark.parametrize(
    "bounds",
    [
        locator.LocatorBounds(maximum_files=1),
        locator.LocatorBounds(maximum_total_bytes=1),
    ],
)
def test_census_budget_rejected_before_any_body_read(tmp_path, monkeypatch, bounds):
    for name in ("a", "b"):
        (tmp_path / name).write_bytes(b"owned")
    monkeypatch.setattr(
        locator, "_artifact_digest", lambda *a, **kw: pytest.fail("overbudget body read")
    )
    with pytest.raises(RecoveryError, match="UNSAFE_OR_BUDGET"):
        locator.onboard_locator(tmp_path, now=AT, bounds=bounds)


def test_secret_location_rejected_before_enumeration(tmp_path, monkeypatch):
    selected = tmp_path / ".aws"
    selected.mkdir()
    monkeypatch.setattr(
        locator.DirectoryPins, "scan", lambda *a: pytest.fail("secret directory enumerated")
    )
    with pytest.raises(RecoveryError):
        locator.onboard_locator(selected, now=AT)


def test_grown_after_census_rejected_before_read(tmp_path, monkeypatch):
    path = tmp_path / "forecast"
    path.write_bytes(b"x")
    original = locator._artifact_digest

    def race(selected, **kwargs):
        selected.write_bytes(b"grown")
        return original(selected, **kwargs)

    monkeypatch.setattr(locator, "_artifact_digest", race)
    with pytest.raises(RecoveryError):
        locator.onboard_locator(path, now=AT, bounds=locator.LocatorBounds(maximum_total_bytes=1))


def test_cli_private_immutable_inventory_and_public_aggregates(tmp_path):
    source = tmp_path / "approved-forecast.json"
    source.write_bytes(b"owned")
    output = tmp_path / "private-inventory.json"
    result = CliRunner().invoke(
        recovery_app, ["add-locator", "--locator", str(source), "--output", str(output)]
    )
    assert result.exit_code == 0, result.output
    summary = json.loads(result.stdout)
    assert summary["files_hashed"] == 1 and not summary["evaluation_authorized"]
    assert "approved-forecast" not in result.stdout
    prior = output.read_bytes()
    repeat = CliRunner().invoke(
        recovery_app, ["add-locator", "--locator", str(source), "--output", str(output)]
    )
    assert repeat.exit_code == 2 and output.read_bytes() == prior
