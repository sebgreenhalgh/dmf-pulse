# GW1 2026/27 Session-1 current-input workflow

This is the exact operator path for one private, current, pre-deadline input that
combines a manual official-FPL capture, one governed live The Odds API EPL `h2h`
request, and explicit team/fixture review. It produces a transient
`SESSION1_DOWNSTREAM_INPUT` in memory and prints only a safe completion summary.

`REAL_CREDENTIALLED_PROVIDER_CALL = OPERATOR_CHECKPOINT`

The target rules remain `VERIFIED`, not globally `ACTIVE`. This route is
`PRESEASON_DECISION_SUPPORT / NON_PRODUCTION`; it does not activate production,
choose a squad, or act on an FPL account.

## 1. Install the exact environment

Run from Windows PowerShell in the repository:

```powershell
Set-Location "<PATH_TO_DMF_PULSE>"
uv sync --all-groups --frozen
. .\.venv\Scripts\Activate.ps1
```

## 2. Configure PostgreSQL and the process-scoped credential

The database records governed odds request/quota/lifecycle evidence. Official-FPL
raw or derived content is never written to it. Use only the database reference on
the command line; never pass a URL or password as a CLI value.

```powershell
$env:DMF_ENVIRONMENT = "TEST"
$env:DMF_TEST_DATABASE_URL = "<POSTGRESQL_URL>"
$env:DMF_PULSE_ODDS_API_KEY = "<YOUR_KEY_HERE>"

uv run alembic upgrade head
dmf ingest odds credential-status --output json
```

Continue only when the credential diagnostic is `{"configured": true}`. The
diagnostic never prints the key, its source, length, prefix, suffix, or hash.

## 3. Capture official FPL manually

Create an operator-owned temporary directory:

```powershell
$CaptureRoot = Join-Path $env:TEMP "dmf-pulse-fpl-current"
New-Item -ItemType Directory -Force -Path $CaptureRoot | Out-Null
$Bootstrap = Join-Path $CaptureRoot "bootstrap-static.json"
$Fixtures = Join-Path $CaptureRoot "fixtures.json"
```

In a normal browser—not PowerShell, `curl`, a scraper, automation, or an
authenticated session—open and save the official `bootstrap-static` and
`fixtures` resources to those exact paths. Record the later actual save time;
do not backdate it. Read event `id = 1` from `$Bootstrap` and copy its exact
`deadline_time` value.

```powershell
$CapturedAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss'Z'")
$InformationCutoff = "<EXACT-GW1-deadline_time-FROM-BOOTSTRAP>"
```

The current 2026/27 GW1 value is expected to describe the official deadline,
but the command trusts only the manually captured bootstrap value and requires
the supplied cutoff to equal it exactly.

Validate each resource before spending a provider request:

```powershell
dmf ingest fpl validate --resource bootstrap --input $Bootstrap --contract-version fpl-reference-v1 --output json
if ($LASTEXITCODE -ne 0) { throw "Official-FPL bootstrap validation failed." }

dmf ingest fpl validate --resource fixtures --input $Fixtures --contract-version fpl-reference-v1 --output json
if ($LASTEXITCODE -ne 0) { throw "Official-FPL fixtures validation failed." }

dmf ingest fpl current validate --bootstrap $Bootstrap --fixtures $Fixtures --competition-key PL --season-code "2026/27" --captured-at $CapturedAt --information-cutoff $InformationCutoff --rights-profile fpl_official_private_manual_v1 --gameweek 1 --output json
if ($LASTEXITCODE -ne 0) { throw "Current official-FPL bundle validation failed." }
```

## 4. Run the single-process Session-1 path

Do not redirect stderr and do not use `2>` or `*>`. The command displays the
private FPL-derived review template on stderr so the final stdout remains one
machine-readable summary. The template is transient display only and is not
authorized for a file, database, object store, backup, Git, evidence, or chat.

```powershell
$Session1Json = dmf ingest session1 run --bootstrap $Bootstrap --fixtures $Fixtures --captured-at $CapturedAt --information-cutoff $InformationCutoff --reviewer "Sebastian Greenhalgh" --database-url-ref env:DMF_TEST_DATABASE_URL --competition-key PL --season-code "2026/27" --gameweek 1 --fpl-rights-profile fpl_official_private_manual_v1 --odds-provider the_odds_api --odds-sport-key soccer_epl --odds-region uk --odds-market h2h --output json
$Session1ExitCode = $LASTEXITCODE
$Session1Json
```

