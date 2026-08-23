"""Structural regression tests for the sharded Linux CI architecture."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

WORKFLOW_PATH = Path(".github/workflows/ci.yml")
POSTGRES_IMAGE = (
    "postgres:18.4-bookworm@sha256:1961f96e6029a02c3812d7cb329a3b03a3ac2bb067058dec17b0f5596aca9296"
)
GCS_BRANCH_CONDITION = (
    "github.ref_name == 'stage/A8/GCS-008-goal-clean-sheet-distributions' || "
    "github.head_ref == 'stage/A8/GCS-008-goal-clean-sheet-distributions'"
)


def _workflow() -> dict[str, Any]:
    value = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _jobs() -> dict[str, dict[str, Any]]:
    jobs = _workflow()["jobs"]
    assert isinstance(jobs, dict)
    return jobs


def _step(job: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [step for step in job["steps"] if step.get("name") == name]
    assert len(matches) == 1
    return matches[0]


def _normalise(value: object) -> str:
    return " ".join(str(value).split())


def _runs(job: dict[str, Any]) -> str:
    return _normalise("\n".join(str(step["run"]) for step in job["steps"] if "run" in step))


def _assert_fragments_in_order(value: str, fragments: list[str]) -> None:
    position = -1
    for fragment in fragments:
        next_position = value.find(fragment, position + 1)
        assert next_position >= 0, fragment
        position = next_position


def _assert_postgres_contract(job: dict[str, Any]) -> None:
    postgres = job["services"]["postgres"]
    assert postgres["image"] == POSTGRES_IMAGE
    assert postgres["env"] == {
        "POSTGRES_DB": "dmf_pulse_test",
        "POSTGRES_USER": "dmf_test",
        "POSTGRES_PASSWORD": "changeme",
    }
    assert postgres["ports"] == ["5432:5432"]
    assert "pg_isready -U dmf_test -d dmf_pulse_test" in postgres["options"]
    assert job["env"]["DMF_ENVIRONMENT"] == "TEST"
    assert (
        job["env"]["DMF_TEST_DATABASE_URL"]
        == "postgresql+psycopg://dmf_test@127.0.0.1:5432/dmf_pulse_test"
    )
    assert job["env"]["PGPASSWORD"] == "changeme"


def test_workflow_is_the_bounded_fail_closed_five_job_dag() -> None:
    jobs = _jobs()
    assert list(jobs) == [
        "pre_flight",
        "coverage_shards",
        "combined_coverage",
        "post_coverage",
        "quality",
    ]
    assert jobs["coverage_shards"]["needs"] == "pre_flight"
    assert jobs["combined_coverage"]["needs"] == ["pre_flight", "coverage_shards"]
    assert jobs["post_coverage"]["needs"] == ["pre_flight", "combined_coverage"]
    assert jobs["quality"]["needs"] == [
        "pre_flight",
        "coverage_shards",
        "combined_coverage",
        "post_coverage",
    ]
    assert jobs["coverage_shards"]["timeout-minutes"] == 35
    assert all(job["timeout-minutes"] <= 35 for job in jobs.values())


def test_every_executing_stage_uses_the_frozen_checkout_toolchain() -> None:
    jobs = _jobs()
    for job_name in ("pre_flight", "coverage_shards", "combined_coverage", "post_coverage"):
        job = jobs[job_name]
        checkout = _step(job, "Check out without persisted credentials")
        assert checkout["uses"] == "actions/checkout@v4"
        assert checkout["with"] == {"fetch-depth": 0, "persist-credentials": False}
        assert _step(job, "Set up Python 3.13")["uses"] == "actions/setup-python@v5"
        assert (
            _step(job, "Install the pinned uv frontend")["run"]
            == "python -m pip install --disable-pip-version-check uv==0.11.26"
        )
        assert _step(job, "Frozen dependency sync")["run"] == "uv sync --all-groups --frozen"
        assert job["env"]["UV_CACHE_DIR"] == "${{ github.workspace }}/../.uv-cache"


def test_preflight_preserves_static_postgres_and_planning_semantics() -> None:
    pre_flight = _jobs()["pre_flight"]
    _assert_postgres_contract(pre_flight)
    frozen_scope = _step(pre_flight, "Validate GCS-008 frozen scope")
    assert _normalise(frozen_scope["if"]) == GCS_BRANCH_CONDITION
    commands = _runs(pre_flight)
    _assert_fragments_in_order(
        commands,
        [
            "uv run ruff format --check .",
            "uv run ruff check .",
            "uv run mypy src/dmf_pulse",
            "scripts/test_migration_matrix.py --baseline-revision 20260803_0005 --target head",
            'uv run pytest -m "postgres and integration" tests/integration',
            "uv run alembic upgrade head --sql",
            "uv run dmf data-model doctor --json",
            "uv run dmf data-model schema-manifest --json",
            "uv run dmf data-model demo --fixture fixtures/data_model/DAT-003/demo.json --json",
            "uv run dmf data-model as-of --fixture fixtures/data_model/DAT-003/as_of_queries.json --json",
            "scripts/ci_coverage_shards.py plan --shard-count 8",
        ],
    )
    upload = _step(pre_flight, "Upload coverage shard plan")
    assert upload["uses"] == "actions/upload-artifact@v7"
    assert upload["with"]["name"] == "coverage-plan-${{ github.sha }}"
    assert upload["with"]["if-no-files-found"] == "error"
    assert "overwrite" not in upload["with"]


def test_all_eight_coverage_shards_are_mandatory_and_branch_instrumented() -> None:
    shard_job = _jobs()["coverage_shards"]
    assert shard_job["strategy"] == {
        "fail-fast": False,
        "matrix": {"shard": list(range(8))},
    }
    _assert_postgres_contract(shard_job)
    assert _step(shard_job, "Initialize the fresh shard database")["run"] == (
        "uv run alembic upgrade head"
    )
    command = _normalise(_step(shard_job, "Execute assigned branch-coverage shard")["run"])
    for fragment in (
        "printf -v shard_label '%02d'",
        "@${RUNNER_TEMP}/coverage-plan/shard-${shard_label}.args",
        "--cov=dmf_pulse",
        "--cov-branch",
        "--cov-report=",
        "--cov-fail-under=0",
        '-m "not performance"',
    ):
        assert fragment in command
    assert "--cov-report=json" not in command
    materialize = _normalise(_step(shard_job, "Materialize shard transport")["run"])
    assert "scripts/ci_coverage_shards.py materialize" in materialize
    assert '--coverage-data "${RUNNER_TEMP}/coverage-raw/.coverage"' in materialize
    upload = _step(shard_job, "Upload shard coverage data")
    assert upload["uses"] == "actions/upload-artifact@v7"
    assert upload["with"]["name"] == ("coverage-shard-${{ github.sha }}-${{ matrix.shard }}")
    assert upload["with"]["path"] == "${{ runner.temp }}/coverage-shard"
    assert upload["with"]["if-no-files-found"] == "error"
    assert "overwrite" not in upload["with"]


def test_combined_gate_verifies_artifact_population_before_coverage_gates() -> None:
    combined = _jobs()["combined_coverage"]
    shard_download = _step(combined, "Download every shard artifact without merging boundaries")
    assert shard_download["uses"] == "actions/download-artifact@v8"
    assert shard_download["with"] == {
        "pattern": "coverage-shard-${{ github.sha }}-*",
        "path": "${{ runner.temp }}/downloaded-coverage",
        "merge-multiple": False,
        "digest-mismatch": "error",
    }
    step_names = [step["name"] for step in combined["steps"]]
    assert step_names.index("Verify complete shard artifacts and exact current collection") < (
        step_names.index("Combine coverage and enforce repository floor")
    )
    assert step_names.index("Combine coverage and enforce repository floor") < step_names.index(
        "Verify combined branch data"
    )
    assert step_names.index("Verify combined branch data") < step_names.index(
        "Enforce GCS-008 combined coverage gates"
    )
    commands = _runs(combined)
    _assert_fragments_in_order(
        commands,
        [
            "scripts/ci_coverage_shards.py verify-artifacts",
            "uv run python -m coverage erase",
            "uv run python -m coverage combine --keep",
            "uv run python -m coverage report --show-missing --fail-under=90",
            "uv run python -m coverage json --fail-under=90 -o evidence/tickets/GCS-008/coverage.json",
            "scripts/ci_coverage_shards.py verify-branch-report evidence/tickets/GCS-008/coverage.json",
            "scripts/check_gcs008_coverage_gates.py evidence/tickets/GCS-008/coverage.json",
        ],
    )
    upload = _step(combined, "Upload combined coverage report")
    assert upload["uses"] == "actions/upload-artifact@v7"
    assert upload["with"] == {
        "name": "combined-coverage-${{ github.sha }}",
        "path": "evidence/tickets/GCS-008/coverage.json",
        "if-no-files-found": "error",
    }


def test_post_coverage_reconstructs_database_and_preserves_every_gate() -> None:
    post = _jobs()["post_coverage"]
    _assert_postgres_contract(post)
    assert _step(post, "Initialize the fresh acceptance database")["run"] == (
        "uv run alembic upgrade head"
    )
    download = _step(post, "Download verified combined coverage report")
    assert download["uses"] == "actions/download-artifact@v8"
    assert download["with"] == {
        "name": "combined-coverage-${{ github.sha }}",
        "path": "evidence/tickets/GCS-008",
        "digest-mismatch": "error",
    }
    commands = _runs(post)
    _assert_fragments_in_order(
        commands,
        [
            "uv run pytest -m performance tests/performance",
            "uv run dmf specs validate",
            "uv run dmf ingest fpl validate",
            "uv run dmf ingest fpl replay",
            "uv run dmf ingest odds replay",
            "uv run dmf market observations",
            "CREDENTIAL_UNAVAILABLE",
            "uv run pytest tests/unit/football_events",
            "uv run dmf events score-distribution",
            "uv run dmf events explain-market-fit",
            "uv run python scripts/validate_gcs008_acceptance.py",
            "uv run dmf rules validate",
            "uv run dmf rules compile",
            "uv run dmf rules score-fixture",
            "uv run dmf rules score-gameweek",
            "uv build",
            "uv run python scripts/verify_odd005_wheel.py",
            "uv run python scripts/verify_gcs008_wheel.py",
            "uv run python scripts/validate_repository.py",
            "uv run python scripts/scan_secrets.py",
        ],
    )
    acceptance = _step(post, "Validate GCS-008 acceptance")
    assert _normalise(acceptance["if"]) == GCS_BRANCH_CONDITION


def test_public_quality_check_is_an_explicit_fail_closed_sentinel() -> None:
    quality = _jobs()["quality"]
    assert quality["name"] == "Python 3.13 / Ubuntu"
    assert quality["if"] == "${{ always() }}"
    assert quality["needs"] == [
        "pre_flight",
        "coverage_shards",
        "combined_coverage",
        "post_coverage",
    ]
    sentinel = _step(quality, "Require every mandatory CI stage to succeed")
    assert sentinel["env"] == {
        "PRE_FLIGHT_RESULT": "${{ needs.pre_flight.result }}",
        "COVERAGE_SHARDS_RESULT": "${{ needs.coverage_shards.result }}",
        "COMBINED_COVERAGE_RESULT": "${{ needs.combined_coverage.result }}",
        "POST_COVERAGE_RESULT": "${{ needs.post_coverage.result }}",
    }
    command = _normalise(sentinel["run"])
    for name in sentinel["env"]:
        assert f'"${name}" != "success"' in command
    assert "exit 1" in command


def test_artifact_transport_and_failure_policy_have_no_soft_paths() -> None:
    jobs = _jobs()
    for job in jobs.values():
        for step in job["steps"]:
            if step.get("uses") == "actions/upload-artifact@v7":
                assert step["with"]["if-no-files-found"] == "error"
                assert "overwrite" not in step["with"]
                assert "include-hidden-files" not in step["with"]
            if step.get("uses") == "actions/download-artifact@v8":
                assert step["with"]["digest-mismatch"] == "error"
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "continue-on-error" not in workflow_text
    assert "pytest-rerunfailures" not in workflow_text
    assert "--reruns" not in workflow_text
    assert workflow_text.count("--cov-fail-under=0") == 1
    assert workflow_text.count("--fail-under=90") == 2
    assert "timeout-minutes: 60" not in workflow_text
