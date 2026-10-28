"""ACCEL synthetic public command from an installed wheel outside the checkout."""

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
attempts = []
def denied(*args, **kwargs):
    attempts.append(True)
    raise AssertionError('ACCEL wheel must remain offline')
socket.create_connection = socket.getaddrinfo = socket.socket.connect = denied
socket.socket.connect_ex = socket.socket.sendto = denied
import dmf_pulse
from typer.testing import CliRunner
from dmf_pulse.cli.app import app
from dmf_pulse.evaluation.p01_synthetic_readiness import SyntheticPipelineReceiptV1
from dmf_pulse.evaluation.p01_fallback_store import load_fallback
assert Path(dmf_pulse.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
args = json.loads(Path('args.json').read_bytes())
first = CliRunner().invoke(app, args)
assert first.exit_code == 0, first.output
strict = SyntheticPipelineReceiptV1.model_validate_json(first.stdout)
assert strict.fixture_count == 10 and strict.product_rows == 30
rows = json.loads(Path('matchday.json').read_bytes())
for row in rows: row['leagueName'] = None
Path('matchday.json').write_text(json.dumps(rows), encoding='utf-8')
second = CliRunner().invoke(app, args + ['--candidate'])
assert second.exit_code == 0, second.output
candidate = SyntheticPipelineReceiptV1.model_validate_json(second.stdout)
assert candidate.metadata_policy == 'INACTIVE_CANDIDATE_V1'
assert candidate.actual_p01_scored is False and candidate.policy_accepted is False
assert 'DESCRIPTIVE_P01_PILOT' not in second.stdout and 'home_goals' not in second.stdout
Path('synthetic-receipt.json').write_text(second.stdout, encoding='utf-8')
assert SyntheticPipelineReceiptV1.model_validate_json(Path('synthetic-receipt.json').read_bytes()) == candidate
try:
    load_fallback(Path('synthetic-receipt.json'), expected_sha256=candidate.semantic_sha256)
except ValueError:
    pass
else:
    raise AssertionError('synthetic receipt admitted by operational store')
failed = CliRunner().invoke(app, args)
assert failed.exit_code == 2 and failed.stdout == ''
assert not attempts
print(json.dumps({'status':'PASS','installed_import':True,'public_synthetic_command':True,
    'inactive_candidate':True,'legacy_strict_preserved':True,'synthetic_receipt_roundtrip':True,
    'actual_p01_scored':False,'provider_network_attempts':len(attempts)}))
"""


def verify() -> dict[str, object]:
    sys.path.insert(0, str(REPOSITORY_ROOT))
    from tests.unit.evaluation.test_p01_synthetic_readiness import command_inputs

    uv = shutil.which("uv")
    if uv is None:
        raise VerificationError("uv unavailable")
    with tempfile.TemporaryDirectory(prefix="dmf-accel001-wheel-") as temporary:
        root = Path(temporary).resolve()
        if root.is_relative_to(REPOSITORY_ROOT):
            raise VerificationError("wheel must execute outside checkout")
        args = command_inputs(root)
        (root / "args.json").write_text(json.dumps(args), encoding="utf-8")
        venv = root / "venv"
        _run(
            [uv, "venv", "--python", "3.13", "--no-project", str(venv)],
            cwd=root,
            environment=_environment(),
            step="clean ACCEL environment",
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
            step="install ACCEL wheel",
        )
        return _json_object(
            _run(
                [str(python), "-c", SMOKE],
                cwd=root,
                environment=environment,
                step="ACCEL installed synthetic command",
            ).stdout
        )


if __name__ == "__main__":
    print(json.dumps(verify(), sort_keys=True))
