"""Generated coverage remains fully scanned under unchanged first-party bounds."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from dmf_pulse.assurance.secret_scan import MAX_SCANNED_FILE_BYTES, scan_repository

pytestmark = pytest.mark.unit


def module():
    path = Path("scripts/scan_ci_coverage.py").resolve()
    spec = importlib.util.spec_from_file_location("owned_ci_coverage_scan", path)
    assert spec is not None and spec.loader is not None
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def report():
    padding = list(range(11_000))
    return {
        "meta": {"branch_coverage": True, "format": 3},
        "totals": {"covered_lines": 400, "num_statements": 500, "num_branches": 300},
        "files": {
            f"src/owned_{i:03}.py": {
                "executed_lines": [1, 2, 4, 5],
                "missing_lines": [3],
                "executed_branches": [[1, 2], [1, 4]],
                "missing_branches": [[2, 3]],
                "functions": {"example": {"padding": padding}},
                "classes": {"Example": {"arbitrary": [None, True, 1, 1.0, -0.0, "é"]}},
            }
            for i in range(100)
        },
        "unknown_root_field": {"must_remain": [1, {"extra": "unchanged"}]},
    }


def checkout(tmp_path, value):
    root = tmp_path / "checkout"
    path = root / "evidence/tickets/GCS-008/coverage.json"
    path.parent.mkdir(parents=True)
    before = (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    path.write_bytes(before)
    return root, path, before, tmp_path / "original-coverage.json"


def test_every_field_is_scanned_and_reconstructed_with_original_bytes_restored(tmp_path):
    m = module()
    value = report()
    root, path, before, backup = checkout(tmp_path, value)
    assert len(before) > MAX_SCANNED_FILE_BYTES
    with m.coverage_scan_transport(root, backup, page_bytes=512 * 1024) as receipt:
        assert not path.exists()
        assert backup.read_bytes() == before
        combined = {}
        for row in receipt["pages"]:
            page = root / m.PAGES / row["path"]
            assert page.stat().st_size <= 512 * 1024 < MAX_SCANNED_FILE_BYTES
            parsed = json.loads(page.read_bytes())
            assert parsed["header"] == {k: v for k, v in value.items() if k != "files"}
            combined.update(parsed["file_records"])
        assert combined == value["files"]
        assert scan_repository(root) == []
    assert path.read_bytes() == backup.read_bytes() == before
    assert receipt["restored_original_sha256"] == receipt["original_sha256"]
    assert json.loads(path.read_bytes())["totals"] == value["totals"]
    assert m.MAX_SCANNED_FILE_BYTES == MAX_SCANNED_FILE_BYTES == 5 * 1024 * 1024


@pytest.mark.parametrize("where", ["first", "middle", "last", "metadata"])
def test_secrets_in_every_region_are_detected_and_original_is_restored(tmp_path, where):
    m = module()
    value = report()
    owned_canary = "AKIA" + "A" * 16
    if where == "metadata":
        value["unknown_root_field"]["sample"] = owned_canary
    else:
        index = {"first": 0, "middle": 50, "last": 99}[where]
        value["files"][f"src/owned_{index:03}.py"]["sample"] = owned_canary
    root, path, before, backup = checkout(tmp_path, value)
    with m.coverage_scan_transport(root, backup, page_bytes=512 * 1024):
        findings = scan_repository(root)
        assert findings and all(f.rule_id != "SCAN_COVERAGE" for f in findings)
        assert all("coverage-secret-scan-pages/page-" in f.path for f in findings)
    assert path.read_bytes() == backup.read_bytes() == before


def test_scanner_exception_restores_exact_original(tmp_path):
    m = module()
    root, path, before, backup = checkout(tmp_path, report())
    with (
        pytest.raises(RuntimeError, match="owned scanner failure"),
        m.coverage_scan_transport(root, backup),
    ):
        raise RuntimeError("owned scanner failure")
    assert path.read_bytes() == backup.read_bytes() == before


@pytest.mark.parametrize("change", ["page", "manifest", "backup"])
def test_transport_tampering_refuses_after_restoring_original(tmp_path, change):
    m = module()
    root, path, before, backup = checkout(tmp_path, report())
    with (
        pytest.raises(m.TransportError, match="CHANGED"),
        m.coverage_scan_transport(root, backup) as receipt,
    ):
        target = (
            backup
            if change == "backup"
            else root
            / m.PAGES
            / ("manifest.json" if change == "manifest" else receipt["pages"][0]["path"])
        )
        target.write_bytes(b"owned altered transport")
    assert path.read_bytes() == before


@pytest.mark.parametrize("collision", ["pages", "backup", "inside-backup"])
def test_existing_or_inside_checkout_outputs_fail_before_report_mutation(tmp_path, collision):
    m = module()
    root, path, before, backup = checkout(tmp_path, report())
    if collision == "pages":
        (root / m.PAGES).mkdir()
    elif collision == "backup":
        backup.write_bytes(b"existing unrelated artifact")
    else:
        backup = root / "inside.json"
    with pytest.raises(m.TransportError), m.coverage_scan_transport(root, backup):
        pytest.fail("refused transport must not yield")
    assert path.read_bytes() == before


def test_oversized_indivisible_record_is_not_split_or_removed(tmp_path):
    m = module()
    value = report()
    value["files"] = {"oversized.py": {"padding": "e" * (MAX_SCANNED_FILE_BYTES + 1)}}
    root, path, before, backup = checkout(tmp_path, value)
    with (
        pytest.raises(m.TransportError, match="INDIVIDUAL_COVERAGE_RECORD"),
        m.coverage_scan_transport(root, backup),
    ):
        pytest.fail("oversized record must be refused")
    assert path.read_bytes() == before and not backup.exists()


@pytest.mark.parametrize("body", [b'{"files":{},"files":{}}', b'{"files":{},"extra":NaN}'])
def test_ambiguous_or_nonfinite_input_is_not_modified(tmp_path, body):
    m = module()
    root, path, _, backup = checkout(tmp_path, {"files": {}})
    path.write_bytes(body)
    with pytest.raises(m.TransportError), m.coverage_scan_transport(root, backup):
        pytest.fail("invalid input must not yield")
    assert path.read_bytes() == body and not backup.exists()


def test_cli_runs_only_original_scanner_and_propagates_actual_failure(tmp_path, monkeypatch):
    m = module()
    root, path, before, backup = checkout(tmp_path, report())
    monkeypatch.setattr(m, "REPOSITORY_ROOT", root)
    monkeypatch.setattr(m.shutil, "which", lambda _: "owned-uv")
    calls = []

    def scanner(argv, **kwargs):
        calls.append(argv)
        assert argv == ["owned-uv", "run", "python", "scripts/scan_secrets.py"]
        assert kwargs["cwd"] == root and not path.exists()
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(m.subprocess, "run", scanner)
    assert m.main(["--retained-original", str(backup), "--", *m.SCANNER_COMMAND]) == 1
    assert len(calls) == 1 and path.read_bytes() == before
    with pytest.raises(m.TransportError, match="ONLY_UNCHANGED"):
        m.main(["--retained-original", str(backup), "--", "other-command"])


def test_workflow_keeps_literal_scanner_inside_the_bounded_transport():
    workflow = yaml.safe_load(Path(".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["post_coverage"]["steps"]
    command = next(step["run"] for step in steps if step["name"] == "First-party secret scan")
    assert "scripts/scan_ci_coverage.py" in command
    assert '--retained-original "${RUNNER_TEMP}/coverage-secret-scan-original.json"' in command
    assert "-- uv run python scripts/scan_secrets.py" in command
    assert len(workflow["jobs"]["coverage_shards"]["strategy"]["matrix"]["shard"]) == 16


def test_page_population_bound_is_enforced_during_construction(monkeypatch):
    m = module()
    monkeypatch.setattr(m, "MAX_PAGES", 1)
    value = {"meta": {}, "files": {str(i): {"padding": "e" * 700} for i in range(10)}}
    with pytest.raises(m.TransportError, match="PAGE_POPULATION"):
        m.pages_for(value, 1024)
