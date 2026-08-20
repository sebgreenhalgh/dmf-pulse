# GW1 Checkpoint 2.1 — current market-consensus validation

## Scope and identity

- Canonical branch — `readiness/GW1-2026-27-live-input-initial-squad`.
- Immutable programme parent — `9eb57143f6ee92f67c78607cc386678d962e62d4`.
- Starting accepted remote SHA — `eb4eaa66c74b138e1cecd94931bf742a8cd9336d`.
- Capability commit — `57c5b5f68e0e1a5a2c5a2d6b9c14f4e9e43d0924`.
- Hostile-review remediation — `2858e6f155c6606fa6bfc1a51d72c3286da33317`.
- Final Linux validation workflow — `32317678585` (`PASS`), job
  `96273329722`, exact head `2858e6f155c6606fa6bfc1a51d72c3286da33317`.
- Real credentialled provider call — `OPERATOR_CHECKPOINT`.

## Implemented vertical slice

- `ODDS_PROVIDER_CURRENT_INPUT` now independently hashes the normalized event,
  bookmaker, market, timestamp, outcome and exact Decimal-price material used by
  downstream calculations. Raw provider payload retention remains forbidden.
- `GW1_CURRENT_MARKET_CONSENSUS` independently revalidates the complete
  `SESSION1_DOWNSTREAM_INPUT`, source-market hash, reviewed event/fixture
  coverage, rights, actual decision time and all result hashes.
- Each complete `h2h` bookmaker book is translated deterministically to accepted
  Stage-6 `ExclusiveOutcomeQuote` rows and evaluated by the authenticated frozen
  power/proportional and operator-consensus policy.
- Stale or otherwise ineligible books remain typed exclusions. A target fixture
  with no eligible fresh complete book fails closed; no model-only probability is
  imputed in the market core.
- A missing market-level provider timestamp uses the earlier governed bookmaker
  timestamp and emits an explicit degradation warning.
- The output is private, transient, database-free and non-production. Its Stage-6
  fixture UUID is explicitly labelled
  `DETERMINISTIC_TRANSIENT_SURROGATE_NO_DATABASE_RESOLUTION`; it is not presented
  as a persisted central canonical entity ID.
- The safe summary discloses only counts, confidence grades, policy/source/result
  hashes, timing and the no-persistence boundary. It does not disclose FPL player
  data, provider prices or credentials.

## Hostile review and remediation

### P0

- None found.

### P1

1. The pre-existing current-odds contract authenticated the raw-response hash
   and event identity view, but a deserialized parsed price mutation was not
   independently tied to a semantic hash. Remediation: add and revalidate a
   canonical parsed-market semantic hash and bind it into Session-1 and Stage-6
   downstream identities.
2. Both live-odds database-error handlers could call an arbitrary injected
   credential provider while selecting error precedence, contrary to the
   secret-boundary rule. Remediation: use a non-reading configuration hint for
   known runtime/static/unavailable providers; unknown providers are never
   invoked from the handler and the database error remains primary.
3. The first wrapper revision called its locally derived UUID canonical although
   central database resolution is forbidden for the official-FPL source.
   Remediation: rename it `transient_fixture_id` and require the explicit
   no-database surrogate identity mode in public output and safe summary.

### P2 / P3

- No unresolved P2 or P3 finding is recorded for this bounded checkpoint.

## Local validation

- New Checkpoint-2.1 tests — `9 passed`.
- New service branch-aware coverage — `95.43%` (`151` statements, `24`
  branches), above the required `90%`.
- Inherited unit/property market, complete ingestion-unit and Session-1 CLI
  suite — `546 passed, 4 deselected`. The four deselections are Windows symlink
  cases requiring a host privilege unavailable here; all remain enabled in the
  Linux workflow.
- Disposable PostgreSQL 18.4 migration plus odds-evidence and Stage-6
  integration regressions — `22 passed`; the named container was stopped and
  auto-removed.
- Ruff format — `PASS`, `510 files already formatted` before the final bounded
  terminology-only remediation; the remediation files were then formatted and
  linted again.
- Ruff lint — `PASS`.
- Strict mypy — `PASS`, `194 source files`; the remediated module also passed a
  fresh strict targeted check.
- First-party secret scan — `PASS`, `finding_count=0`.
- Canonical source/wheel build — `PASS`, `dmf-pulse 0.2.0`.
- Workflow YAML parse and `git diff --check` — `PASS`.
- Repository validation — `NOT_EXECUTED` at this bounded checkpoint. The known
  branch-wide stale GCS-008 current-manifest debt (`105` errors at Checkpoint
  1.5) remains a final engineering-acceptance gate and is not promoted to PASS.

## Linux and remote validation

- Initial capability workflow `32317472080` passed every step on exact commit
  `57c5b5f68e0e1a5a2c5a2d6b9c14f4e9e43d0924`.
- After hostile-review terminology remediation, workflow `32317678585` passed
  PostgreSQL migration, current market/Stage-6/ingestion tests, branch coverage,
  PostgreSQL integration, Ruff, strict mypy, build, secret scan, whitespace
  assurance and container cleanup on exact commit
  `2858e6f155c6606fa6bfc1a51d72c3286da33317`.
- Local HEAD and the canonical remote branch were fetched and verified equal at
  `2858e6f155c6606fa6bfc1a51d72c3286da33317` before this attestation.

## Final capability file hashes

- `src/dmf_pulse/ingestion/odds/credentials.py` —
  `61a5dbf5054824aaa518733b1a33110df5d2769f6b54cc97ece02645fbbdf110`.
- `src/dmf_pulse/ingestion/odds/current.py` —
  `7ff765f4b13fe25916b69d96f7d833f0c32d7ebc5b6a9c64cdda1f62b9cc1b92`.
- `src/dmf_pulse/ingestion/odds/live.py` —
  `5c74cefbfc5fbd481173357e22cf766c4280e0d7974d54adf548fea970d2a30c`.
- `src/dmf_pulse/ingestion/odds/service.py` —
  `86d4e60755267d8ee2a7df45fe0fcbfb644263ab6b264be7674171fc77347c1e`.
- `src/dmf_pulse/ingestion/session1.py` —
  `71fdc11f06bc5debaeac6d42ffe62086623deacda04700fdb2da9756c02f3f13`.
- `src/dmf_pulse/markets/current.py` —
  `17f4d7999c0097f9c6e75b73dd63053dce8c4115cb2eb46e05e67d7f14471ba8`.
- `tests/unit/markets/test_current_market.py` —
  `4f6308df6e121006b526d4d1c6797853a26dd9f5ce57103670e94b8acad4aad7`.
- `.github/workflows/gw1-checkpoint-2-1-validation.yml` —
  `7dbae752bbfaa58627fb0d6c2a29548034a4e4f212dc1299ab4b51b8abdb5a3f`.

## Status

- Local engineering result — `PASS`.
- Linux engineering result — `PASS`.
- Checkpoint 2.1 — `COMPLETE`.
- Exact next action — publish this evidence-only attestation, verify the new
  remote head, then begin Checkpoint 2.2 structured availability/start/minutes
  integration without widening the accepted Stage-7 model.
