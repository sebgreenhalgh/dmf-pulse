"""Prove both OPT-010 commands from an isolated installed wheel, offline."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _run(
    arguments: list[str], *, cwd: Path, environment: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        arguments,
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _json_output(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"installed command did not emit JSON: {result.stderr}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("installed command JSON output must be an object")
    return value


def main() -> int:
    repository = Path.cwd().resolve()
    wheels = sorted((repository / "dist").glob("*.whl"), key=lambda path: path.stat().st_mtime)
    if not wheels:
        print("no wheel found")
        return 1
    wheel = wheels[-1].resolve()
    uv = shutil.which("uv")
    if uv is None:
        print("uv executable is unavailable")
        return 1

    fixture_root = repository / "fixtures/optimisation/one_gameweek"
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.update(
        {
            "NO_PROXY": "*",
            "PIP_NO_INDEX": "1",
            "PYTHONNOUSERSITE": "1",
            "UV_OFFLINE": "1",
        }
    )

    with tempfile.TemporaryDirectory(prefix="opt010-wheel-") as directory:
        outside = Path(directory).resolve()
        venv = outside / "venv"
        create = _run(
            [uv, "venv", "--python", sys.executable, str(venv)],
            cwd=outside,
            environment=environment,
        )
        python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        install = _run(
            [uv, "pip", "install", "--offline", "--python", str(python), str(wheel)],
            cwd=outside,
            environment=environment,
        )
        probe = _run(
            [
                str(python),
                "-I",
                "-c",
                (
                    "import hashlib,json; from importlib.resources import files; "
                    "import dmf_pulse; "
                    "data=files('dmf_pulse.optimisation.resources').joinpath("
                    "'one_gameweek.yaml').read_bytes(); "
                    "print(json.dumps({'import_path':str(dmf_pulse.__file__),"
                    "'policy_sha256':hashlib.sha256(data).hexdigest()}))"
                ),
            ],
            cwd=outside,
            environment=environment,
        )
        probe_payload = _json_output(probe) if probe.returncode == 0 else {}
        expected_policy = hashlib_sha256(
            repository / "src/dmf_pulse/optimisation/resources/one_gameweek.yaml"
        )
        import_path = Path(str(probe_payload.get("import_path", repository))).resolve()
        isolated = repository not in import_path.parents and import_path != repository
        policy_ok = probe_payload.get("policy_sha256") == expected_policy

        dmf = venv / ("Scripts/dmf.exe" if os.name == "nt" else "bin/dmf")
        command = [str(dmf)]
        artifact_root = outside / "artifacts"
        success = _run(
            [
                *command,
                "optimise",
                "one-gameweek",
                "--request",
                str(fixture_root / "request.json"),
                "--gameweek-artifact",
                str(fixture_root / "stage9_gameweek_result.json"),
                "--ruleset",
                str(fixture_root / "reference_ruleset_test_only.json"),
                "--artifact-root",
                str(artifact_root),
                "--output",
                "json",
            ],
            cwd=outside,
            environment=environment,
        )
        success_payload = _json_output(success)
        artifacts = sorted(artifact_root.rglob("*.json"))
        success_ok = (
            success.returncode == 0
            and success_payload.get("status") == "SUCCESS"
            and len(artifacts) == 1
        )
        validate = _run(
            [
                *command,
                "optimise",
                "validate-plan",
                "--request",
                str(fixture_root / "request.json"),
                "--gameweek-artifact",
                str(fixture_root / "stage9_gameweek_result.json"),
                "--ruleset",
                str(fixture_root / "reference_ruleset_test_only.json"),
                "--artifact",
                str(artifacts[0]) if artifacts else str(outside / "missing.json"),
                "--output",
                "json",
            ],
            cwd=outside,
            environment=environment,
        )
        validate_payload = _json_output(validate)
        validate_ok = validate.returncode == 0 and validate_payload.get("legal") is True

    ok = (
        create.returncode == 0
        and install.returncode == 0
        and probe.returncode == 0
        and isolated
        and policy_ok
        and success_ok
        and validate_ok
    )
    report = {
        "create_exit_code": create.returncode,
        "import_path": str(import_path),
        "install_exit_code": install.returncode,
        "network_mode": "OFFLINE",
        "ok": ok,
        "one_gameweek": {
            "exit_code": success.returncode,
            "ok": success_ok,
            "status": success_payload.get("status"),
        },
        "packaged_policy_matches": policy_ok,
        "source_checkout_absent_from_import_path": isolated,
        "validate_plan": {
            "exit_code": validate.returncode,
            "legal": validate_payload.get("legal"),
            "ok": validate_ok,
        },
        "wheel": str(wheel),
    }
    output = repository / "evidence/tickets/OPT-010/wheel_report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if ok else 1


def hashlib_sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
