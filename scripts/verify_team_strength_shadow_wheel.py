"""Runtime-only installed-wheel 001P comparison on generated synthetic inputs."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

from verify_current_team_strength_p0_wheel import (
    REPOSITORY_ROOT,
    VerificationError,
    _environment,
    _json_object,
    _python,
    _run,
    _wheel,
)

sys.path.insert(0, str(REPOSITORY_ROOT))

from dmf_pulse.private_v1.team_strength_shadow_inputs import (
    prepare_team_strength_shadow,
)
from tests.unit.private_v1.team_strength_case_support import CASES, case_prepared
from tests.unit.private_v1.team_strength_shadow_support import (
    synthetic_model_prepared,
    synthetic_strength,
)

_SMOKE = r"""
import json
from pathlib import Path
import socket
import sys

def blocked(*args, **kwargs):
    raise AssertionError("installed 001P acceptance must remain offline")

socket.create_connection = blocked
socket.getaddrinfo = blocked
socket.socket.connect = blocked
socket.socket.connect_ex = blocked
socket.socket.sendto = blocked

import dmf_pulse
from dmf_pulse.ingestion.fpl.direct_payloads import DirectFplSnapshot
from dmf_pulse.private_v1.one_command import _PrivateV1PreparedRollingContext
from dmf_pulse.private_v1.rolling_models import PrivateV1RollingExecutionInput
from dmf_pulse.private_v1.team_strength_shadow_inputs import TeamStrengthShadowPreparation
from dmf_pulse.private_v1.team_strength_comparison import run_team_strength_shadow_comparison, safe_team_strength_summary

assert Path(dmf_pulse.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
root = Path(sys.argv[1])
execution = PrivateV1RollingExecutionInput.model_validate_json((root / "execution.json").read_bytes())
preparation = TeamStrengthShadowPreparation.model_validate_json((root / "preparation.json").read_bytes())
assert execution.current_execution.retention_class == "SYNTHETIC_REPLAY_ALLOWED"
current = execution.current_execution
# The synthetic context has no manager endpoint/credential material. Only the
# snapshot fields consumed by this private preparation seam are constructed.
snapshot = DirectFplSnapshot.model_construct(fpl_input=current.current_state.fpl_input)
prepared = _PrivateV1PreparedRollingContext(
    snapshot=snapshot, rolling_execution=execution, player_identity_map=current.player_identity_map,
    fpl_request_count=0, fpl_endpoint_classes=(), odds_request_count=0, odds_endpoint_classes=(),
    score_prior_acquisition_count=1, fpl_rights_profile_id="fpl_official_private_manual_v1",
    odds_rights_profile_id="the_odds_api_private_analytics_v1",
    information_cutoff=current.current_state.information_cutoff,
)
run = run_team_strength_shadow_comparison(prepared, preparation)
summary = safe_team_strength_summary(run)
assert summary["comparison"]["classification"] == "TEAM_STRENGTH_ROOT_ACTION_MATERIAL"
assert summary["comparison"]["utility_delta"] == "-5"
assert summary["provider_requests_during_solves"] == 0
assert summary["production_activation"] is False
print(json.dumps({
    "installed_import": True, "classification": summary["comparison"]["classification"],
    "utility_delta": summary["comparison"]["utility_delta"],
    "comparison_sha256": summary["comparison_sha256"],
    "player_count": summary["projection_movement"]["player_count"],
    "provider_requests_during_solves": 0, "production_activation": False,
}))
"""


def verify() -> dict[str, object]:
    uv = shutil.which("uv")
    if uv is None:
        raise VerificationError("uv unavailable")
    with tempfile.TemporaryDirectory(prefix="dmf-001p-wheel-") as temporary:
        root = Path(temporary).resolve()
        if root.is_relative_to(REPOSITORY_ROOT):
            raise VerificationError("installed-wheel test must be outside source tree")
        prepared = synthetic_model_prepared(REPOSITORY_ROOT, root / "synthetic-source")
        prepared = case_prepared(prepared, CASES[1])
        dataset, artifact = synthetic_strength()
        preparation = prepare_team_strength_shadow(
            prepared.rolling_execution,
            artifact=artifact,
            expected_artifact_sha256=artifact.semantic_sha256,
            fixture_registry=dataset.fixture_registry,
        )
        (root / "execution.json").write_text(
            prepared.rolling_execution.model_dump_json(), encoding="utf-8"
        )
        (root / "preparation.json").write_text(preparation.model_dump_json(), encoding="utf-8")
        venv = root / "venv"
        _run(
            [uv, "venv", "--python", "3.13", "--no-project", str(venv)],
            cwd=root,
            environment=_environment(),
            step="clean runtime environment",
        )
        environment = _environment(venv)
        _run(
            [uv, "sync", "--frozen", "--offline", "--no-dev", "--no-install-project", "--active"],
            cwd=REPOSITORY_ROOT,
            environment=environment,
            step="locked runtime dependencies",
        )
        python = _python(venv)
        _run(
            [
                uv,
                "pip",
                "install",
                "--offline",
                "--no-deps",
                "--python",
                str(python),
                str(_wheel()),
            ],
            cwd=root,
            environment=environment,
            step="offline wheel install",
        )
        result = _json_object(
            _run(
                [str(python), "-c", _SMOKE, str(root)],
                cwd=root,
                environment=environment,
                step="installed real two-world comparison",
            ).stdout
        )
        return {
            "status": "PASS",
            "clean_environment_outside_repository": True,
            "locked_runtime_only": True,
            "offline_installation": True,
            "synthetic_only": True,
            "private_live_persistence": False,
            **result,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    report = verify()
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
