$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RequiredParent = "a5a0b66afd6e9645f971976d723e238824bee6a8"
$ExpectedBranch = "stage/A8/GCS-008-goal-clean-sheet-distributions"
$CoveragePath = "evidence/tickets/GCS-008/coverage.json"

function Assert-NativeSuccess {
    param([Parameter(Mandatory = $true)][string]$Step)
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE"
    }
}

if ((git merge-base HEAD $RequiredParent) -ne $RequiredParent) {
    throw "HEAD is not descended from the required GCS-008 parent."
}
if ((git branch --show-current) -ne $ExpectedBranch) {
    throw "Run acceptance on $ExpectedBranch."
}

git diff --check
Assert-NativeSuccess "git diff --check"
uv sync --all-groups --frozen
Assert-NativeSuccess "frozen dependency sync"
uv run python scripts/validate_gcs008_scope.py
Assert-NativeSuccess "GCS-008 scope validation"

uv run ruff format --check .
Assert-NativeSuccess "Ruff formatting"
uv run ruff check .
Assert-NativeSuccess "Ruff lint"
uv run mypy src/dmf_pulse
Assert-NativeSuccess "strict mypy"

uv run pytest -q tests/unit/football_events tests/unit/scripts/test_gcs008_acceptance.py tests/unit/scripts/test_gcs008_coverage_gate.py tests/unit/scripts/test_gcs008_scope.py tests/unit/scripts/test_gcs008_wheel.py
Assert-NativeSuccess "GCS-008 unit tests"
uv run pytest -q tests/property/football_events
Assert-NativeSuccess "GCS-008 property tests"
uv run pytest -q tests/contract/football_events tests/golden/football_events tests/integration/football_events
Assert-NativeSuccess "GCS-008 contract, golden and integration tests"

$env:DMF_ENVIRONMENT = "TEST"
$env:PGPASSWORD = "changeme"
$env:DMF_TEST_DATABASE_URL = "postgresql+psycopg://dmf_test@127.0.0.1:55432/dmf_pulse_test"
docker compose -f compose.test.yaml up -d --wait
Assert-NativeSuccess "disposable PostgreSQL startup"
try {
    uv run pytest --cov=dmf_pulse --cov-branch --cov-report=term-missing --cov-report=json:$CoveragePath
    Assert-NativeSuccess "complete repository coverage suite"
    uv run python scripts/check_gcs008_coverage_gates.py $CoveragePath
    Assert-NativeSuccess "GCS-008 coverage gates"
    uv run python scripts/validate_gcs008_acceptance.py
    Assert-NativeSuccess "GCS-008 acceptance validation"

    $Projection = uv run dmf events score-distribution `
        --fixture fixtures/events/score/GCS-008/balanced_fixture.json `
        --artifact-root artifacts/gcs008-acceptance `
        --output json | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) {
        throw "score-distribution command failed with exit code $LASTEXITCODE"
    }
    $ArtifactPath = [string]$Projection.artifact_path
    if ([string]::IsNullOrWhiteSpace($ArtifactPath) -or -not (Test-Path -LiteralPath $ArtifactPath)) {
        throw "score-distribution did not return a readable artifact path"
    }
    uv run dmf events explain-market-fit --fixture fixtures/events/score/GCS-008/balanced_fixture.json --output json
    Assert-NativeSuccess "explain-market-fit CLI"
    uv run dmf events validate --distribution $ArtifactPath --output json
    Assert-NativeSuccess "distribution validation CLI"
    uv run dmf events evaluate --distribution $ArtifactPath --home-goals 2 --away-goals 1 --output json
    Assert-NativeSuccess "distribution evaluation CLI"

    uv run python scripts/test_migration_matrix.py --baseline-revision 20260803_0005 --target head
    Assert-NativeSuccess "migration matrix"
    uv run pytest -m "postgres and integration" tests/integration
    Assert-NativeSuccess "PostgreSQL integration tests"
}
finally {
    docker compose -f compose.test.yaml down -v --remove-orphans
    Assert-NativeSuccess "disposable PostgreSQL teardown"
}

uv build
Assert-NativeSuccess "wheel build"
uv run python scripts/verify_gcs008_wheel.py
Assert-NativeSuccess "installed-wheel verification"
uv run python scripts/validate_repository.py
Assert-NativeSuccess "repository validation"
uv run python scripts/scan_secrets.py
Assert-NativeSuccess "secret scan"
# Governed ticket-evidence validation is intentionally deferred until real command, commit, CI, review, and human records have been assembled.
