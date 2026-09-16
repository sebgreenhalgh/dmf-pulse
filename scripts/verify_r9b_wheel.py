"""Clean installed-wheel R9B synthetic-only compiler/summary validation."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import verify_current_score_prior_wheel as wheel


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from dmf_pulse.fpl_points.current_player_shadow import compile_current_player_shadow
    from tests.unit.fpl_points.current_shadow_support import synthetic_inputs

    inputs = synthetic_inputs(root, count=20)
    expected = compile_current_player_shadow(**inputs).semantic_sha256
    payload = json.dumps({name: value.model_dump(mode="json") for name, value in inputs.items()})
    wheel._INSTALLED_SMOKE = """
import json,sys,socket
import dmf_pulse
from dmf_pulse.fpl_points.current_player_posterior import HistoricalRateResource,load_historical_rate_resource
from dmf_pulse.fpl_points.current_player_shadow import compile_current_player_shadow
from dmf_pulse.fpl_points.current_player_shadow_diagnostics import safe_shadow_summary
from dmf_pulse.fpl_points.player_prior import CurrentGwPlayerPriorBinding,CurrentGwStalePriorCarryForwardPolicy,GovernedPlayerPrior
from dmf_pulse.ingestion.fpl.current import CurrentFplInputBundle
from dmf_pulse.ingestion.fpl.current_player_history import CurrentPlayerHistoryEvidence
def blocked(*args,**kwargs):
    raise AssertionError("network forbidden in installed synthetic smoke")
socket.socket.connect=blocked
socket.create_connection=blocked
raw=json.loads(sys.stdin.read())
classes=dict(history=CurrentPlayerHistoryEvidence,current_fpl=CurrentFplInputBundle,binding=CurrentGwPlayerPriorBinding,
    policy=CurrentGwStalePriorCarryForwardPolicy,prior=GovernedPlayerPrior,historical=HistoricalRateResource)
inputs={name:cls.model_validate_json(json.dumps(raw[name])) for name,cls in classes.items()}
assert load_historical_rate_resource()==inputs["historical"]
shadow=compile_current_player_shadow(**inputs)
summary=safe_shadow_summary(shadow,inputs["history"])
assert summary["current_player_count"]==20 and not summary["persistence_performed"]
print(json.dumps(dict(status="PASS",module_path=dmf_pulse.__file__,shadow_sha256=shadow.semantic_sha256,
                     resource_sha256=load_historical_rate_resource().semantic_sha256,provider_requests=0)))
"""
    original_run = wheel._run

    def run_with_synthetic_stdin(command, *, cwd, environment, step):
        if step != "installed score-prior smoke":
            return original_run(command, cwd=cwd, environment=environment, step=step)
        result = subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            input=payload,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=120,
        )
        if result.returncode:
            raise wheel.VerificationError(
                "installed R9B synthetic smoke failed: " + result.stderr[-2000:]
            )
        if json.loads(result.stdout)["shadow_sha256"] != expected:
            raise wheel.VerificationError("installed/source synthetic posterior hashes differ")
        return result

    wheel._run = run_with_synthetic_stdin
    print(json.dumps(wheel.verify(), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
