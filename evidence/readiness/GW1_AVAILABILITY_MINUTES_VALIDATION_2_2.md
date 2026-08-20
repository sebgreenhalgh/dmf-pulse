# GW1 Checkpoint 2.2 — current availability and minutes validation

## Scope and identity

- Canonical branch — `readiness/GW1-2026-27-live-input-initial-squad`.
- Immutable programme parent — `9eb57143f6ee92f67c78607cc386678d962e62d4`.
- Starting accepted remote SHA — `923d0761ce1f4bf327623948cdc82ad7306d9aeb`.
- Capability commit — `e7c40a03ac664e5f736d019b375d3478a654176b`.
- Linux validation workflow — run `32319850997` (`PASS`), job `96279685296`,
  exact head `e7c40a03ac664e5f736d019b375d3478a654176b`.
- Real credentialled provider call — `OPERATOR_CHECKPOINT`.

## Implemented vertical slice

- `GW1_CURRENT_AVAILABILITY_REVIEW` independently revalidates the complete
  Checkpoint-2.1 market bundle and binds the exact current target-team roster,
  status, chance, news, position, identity and fixture material into a private,
  deterministic transient review hash.
- The operator must confirm that exact hash and all-player review. Every FPL
  availability alert requires an explicit fixture-scoped decision with typed
  evidence, reviewer, source locator, observed/usable times and expiry through
  kickoff.
- Hard zero is limited to fresh high-confidence official suspension or formal
  ineligibility evidence. New-signing status requires official transfer or
  registration evidence. Manager quotes, training reports, medical statements,
  FPL alerts and analyst judgement cannot directly force a numeric probability.
- Confirmed fixture cancellation blocks the complete fixture projection; it
  cannot be selectively applied to one player while a match projection proceeds.
- Every target-fixture team is mapped to explicit deterministic transient
  fixture/team/player UUID surrogates. No identifier is represented as a
  database-resolved central canonical entity.
- The accepted Stage-7 model runs with the current official roster and an
  explicit empty competitive-history set. Both pre-override and post-override
  team projections are retained in memory with exact per-decision effect hashes.
- Outputs preserve exact 91-bin minute PMFs, joint START/BENCH/OUT coherence,
  256-scenario identity, complete two-team fixture coverage and hard-zero
  semantics. An insufficient eligible roster fails closed.
- The result is labelled
  `SYNTHETIC_CONTRACT_BASELINE_COLD_START / NON_PRODUCTION` with no production
  calibration claim. Unknown manager-regime and promoted-team state are not
  inferred. These are material limitations, not hidden confidence.
- Official-FPL raw and derived retention remain denied. The adapter performs no
  filesystem write, database access, provider call or public player-data
  disclosure; its safe summary contains only counts, grades, limitations and
  semantic identities.

## Hostile review and remediation

### P0

- None found.

### P1

1. The inherited current-FPL bundle identity authenticates its source bootstrap
   semantic hash but does not separately hash the normalized player fields now
   consumed by Stage 7. Remediation: independently hash every target player's
   exact normalized availability/identity/roster material and bind it into the
   review template, output and safe summary.
2. Unstructured evidence could turn a manager quote, training report or medical
   statement into an invented hard 0/1 probability. Remediation: typed evidence
   classes, authoritative hard/new-signing whitelists, complete flagged-player
   review and explicit `SOFT_EVIDENCE_NO_MODEL_ADJUSTMENT` semantics.
3. A player-scoped cancellation override could leave the rest of a cancelled
   fixture projected. Remediation: authoritative fixture cancellation now blocks
   the complete fixture projection.

### P2

1. Strict Python-mode revalidation of the Stage-6 model rejected its serialized
   Decimal strings. Remediation: use the model's canonical JSON round trip,
   which reconstructs strict Decimal values and reruns every Stage-6 validator.
2. Re-running the complete frozen synthetic evaluation dataset on every current
   bundle validation added no new current-input evidence and materially slowed
   validation. Remediation: validate the packaged training/policy hashes and
   refit the frozen authenticated artifact at the adapter boundary; retain the
   already accepted evaluation identity and explicit no-production claim.

### Unresolved findings

- No unresolved P0, P1, P2 or P3 finding is recorded for this bounded slice.

## Local validation

- New Checkpoint-2.2 tests — `13 passed` after final hostile-review hardening.
- New adapter branch-aware coverage — `93%` (`351` statements, `80` branches),
  above the required `90%`.
- Availability unit/property/contract plus Checkpoint-2.1 and Session-1
  upstream regressions — `200 passed` before the final two focused hostile-path
  variants; both additional variants passed in the final 13-test focused run.
- Disposable PostgreSQL 18.4 migration plus complete Stage-7 integration suite
  — `28 passed`; the named container was stopped and auto-removed.
- Ruff format — `PASS`, `512 files`.
- Ruff lint — `PASS` after the bounded export-order remediation.
- Strict mypy — `PASS`, `195 source files`; the new adapter also passed a fresh
  targeted strict check.
- First-party secret scan — `PASS`, `finding_count=0`.
- Canonical source/wheel build — `PASS`, `dmf-pulse 0.2.0`.
- Workflow YAML parse and `git diff --check` — `PASS`.
- Repository validation — `NOT_EXECUTED` at this bounded checkpoint. The known
  branch-wide stale GCS-008 current-manifest debt remains a final engineering
  acceptance gate and is not promoted to PASS.

## Linux and remote validation

- Dedicated Linux run `32319850997` passed on exact capability commit
  `e7c40a03ac664e5f736d019b375d3478a654176b`; job `96279685296` passed every
  step.
- Frozen sync and disposable PostgreSQL migration passed.
- The final current-availability, complete Stage-7 unit/property/contract,
  Checkpoint-2.1 and Session-1 regression command passed `202` tests.
- New current-availability branch coverage passed the configured `90%` gate.
- The complete PostgreSQL Stage-7 integration command passed `28` tests.
- Ruff format, Ruff lint, strict mypy, wheel/sdist build, first-party secret
  scan, commit whitespace assurance and container cleanup all passed.
- The canonical branch was fetched after completion. Local HEAD and
  `origin/readiness/GW1-2026-27-live-input-initial-squad` were exactly equal at
  `e7c40a03ac664e5f736d019b375d3478a654176b` before this attestation.

## Capability file hashes

- `src/dmf_pulse/availability/current.py` —
  `3ae2b72b6596f8959a8ae5080a9c087c69f7059a3e4bee3a875701d2ebaf456c`.
- `src/dmf_pulse/availability/__init__.py` —
  `306a08d5b2665bb5604c69c242d3df691186a7b829d09fc37b961be8d86a8e2d`.
- `tests/unit/availability/test_current_availability.py` —
  `7febb48a89583aeaf0400a1a84ec3ceca019f45bf662b50728f1be0b0a9e2f8a`.
- `.github/workflows/gw1-checkpoint-2-2-validation.yml` —
  `9f7597925c10c11eccec6983528a23ea038735674577dcdeb6c71ee2dd7dea9e`.

## Status

- Local engineering result — `PASS`.
- Linux engineering result — `PASS`.
- Checkpoint 2.2 — `COMPLETE`.
- Exact next action — publish this evidence-only attestation, verify its remote
  SHA, then begin Checkpoint 2.3 current football-event distributions without
  widening the accepted Stage-8 baseline or hiding the Stage-7 cold-start debt.
