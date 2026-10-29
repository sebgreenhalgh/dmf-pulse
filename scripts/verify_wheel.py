"""Build and verify the DMF Pulse wheel from a clean environment outside the repository."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from collections.abc import Sequence
from pathlib import Path

from packaging.markers import Marker

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = REPOSITORY_ROOT / "evidence" / "tickets" / "DAT-003" / "package_report.json"
RUNTIME_MANIFEST = REPOSITORY_ROOT / "specs" / "manifests" / "runtime_lock_manifest.json"
BUNDLED_ZONEINFO = "dmf_pulse/_data/zoneinfo/Europe/London"
BUNDLED_ZONEINFO_SHA256 = "676541f0b8ad457c744c093f807589adcad909e3fd03f901787d08786eedbd33"
_ANSI_CONTROL = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_DASHBOARD_PARSER_PROBE = """
import json
from dmf_pulse.cli.app import app
from typer.main import get_command

dashboard = get_command(app).commands.get('dashboard')
if dashboard is None:
    raise RuntimeError('dashboard command missing')
for option, expected in (('--demo', True), ('--no-demo', False)):
    with dashboard.make_context('dashboard', [option]) as context:
        if context.params.get('demo') is not expected:
            raise RuntimeError('dashboard demo option does not parse as a boolean')
try:
    dashboard.make_context('dashboard', ['--dmf-invalid-wheel-probe-option'])
except Exception as error:
    if type(error).__name__ != 'NoSuchOption':
        raise
else:
    raise RuntimeError('dashboard parser accepted an unknown option')
