"""Exercise public freeze/score commands from a clean external installed wheel."""

from __future__ import annotations

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

SMOKE = r"""
import json, socket, sys
from pathlib import Path
from datetime import UTC, datetime
def denied(*args, **kwargs):
    raise AssertionError('installed U smoke must remain offline')
socket.create_connection = socket.getaddrinfo = socket.socket.connect = denied
socket.socket.connect_ex = socket.socket.sendto = denied
import dmf_pulse
from dmf_pulse.cli import team_strength as commands
from dmf_pulse.cli.app import app
from dmf_pulse.evaluation.team_strength_prospective import (
    PublicForecastBuildRequestV1, freeze_public_forecast_request, PrivateProspectiveStorageDenied,
    require_public_prospective_storage)
from dmf_pulse.private_v1.team_strength_live_authority import CURRENT_APPROVAL, CURRENT_ATTESTATION
from dmf_pulse.football_events.team_strength_model import TeamStrengthModelArtifactV1
from dmf_pulse.football_events.team_strength_parameter_draws import ParameterDrawSetV1, authenticate_parameter_draws
from typer.testing import CliRunner
assert Path(dmf_pulse.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
assert CURRENT_APPROVAL is CURRENT_ATTESTATION is None
golden = json.loads(Path('windows-golden.json').read_bytes())
artifact = TeamStrengthModelArtifactV1.model_validate_json(json.dumps(golden['fit_artifact']))
stored = ParameterDrawSetV1.model_validate_json(json.dumps(golden['draw_set']))
assert authenticate_parameter_draws(artifact, stored) == stored
request = PublicForecastBuildRequestV1.model_validate_json(Path('request.json').read_bytes())
# A test-only clock holds immutable synthetic dates; the production command uses actual UTC now.
commands.freeze_public_forecast_request = lambda value: freeze_public_forecast_request(
    value, clock=lambda: request.forecast_origin)
runner = CliRunner()
result = runner.invoke(app, ['events','team-strength','prospective-freeze',
    '--request','request.json','--retained-artifact-root','retained'])
assert result.exit_code == 0, result.stdout
value = json.loads(result.stdout)
assert value['status'] == 'SHADOW_NOT_MODEL_INPUT' and value['production_active'] is False
sha = value['forecast_sha256']
forecast = Path('retained/public-team-strength-prospective') / (sha+'.json')
before = forecast.read_bytes()
class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 10, 6, tzinfo=UTC)
commands.datetime = Clock
result = runner.invoke(app, ['events','team-strength','prospective-score',
    '--forecast',str(forecast),'--forecast-sha256',sha,'--outcomes','outcome.json'])
assert result.exit_code == 0, result.stdout
scored = json.loads(result.stdout)
assert len(scored['scores']) == 3 and forecast.read_bytes() == before
try:
    require_public_prospective_storage('PRIVATE_FPL_DERIVED')
except PrivateProspectiveStorageDenied:
    pass
else:
    raise AssertionError('private storage accepted')
result = runner.invoke(app, ['events','team-strength','promotion-status'])
assert result.exit_code == 0 and not json.loads(result.stdout)['automatic_activation']
print(json.dumps({'status':'PASS','installed_import':True,'public_freeze_command':True,
    'public_score_command':True,'three_products':True,'frozen_forecast_unchanged':True,
    'private_storage_denied':True,'provider_calls':0,'production_active':False}))
"""


def verify() -> dict[str, object]:
    sys.path.insert(0, str(REPOSITORY_ROOT))
    from dmf_pulse.evaluation.team_strength_prospective import PublicForecastBuildRequestV1
    from tests.unit.evaluation.test_team_strength_prospective import frozen, outcome

    uv = shutil.which("uv")
    if uv is None:
        raise VerificationError("uv unavailable")
    value = frozen()
    request = PublicForecastBuildRequestV1(
        artifact=value.artifact,
        expected_artifact_sha256=value.artifact.semantic_sha256,
        training_dataset=value.training_dataset,
        fixture_registry=value.fixture_registry,
        public_schedule=value.public_schedule,
        draw_policy=value.draw_set.policy,
        forecast_origin=value.forecast_origin,
        fixture_ids=(value.forecasts[0].fixture.fixture_id,),
        league_baseline=value.league_baseline,
    )
    with tempfile.TemporaryDirectory(prefix="dmf-u-wheel-") as temporary:
        root = Path(temporary).resolve()
        if root.is_relative_to(REPOSITORY_ROOT):
            raise VerificationError("wheel verification must run outside the source tree")
        (root / "request.json").write_text(request.model_dump_json(), encoding="utf-8")
        (root / "outcome.json").write_text(outcome(value).model_dump_json(), encoding="utf-8")
        shutil.copyfile(
            REPOSITORY_ROOT / "evidence/tickets/CURRENT-TEAM-STRENGTH-001U/STAGE8-GOLDEN.json",
            root / "windows-golden.json",
        )
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
        return _json_object(
            _run(
                [str(python), "-c", SMOKE],
                cwd=root,
                environment=environment,
                step="installed U freeze/score smoke",
            ).stdout
        )


if __name__ == "__main__":
    print(json.dumps(verify(), sort_keys=True))