The command performs exactly one accepted live `soccer_epl`, `uk`, `h2h`
retrieval after the FPL and option gates pass. The provider endpoint can return
later upcoming fixtures, so the service transparently scopes its in-memory
working input to the inclusive minimum/maximum kickoff window published for the
official target Gameweek. The review reports source and excluded event counts;
an extra event inside that official window is not silently discarded and will
fail exact coverage. It then prints a deterministic
`SESSION1_IDENTITY_REVIEW_TEMPLATE` and prompts in sorted order:

1. enter one official FPL team ID for every exact provider team string;
2. enter one official FPL fixture ID for every provider event;
3. type the complete displayed `template_sha256` to approve the exact choices.

Exact, case-sensitive equality may be shown as a candidate hint, but no hint is
selected automatically. A spelling variant receives no exact candidate. There
is no fuzzy matching, alias guessing, default answer, saved mapping-plan file,
or silent approval. The command rejects incomplete, duplicate, stale, reversed,
wrong-kickoff, wrong-Gameweek, post-cutoff, or hash-mismatched choices.

Inspect the safe completion summary:

```powershell
if ($Session1ExitCode -ne 0) { throw "Session-1 current input did not complete." }
$Session1 = $Session1Json | ConvertFrom-Json
$Session1 | Select-Object status, contract, run_classification, production_status, target_gameweek, decision_information_at, information_cutoff, source_provider_event_count, excluded_provider_event_count, identity_coverage, fpl_raw_storage, fpl_derived_storage, fpl_persistence_performed, storage_mode
```

Required success values include:

- `status = COMPLETE`;
- `contract = SESSION1_DOWNSTREAM_INPUT`;
- `run_classification = PRESEASON_DECISION_SUPPORT`;
- `production_status = NON_PRODUCTION`;
- `decision_information_at` is the actual operator approval time and is the
  downstream no-lookahead boundary;
- `information_cutoff` is the official deadline ceiling and is never treated as
  evidence that information from after `decision_information_at` was observed;
- `identity_coverage = COMPLETE`;
- `fpl_raw_storage = DENY` and `fpl_derived_storage = DENY`;
- `fpl_persistence_performed = false`;
- `storage_mode = TRANSIENT_IN_MEMORY`.

The detailed FPL bundle, provider-current odds, reviewed identity plans, and
identity map exist only inside that command process. Later modelling commands
must call the same application service in the same process; this route does not
serialize prohibited FPL-derived content for handoff.

## 5. Controlled failures

- `CREDENTIAL_UNAVAILABLE`, `QUOTA_EXHAUSTED`, or `RIGHTS_BLOCKED`: stop before
  retrying; correct only the declared credential/quota/rights condition.
- `POST_CUTOFF`: make a new genuine capture/run before the official deadline;
  never backdate a timestamp.
- `MAPPING_CONFLICT`: re-read the displayed exact current options and provide a
  complete, one-to-one review; never guess or fuzzy-match.
- `QUALITY_BLOCKED`: do not use the current inputs or substitute synthetic odds.
- provider/network codes: inspect the secret-safe JSON error and retry only when
  its policy permits. Never expose the provider body or credential.

A failed command does not authorize persistence, a hidden fallback, or a claim
that a current Session-1 input exists.

## 6. Delete current FPL files and clear process state

Run this whether the workflow succeeds or fails:

```powershell
Remove-Item -LiteralPath $Bootstrap -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $Fixtures -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $CaptureRoot -Force -Recurse -ErrorAction SilentlyContinue

Remove-Item Env:DMF_PULSE_ODDS_API_KEY -ErrorAction SilentlyContinue
Remove-Item Env:DMF_TEST_DATABASE_URL -ErrorAction SilentlyContinue
Remove-Item Env:DMF_ENVIRONMENT -ErrorAction SilentlyContinue
Remove-Variable CaptureRoot, Bootstrap, Fixtures, CapturedAt, InformationCutoff, Session1Json, Session1ExitCode, Session1 -ErrorAction SilentlyContinue
```

Do not claim a real current-data success until the operator has executed this
workflow locally with a genuine current manual capture and real process-scoped
provider credential.
