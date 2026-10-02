"""Capped explicit public/synthetic 001U review archive and verified evidence hashes."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path

from dmf_pulse.assurance.canonical import canonical_sha256

ROOT = Path(__file__).resolve().parents[1]
TICKET = "CURRENT-TEAM-STRENGTH-001U"
EVIDENCE = ROOT / "evidence/tickets" / TICKET
NAMES = (
    f"tickets/{TICKET}/ticket.yaml",
    f"tickets/{TICKET}/CONVERGENCE-POLICY.md",
    f"evidence/tickets/{TICKET}/COVARIANCE-AUDIT.md",
    f"evidence/tickets/{TICKET}/U06-PROSPECTIVE.md",
    f"evidence/tickets/{TICKET}/U07-ACCEPTANCE.md",
    f"evidence/tickets/{TICKET}/INDEPENDENT-REVIEW.md",
    "src/dmf_pulse/football_events/team_strength_parameter_draws.py",
    "src/dmf_pulse/football_events/team_strength_mixture.py",
    "src/dmf_pulse/football_events/team_strength_mixture_stage8.py",
    "src/dmf_pulse/evaluation/team_strength_prospective.py",
    "src/dmf_pulse/evaluation/team_strength_prospective_store.py",
    "src/dmf_pulse/evaluation/team_strength_mixture_analysis.py",
    "src/dmf_pulse/private_v1/team_strength_comparison.py",
    "src/dmf_pulse/private_v1/team_strength_screen_metrics.py",
    "src/dmf_pulse/cli/team_strength.py",
    "tests/unit/football_events/test_team_strength_parameter_draws.py",
    "tests/unit/football_events/test_team_strength_mixture.py",
    "tests/unit/football_events/test_team_strength_mixture_stage8.py",
    "tests/unit/evaluation/test_team_strength_prospective.py",
    "tests/unit/private_v1/test_team_strength_screen_metrics.py",
    f"evidence/tickets/{TICKET}/CONVERGENCE.json",
    f"evidence/tickets/{TICKET}/PERFORMANCE.json",
    f"evidence/tickets/{TICKET}/NUMERICAL-VALIDATION.json",
    f"evidence/tickets/{TICKET}/current_manifest.json",
)


def metadata(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(ROOT):
        raise ValueError("unsafe review/evidence file")
    body = path.read_bytes()
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def build() -> dict[str, object]:
    for name in ("CONVERGENCE.json", "NUMERICAL-VALIDATION.json", "PERFORMANCE.json"):
        report = json.loads((EVIDENCE / name).read_bytes())
        if report.pop("semantic_sha256") != canonical_sha256(report):
            raise ValueError("numerical/convergence/performance report identity mismatch")
        if name == "PERFORMANCE.json" and any(
            metadata(ROOT / path)["sha256"] != digest
            for path, digest in report["source_sha256s"].items()
        ):
            raise ValueError("benchmark evidence does not describe current sources")
    # Publication evidence cannot claim local closure while required checks failed.
    for phase in ("focus", "quality", "wheel", "scope", "repair", "authority-repair"):
        record = json.loads((EVIDENCE / f"COMMANDS-{phase}.json").read_bytes())
        if record["status"] != "PASS" or any(row["exit_code"] != 0 for row in record["commands"]):
            raise ValueError("required local acceptance phase did not pass")
        for row in record["commands"]:
            path = ROOT / row["output_path"]
            if not path.resolve().is_relative_to(EVIDENCE) or path.is_symlink():
                raise ValueError("unsafe command output path")
            if hashlib.sha256(path.read_bytes()).hexdigest() != row["output_sha256"]:
                raise ValueError("command output hash mismatch")
        if phase == "repair":
            row = record["commands"][0]
            if (
                row["argv"]
                != [
                    "uv",
                    "run",
                    "--offline",
                    "pytest",
                    "tests/unit/private_v1/test_team_strength_shadow_cases.py",
                    "tests/unit/private_v1/test_team_strength_d7_evidence.py",
                    "-q",
                ]
                or re.search(
                    r"(?m)^7 passed in ", (ROOT / row["output_path"]).read_text(encoding="utf-8")
                )
                is None
            ):
                raise ValueError("repair did not execute the complete seven-test population")
        if phase == "authority-repair":
            row = record["commands"][0]
            if (
                row["argv"]
                != [
                    "uv",
                    "run",
                    "--offline",
                    "pytest",
                    "tests/unit/private_v1/test_team_strength_l1.py",
                    "-q",
                ]
                or re.search(
                    r"(?m)^44 passed in ",
                    (ROOT / row["output_path"]).read_text(encoding="utf-8"),
                )
                is None
            ):
                raise ValueError("authority repair did not execute the complete L1 population")
    regression = json.loads((EVIDENCE / "COMMANDS-regression.json").read_bytes())
    if len(regression["commands"]) != 1:
        raise ValueError("regression evidence must contain the complete recorded command")
    row = regression["commands"][0]
    path = ROOT / row["output_path"]
    if (
        path.is_symlink()
        or not path.resolve().is_relative_to(EVIDENCE)
        or hashlib.sha256(path.read_bytes()).hexdigest() != row["output_sha256"]
        or (regression["status"] == "PASS" and row["exit_code"] != 0)
    ):
        raise ValueError("regression output identity/status mismatch")
    resolved = []
    if regression["status"] != "PASS":
        log = (ROOT / regression["commands"][0]["output_path"]).read_text(encoding="utf-8")
        resolved = re.findall(r"^FAILED[ \t]+(\S+)(?:[ \t]+-.*)?[ \t]*$", log, flags=re.MULTILINE)
        summary = re.search(r"(?m)^(\d+) failed, (\d+) passed(?:, \d+ deselected)? in ", log)
        allowed = {
            "tests/unit/private_v1/test_team_strength_d7_evidence.py::test_d7_historical_authorities_remain_closed_under_l8",
            "tests/unit/private_v1/test_team_strength_l1.py::test_l8_rights_hashes_and_current_authority_are_exact",
            *(
                "tests/unit/private_v1/test_team_strength_shadow_cases.py::test_locked_real_canonical_case["
                + case
                + "]"
                for case in ("A_ROBUST", "B_ROOT", "C_CONTINUATION", "D_TACTICS", "E_SCREEN")
            ),
        }
        if (
            not resolved
            or summary is None
            or int(summary.group(1)) != len(resolved)
            or regression["status"] != "FAIL"
            or re.search(r"(?m)^(?:ERROR\s|ERROR:|INTERNALERROR>|Interrupted:)", log)
            or not set(resolved) <= allowed
            or regression["commands"][0]["exit_code"] != 1
        ):
            raise ValueError("unresolved regression failure")
    if len(NAMES) != len(set(NAMES)) or len(NAMES) + 1 > 25:
        raise ValueError("review entry cap exceeded")
    bodies = {}
    files = []
    for name in sorted(NAMES):
        path = ROOT / name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(ROOT):
            raise ValueError("unsafe review source path")
        body = path.read_bytes()
        bodies[name] = body
        files.append({"path": name, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()})
    if (
        any(len(body) > 1024 * 1024 for body in bodies.values())
        or sum(map(len, bodies.values())) > 5 * 1024 * 1024
    ):
        raise ValueError("review byte cap exceeded")
    manifest = {"ticket": TICKET, "private_live_material": False, "files": files}
    archive = ROOT / "review_pack" / (TICKET + ".zip")
    archive.parent.mkdir(exist_ok=True)
    if archive.is_symlink() or not archive.resolve().is_relative_to(ROOT):
        raise ValueError("unsafe review destination")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for name, body in (
            *bodies.items(),
            ("MANIFEST.json", json.dumps(manifest, sort_keys=True).encode()),
        ):
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            output.writestr(entry, body, compress_type=zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(archive) as output:
        if len(output.namelist()) != len(bodies) + 1 or any(
            output.read(name) != body for name, body in bodies.items()
        ):
            raise ValueError("review archive verification failed")
    report = {
        "status": "PASS",
        "files": len(bodies) + 1,
        "uncompressed_source_bytes": sum(map(len, bodies.values())),
        "archive": metadata(archive),
    }
    (EVIDENCE / "REVIEW-PACK.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    artifacts = [
        metadata(path)
        for path in sorted(EVIDENCE.iterdir())
        if path.is_file() and path.name != "evidence_manifest.json"
    ]
    evidence = {
        "schema_version": "team-strength-u-evidence-manifest-v1",
        "ticket": TICKET,
        "classification": "PUBLIC_SYNTHETIC_OFFLINE_ONLY_NO_PRIVATE_PROVIDER_ACCESS",
        "status": "LOCAL_EVIDENCE_COMPLETE_EXACT_SHA_CI_SEPARATE_PUBLICATION_GATE",
        "historical_test_expectation_failures_resolved_by_repair_phase": resolved,
        "authority_sha256": hashlib.sha256(
            (ROOT / "specs/manifests/authority_manifest.json").read_bytes()
        ).hexdigest(),
        "artifacts": artifacts,
    }
    destination = EVIDENCE / "evidence_manifest.json"
    destination.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    reloaded = json.loads(destination.read_bytes())
    if any(metadata(ROOT / item["path"]) != item for item in reloaded["artifacts"]):
        raise ValueError("exact evidence hashes differ")
    return report | {"evidence_artifacts_verified": len(artifacts)}


if __name__ == "__main__":
    print(json.dumps(build(), sort_keys=True))
