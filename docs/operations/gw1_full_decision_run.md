# GW1 2026/27 full decision run (Windows PowerShell)

This is the one implemented operator path from manual current FPL files and one
live Odds API retrieval to three initial-squad portfolios, XI, bench order,
captain, vice-captain, uncertainty, and a hash-only prospective receipt.

`REAL_CREDENTIALLED_PROVIDER_CALL = OPERATOR_CHECKPOINT`

The command is private `PRESEASON_DECISION_SUPPORT / NON_PRODUCTION`. It does
not activate the verified rules, persist FPL-derived output, use a chip, or act
on an FPL account. Run it before the official GW1 deadline from a clean checkout
of the canonical readiness branch.

## 1. Synchronise and install

```powershell
Set-Location "<PATH_TO_DMF_PULSE>"
git switch readiness/GW1-2026-27-live-input-initial-squad
git fetch origin
if ((git rev-parse HEAD) -ne (git rev-parse origin/readiness/GW1-2026-27-live-input-initial-squad)) { throw "Local branch is not the published readiness revision." }
uv sync --all-groups --frozen
$CodeCommit = git rev-parse HEAD
if ($CodeCommit -notmatch '^[0-9a-f]{40}$') { throw "Commit identity is invalid." }
```

## 2. Start PostgreSQL and set process-only secrets

The database stores governed Odds request/quota lifecycle evidence. It does not
store official-FPL input or the detailed decision. Keep all actual values out of
the command line, shell history, logs, evidence, Git, and chat.

```powershell
$env:DMF_ENVIRONMENT = "TEST"
$env:DMF_TEST_DATABASE_URL = "<POSTGRESQL_URL_WITHOUT_PASSWORD>"
$env:PGPASSWORD = (Read-Host "Enter the local PostgreSQL password" -MaskInput)
$env:DMF_PULSE_ODDS_API_KEY = (Read-Host "Enter the Odds API key" -MaskInput)

docker compose -f compose.test.yaml up -d --wait
uv run alembic upgrade head
uv run dmf ingest odds credential-status --output json
if ($LASTEXITCODE -ne 0) { throw "Odds credential diagnostic failed." }
```

Continue only when the diagnostic is `{"configured": true}`. It never prints a
key, key fragment, length, source, or fingerprint.

## 3. Capture and validate official FPL manually

```powershell
$CaptureRoot = Join-Path $env:TEMP "dmf-pulse-gw1-current"
New-Item -ItemType Directory -Force -Path $CaptureRoot | Out-Null
$Bootstrap = Join-Path $CaptureRoot "bootstrap-static.json"
$Fixtures = Join-Path $CaptureRoot "fixtures.json"
```

In a normal browser—not a script, scraper, CLI HTTP client, or authenticated
manager session—save the official `bootstrap-static` and `fixtures` resources
to those exact paths. Immediately record the actual later save time. Read event
`id = 1` from the bootstrap and copy its exact `deadline_time`.

```powershell
$CapturedAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss'Z'")
$InformationCutoff = "<EXACT_GW1_DEADLINE_TIME_FROM_BOOTSTRAP>"

uv run dmf ingest fpl validate --resource bootstrap --input $Bootstrap --contract-version fpl-reference-v1 --output json
if ($LASTEXITCODE -ne 0) { throw "Bootstrap validation failed." }
uv run dmf ingest fpl validate --resource fixtures --input $Fixtures --contract-version fpl-reference-v1 --output json
if ($LASTEXITCODE -ne 0) { throw "Fixtures validation failed." }
uv run dmf ingest fpl current validate --bootstrap $Bootstrap --fixtures $Fixtures --competition-key PL --season-code "2026/27" --captured-at $CapturedAt --information-cutoff $InformationCutoff --rights-profile fpl_official_private_manual_v1 --gameweek 1 --output json
if ($LASTEXITCODE -ne 0) { throw "Current FPL validation failed." }
```

## 4. Prepare the accepted event-prior input

Set `$EventPrior` to the operator-owned JSON artifact produced by the accepted
current team-strength/event-allocation process and independently accepted under
`GW1_CURRENT_FOOTBALL_EVENT_PRIOR_ARTIFACT`. It must exactly cover the current
fixtures and transient player/team identities displayed during this run, have a
fresh pre-cutoff information set, preserve its evidence and acceptance
references, and carry its valid `artifact_sha256`.

```powershell
$EventPrior = "<PATH_TO_GOVERNANCE_ACCEPTED_CURRENT_EVENT_PRIOR_JSON>"
if (-not (Test-Path -LiteralPath $EventPrior -PathType Leaf)) { throw "Accepted event prior is unavailable." }
```

There is no synthetic or inferred fallback. If no current accepted artifact
exists, stop with `CURRENT_EVENT_PRIOR = OPERATOR_INPUT_REQUIRED`.

## 5. Run the one-process full pipeline

