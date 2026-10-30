"""Installed public pulse boundary with synthetic in-memory service output only."""

from __future__ import annotations

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
import json, os, socket, sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
attempts = []
def denied(*args, **kwargs):
    attempts.append(True)
    raise AssertionError('ACCEL private wheel must remain offline')
socket.create_connection = socket.getaddrinfo = socket.socket.connect = denied
socket.socket.connect_ex = socket.socket.sendto = denied
import dmf_pulse
from typer.testing import CliRunner
from dmf_pulse.cli import pulse
from dmf_pulse.cli.app import app
from dmf_pulse.private_v1.actionability import ActionabilityReceipt, DeadlineGuard, checked_report
from dmf_pulse.private_v1.errors import PrivateV1Error
from dmf_pulse.authorization_errors import AuthorizationError
from dmf_pulse.operation.console import publish_runtime
assert Path(dmf_pulse.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
now = datetime(2026, 9, 1, 12, tzinfo=UTC)
deadline = now + timedelta(hours=1)
state = {'now': now}
report = 'SYNTHETIC PRIVATE WHEEL ACTION'
receipt = DeadlineGuard(lambda: now).bind(
    deadline_at=deadline, decision_sha256='a'*64, report=report)
assert ActionabilityReceipt.model_validate_json(receipt.model_dump_json()) == receipt
class Runtime:
    def refresh(self, horizon):
        assert horizon == 1
        return SimpleNamespace(status='COMPLETE', job_id='owned-installed-publication')
    def view(self):
        result = SimpleNamespace(report=report, actionability=receipt, publication_not_before=now,
            decision=SimpleNamespace(semantic_sha256='a'*64))
        try:
            checked_report(result, clock=lambda: state['now'])
        except PrivateV1Error:
            raise AuthorizationError('REFRESH_GRANT_EXPIRED', 'EXPIRED') from None
        return SimpleNamespace(team=SimpleNamespace(report=report), gameweeks=(1,),
            dataset_mode='SYNTHETIC_CURRENT_MODE', job_id='owned-installed-publication')
    def close(self): state['closed'] = True
def enrolled(**kwargs):
    assert kwargs['entry_id'] == 42 and kwargs['authorization_id'] == 'OWNED-TEST'
    return publish_runtime(Runtime(), horizon=kwargs['horizon'], publish=kwargs['publish'])
pulse.run_enrolled_current = enrolled
args = ['pulse','--entry-id','42','--no-progress','--refresh-approval','OWNED-TEST']
valid = CliRunner().invoke(app,args)
assert valid.exit_code == 0 and report in valid.stdout, valid.output
state['now'] = deadline
expired = CliRunner().invoke(app,args)
assert expired.exit_code == 2 and expired.stdout == '', expired.output
assert report not in expired.output and 'REFRESH_GRANT_EXPIRED' in expired.stderr
assert state['closed']
assert not attempts
print(json.dumps({'status':'PASS','installed_import':True,'public_pulse_boundary':True,
    'synthetic_service_only':True,'exact_deadline_withheld':True,
    'private_provider_requests':0,'provider_network_attempts':len(attempts)}))
"""


def verify() -> dict[str, object]:
    uv = shutil.which("uv")
    if uv is None:
        raise VerificationError("uv unavailable")
    with tempfile.TemporaryDirectory(prefix="dmf-accel001-private-wheel-") as temporary:
        root = Path(temporary).resolve()
        if root.is_relative_to(REPOSITORY_ROOT):
            raise VerificationError("wheel must execute outside checkout")
        venv = root / "venv"
        _run(
            [uv, "venv", "--python", "3.13", "--no-project", str(venv)],
            cwd=root,
            environment=_environment(),
            step="clean private ACCEL environment",
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
            step="install private ACCEL wheel",
        )
        return _json_object(
            _run(
                [str(python), "-c", SMOKE],
                cwd=root,
                environment=environment,
                step="installed synthetic pulse publication",
            ).stdout
        )


if __name__ == "__main__":
    print(json.dumps(verify(), sort_keys=True))
