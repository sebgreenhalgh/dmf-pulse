"""Exercise the supported OPT-011 offline optimise/advance CLI workflow."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def _run(root: Path, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "src")
    return subprocess.run(
        [sys.executable, "-m", "dmf_pulse.cli.optimise", *arguments],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def _payload(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise ValueError("CLI output must be a JSON object")
    return value


def main() -> int:
    root = Path.cwd().resolve()
    request = root / "fixtures/optimisation/multi_gameweek/request.json"
    ruleset = root / "fixtures/optimisation/multi_gameweek/reference_ruleset_test_only.json"
    with tempfile.TemporaryDirectory(prefix="opt011-cli-") as directory:
        artifact_root = Path(directory) / "artifacts"
        optimised = _run(
            root,
            [
                "multi-gameweek",
                "--request",
                str(request),
                "--ruleset",
                str(ruleset),
                "--artifact-root",
                str(artifact_root),
                "--output",
                "json",
            ],
        )
        optimised_payload = _payload(optimised)
        result_artifacts = sorted(artifact_root.rglob("results/**/*.json"))
        result_path = result_artifacts[0] if result_artifacts else artifact_root / "missing.json"
        advanced = _run(
            root,
            [
                "advance-multi-gameweek",
                "--request",
                str(request),
                "--result",
                str(result_path),
                "--artifact-root",
                str(artifact_root),
                "--observed-node",
                "gw2-price-rise",
                "--output",
                "json",
            ],
        )
        advanced_payload = _payload(advanced)
        advance_artifacts = sorted(artifact_root.rglob("advances/**/*.json"))
    optimise_ok = (
        optimised.returncode == 0
        and optimised_payload.get("status") == "SUCCESS"
        and optimised_payload.get("current_action", {}).get("transfers_out") == ["p07"]
        and optimised_payload.get("current_action", {}).get("transfers_in") == ["p15"]
        and len(result_artifacts) == 1
    )
    advance_ok = (
        advanced.returncode == 0
        and advanced_payload.get("observed_node_id") == "gw2-price-rise"
        and advanced_payload.get("manager_state", {}).get("current_gameweek") == 2
        and len(advance_artifacts) == 1
    )
    report = {
        "schema_version": "opt-011-cli-acceptance-v1",
        "optimise": {
            "exit_code": optimised.returncode,
            "status": optimised_payload.get("status"),
            "current_action": optimised_payload.get("current_action"),
            "artifact_count": len(result_artifacts),
            "ok": optimise_ok,
        },
        "advance": {
            "exit_code": advanced.returncode,
            "observed_node_id": advanced_payload.get("observed_node_id"),
            "current_gameweek": advanced_payload.get("manager_state", {}).get("current_gameweek"),
            "artifact_count": len(advance_artifacts),
            "ok": advance_ok,
        },
        "ok": optimise_ok and advance_ok,
    }
    output = root / "evidence/tickets/OPT-011/cli_acceptance.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
