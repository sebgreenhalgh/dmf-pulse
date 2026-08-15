"""Exercise explicit-path CLI fail-closed behavior on the current target artifact."""

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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-root", type=Path, required=True)
    parser.parse_args()
    rules = Path("artifacts/rules/fpl-2026-27-0.1.0-prelaunch.1.schema-v1.1.json")
    with tempfile.TemporaryDirectory(prefix="opt010-cli-") as directory:
        root = Path(directory)
        req = request()
        (root / "request.json").write_bytes(canonical_json_bytes(req))
        stage9 = projection(
            req.candidate_pool.candidates
            and "c9fee6287bcb12170aa2f046d486dd812cfa0404efe214344e39f5aeb739cccf"
        )
        stage9_path = root / "gameweek.json"
        stage9_path.write_bytes(canonical_json_bytes(stage9))
        digest = hashlib.sha256(stage9_path.read_bytes()).hexdigest()
        stage9_path.with_suffix(".sha256").write_text(
            f"{digest}  {stage9_path.name}\n", encoding="ascii"
        )
        result = subprocess.run(
            [
                "uv",
                "run",
                "dmf",
                "optimise",
                "one-gameweek",
                "--request",
                str(root / "request.json"),
                "--gameweek-artifact",
                str(stage9_path),
                "--ruleset",
                str(rules),
                "--artifact-root",
                str(root / "artifacts"),
                "--output",
                "json",
            ],
            capture_output=True,
            text=True,
        )
        parsed = json.loads(result.stdout)
        ok = (
            result.returncode == 3
            and parsed.get("error_code") == "MANAGER_TACTICS_CAPABILITY_UNAVAILABLE"
        )
    report = {
        "current_target": "BLOCKED",
        "exit_code": result.returncode,
        "error_code": parsed.get("error_code"),
        "ok": ok,
    }
    output = Path("evidence/tickets/OPT-010/cli_acceptance.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
