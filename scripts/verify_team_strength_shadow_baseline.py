"""Prove literal baseline semantics against exact f39 in isolated offline processes."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.unit.private_v1.team_strength_shadow_support import synthetic_prepared  # noqa: E402

PRIVATE_PARENT = "f39ba4ee3ea748cf60c5743e48f7f68cc6784a71"
_RUN = r"""
from dataclasses import asdict, is_dataclass
import hashlib
import json
from pathlib import Path
import re
import socket
import sys

def blocked(*args, **kwargs):
    raise AssertionError("baseline verification must remain offline")

socket.create_connection = blocked
socket.getaddrinfo = blocked
socket.socket.connect = blocked
socket.socket.connect_ex = blocked
socket.socket.sendto = blocked
root, input_path = map(Path, sys.argv[1:])
sys.path.insert(0, str(root / "src"))
import dmf_pulse
assert Path(dmf_pulse.__file__).resolve() == (root / "src/dmf_pulse/__init__.py").resolve()
from dmf_pulse.private_v1.rolling import PrivateV1RollingRecommendationService
from dmf_pulse.private_v1.rolling_models import PrivateV1RollingExecutionInput
execution = PrivateV1RollingExecutionInput.model_validate_json(input_path.read_bytes())
from dmf_pulse.markets.current import CurrentMarketConstraintService, bind_current_market_constraint_request
from dmf_pulse.private_v1.models import seal_execution_input
from dmf_pulse.private_v1.rolling_models import seal_rolling_execution_input
current = execution.current_execution
expected_markets = CurrentMarketConstraintService().build(
    bind_current_market_constraint_request(current.current_state, current.market_identity_view),
    source=current.current_state, identity_view=current.market_identity_view,
)
# Existing market provenance intentionally hashes ALL installed Python sources.
# Rebuild under each actual build (never spoof code_identity), then compare all
# numerical/decision/report content with only propagated SHA values normalised.
information_sets = {}
def semantic(value):
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if is_dataclass(value):
        value = asdict(value)
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, default=str)
    for key, label in information_sets.items():
        text = text.replace(key, label)
    return re.sub(r"(?<![a-f0-9])[a-f0-9]{64}(?![a-f0-9])", "<SHA256>", text)
assert semantic(current.market_constraints) == semantic(expected_markets)
current_values = dict(current)
current_values["market_constraints"] = expected_markets
execution_values = dict(execution)
execution_values["current_execution"] = seal_execution_input(
    type(current).model_construct(**current_values)
)
execution = seal_rolling_execution_input(type(execution).model_construct(**execution_values))
result = PrivateV1RollingRecommendationService().run(execution)
information_sets = {
    node.information_set_key: f"info-GW-{node.gameweek}"
    for node in result.optimiser_request.scenario_tree.nodes
}
assert len(information_sets) == 3
def digest(value):
    return hashlib.sha256(semantic(value).encode()).hexdigest()
print(json.dumps({
    "execution_content_sha256": digest(execution),
    "decision_content_sha256": digest(result.decision),
    "report_content_sha256": digest(result.report),
    "optimiser_request_content_sha256": digest(result.optimiser_request),
    "optimiser_result_content_sha256": digest(result.optimiser_result),
    "one_gameweek_result_content_sha256": digest(result.one_gameweek_optimiser_result),
    "projection_content_sha256s": [digest(row) for row in result.gameweek_projections],
    "stage11_work_content_sha256": digest(result.stage11_work),
}, sort_keys=True))
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-parent-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    parent = args.private_parent_root.resolve()
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=parent,
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    ).stdout.strip()
    if revision != PRIVATE_PARENT:
        raise ValueError("baseline worktree is not the exact accepted private parent")
    # Only source modules used by the proof need be clean; do not inspect any
    # credentials or private observations in the separate parent worktree.
    changes = subprocess.run(
        ["git", "diff", "HEAD", "--", "src/dmf_pulse", "config", "pyproject.toml"],
        cwd=parent,
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    ).stdout
    if changes:
        raise ValueError("baseline worktree source is modified")
    with tempfile.TemporaryDirectory(prefix="dmf-001p-baseline-") as temporary:
        working = Path(temporary)
        execution = synthetic_prepared(ROOT, working / "source").rolling_execution
        input_path = working / "synthetic-execution.json"
        input_path.write_text(execution.model_dump_json(), encoding="utf-8")
        results = []
        for source in (parent, ROOT):
            process = subprocess.run(
                [sys.executable, "-c", _RUN, str(source), str(input_path)],
                cwd=working,
                text=True,
                capture_output=True,
                check=False,
                timeout=180,
            )
            if process.returncode:
                raise ValueError(
                    "offline synthetic baseline process failed: " + process.stderr[-2400:]
                )
            results.append(json.loads(process.stdout))
        if results[0] != results[1]:
            raise ValueError(
                "literal default baseline semantics changed: "
                + str([key for key in results[0] if results[0][key] != results[1][key]])
            )
    report = {
        "status": "PASS",
        "private_parent": PRIVATE_PARENT,
        "classification": "SYNTHETIC_OFFLINE",
        "separate_processes": True,
        "default_service_construction": True,
        "decisions_reports_projections_and_optimiser_semantics_equal": True,
        "build_provenance": "Market evidence rebuilt under each exact package; propagated SHA values and information-set content IDs (bijective to GW) normalised for content comparison only; production authentication unchanged.",
        "semantic_results": results[0],
        "provider_calls": 0,
        "production_activation": False,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
