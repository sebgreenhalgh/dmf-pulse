$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RequiredParent = "43270ee54ceff6c4692a6a84118565c16fa6be72"
$ExpectedBranch = "stage/A9/PTS-009-static-acceptance-r2"
$ScopeDeclaration = "evidence/tickets/PTS-009-STATIC-FIX/round2/CHANGED_FILES.txt"
$Stage9Coverage = "evidence/stages/09/coverage.json"
$RepositoryCoverage = "evidence/stages/09/repository_coverage.json"

function Assert-NativeSuccess {
    param([Parameter(Mandatory = $true)][string]$Step)
    if ($LASTEXITCODE -ne 0) { throw "$Step failed with exit code $LASTEXITCODE" }
}

if ((git merge-base HEAD $RequiredParent) -ne $RequiredParent) {
    throw "HEAD is not descended from the required PTS-009 R2 parent."
}
if ((git branch --show-current) -ne $ExpectedBranch) {
    throw "Run acceptance on $ExpectedBranch."
}

git diff --check
Assert-NativeSuccess "git diff --check"
uv sync --all-groups --frozen
Assert-NativeSuccess "frozen dependency sync"
uv run python scripts/assurance/check_stage9_scope.py --root . `
    --parent-revision $RequiredParent --declaration $ScopeDeclaration
Assert-NativeSuccess "Stage-9 scope"
uv run python scripts/assurance/check_stage9_resources.py
Assert-NativeSuccess "Stage-9 generated resources"

uv run ruff format --check .
Assert-NativeSuccess "Ruff formatting"
uv run ruff check .
Assert-NativeSuccess "Ruff lint"
uv run mypy src/dmf_pulse
Assert-NativeSuccess "strict mypy"

uv run pytest -q --cov=src/dmf_pulse/fpl_points --cov-branch --cov-fail-under=0 `
    --cov-report=term-missing --cov-report=json:$Stage9Coverage `
    tests/unit/fpl_points tests/property/fpl_points tests/contract/fpl_points `
    tests/golden/fpl_points tests/integration/fpl_points tests/assurance/fpl_points
Assert-NativeSuccess "complete Stage-9 suite and coverage"
uv run python scripts/assurance/check_stage9_coverage.py $Stage9Coverage `
    --minimum-line-percent 85 --minimum-branch-percent 70
Assert-NativeSuccess "Stage-9 coverage gate"
uv run pytest -q tests/performance/fpl_points
Assert-NativeSuccess "Stage-9 performance smoke"

uv run pytest -q tests/unit/rules tests/property/rules tests/golden/rules
Assert-NativeSuccess "accepted Stage-2 rules compatibility"
uv run pytest -q tests/contract/availability tests/unit/availability tests/property/availability
Assert-NativeSuccess "accepted Stage-7 compatibility"
uv run pytest -q tests/unit/football_events tests/property/football_events `
    tests/contract/football_events tests/golden/football_events tests/integration/football_events
Assert-NativeSuccess "accepted Stage-8 compatibility"

$env:DMF_ENVIRONMENT = "TEST"
$env:PGPASSWORD = "changeme"
$env:DMF_TEST_DATABASE_URL = "postgresql+psycopg://dmf_test@127.0.0.1:55432/dmf_pulse_test"
docker compose -f compose.test.yaml config --quiet
Assert-NativeSuccess "Docker compose validity"
docker compose -f compose.test.yaml up -d --wait
Assert-NativeSuccess "disposable PostgreSQL startup"
try {
    uv run python scripts/test_migration_matrix.py `
        --baseline-revision 20260803_0005 --target head
    Assert-NativeSuccess "migration matrix"
    uv run pytest -q -m "postgres and integration" tests/integration
    Assert-NativeSuccess "PostgreSQL integration"

    # The current repository snapshot must include the generated Stage-9 resources
    # and focused coverage evidence before its integration test executes.
    uv run python scripts/generate_repository_manifest.py --ticket GCS-008
    Assert-NativeSuccess "pre-regression repository snapshot"

    # This is the single final complete repository coverage regression. The
    # wall-clock performance smoke ran above without coverage instrumentation.
    uv run pytest -q --ignore=tests/performance --cov=dmf_pulse --cov-branch `
        --cov-report=json:$RepositoryCoverage
    Assert-NativeSuccess "complete repository coverage suite"
}
finally {
    docker compose -f compose.test.yaml down -v --remove-orphans
    Assert-NativeSuccess "disposable PostgreSQL teardown"
}

$CliRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("dmf-pts009-cli-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $CliRoot | Out-Null
$Projection = uv run dmf fpl-points simulate-fixture `
    --request fixtures/points/PTS-009/fixture_request_example.json `
    --ruleset fixtures/points/PTS-009/reference_ruleset_test_only.json `
    --mc-policy config/models/fpl_points_simulation.yaml `
    --artifact-root $CliRoot --output json | ConvertFrom-Json
Assert-NativeSuccess "Stage-9 TEST CLI"
$ArtifactPath = [string]$Projection.artifact_path
if ([string]::IsNullOrWhiteSpace($ArtifactPath) -or -not (Test-Path -LiteralPath $ArtifactPath)) {
    throw "Stage-9 TEST CLI did not return a readable artifact."
}
uv run dmf fpl-points validate --artifact $ArtifactPath --output json
Assert-NativeSuccess "Stage-9 artifact validation CLI"
uv run dmf fpl-points mc-diagnostics --artifact $ArtifactPath --output json
Assert-NativeSuccess "Stage-9 MC diagnostics CLI"
uv run python scripts/assurance/check_stage9_artifact.py $ArtifactPath `
    --ruleset fixtures/points/PTS-009/reference_ruleset_test_only.json
Assert-NativeSuccess "Stage-9 independent artifact assurance"

uv build
Assert-NativeSuccess "wheel build"
uv run python scripts/verify_pts009_wheel.py
Assert-NativeSuccess "isolated installed-wheel verification"

# The full coverage run changes its tracked JSON evidence after the repository
# manifest integration test has executed, so refresh the current snapshot once.
uv run python scripts/generate_repository_manifest.py --ticket GCS-008
Assert-NativeSuccess "final repository snapshot"
uv run python scripts/validate_repository.py
Assert-NativeSuccess "repository validation"
uv run python scripts/scan_secrets.py
Assert-NativeSuccess "secret scan"
git diff --check
Assert-NativeSuccess "final git diff --check"

Write-Host "All PTS-009 integration gates passed; independent acceptance remains separate."
