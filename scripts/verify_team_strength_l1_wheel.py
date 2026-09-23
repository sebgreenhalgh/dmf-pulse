"""Offline consumed-L1/L2 authority smoke in a runtime-only external wheel."""

import json
import shutil
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

SMOKE = r"""
import json, socket, sys
from pathlib import Path
from datetime import datetime, UTC
def denied(*args, **kwargs):
    raise AssertionError('installed L1 test must remain offline')
socket.create_connection = denied
socket.getaddrinfo = denied
socket.socket.connect = denied
import dmf_pulse
from dmf_pulse.private_v1.team_strength_live_authority import validate_l1_authority, APPROVAL, ATTESTATION, L1_APPROVAL, L1_ATTESTATION, L2_APPROVAL, L2_ATTESTATION, ConsumedL1ApprovalError
from dmf_pulse.private_v1.team_strength_diagnostics import ComparisonTrace, ComparisonStage, ComparisonReason, safe_comparison_failure
from dmf_pulse.private_v1.team_strength_live import L1OperatorRequest, TeamStrengthL1ObservationService
from dmf_pulse.ingestion.openfootball.team_strength_current import discover_current_resource
assert Path(dmf_pulse.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
stamp = datetime(2026, 10, 1, tzinfo=UTC)
for approval, attestation in ((L1_APPROVAL, L1_ATTESTATION), (L2_APPROVAL, L2_ATTESTATION)):
    try:
        validate_l1_authority(approval=approval, attestation=attestation, checked_at=stamp)
    except ConsumedL1ApprovalError:
        pass
    else:
        raise AssertionError('consumed approval reusable')
try:
    discover_current_resource('HEAD')
except ValueError:
    pass
else:
    raise AssertionError('mutable source accepted')
result = TeamStrengthL1ObservationService(clock=lambda: stamp).run(
    L1OperatorRequest(42, 'a'*40, 'old-approval', ATTESTATION, '0'*64), None)
assert result['reason'] == 'AUTHORITY_INVALID' and not result['private_attempt_consumed']
assert result['fpl_requests'] == result['odds_requests'] == 0
result = TeamStrengthL1ObservationService(clock=lambda: stamp).run(
    L1OperatorRequest(42, 'a'*40, L1_APPROVAL, L1_ATTESTATION, '0'*64), None)
assert result['reason'] == 'AUTHORITY_CONSUMED' and result['fresh_live_authorization_required']
assert result['fpl_requests'] == result['odds_requests'] == 0
result = TeamStrengthL1ObservationService(clock=lambda: stamp).run(
    L1OperatorRequest(42, 'a'*40, APPROVAL, ATTESTATION, '0'*64), None)
assert result['reason'] == 'PUBLIC_READINESS_INVALID' and not result['private_attempt_consumed']
assert result['fpl_requests'] == result['odds_requests'] == 0
diagnostic = safe_comparison_failure(ComparisonTrace().failure(
    ComparisonStage.SEAL_COMPARISON, ComparisonReason.COMPARISON_SEAL_FAILED, ValueError('private')))
assert diagnostic['stage'] == 'SEAL_COMPARISON' and 'private' not in json.dumps(diagnostic)
print(json.dumps({'installed_import': True, 'l3_authority_valid': True, 'l1_l2_authorities_consumed': True, 'closed_diagnostic': True, 'mutable_source_rejected': True,
    'wrong_purpose_blocked_before_providers': True, 'provider_calls': 0, 'production_activation': False}))
"""


def verify() -> dict[str, object]:
    uv = shutil.which("uv")
    if uv is None:
        raise VerificationError("uv unavailable")
    with tempfile.TemporaryDirectory(prefix="dmf-l1-wheel-") as temporary:
        root = Path(temporary).resolve()
        if root.is_relative_to(REPOSITORY_ROOT):
            raise VerificationError("installed-wheel check must be outside source tree")
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
            step="install wheel",
        )
        result = _json_object(
            _run(
                [str(python), "-c", SMOKE],
                cwd=root,
                environment=environment,
                step="L1 installed authority smoke",
            ).stdout,
        )
        script = root / "operator.py"
        shutil.copyfile(REPOSITORY_ROOT / "scripts/run_team_strength_l1.py", script)
        _run(
            [str(python), str(script), "--help"],
            cwd=root,
            environment=environment,
            step="installed operator help",
        )
        return {"status": "PASS", "operator_help": True, **result}


if __name__ == "__main__":
    print(json.dumps(verify(), sort_keys=True))
