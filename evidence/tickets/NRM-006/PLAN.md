# NRM-006 implementation plan

Updated: 2026-08-06

Current status: **PREACCEPTANCE GREEN; COMPLETION COMMIT PENDING** under
corrected Pack 1.1. The vertical slice and every mandatory ODD-005 remediation
are implemented. Post-remediation static, migration, concurrency, temporal,
security, full-suite, and critical-coverage gates pass with zero skips, and the
final independent read-only audit found no unresolved P0/P1 issue. The literal
32-command ledger and final archive validation have not started. The Pack 1.0
quota fixture and publication-boundary blockers are resolved by the new frozen
authority. The original stop evidence is retained byte-for-byte under
`prior_blockers/PACK_1_0_BLOCKER.md`.

## Frozen context

- Branch: `stage/A6/NRM-006-odds-normalisation`.
- Required and observed baseline HEAD:
  `e36ea84cda9e80191a9160d037f8e7035477b9b1`.
- External pack:
  `DMF_PULSE_CODEX_PACK_006_ODDS_NORMALISATION_FOUNDATION_v1.1`.
- Pack manifest SHA-256:
  `6be2a825a90dfa89f7e5ce1da5475c144cb44cee265b33d75396cef3256966e4`.
- Prompt SHA-256:
  `478499ae3f7950fb3a736a0aad870036bb2a8aeb41284aa8543a13bbe52d599e`.
- Pack verification: 79 manifest entries, 80 detached checksums, and 81 actual
  files validated with zero errors.
- Corrected retry fixture SHA-256:
  `f5e85faa12fd1655f70b405c3ddd0cc801edca27c1b0607c5838af6bdeeb68e6`.
- Preserved Pack 1.0 blocker SHA-256:
  `b034541a1d162219a375ff22ba0621d7dd0aa9b2793babbd26969c2fa933ea84`.
- Docker Engine 29.6.2, Compose 5.3.1, pinned
  `postgres:18.4-bookworm`, and server PostgreSQL 18.4 verified.
- Inherited Alembic head: `20260725_0004`.
- Inherited regression: 882 passed in 131.77 seconds with zero skips.
- Network/credential policy: synthetic fixtures, fake transports, scripted
  clocks, and injected sleepers only; never a live provider request or real
  credential.

## Scope and allowed change map

Changes are bounded to the mandatory ODD-005 temporal, mapping, retry,
duplicate, provenance, and mapping-validity remediations plus the NRM-006
normalisation vertical slice. Allowed areas are odds ingestion and markets
production code, the directly required data-model/database migration and CLI,
versioned provider/normalisation policy, public contracts, manifest-approved
synthetic fixtures, tests, portable verification/review tooling, ticket
contracts/evidence, and this repository execution plan. Prior migrations stay
immutable and no new dependency is permitted.

Excluded areas remain live transport, real credentials, additional providers,
raw odds redistribution, Shin production, exchanges, player props, other
market families, calibration/training, forecasting, FPL points, transfers,
chips, optimisation, scheduler, API, UI, and betting action/advice.

## Invariants

- `observed_at`, `received_at`, and post-commit attested `usable_at` remain
  distinct UTC facts; no receipt-derived offsets or backdating.
- One immutable publication batch atomically contains canonical activation;
  strict reads require its separately committed immutable attestation.
- Every strict replay carries one explicit `mapping_cutoff`; valid time,
  system-known time, aliases, and fixture schedule state are resolved at that
  cutoff.
- Synthetic evidence remains TEST_ONLY and cannot create authoritative
  `official_fpl` mappings.
- Partial quota headers remain invalid. A 429 sleeps through an injected
  bounded policy only when attempt, quota, and total-deadline budgets permit.
- Source-scale Decimal odds remain unchanged. All accepted mathematical work
  uses local Decimal precision 60, HALF_EVEN, exactly 256 power bisections, and
  the frozen 12-place residual rule.
- Books are operator-specific, complete full-time HOME/DRAW/AWAY only.
  Consensus is equal canonical-operator weight.
- Normalisation inputs, results, warnings, exclusions, policy, code identity,
  mappings, and source observations remain immutable and hash-addressed.
- PostgreSQL 18.4 is the only integration database; no SQLite substitute.

## Ordered checkpoints

1. **Frozen contracts and canaries** - install the NRM-006 ticket, acceptance
   contract, public schemas, policy, manifest-approved fixtures/oracles, and
   exact authority-resolution evidence. Add failing contract tests before or
   alongside behavior changes.
