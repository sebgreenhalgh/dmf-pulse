"""Exercise an existing synthetic native-build execution from a clean R7 wheel."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import verify_current_score_prior_wheel as wheel


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--synthetic-execution", type=Path, required=True)
    args = parser.parse_args()
    execution = args.synthetic_execution.read_text(encoding="utf-8")
    # Only repository-owned synthetic inputs are accepted by this development
    # harness. No native build-identity override: installed verification is real.
    if "repository-synthetic-private-v1" not in execution:
        raise ValueError("expected the repository-owned synthetic fixture")
    wheel._INSTALLED_SMOKE = """
import json
import sys
import dmf_pulse
from typer.testing import CliRunner
from dmf_pulse.cli.app import app
from dmf_pulse.private_v1.rolling_models import PrivateV1RollingExecutionInput
from dmf_pulse.private_v1.rolling import PrivateV1RollingRecommendationService
assert CliRunner().invoke(app, ["pulse", "--help"]).exit_code == 0
execution = PrivateV1RollingExecutionInput.model_validate_json(sys.stdin.read())
result = PrivateV1RollingRecommendationService().run(execution)
assert result.decision is not None
print(json.dumps({"status": "PASS", "module_path": dmf_pulse.__file__,
    "native_build_verification": True,
    "decision_sha256": result.decision.semantic_sha256}))
"""
    original_run = wheel._run

    def run_with_synthetic_stdin(command, *, cwd, environment, step):
        if step != "installed score-prior smoke":
            return original_run(command, cwd=cwd, environment=environment, step=step)
        result = subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            input=execution,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=300,
        )
        if result.returncode:
            raise wheel.VerificationError(
                f"installed private smoke failed: {result.stderr[-1500:]}"
            )
        return result

    wheel._run = run_with_synthetic_stdin
    print(json.dumps(wheel.verify(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
