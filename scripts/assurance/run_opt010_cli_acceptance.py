"""Exercise the frozen OPT-010 public CLI success and fail-closed contracts."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dmf_pulse.fpl_points.artifacts import canonical_json_bytes
from tests.support.optimisation_factories import projection, request


def _run(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(arguments, capture_output=True, text=True, check=False)


def _json_output(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"CLI did not emit JSON: {result.stderr}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("CLI JSON output must be an object")
    return value


def _write_stage9(path: Path, ruleset_hash: str) -> None:
    stage9 = projection(ruleset_hash)
    path.write_bytes(canonical_json_bytes(stage9))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_suffix(".sha256").write_text(f"{digest}  {path.name}\n", encoding="ascii")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-root", type=Path, required=True)
    args = parser.parse_args()
    fixture_root = args.fixture_root.resolve()
    request_path = fixture_root / "request.json"
    stage9_path = fixture_root / "stage9_gameweek_result.json"
    reference_rules = fixture_root / "reference_ruleset_test_only.json"
    target_rules = Path("artifacts/rules/fpl-2026-27-0.1.0-prelaunch.1.schema-v1.1.json").resolve()

    with tempfile.TemporaryDirectory(prefix="opt010-cli-") as directory:
        root = Path(directory)
        artifact_root = root / "artifacts"
        success = _run(
            [
                "uv",
                "run",
                "dmf",
                "optimise",
                "one-gameweek",
                "--request",
                str(request_path),
                "--gameweek-artifact",
                str(stage9_path),
                "--ruleset",
                str(reference_rules),
                "--artifact-root",
                str(artifact_root),
                "--output",
                "json",
            ]
        )
        success_payload = _json_output(success)
        artifacts = sorted(artifact_root.rglob("*.json"))
        success_ok = (
            success.returncode == 0
            and success_payload.get("status") == "SUCCESS"
            and len(artifacts) == 1
        )

        validate = _run(
            [
                "uv",
                "run",
                "dmf",
                "optimise",
                "validate-plan",
                "--request",
                str(request_path),
                "--gameweek-artifact",
                str(stage9_path),
                "--ruleset",
                str(reference_rules),
                "--artifact",
                str(artifacts[0]) if artifacts else str(root / "missing.json"),
                "--output",
                "json",
            ]
        )
        validate_payload = _json_output(validate)
        validate_ok = validate.returncode == 0 and validate_payload.get("legal") is True

        target_request = request()
        target_request_path = root / "target-request.json"
        target_request_path.write_bytes(canonical_json_bytes(target_request))
        target_stage9_path = root / "target-stage9.json"
        _write_stage9(
            target_stage9_path,
            "c9fee6287bcb12170aa2f046d486dd812cfa0404efe214344e39f5aeb739cccf",
        )
        blocked = _run(
            [
                "uv",
                "run",
                "dmf",
                "optimise",
                "one-gameweek",
                "--request",
                str(target_request_path),
                "--gameweek-artifact",
                str(target_stage9_path),
                "--ruleset",
                str(target_rules),
                "--artifact-root",
                str(root / "blocked-artifacts"),
                "--output",
                "json",
            ]
        )
        blocked_payload = _json_output(blocked)
        blocked_ok = (
            blocked.returncode == 3
            and blocked_payload.get("error_code") == "MANAGER_TACTICS_CAPABILITY_UNAVAILABLE"
        )

        invalid_rules = root / "invalid-rules.json"
        invalid_rules.write_bytes(b"{}\n")
        invalid = _run(
            [
                "uv",
                "run",
                "dmf",
                "optimise",
                "one-gameweek",
                "--request",
                str(request_path),
                "--gameweek-artifact",
                str(stage9_path),
                "--ruleset",
                str(invalid_rules),
                "--artifact-root",
                str(root / "invalid-artifacts"),
                "--output",
                "json",
            ]
        )
        invalid_payload = _json_output(invalid)
        invalid_ok = invalid.returncode == 2 and invalid_payload.get("error_code") == (
            "RULESET_ARTIFACT_INVALID"
        )

    ok = success_ok and validate_ok and blocked_ok and invalid_ok
    report = {
        "blocked": {
            "error_code": blocked_payload.get("error_code"),
            "exit_code": blocked.returncode,
            "ok": blocked_ok,
        },
        "invalid": {
            "error_code": invalid_payload.get("error_code"),
            "exit_code": invalid.returncode,
            "ok": invalid_ok,
        },
        "ok": ok,
        "one_gameweek": {
            "exit_code": success.returncode,
            "ok": success_ok,
            "status": success_payload.get("status"),
        },
        "validate_plan": {
            "exit_code": validate.returncode,
            "legal": validate_payload.get("legal"),
            "ok": validate_ok,
        },
    }
    output = Path("evidence/tickets/OPT-010/cli_acceptance.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