2. **Truthful activation and historical mapping** - refactor odds promotion
   into prepared work, atomic batch activation, post-commit clock attestation,
   conservative repair, and strict attestation-aware reads. Carry
   `mapping_cutoff` through fixture/team/operator/alias/schedule resolution and
   persist mapping-plan approval/evidence lineage.
3. **ODD-005 P2 hardening** - add complete-header-preserving 429 delay policy
   with injected clock/sleeper and safe evidence; preserve independent
   reobservations; emit duplicate warning/count; prevent synthetic-to-official
   provenance; replace date literals with context/open-ended validity policy.
4. **Pure normalisation and consensus** - implement typed Decimal models,
   source-scale validation, raw implied/proportional/power algorithms, exact
   public rounding, typed fallback, completeness/staleness filtering,
   per-operator normalisation, equal-weight consensus, disagreement, bounds,
   freshness, confidence, and frozen golden projections.
5. **Immutable persistence and migration** - add revision `20260803_0005`
   descending directly from `20260725_0004`; persist policy, runs, operator and
   consensus results, outcome vectors, exclusions/warnings, source lineage,
   publication attestations, deterministic signatures/hashes, immutability,
   and concurrency-safe reuse. Prove upgrade/downgrade/re-upgrade and schema
   fingerprint stability.
6. **Public API, CLI, wheel, and portable verification** - expose the approved
   library functions/enums and `dmf market normalise`; keep CLI and library
   output identical and schema-valid; add golden, temporal, migration,
   installed-wheel, coverage, acceptance, and review-pack tools.
7. **Assurance and finalization** - pass focused and full tests with zero skips,
   Ruff, strict mypy, migration/concurrency, >=90% overall branch coverage,
   >=95% critical paths, 100% mathematical core branch coverage, secret/rights
   scans, and independent read-only P0/P1 review. Commit only after green
   preacceptance, run all 32 literal commands with measured evidence, ensure a
   clean tree, and validate the maximum-20-root-file review ZIP by CRC,
   manifest, and detached checksums.

## Test-first map

- Unit/property/golden: Decimal boundaries, global-context isolation, 256-step
  power solver, vector residuals, fallback, completeness, grouping,
  staleness, consensus, bounds, disagreement, confidence, and exact oracle
  projections.
- Contract/security: schemas, public API/CLI parity, complete quota headers,
  bounded Retry-After/default/deadline paths, no real sleep/network, safe
  evidence, provenance separation, rights gates, secret/body canaries.
- PostgreSQL integration: activation/attestation failure and repair,
  processing-crosses-cutoff, future mappings/aliases/kickoff, repeated equal
  observations, immutable normalisation lineage, as-of stability, concurrent
  same-signature reuse/corrections, migration matrix, and schema fingerprint.
- Packaging: installed wheel outside the source tree runs replay,
  observations, and normalisation using only synthetic stored data.

## Acceptance and evidence

Preacceptance verification recorded 1,175 tests passing with zero skips before
the final four boundary-oracle additions, followed by 48/48 focused tests.
PostgreSQL verification recorded 63/63 migration tests, 8/8 cache/concurrency
tests, and 85/85 integration-marker tests. The independently materialized
coverage gate now records 90.081919% repository branch coverage, 96.296296%
temporal-mapping coverage, 100% persistence coverage, and 100% mathematical
core branch coverage. Ruff, strict mypy, lock/spec/repository validation,
secret scanning, wheel, golden, temporal, and migration-matrix checks are
green.

Run the 32 commands from `22_ACCEPTANCE_COMMANDS.txt` literally and record each
command, start/end/duration, exit code, and actual result. Command 23 must match
the frozen happy-path semantic projection. Command 30 must be empty after the
completion commit/evidence finalization. Command 32 runs even after any earlier
failure. Build and independently validate
`review_pack/NRM-006/DMF_PULSE_NRM-006_REVIEW.zip` with no more than 20 root
files, no nested entries, complete baseline patch, valid CRC, archive manifest,
and detached SHA-256 checksums.

## Risks and fail-closed behavior

- Post-commit attestation is intentionally two-phase: a committed but
  unattested batch is durable yet invisible to strict reads. Recovery can only
  attest with a newly sampled later time.
- Decimal exponentiation failures must be typed and fall back only as frozen;
  malformed or incomplete books never receive invented probability vectors.
- Concurrency must reuse only exact input signatures and must never collapse a
  later source-observation event into earlier lineage.
- Stop and record exact evidence on any remaining contract/oracle conflict,
  rights ambiguity, unavailable required historical state, real credential or
  network requirement, unapproved dependency/interface change, non-reversible
  migration, or inability to prove deterministic cutoff-safe behavior.