Do not use `>`, `2>`, `*>`, `Tee-Object`, `Out-File`, transcript capture, or a
pipeline. The command makes the live Odds request internally, then keeps all
FPL-derived reviews and outputs in memory/stdout only. A separate preliminary
Odds snapshot would spend another provider request and would not be the input to
this process.

```powershell
uv run dmf gw1 run --bootstrap $Bootstrap --fixtures $Fixtures --captured-at $CapturedAt --information-cutoff $InformationCutoff --reviewer "<OPERATOR_NAME>" --event-prior $EventPrior --code-commit $CodeCommit --database-url-ref env:DMF_TEST_DATABASE_URL --rules-source config/rules/fpl-2026-27 --mc-policy config/models/fpl_points_simulation.yaml --prospective-root artifacts/prospective --root-seed 2026270001 --scenario-count 1000 --output json
$DecisionExitCode = $LASTEXITCODE
if ($DecisionExitCode -ne 0) { throw "GW1 decision pipeline did not produce an accepted decision." }
```

Complete the prompts in order:

1. For every provider team and event, enter the exact official FPL team/fixture
   ID after checking orientation and kickoff; type the complete Session-1 hash.
2. Review every displayed availability row. Paste one JSON array of
   `CurrentPlayerAvailabilityDecision` objects. Every flagged player/fixture
   requires fresh evidence. Use `[]` only when no row says
   `explicit_decision_required = true`; type the complete availability hash.
3. Check the displayed event identities against the accepted prior; type the
   complete event-template hash and complete prior-artifact hash.

The final JSON is a private transient operator display. Check:

- `safe_summary.status = SUCCESS` and `blocker_codes = []`;
- three distinct portfolios: `EXPECTED_POINTS`, `CONSERVATIVE`, and
  `HIGHER_UPSIDE`;
- 15 players, budget/bank, legal XI, bench goalkeeper and bench order;
- distinct captain and vice-captain in the XI;
- player mean/quantiles, P(appearance), P(start), minutes and uncertainty;
- `automated_fpl_account_action = false`, `chip_used = false`, and
  `persistence_performed = false`;
- a `prospective_receipt_sha256` and content-addressed `receipt.json` path.

Only the receipt may remain on disk. It contains immutable hashes, timestamps,
the code/rules/capability identities, and explicit no-content flags—no players,
prices, squad, provider payload, or detailed decision.

## 6. Controlled failures

- `CREDENTIAL_UNAVAILABLE`, `QUOTA_EXHAUSTED`, `HTTP_429`, or a network code:
  do not substitute odds or expose provider content; retry only under policy.
- `POST_CUTOFF`: stop. Never backdate a capture, mapping, evidence item, prior,
  or approval.
- `MAPPING_CONFLICT`: repeat the run and explicitly review exact identities; do
  not fuzzy-match or reverse home/away.
- `QUALITY_BLOCKED` or `SOURCE_LINEAGE_INVALID`: do not use partial output.
- `UPSTREAM_MONTE_CARLO_CONTINUE/BLOCKED`: increase scenarios only within the
  accepted policy and resource limits; never waive the stopping rule.
- `INITIAL_SQUAD_BLOCKED`: no squad, XI, bench, or receipt is accepted.
- missing/stale/unaccepted event prior: obtain external governance acceptance;
  never create an ad-hoc prior inside this workflow.

## 7. Clean up

Run this after success or failure. Confirm the paths still point to the temporary
capture directory before removing them.

```powershell
$ResolvedCaptureRoot = [System.IO.Path]::GetFullPath($CaptureRoot)
$ResolvedTempRoot = [System.IO.Path]::GetFullPath($env:TEMP)
if (-not $ResolvedCaptureRoot.StartsWith($ResolvedTempRoot, [System.StringComparison]::OrdinalIgnoreCase)) { throw "Capture cleanup target is outside TEMP." }
Remove-Item -LiteralPath $Bootstrap -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $Fixtures -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $ResolvedCaptureRoot -Force -Recurse -ErrorAction SilentlyContinue

Remove-Item Env:DMF_PULSE_ODDS_API_KEY -ErrorAction SilentlyContinue
Remove-Item Env:DMF_TEST_DATABASE_URL -ErrorAction SilentlyContinue
Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
Remove-Item Env:DMF_ENVIRONMENT -ErrorAction SilentlyContinue
docker compose -f compose.test.yaml down
Remove-Variable CodeCommit, CaptureRoot, ResolvedCaptureRoot, ResolvedTempRoot, Bootstrap, Fixtures, CapturedAt, InformationCutoff, EventPrior, DecisionExitCode -ErrorAction SilentlyContinue
```

Do not claim `REAL_GW1_DECISION_COMPLETE` until this exact workflow succeeds
locally with current manual FPL files, the operator's process-only credential,
explicit reviews, and a current independently accepted event-prior artifact.
