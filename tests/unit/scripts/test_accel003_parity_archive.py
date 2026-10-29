"""Installed parity inventories survive cleanup with bounded immutable custody."""

from __future__ import annotations

import hashlib
import json
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
VERIFY = runpy.run_path(str(ROOT / "scripts/verify_wheel.py"))
archive = VERIFY["_archive_accel003_parity"]
VerificationError = VERIFY["VerificationError"]
WHEEL = "a" * 64
pytestmark = pytest.mark.unit


def write_inventories(controls: Path):
    controls.mkdir()
    cases = []
    for horizon in (1, 3):
        body = json.dumps(
            {"checked_fields": 10, "numeric_fields": 8, "excluded": [], "mismatches": []}
        ).encode()
        (controls / f"parity-{horizon}.json").write_bytes(body)
        cases.append(
            {
                "horizon": horizon,
                "checked_fields": 10,
                "numeric_fields": 8,
                "custody_exclusion_count": 0,
                "custody_inventory_sha256": hashlib.sha256(body).hexdigest(),
            }
        )
    return {"cases": cases}


def test_exact_raw_inventories_are_content_addressed_and_repeatable(tmp_path):
    controls = tmp_path / "temporary"
    expected = write_inventories(controls)
    artifacts = archive(controls, WHEEL, repository_root=tmp_path, acceptance=expected)
    assert [row["horizon"] for row in artifacts] == [1, 3]
    for row in artifacts:
        destination = tmp_path / row["path"]
        assert destination.parent.name == "accel003-installed-parity-" + WHEEL[:16]
        assert row["sha256"] in destination.name
        assert destination.read_bytes() == (controls / f"parity-{row['horizon']}.json").read_bytes()
        assert row["bytes"] == destination.stat().st_size
        assert row["wheel_sha256"] == WHEEL
    assert archive(controls, WHEEL, repository_root=tmp_path, acceptance=expected) == artifacts


def test_failed_partial_or_malformed_raw_comparison_is_preserved(tmp_path):
    controls = tmp_path / "temporary"
    controls.mkdir()
    raw = b'{"mismatches":[{"expected":1,"actual":2}],"incomplete":'
    (controls / "parity-1.json").write_bytes(raw)
    (controls / "unrelated-private-source.json").write_bytes(b"not an allowed archive")
    artifacts = archive(controls, WHEEL, repository_root=tmp_path)
    assert len(artifacts) == 1
    assert (tmp_path / artifacts[0]["path"]).read_bytes() == raw
    assert len(list((tmp_path / "review_pack").rglob("*.json"))) == 1


def test_failed_run_before_parity_produces_no_false_complete_inventory(tmp_path):
    assert archive(tmp_path / "absent", WHEEL, repository_root=tmp_path) == []


def test_forced_timeout_preserves_completed_comparison_inside_owned_run(tmp_path):
    controls = tmp_path / "temporary"
    run = controls / "owned-runs-interrupted"
    run.mkdir(parents=True)
    raw = b'{"mismatches":[{"phase":"interrupted"}]}'
    (run / "parity-1.json").write_bytes(raw)
    artifacts = archive(controls, WHEEL, repository_root=tmp_path)
    assert (tmp_path / artifacts[0]["path"]).read_bytes() == raw


def test_multiple_interrupted_runs_are_ambiguous_and_never_selected_by_outcome(tmp_path):
    controls = tmp_path / "temporary"
    for name in ("owned-runs-a", "owned-runs-b"):
        run = controls / name
        run.mkdir(parents=True)
        (run / "parity-1.json").write_bytes(b"{}")
    with pytest.raises(VerificationError, match="ambiguous"):
        archive(controls, WHEEL, repository_root=tmp_path)


def test_success_requires_both_inventories(tmp_path):
    controls = tmp_path / "temporary"
    expected = write_inventories(controls)
    (controls / "parity-3.json").unlink()
    with pytest.raises(VerificationError, match="missing"):
        archive(controls, WHEEL, repository_root=tmp_path, acceptance=expected)
    # The available artifact survives the failing acceptance check.
    assert len(list((tmp_path / "review_pack").rglob("*.json"))) == 1


@pytest.mark.parametrize("body", [b"", b"x" * (2 * 1024 * 1024 + 1)], ids=["empty", "oversized"])
def test_empty_or_oversized_inventory_is_rejected(tmp_path, body):
    controls = tmp_path / "temporary"
    controls.mkdir()
    (controls / "parity-1.json").write_bytes(body)
    with pytest.raises(VerificationError, match="size bound"):
        archive(controls, WHEEL, repository_root=tmp_path)
    assert not (tmp_path / "review_pack").exists()


@pytest.mark.parametrize("attack", ["digest", "count", "numeric", "mismatch", "malformed"])
def test_success_rejects_inconsistent_raw_inventory_or_stdout_metadata(tmp_path, attack):
    controls = tmp_path / "temporary"
    expected = write_inventories(controls)
    if attack == "digest":
        expected["cases"][0]["custody_inventory_sha256"] = "b" * 64
    elif attack == "count":
        expected["cases"][0]["custody_exclusion_count"] = 1
    else:
        path = controls / "parity-1.json"
        body = json.loads(path.read_bytes())
        if attack == "numeric":
            body["numeric_fields"] = True
        elif attack == "mismatch":
            body["mismatches"] = [{"actual": 2, "expected": 1}]
        path.write_bytes(b"{" if attack == "malformed" else json.dumps(body).encode())
    with pytest.raises(VerificationError):
        archive(controls, WHEEL, repository_root=tmp_path, acceptance=expected)
    assert len(list((tmp_path / "review_pack").rglob("*.json"))) == 2


def test_existing_content_addressed_path_is_never_overwritten(tmp_path):
    controls = tmp_path / "temporary"
    expected = write_inventories(controls)
    artifacts = archive(controls, WHEEL, repository_root=tmp_path, acceptance=expected)
    destination = tmp_path / artifacts[0]["path"]
    destination.write_bytes(b"corrupt earlier artifact")
    with pytest.raises(VerificationError, match="conflicts"):
        archive(controls, WHEEL, repository_root=tmp_path, acceptance=expected)
    assert destination.read_bytes() == b"corrupt earlier artifact"


def test_wheel_identity_must_be_exact_sha256(tmp_path):
    with pytest.raises(VerificationError, match="wheel identity"):
        archive(tmp_path, "../untrusted", repository_root=tmp_path)
