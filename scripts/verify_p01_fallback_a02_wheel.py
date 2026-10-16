"""Offline A02 contracts/CLI replay from a clean wheel outside the repository."""

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
import hashlib, json, socket, sys
from pathlib import Path
def denied(*args, **kwargs):
    raise AssertionError('A02 wheel must remain offline')
socket.create_connection = socket.getaddrinfo = socket.socket.connect = denied
socket.socket.connect_ex = socket.socket.sendto = denied
import dmf_pulse
from typer.testing import CliRunner
from dmf_pulse.cli.app import app
from dmf_pulse.evaluation.p01_fallback_context import load_context, require_openligadb_rights
from dmf_pulse.evaluation.p01_fallback import fallback_scorecard, _score_admitted
from dmf_pulse.evaluation.p01_frozen_view import _read_pinned_representation
from dmf_pulse.evaluation.p01_fallback_store import load_fallback, persist_fallback
assert Path(dmf_pulse.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
context = load_context()
assert context.semantic_sha256 == '6bb80a9c0b17b673044be5b5c53a2eda6c4e4110ef09f7a586e87e0d8432c259'
assert require_openligadb_rights().rights_profile_id == 'openligadb_public_final_score_labels_v1'
result = CliRunner().invoke(app, ['events','team-strength','p01-fallback','context'])
assert result.exit_code == 0 and json.loads(result.stdout)['semantic_sha256'] == context.semantic_sha256
index = json.loads(Path('synthetic-index.json').read_bytes())
labels = load_fallback(Path('synthetic-outcomes.json'), expected_sha256=index['outcomes'])
score = load_fallback(Path('synthetic-score.json'), expected_sha256=index['score'])
from dmf_pulse.evaluation import team_strength_prospective as prospective
from dmf_pulse.football_events import team_strength_parameter_draws as draws
prospective.authenticate_parameter_draws = prospective._fixture_forecast = denied
prospective.freeze_public_team_forecasts = draws.joint_parameter_draws = denied
raw = Path('synthetic-forecast.json').read_bytes()
view = _read_pinned_representation(raw, expected_byte_sha256=hashlib.sha256(raw).hexdigest(),
    expected_semantic_sha256=score.context.forecast_sha256)
assert _score_admitted(view, outcomes=labels, as_of=score.metrics.scored_at).metrics.scores == score.metrics.scores
report = fallback_scorecard(score, outcomes=labels)
path = persist_fallback(report, artifact_root=Path('retained'))
assert load_fallback(path, expected_sha256=report.semantic_sha256) == report
assert len(report.score.metrics.scores) == 30
assert report.provenance == score.provenance == labels.provenance == 'PUBLIC_FALLBACK_OUTCOME_SOURCE'
assert not report.score.promotion.production_active
print(json.dumps({'status':'PASS','installed_import':True,'packaged_context_and_rights':True,
    'public_context_command':True,'typed_fallback_roundtrip':True,'full_metric_report_replay':True,
    'nongenerative_frozen_view_scoring':True,
    'fixture_count':10,'product_count':3,'provider_calls':0,'production_active':False}))
"""


def verify() -> dict[str, object]:
    sys.path.insert(0, str(REPOSITORY_ROOT))
    from tests.unit.evaluation.test_p01_fallback_a02 import labels, scored, ten_forecast

    uv = shutil.which("uv")
    if uv is None:
        raise VerificationError("uv unavailable")
    outcomes, score = labels(), scored()
    with tempfile.TemporaryDirectory(prefix="dmf-p01-a02-wheel-") as temporary:
        root = Path(temporary).resolve()
        if root.is_relative_to(REPOSITORY_ROOT):
            raise VerificationError("wheel verification must run outside the source tree")
        (root / "synthetic-outcomes.json").write_text(outcomes.model_dump_json(), encoding="utf-8")
        (root / "synthetic-score.json").write_text(score.model_dump_json(), encoding="utf-8")
        (root / "synthetic-forecast.json").write_text(
            ten_forecast().model_dump_json(), encoding="utf-8"
        )
        (root / "synthetic-index.json").write_text(
            json.dumps({"outcomes": outcomes.semantic_sha256, "score": score.semantic_sha256}),
            encoding="utf-8",
        )
        venv = root / "venv"
        _run(
            [uv, "venv", "--python", "3.13", "--no-project", str(venv)],
            cwd=root,
            environment=_environment(),
            step="clean A02 runtime environment",
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
            step="install A02 wheel",
        )
        return _json_object(
            _run(
                [str(python), "-c", SMOKE],
                cwd=root,
                environment=environment,
                step="installed A02 offline replay",
            ).stdout
        )


if __name__ == "__main__":
    print(json.dumps(verify(), sort_keys=True))