print(json.dumps({'demo': True, 'no_demo': False, 'unknown_option_rejected': True}))
"""


class VerificationError(Exception):
    """A safe package verification failure."""


def _require_dashboard_demo_help(output: str) -> None:
    # Rich can style the first hyphen separately under GitHub Actions. Match
    # the complete option after removing terminal controls, never a prefix.
    plain = _ANSI_CONTROL.sub("", output)
    if re.search(r"(?<![\w-])--demo(?![\w-])", plain) is None:
        raise VerificationError("installed dashboard command is missing its demo option")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _archive_accel003_parity(
    controls: Path,
    wheel_sha256: str,
    *,
    repository_root: Path,
    acceptance: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    """Preserve bounded raw comparisons even when the installed child fails."""
    if re.fullmatch(r"[0-9a-f]{64}", wheel_sha256) is None:
        raise VerificationError("installed ACCEL003 archive wheel identity is invalid")
    limit = 2 * 1024 * 1024
    directory = repository_root / "review_pack" / f"accel003-installed-parity-{wheel_sha256[:16]}"
    artifacts: list[dict[str, object]] = []
    bodies: dict[int, bytes] = {}
    try:
        for horizon in (1, 3):
            source = controls / f"parity-{horizon}.json"
            if not source.exists():
                # A forced process timeout can prevent the probe's own finally
                # from moving its completed comparisons out of the owned run.
                candidates = []
                for run in controls.glob("owned-runs-*"):
                    nested = run / source.name
                    if nested.exists():
                        candidates.append(nested)
                        if len(candidates) > 1:
                            raise VerificationError("installed ACCEL003 parity source is ambiguous")
                if not candidates:
                    continue
                source = candidates[0]
            if (
                source.is_symlink()
                or not source.is_file()
                or not source.resolve().is_relative_to(controls.resolve())
            ):
                raise VerificationError("installed ACCEL003 parity source is not a regular file")
            with source.open("rb") as handle:
                body = handle.read(limit + 1)
            if not body or len(body) > limit:
                raise VerificationError(
                    "installed ACCEL003 parity inventory exceeds its size bound"
                )
            digest = hashlib.sha256(body).hexdigest()
            directory.mkdir(parents=True, exist_ok=True)
            if not directory.resolve().is_relative_to(repository_root.resolve()):
                raise VerificationError("installed ACCEL003 parity archive escaped repository")
            destination = directory / f"parity-{horizon}-{digest}.json"
            try:
                with destination.open("xb") as handle:
                    handle.write(body)
            except FileExistsError:
                if destination.is_symlink() or not destination.is_file():
                    raise VerificationError(
                        "installed ACCEL003 parity archive is not a regular file"
                    ) from None
                with destination.open("rb") as handle:
                    retained = handle.read(limit + 1)
                if retained != body:
                    raise VerificationError(
                        "installed ACCEL003 immutable parity archive conflicts"
                    ) from None
            artifacts.append(
                {
                    "horizon": horizon,
                    "path": destination.relative_to(repository_root).as_posix(),
                    "bytes": len(body),
                    "sha256": digest,
                    "wheel_sha256": wheel_sha256,
                }
            )
            bodies[horizon] = body
        if acceptance is not None:
            if set(bodies) != {1, 3}:
                raise VerificationError("installed ACCEL003 successful parity inventory is missing")
            cases = acceptance["cases"]
            if not isinstance(cases, list):
                raise VerificationError("installed ACCEL003 parity case inventory is invalid")
            for case in cases:
                inventory = json.loads(bodies[case["horizon"]])
                if (
                    not isinstance(inventory, dict)
                    or set(inventory)
                    != {"checked_fields", "numeric_fields", "excluded", "mismatches"}
                    or inventory["mismatches"] != []
                    or not isinstance(inventory["excluded"], list)
                    or type(inventory["checked_fields"]) is not int
                    or type(inventory["numeric_fields"]) is not int
                    or not 0 < inventory["numeric_fields"] <= inventory["checked_fields"]
                    or inventory["checked_fields"] != case["checked_fields"]
                    or inventory["numeric_fields"] != case["numeric_fields"]
                    or len(inventory["excluded"]) != case["custody_exclusion_count"]
                    or hashlib.sha256(bodies[case["horizon"]]).hexdigest()
                    != case["custody_inventory_sha256"]
                ):
                    raise VerificationError(
                        "installed ACCEL003 retained parity inventory is inconsistent"
                    )
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, RecursionError) as exc:
        raise VerificationError("installed ACCEL003 parity archival failed") from exc
    return artifacts


def _require_accel003_acceptance(value: object) -> dict[str, object]:
    """Reject partial or synthetic-unit-only claims from the installed process probe."""
    if not isinstance(value, dict) or any(
        value.get(key) != expected
        for key, expected in {
            "status": "PASS",
            "classification": "OWNED_SYNTHETIC_ENGINEERING_ONLY",
            "horizons": [1, 3],
            "cleanup": "CONFIRMED",
        }.items()
    ):
        raise VerificationError("installed ACCEL003 process acceptance is incomplete")
    if (
        value.get("all_numeric_projection_and_decision_fields_exact") is not True
        or value.get("no_full_semantic_hash_parity_claim") is not True
        or type(value.get("external_provider_requests")) is not int
        or value["external_provider_requests"] != 0
    ):
        raise VerificationError("installed ACCEL003 numerical/network claims failed")
    cases = value.get("cases")
    if not isinstance(cases, list) or [
        row.get("horizon") for row in cases if isinstance(row, dict)
    ] != [1, 3]:
        raise VerificationError("installed ACCEL003 horizons are incomplete")
    for case in cases:
        if (
            not isinstance(case, dict)
            or any(
                case.get(key) is not True
                for key in (
                    "default_process_worker",
                    "same_run_browser_decision_equal",
                    "all_numeric_projection_and_decision_fields_exact",
                )
            )
            or (case.get("catalogue"), case.get("projected"), case.get("blocked")) != (121, 120, 1)
            or case.get("player_gameweek_details_equal") != 120 * case["horizon"]
            or case.get("owned_transport_attempts") != {"FPL": 8, "ODDS": 1, "OPENFOOTBALL": 4}
            or case.get("external_provider_requests") != 0
            or case.get("cleanup") != "CONFIRMED"
            or case.get("reference_service") != "DEFAULT_DEMO_PROCESS_ACCEPTED_CLI_SYNTHETIC"
        ):
            raise VerificationError("installed ACCEL003 current worker contract failed")
    cancellations = value.get("cancellations")
    if not isinstance(cancellations, list) or [
        row.get("phase") for row in cancellations if isinstance(row, dict)
    ] != ["acquisition", "modelling"]:
        raise VerificationError("installed ACCEL003 process cancellation proof missing")
    for case in cancellations:
        if (
            not isinstance(case, dict)
            or any(
                case.get(key) is not True
                for key in (
                    "pause_marker_observed",
                    "terminated_and_handle_closed",
                    "result_withheld",
                    "reservation_still_spent",
                )
            )
            or case.get("owned_attempts_before_cancellation")
            != (1 if case["phase"] == "acquisition" else 13)
        ):
            raise VerificationError("installed ACCEL003 process cancellation failed")
    cli = value.get("installed_cli")
    if (
        not isinstance(cli, dict)
        or cli.get("cohort_freeze_labels_score") != "PASS"
        or cli.get("report_exact_service_equality") is not True
        or cli.get("player_evidence_exact_service_equality") is not True
        or cli.get("real_cohort_size") != 0
    ):
        raise VerificationError("installed ACCEL003 operational CLI acceptance failed")
    guards = value.get("network_guards")
    if (
        not isinstance(guards, list)
        or not guards
        or any(
            not isinstance(row, dict)
            or row.get("unexpected_denials") != 0
            or row.get("self_test_denials") != 1
            for row in guards
        )
    ):
        raise VerificationError("installed ACCEL003 network guard proof failed")
    for case in [*cases, *cancellations]:
        if not any(
            row.get("pid") == case.get("actual_spawn_child_pid")
            and row.get("role") == "__mp_main__"
            for row in guards
        ):
            raise VerificationError("installed ACCEL003 child network guard missing")
    for case in cases:
        if not any(
            row.get("pid") == case.get("reference_spawn_child_pid")
            and row.get("role") == "__mp_main__"
            for row in guards
        ):
            raise VerificationError("installed ACCEL003 reference child network guard missing")
    return value


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    step: str,
    timeout_seconds: float = 180.0,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            list(command),
            cwd=cwd,
            env=environment,
            check=False,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise VerificationError(f"{step} timed out") from exc
    except OSError as exc:
        raise VerificationError(f"{step} could not start") from exc
    if result.returncode != 0:
        raise VerificationError(f"{step} failed with exit code {result.returncode}")
    return result


def _environment_python(environment_root: Path) -> Path:
    if os.name == "nt":
        return environment_root / "Scripts" / "python.exe"
    return environment_root / "bin" / "python"


def _environment_dmf(environment_python: Path) -> tuple[str, ...]:
    """Invoke the installed console entry point without an unsigned launcher shim.

    Windows application-control policies can reject the distlib ``dmf.exe``
    generated in a disposable directory. Loading the wheel's installed entry
    point through the clean environment's trusted Python executable exercises
    the same metadata and callable while remaining portable to POSIX.
    """

    runner = (
        "import importlib.metadata as m,sys;"
        "e=[e for e in m.distribution('dmf-pulse').entry_points "
        "if e.group=='console_scripts' and e.name=='dmf'];"
        "ep=e[0] if len(e)==1 else sys.exit(125);"
        "sys.exit(ep.load()()) "
        "if ep.value=='dmf_pulse.cli.app:main' else sys.exit(125)"
    )
    return (str(environment_python), "-I", "-c", runner)


def _sanitized_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("VIRTUAL_ENV", None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["UV_OFFLINE"] = "1"
    return environment


def _project_identity() -> tuple[str, str]:
    pyproject = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject.get("project")
    if not isinstance(project, dict) or not isinstance(project.get("name"), str):
        raise VerificationError("pyproject project identity is invalid")
    name = project["name"]
    tool = pyproject.get("tool")
    hatch = tool.get("hatch") if isinstance(tool, dict) else None
    version_config = hatch.get("version") if isinstance(hatch, dict) else None
    version_path = version_config.get("path") if isinstance(version_config, dict) else None
    if not isinstance(version_path, str):
        raise VerificationError("canonical dynamic version path is unavailable")
    try:
        version_source = (REPOSITORY_ROOT / version_path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise VerificationError("canonical version source is unavailable") from exc
    matches = re.findall(r'^__version__\s*=\s*"([^"]+)"', version_source, re.MULTILINE)
    if len(matches) != 1:
        raise VerificationError("canonical version source is ambiguous")
    version = matches[0]
    return name, version


def _dependency_request(item: object) -> tuple[str, frozenset[str]] | None:
    if not isinstance(item, dict) or not isinstance(item.get("name"), str):
        return None
    raw_extras = item.get("extra", item.get("extras", []))
    if not isinstance(raw_extras, list) or not all(isinstance(extra, str) for extra in raw_extras):
        raise VerificationError("uv.lock dependency extras are malformed")
    return item["name"], frozenset(raw_extras)


def _resolve_runtime_graph(
    packages: dict[str, dict[str, object]], roots: list[object]
) -> tuple[dict[str, list[dict[str, object]]], dict[str, set[str]]]:
    selected_dependencies: dict[str, list[dict[str, object]]] = {}
    activated_extras: dict[str, set[str]] = {}
    pending = [request for item in roots if (request := _dependency_request(item))]
    while pending:
        name, extras = pending.pop()
        prior_extras = activated_extras.setdefault(name, set())
        if name in selected_dependencies and extras.issubset(prior_extras):
            continue
        prior_extras.update(extras)
        package = packages.get(name)
        if not isinstance(package, dict):
            raise VerificationError("uv.lock runtime graph is incomplete")
        dependencies = package.get("dependencies", [])
        optional = package.get("optional-dependencies", {})
        if not isinstance(dependencies, list) or not isinstance(optional, dict):
            raise VerificationError("uv.lock runtime dependency graph is malformed")
        expanded = list(dependencies)
        for extra in sorted(prior_extras):
            extra_dependencies = optional.get(extra)
            if not isinstance(extra_dependencies, list):
                raise VerificationError("uv.lock runtime dependency extra is missing")
            expanded.extend(extra_dependencies)
        selected_dependencies[name] = expanded
        pending.extend(request for item in expanded if (request := _dependency_request(item)))
    return selected_dependencies, activated_extras


def _runtime_manifest_from_lock() -> dict[str, object]:
    lock = tomllib.loads((REPOSITORY_ROOT / "uv.lock").read_text(encoding="utf-8"))
    raw_packages = lock.get("package")
    if not isinstance(raw_packages, list):
        raise VerificationError("uv.lock package table is missing")
    packages: dict[str, dict[str, object]] = {
        item["name"]: item
        for item in raw_packages
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    project = packages.get("dmf-pulse")
    if not isinstance(project, dict) or not isinstance(project.get("dependencies"), list):
        raise VerificationError("uv.lock project runtime dependencies are missing")
    roots = project["dependencies"]
    selected_dependencies, activated_extras = _resolve_runtime_graph(packages, roots)
    selected = set(selected_dependencies)
    records = []
    for name in sorted(selected):
        package = packages[name]
        version = package.get("version")
        dependencies = selected_dependencies[name]
        if not isinstance(version, str):
            raise VerificationError("uv.lock runtime package metadata is malformed")
        records.append(
            {
                "activated_extras": sorted(activated_extras[name]),
                "dependencies": sorted(
                    [
                        {"marker": item.get("marker"), "name": item["name"]}
                        for item in dependencies
                        if isinstance(item, dict)
                        and isinstance(item.get("name"), str)
                        and item["name"] in selected
                    ],
                    key=lambda item: (item["name"], str(item["marker"])),
                ),
                "name": name,
                "version": version,
            }
        )
    return {
        "lock_sha256": _sha256(REPOSITORY_ROOT / "uv.lock"),
        "manifest_version": "1.1",
        "packages": records,
        "project": "dmf-pulse",
        "roots": sorted(item["name"] for item in roots if isinstance(item, dict)),
    }


def _expected_runtime_distributions() -> dict[str, str]:
    try:
        manifest = json.loads(RUNTIME_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VerificationError("locked runtime manifest is unavailable or invalid") from exc
    if manifest != _runtime_manifest_from_lock():
        raise VerificationError("locked runtime manifest does not exactly match uv.lock")
    raw_packages = manifest.get("packages")
    roots = manifest.get("roots")
    if not isinstance(raw_packages, list) or not isinstance(roots, list):
        raise VerificationError("locked runtime manifest shape is invalid")
    packages = {
        item.get("name"): item
        for item in raw_packages
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    selected: set[str] = set()
    pending = list(roots)
    while pending:
        name = pending.pop()
        if not isinstance(name, str) or name in selected:
            continue
        package = packages.get(name)
        if not isinstance(package, dict) or not isinstance(package.get("version"), str):
            raise VerificationError("locked runtime package graph is incomplete")
        selected.add(name)
        dependencies = package.get("dependencies", [])
        if not isinstance(dependencies, list):
            raise VerificationError("locked runtime dependency graph is malformed")
        for dependency in dependencies:
            if not isinstance(dependency, dict) or not isinstance(dependency.get("name"), str):
                raise VerificationError("locked runtime dependency is malformed")
            marker = dependency.get("marker")
            if marker is None or (isinstance(marker, str) and Marker(marker).evaluate()):
                pending.append(dependency["name"])
    return {name: str(packages[name]["version"]) for name in sorted(selected)}


def verify_wheel(*, report_path: Path = DEFAULT_REPORT) -> dict[str, object]:
    """Perform the complete build/content/clean-install/CLI verification."""

    uv = shutil.which("uv")
    if uv is None:
        raise VerificationError("uv is unavailable")
    uv_version = _run([uv, "--version"], cwd=REPOSITORY_ROOT, step="uv version").stdout.strip()
    project_name, project_version = _project_identity()
    normalized_distribution = project_name.replace("-", "_")
    expected_runtime = _expected_runtime_distributions()
    offline_environment = _sanitized_environment()
    temporary_path: Path | None = None
    report: dict[str, object]
    with tempfile.TemporaryDirectory(prefix="dmf-wheel-") as temporary:
        temporary_path = Path(temporary).resolve()
        try:
            temporary_path.relative_to(REPOSITORY_ROOT.resolve())
        except ValueError:
            pass
        else:
            raise VerificationError("temporary verification directory is inside the repository")

        distribution_directory = temporary_path / "distributions"
        distribution_directory.mkdir()
        _run(
            [uv, "build", "--out-dir", str(distribution_directory)],
            cwd=REPOSITORY_ROOT,
            step="distribution build",
            environment=offline_environment,
        )
        distributions = sorted(
            distribution_directory.glob(f"{normalized_distribution}-{project_version}*")
        )
        if [path.name for path in distributions] != [
            f"{normalized_distribution}-{project_version}-py3-none-any.whl",
            f"{normalized_distribution}-{project_version}.tar.gz",
        ]:
            raise VerificationError("uv build did not produce the exact sdist and wheel pair")
        wheel = distributions[0]
        try:
            with zipfile.ZipFile(wheel) as archive:
                wheel_names = archive.namelist()
                bundled_zoneinfo_sha256 = hashlib.sha256(archive.read(BUNDLED_ZONEINFO)).hexdigest()
        except zipfile.BadZipFile as exc:
            raise VerificationError("built wheel is malformed") from exc
        except KeyError as exc:
            raise VerificationError(
                "built wheel does not contain the Windows zoneinfo fallback"
            ) from exc
        if "dmf_pulse/py.typed" not in wheel_names:
            raise VerificationError("built wheel does not contain dmf_pulse/py.typed")
        if bundled_zoneinfo_sha256 != BUNDLED_ZONEINFO_SHA256:
            raise VerificationError("built wheel zoneinfo fallback hash is invalid")

        environment_root = temporary_path / "clean-environment"
        _run(
            [uv, "venv", "--python", "3.13", "--no-project", str(environment_root)],
            cwd=temporary_path,
            step="clean environment creation",
            environment=offline_environment,
        )
        environment_python = _environment_python(environment_root)
        environment_dmf = _environment_dmf(environment_python)
        dependency_environment = dict(offline_environment)
        dependency_environment["VIRTUAL_ENV"] = str(environment_root)
        _run(
            [
                uv,
                "sync",
                "--frozen",
                "--offline",
                "--no-dev",
                "--no-install-project",
                "--active",
            ],
            cwd=REPOSITORY_ROOT,
            step="locked runtime dependency installation",
            environment=dependency_environment,
        )
        _run(
            [
                uv,
                "pip",
                "install",
                "--offline",
                "--no-deps",
                "--python",
                str(environment_python),
                str(wheel),
            ],
            cwd=temporary_path,
            step="clean wheel installation",
            environment=offline_environment,
        )
        clean_environment = offline_environment
        version_result = _run(
            [*environment_dmf, "--version"],
            cwd=temporary_path,
            step="installed dmf version",
            environment=clean_environment,
        )
        if version_result.stdout.strip() != f"dmf {project_version}":
            raise VerificationError("installed dmf version output is not exact")
        doctor_result = _run(
            [*environment_dmf, "doctor", "--json"],
            cwd=temporary_path,
            step="installed dmf doctor",
            environment=clean_environment,
        )
        try:
            doctor = json.loads(doctor_result.stdout)
        except json.JSONDecodeError as exc:
            raise VerificationError("installed dmf doctor did not emit JSON") from exc
        if not isinstance(doctor, dict) or doctor.get("status") != "HEALTHY":
            raise VerificationError("installed dmf doctor was not healthy")

        rules_result = _run(
            [
                *environment_dmf,
                "rules",
                "validate",
                str(REPOSITORY_ROOT / "fixtures/rules/RUL-002/synthetic_complete"),
                "--json",
            ],
            cwd=temporary_path,
            step="installed rules validation",
            environment=clean_environment,
        )
        try:
            rules_report = json.loads(rules_result.stdout)
        except json.JSONDecodeError as exc:
            raise VerificationError("installed rules command did not emit JSON") from exc
        if rules_report.get("ruleset_id") != "fpl-synthetic-2099-2100":
            raise VerificationError("installed rules command did not validate the fixture")

        database_url = clean_environment.get("DMF_TEST_DATABASE_URL")
        if not database_url:
            raise VerificationError("DMF_TEST_DATABASE_URL is required for wheel verification")
        clean_environment["DMF_ENVIRONMENT"] = "TEST"
        data_model_root = REPOSITORY_ROOT / "fixtures/data_model/DAT-003"
        database_doctor_result = _run(
            [*environment_dmf, "data-model", "doctor", "--json"],
            cwd=temporary_path,
            step="installed database doctor",
            environment=clean_environment,
        )
        schema_manifest_result = _run(
            [*environment_dmf, "data-model", "schema-manifest", "--json"],
            cwd=temporary_path,
            step="installed schema manifest",
            environment=clean_environment,
        )
        demo_result = _run(
            [
                *environment_dmf,
                "data-model",
                "demo",
                "--fixture",
                str(data_model_root / "demo.json"),
                "--json",
            ],
            cwd=temporary_path,
            step="installed data-model demo",
            environment=clean_environment,
        )
        as_of_result = _run(
            [
                *environment_dmf,
                "data-model",
                "as-of",
                "--fixture",
                str(data_model_root / "as_of_queries.json"),
                "--json",
            ],
            cwd=temporary_path,
            step="installed data-model as-of",
            environment=clean_environment,
        )
        try:
            database_doctor = json.loads(database_doctor_result.stdout)
            schema_manifest = json.loads(schema_manifest_result.stdout)
            demo = json.loads(demo_result.stdout)
            as_of = json.loads(as_of_result.stdout)
        except json.JSONDecodeError as exc:
            raise VerificationError("installed data-model command did not emit JSON") from exc
        if database_doctor.get("status") != "HEALTHY":
            raise VerificationError("installed database doctor was not healthy")
        expected_schema = json.loads((data_model_root / "expected_schema.json").read_text("utf-8"))
        capabilities = database_doctor.get("capabilities")
        if not isinstance(capabilities, dict) or set(capabilities) != set(
            expected_schema["required_capabilities"]
        ) | {"player_research_custody", "canonical_refresh_control"}:
            raise VerificationError("installed database capabilities differ from contract")
        if not all(value is True for value in capabilities.values()):
            raise VerificationError("installed database capability probe failed")
        if schema_manifest.get("schema_sha256") != database_doctor.get("schema_sha256"):
            raise VerificationError("installed schema manifest differs from database doctor")
        if not all(item.get("passed") is True for item in demo.get("assertions", [])):
            raise VerificationError("installed data-model demo assertions failed")
        if not all(item.get("passed") is True for item in as_of.get("assertions", [])):
            raise VerificationError("installed data-model as-of assertions failed")
        installed_database_output = (
            database_doctor_result.stdout
            + schema_manifest_result.stdout
            + demo_result.stdout
            + as_of_result.stdout
        )
        if any(value in installed_database_output for value in ("changeme", "dmf_test_password")):
            raise VerificationError("installed data-model output exposed a database secret")

        zoneinfo_result = _run(
            [
                str(environment_python),
                "-c",
                (
                    "import pathlib,sys,zoneinfo;"
                    "zoneinfo.reset_tzpath(());zoneinfo.ZoneInfo.clear_cache();"
                    "import dmf_pulse.config.models as m;"
                    "m.TZPATH=();sys.base_prefix=str(pathlib.Path.cwd()/'no-system-zoneinfo');"
                    "c=m.AppConfig(environment=m.EnvironmentName.TEST,artifact_root=pathlib.Path('artifacts'));"
                    "assert c.display_timezone=='Europe/London';print('ZONEINFO_OK')"
                ),
            ],
            cwd=temporary_path,
            step="installed bundled zoneinfo fallback",
            environment=clean_environment,
        )
        if zoneinfo_result.stdout.strip() != "ZONEINFO_OK":
            raise VerificationError("installed bundled zoneinfo fallback did not validate")

        module_result = _run(
            [
                str(environment_python),
                "-c",
                "import dmf_pulse; print(dmf_pulse.__file__)",
            ],
            cwd=temporary_path,
            step="installed module location",
            environment=clean_environment,
        )
        installed_module = Path(module_result.stdout.strip()).resolve()
        try:
            installed_module.relative_to(environment_root.resolve())
        except ValueError as exc:
            raise VerificationError(
                "dmf_pulse was not imported from the clean environment"
            ) from exc
        try:
            installed_module.relative_to(REPOSITORY_ROOT.resolve())
        except ValueError:
            pass
        else:
            raise VerificationError("dmf_pulse was imported from the repository source tree")

        # Copy the acceptance driver outside the checkout and import only from
        # the clean wheel environment. No tests or editable source are available.
        desk_probe = temporary_path / "accel002_wheel_probe.py"
        desk_help = _run(
            [*environment_dmf, "dashboard", "--help"],
            cwd=temporary_path,
            step="installed dashboard public command",
            environment=clean_environment,
        )
        _require_dashboard_demo_help(desk_help.stdout)
        _run(
            [*environment_dmf, "dashboard", "--demo", "--help"],
            cwd=temporary_path,
            step="installed dashboard demo public command",
            environment=clean_environment,
        )
        # make_context parses the real installed command without invoking its
        # server callback. Help is eager, so independently check boolean values
        # and unknown-option rejection rather than inferring them from help.
        desk_parser_result = _run(
            [str(environment_python), "-I", "-c", _DASHBOARD_PARSER_PROBE],
            cwd=temporary_path,
            step="installed dashboard option parser",
            environment=clean_environment,
        )
        try:
            desk_parser = json.loads(desk_parser_result.stdout)
        except json.JSONDecodeError as exc:
            raise VerificationError("installed dashboard parser did not emit safe JSON") from exc
        if desk_parser != {"demo": True, "no_demo": False, "unknown_option_rejected": True}:
            raise VerificationError("installed dashboard option parser failed")
        shutil.copyfile(REPOSITORY_ROOT / "scripts/accel002_wheel_probe.py", desk_probe)
        desk_result = _run(
            [str(environment_python), "-I", str(desk_probe)],
            cwd=temporary_path,
            step="installed Seb's Desk real-stack synthetic acceptance",
            timeout_seconds=900,
            environment=clean_environment,
        )
        try:
            desk_acceptance = json.loads(desk_result.stdout)
        except json.JSONDecodeError as exc:
            raise VerificationError("installed Seb's Desk did not emit safe JSON") from exc
        if desk_acceptance.get("status") != "PASS":
            raise VerificationError("installed Seb's Desk acceptance failed")

        current_probe = temporary_path / "accel003_wheel_probe.py"
        shutil.copyfile(REPOSITORY_ROOT / "scripts/accel003_wheel_probe.py", current_probe)
        current_controls = temporary_path / "accel003-owned-controls"
        current_acceptance = None
        try:
            current_result = _run(
                [
                    str(environment_python),
                    "-I",
                    str(current_probe),
                    "--control-root",
                    str(current_controls),
                ],
                cwd=temporary_path,
                step="installed ACCEL003 paired ASGI current process, numerical parity and operational CLI",
                timeout_seconds=900,
                environment=clean_environment,
            )
            current_acceptance = _require_accel003_acceptance(json.loads(current_result.stdout))
        except json.JSONDecodeError as exc:
            raise VerificationError("installed ACCEL003 probe did not emit safe JSON") from exc
        finally:
            current_parity_artifacts = _archive_accel003_parity(
                current_controls,
                _sha256(wheel),
                repository_root=REPOSITORY_ROOT,
                acceptance=current_acceptance,
            )

        distributions_result = _run(
            [
                str(environment_python),
                "-c",
                (
                    "import importlib.metadata,json;"
                    "print(json.dumps(sorted((d.metadata['Name'].lower().replace('_','-'),d.version) "
                    "for d in importlib.metadata.distributions())))"
                ),
            ],
            cwd=temporary_path,
            step="installed runtime distribution inventory",
            environment=clean_environment,
        )
        try:
            installed_runtime = dict(json.loads(distributions_result.stdout))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise VerificationError("installed runtime distribution inventory is invalid") from exc
        expected_installed = {project_name: project_version, **expected_runtime}
        if installed_runtime != expected_installed:
            raise VerificationError(
                "installed runtime distributions do not match the frozen lock graph"
            )

        report = {
            "clean_environment_outside_repository": True,
            "cleaned_up": False,
            "network_fetch_disabled": True,
            "doctor_nvidia_status": doctor.get("nvidia", {}).get("status")
            if isinstance(doctor.get("nvidia"), dict)
            else None,
            "doctor_status": doctor.get("status"),
            "installed_module_path": "<temporary-environment>/site-packages/dmf_pulse/__init__.py",
            "installed_version_output": version_result.stdout.strip(),
            "installed_runtime_distributions": [
                {"name": name, "version": version}
                for name, version in sorted(installed_runtime.items())
            ],
            "installed_data_model": {
                "as_of_assertions": len(as_of["assertions"]),
                "database_status": database_doctor["status"],
                "demo_assertions": len(demo["assertions"]),
                "schema_sha256": database_doctor["schema_sha256"],
            },
            "locked_runtime_manifest_sha256": _sha256(RUNTIME_MANIFEST),
            "installed_zoneinfo_fallback": True,
            "installed_sebs_desk": desk_acceptance,
            "installed_accel003_current_mode": current_acceptance,
            "installed_accel003_parity_artifacts": current_parity_artifacts,
            "installed_dashboard_option_parser": desk_parser,
            "platform": {
                "architecture": platform.machine(),
                "operating_system": platform.system(),
                "python": platform.python_version(),
            },
            "status": "PASS",
            "toolchain": {
                "build": importlib.metadata.version("build"),
                "build_backend": "hatchling",
                "hatchling": importlib.metadata.version("hatchling"),
            },
            "uv_version": uv_version,
            "uv_build_distributions": [
                {"bytes": path.stat().st_size, "name": path.name, "sha256": _sha256(path)}
                for path in distributions
            ],
            "wheel": {
                "bytes": wheel.stat().st_size,
                "contains_py_typed": True,
                "file_count": len(wheel_names),
                "name": wheel.name,
                "sha256": _sha256(wheel),
                "zoneinfo_fallback_sha256": bundled_zoneinfo_sha256,
            },
        }
    if temporary_path is None or temporary_path.exists():
        raise VerificationError("temporary verification directory was not cleaned up")
    report["cleaned_up"] = True
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return report


def main() -> int:
    try:
        report = verify_wheel()
    except VerificationError as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, indent=2, sort_keys=True))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
