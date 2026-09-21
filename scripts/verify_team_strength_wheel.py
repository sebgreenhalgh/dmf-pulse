"""Offline installed-wheel shadow CLI acceptance using explicit private retained input."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tarfile
import tempfile
import zipfile
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

from dmf_pulse.assurance.canonical import pretty_json

_SMOKE = r"""
import json
import socket
from pathlib import Path
import sys

def blocked(*args, **kwargs):
    raise AssertionError("installed shadow import attempted network")

socket.create_connection = blocked
socket.getaddrinfo = blocked
socket.socket.connect = blocked
socket.socket.connect_ex = blocked
socket.socket.sendto = blocked

import dmf_pulse
from dmf_pulse.evaluation.team_strength_replay import load_replay_golden
from dmf_pulse.football_events import team_strength_adapter, team_strength_model

assert Path(dmf_pulse.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
golden = load_replay_golden()
assert golden.classification == "RECONSTRUCTED"
assert golden.governed_d_plus_2.metrics.exact_log_loss < golden.baseline.exact_log_loss
print(json.dumps({"installed_import": True, "packaged_golden": golden.semantic_sha256}))
"""


def verify(corpus_root: Path) -> dict[str, object]:
    uv = shutil.which("uv")
    if uv is None:
        raise VerificationError("uv unavailable")
    wheel = _wheel()
    with zipfile.ZipFile(wheel) as archive:
        wheel_names = archive.namelist()
    with tarfile.open(REPOSITORY_ROOT / "dist/dmf_pulse-0.2.0.tar.gz") as archive:
        source_names = archive.getnames()
    for names in (wheel_names, source_names):
        if any(
            any(
                part in name
                for part in (
                    "private_openfootball",
                    "fixture_registry.json",
                    "en.1.json",
                    "team-strength-shadow/",
                )
            )
            for name in names
        ):
            raise VerificationError("distribution contains private corpus or model material")
        if not any(
            name.endswith("evaluation/resources/team_strength_golden.json") for name in names
        ):
            raise VerificationError("distribution lacks sealed aggregate golden")
    with tempfile.TemporaryDirectory(prefix="dmf-team-strength-wheel-") as temporary:
        root = Path(temporary).resolve()
        if root.is_relative_to(REPOSITORY_ROOT.resolve()):
            raise VerificationError("wheel environment must be outside source tree")
        venv = root / "venv"
        _run(
            [uv, "venv", "--python", "3.13", "--no-project", str(venv)],
            cwd=root,
            environment=_environment(),
            step="clean environment",
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
            [uv, "pip", "install", "--offline", "--no-deps", "--python", str(python), str(wheel)],
            cwd=root,
            environment=environment,
            step="wheel install",
        )
        smoke = _json_object(
            _run(
                [str(python), "-c", _SMOKE],
                cwd=root,
                environment=environment,
                step="installed import and golden",
            ).stdout
        )
        command = venv / ("Scripts/dmf.exe" if os.name == "nt" else "bin/dmf")
        summary = _json_object(
            _run(
                [
                    str(command),
                    "events",
                    "team-strength",
                    "fit-reconstructed",
                    "--corpus-root",
                    str(corpus_root.resolve()),
                    "--private-artifact-root",
                    str(root / "private-artifacts"),
                ],
                cwd=root,
                environment=environment,
                step="installed real-corpus shadow CLI",
            ).stdout
        )
        if (
            summary["eligible_matches"] != 6080
            or summary["dataset_mode"] != "RECONSTRUCTED"
            or summary["production_active"] is not False
            or summary["current_live_refit_claimed"] is not False
        ):
            raise VerificationError("installed CLI summary violated fixed shadow contract")
        return {
            "status": "PASS",
            "clean_environment_outside_repository": True,
            "locked_runtime_only": True,
            "offline_installation": True,
            "wheel": wheel.name,
            "private_distribution_material": False,
            "installed_import": smoke["installed_import"],
            "packaged_golden": smoke["packaged_golden"],
            "command": "dmf events team-strength fit-reconstructed",
            "eligible_matches": summary["eligible_matches"],
            "model_semantic_sha256": summary["model_semantic_sha256"],
            "dataset_mode": summary["dataset_mode"],
            "production_active": False,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    report = verify(args.corpus_root)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(pretty_json(report), encoding="utf-8", newline="\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
