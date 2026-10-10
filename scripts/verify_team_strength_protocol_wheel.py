"""Verify pre-result protocol commands from a clean external wheel installation."""

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
import json, socket, sys
from pathlib import Path
def denied(*args, **kwargs):
    raise AssertionError('protocol verification must remain offline')
socket.create_connection = socket.getaddrinfo = socket.socket.connect = denied
socket.socket.connect_ex = socket.socket.sendto = denied
import dmf_pulse
from dmf_pulse.cli.app import app
from dmf_pulse.evaluation.team_strength_protocol import PROTOCOL_SHA, initial_campaign_ledger
from dmf_pulse.private_v1.team_strength_live_authority import CURRENT_APPROVAL, CURRENT_ATTESTATION
from typer.testing import CliRunner
assert Path(dmf_pulse.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
assert CURRENT_APPROVAL is CURRENT_ATTESTATION is None
runner = CliRunner()
shown = runner.invoke(app, ['events','team-strength','protocol','show'])
assert shown.exit_code == 0, shown.stdout
protocol = json.loads(shown.stdout)
assert protocol['protocol_semantic_sha256'] == PROTOCOL_SHA
assert protocol['effective_from_cohort'] == 'P02' and not protocol['production_activation']
retained = runner.invoke(app, ['events','team-strength','protocol','retain',
    '--retained-artifact-root','retained'])
assert retained.exit_code == 0, retained.stdout
value = json.loads(retained.stdout)
assert value['ledger_sha256'] == initial_campaign_ledger().semantic_sha256
shown = runner.invoke(app, ['events','team-strength','protocol','campaign-show',
    '--ledger',value['ledger_path'],'--ledger-sha256',value['ledger_sha256']])
assert shown.exit_code == 0, shown.stdout
ledger = json.loads(shown.stdout)
assert len(ledger['events']) == 1 and ledger['events'][0]['status'] == 'FROZEN'
assert ledger['events'][0]['assignment']['cohort_class'] == 'PROSPECTIVE_PILOT_COHORT'
assert not list(Path('retained').glob('public-team-strength-prospective/*'))
print(json.dumps({'status':'PASS','installed_import':True,'protocol_authenticated':True,
    'genesis_authenticated':True,'provider_calls':0,'forecasts_created':0,
    'actual_cohorts_scored':0,'production_activation':False}))
"""


def verify() -> dict[str, object]:
    uv = shutil.which("uv")
    if uv is None:
        raise VerificationError("uv unavailable")
    with tempfile.TemporaryDirectory(prefix="dmf-protocol-wheel-") as temporary:
        root = Path(temporary).resolve()
        if root.is_relative_to(REPOSITORY_ROOT):
            raise VerificationError("verification must run outside the source tree")
        venv = root / "venv"
        _run(
            [uv, "venv", "--python", "3.13", "--no-project", str(venv)],
            cwd=root,
            environment=_environment(),
            step="clean protocol runtime",
        )
        environment = _environment(venv)
        _run(
            [uv, "sync", "--frozen", "--offline", "--no-dev", "--no-install-project", "--active"],
            cwd=REPOSITORY_ROOT,
            environment=environment,
            step="locked protocol dependencies",
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
            step="install protocol wheel",
        )
        return _json_object(
            _run(
                [str(python), "-c", SMOKE],
                cwd=root,
                environment=environment,
                step="offline installed protocol commands",
            ).stdout
        )


if __name__ == "__main__":
    print(json.dumps(verify(), sort_keys=True))
