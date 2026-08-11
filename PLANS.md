# DMF Pulse execution plans

## MIN-007R5F1 - registry identity and publication atomicity remediation

- Ticket/stage: `MIN-007R5F1`, A7; required parent `7ed2379f551690f04b85dc53a45237f649990894`.
- Scope: close only AUDIT-007-3 findings 1-5: typed semantic hash allowlists, atomic/complete dataset lineage, model artifact conflict truthfulness, prediction graph atomicity/completeness, and recomputed output identity.
- Constraints: preserve frozen B-G identities and Alembic head `20260807_0006`; no fixes for findings 6-12, no new migration revision, no MIN-007H.

### MIN-007R5F1 checkpoints

- [x] Implement typed registry normalization, DB-gated completeness, conflict checks, publication state/atomicity, and output-hash recomputation with focused regressions.
- [x] Run all 20 literal acceptance commands, record evidence, tear down PostgreSQL, and create the single bounded ticket commit.

## MIN-007G - final minutes projection, synthetic evaluation and CLI

- Ticket/stage: `MIN-007G`, A7; required parent `9ca984b785b681531b7c0648cfbbb45c436dc075`.
- Scope: compose the accepted C/D/E outputs into strict public player/team projections, freeze synthetic evaluation, persist final projections/evaluations through the MIN-007F reserved tables, and expose the TEST/REPLAY availability CLI.
- Constraints: no migration, no Stage-8 logic, no live provider/network/credential access, preserve all frozen B/C/D/E/F identities and Alembic head `20260807_0006`.

### MIN-007G checkpoints

- [x] Read and validate the G pack; confirm branch, parent, clean worktree, and Alembic head.
- [x] Implement pure projection, pipeline, evaluation, strict public models, fixture loader, and CLI with focused tests.
- [x] Integrate final projection/evaluation persistence without changing the F schema.
- [x] Run all 24 literal acceptance commands, collect evidence, remove PostgreSQL, and create exactly one bounded ticket commit.

## MIN-007F - PostgreSQL registry, persistence and historical as-of

- Ticket/stage: `MIN-007F`, A7; required parent `0e3b21a702fece94cb0ee6d61867e6fb17574d0a`.
- Scope: immutable dataset/example lineage, model/evaluation registry, prediction bundle persistence, exact numeric database constraints, concurrency-safe idempotency, and historical as-of lookup.
- Constraints: preserve frozen B/C/D/E identities; no final minute mixture, evaluation calculation, CLI, provider, Stage-8, or Stage-9 code.

### MIN-007F checkpoints

- [x] Implemented registry hashes, PostgreSQL migration `20260807_0006`, persistence repositories, and focused tests.
- [x] Ran all 22 literal acceptance commands, recorded evidence, tore down PostgreSQL, and prepared the single bounded ticket commit.

## MIN-007R4 - exact Decimal boundary hardening

- Ticket/stage: `MIN-007R4`, A7; required parent `1ea36d831e18157a669b257a3761f8a9c9a5cdf7`.
- Scope: context-independent exact stored minute-PMF simplex/correction, exact candidate START+BENCH inequality, adversarial regressions, and ticket evidence.
- Constraints: preserve frozen precision-60 calculations and B/C/D/E identities; no sampler, mixture, persistence, CLI, provider, network, or MIN-007F work.

### MIN-007R4 checkpoints

- [x] Implemented the shared exact finite-Decimal invariant utility and focused boundary probes.
- [x] Ran all 15 literal acceptance commands, recorded evidence, and prepared the single bounded ticket commit.

## MIN-007R3E - harden coherent lineup invariants

- Ticket/stage: `MIN-007R3E`, A7; required parent `9848c3ff3d68d75e31ffa55085ff033177aec312`.
- Scope: one-to-one candidate identity, context-independent weight constraints, strict seed suffixes, and truthful projected-result validation.
- Constraints: preserve frozen B/C/D/E identities and race algorithm; do not begin MIN-007F.

### MIN-007R3E checkpoints

- [x] Implemented the four AUDIT-007-2 lineup remediations and focused adversarial probes.
- [x] Run all acceptance commands, record evidence, and create the single bounded ticket commit.

## MIN-007R3D - harden conditional minute invariants

- Ticket/stage: `MIN-007R3D`, A7; required parent `64f6b168db496c6c3aabe39dda82ad7843266a2a`.
- Scope: exact stored Decimal conditional-PMF simplex, UUID-shaped example duplicate identity, and validated minute-result copy boundaries.
- Constraints: preserve frozen B/C/D/E identities; do not modify `lineup.py` or begin MIN-007F.

### MIN-007R3D checkpoints

- [x] Implemented the three assigned AUDIT-007-2 D remediations and focused adversarial tests.
- [x] Run all acceptance commands, record evidence, and create the single bounded ticket commit.

## MIN-007E - coherent lineup sampler

- Ticket/stage: `MIN-007E`, A7.
- Required branch/parent: `stage/A7/MIN-007-basic-minutes-model` from `60c583aa5dafff90aeaf2647d2b6cf9eeef950e9`.
- Scope: deterministic Decimal exponential-race sampling of coherent 11-player lineups and configured benches.
- Constraints: preserve accepted A/B/C/D identities; no minute-PMF coupling, overall minute projection, persistence, CLI, evaluation, network, provider, or credential work.

### MIN-007E checkpoints

- [x] 2026-08-10 - Implemented the exact four-phase Decimal sampler, typed projected/blocked results, semantic scenario hashes, and focused tests.
- [x] 2026-08-10 - Ran all 15 literal acceptance commands with zero final failures, recorded evidence, and prepared the exact ticket commit pending final clean-tree verification.

## MIN-007D - conditional minutes PMFs

- Ticket/stage: `MIN-007D`, A7.
- Required branch/parent: `stage/A7/MIN-007-basic-minutes-model` from `6d31e3e46a9f3609efab9a2a9ca28f269b5ef6bb`.
- Scope: fit typed Decimal START/BENCH minute priors and predict cutoff-safe conditional 91-point minute PMFs.
- Constraints: preserve accepted A/B/C/R1/R2 and NRM identities; no coherent sampler, public role marginals, overall player PMF, persistence, CLI, evaluation, network, provider, or credential work.

### MIN-007D checkpoints

- [x] 2026-08-10 - Implemented Decimal position/role minute priors, cutoff-safe conditional PMFs, reduced synthetic weighting support, and focused unit/property/golden tests; frozen artifact and independent canaries pass.
- [x] 2026-08-10 - Ran all 15 literal acceptance commands with zero final failures, recorded evidence, and prepared the exact ticket commit pending final clean-tree and review-pack validation.

## MIN-007R2 - explicit new-signing identity override

- Ticket/stage: `MIN-007R2`, A7.
- Required branch/parent: `stage/A7/MIN-007-basic-minutes-model` from `11acd4a0f7eee89a7c59ca5209dfa89999627145`.
- Scope: require explicit validated boolean `new_signing: true` for distinct canonical player-ID overrides and add direct identity/evidence-ownership regressions.
- Constraints: preserve all accepted A/B/C/R1 and NRM identities; no 007D work, dependency, network, provider, credential, database, migration or CLI changes.

### MIN-007R2 checkpoints

- [x] 2026-08-10 - Added the distinct-identity guard and direct missing/false/true/collision/cold-start/same-UUID regressions.
- [x] 2026-08-10 - Ran all 13 literal acceptance commands with zero final failures, recorded evidence, and prepared the exact ticket commit pending final clean-tree verification.

## MIN-007R1 - AUDIT-007-1 remediation

- Ticket/stage: `MIN-007R1`, A7.
- Required branch/parent: `stage/A7/MIN-007-basic-minutes-model` from `2be9852da08913a07678bd6235edbe56d6a4664d`.
- Scope: strict UTC timestamp boundaries, shared history identity validation, full-precision Decimal role utilities, canonical-ID override collision rejection and concrete frozen-schema negative tests.
- Constraints: preserve all accepted A/B/C hashes, canaries, coefficients and NRM schemas; no 007D work, dependency, network, provider, credential, database, migration or CLI changes.

### MIN-007R1 checkpoints

- [x] 2026-08-09 - validated the remediation pack, reproduced all four P1 probes, implemented the five narrow remediations and added direct regression coverage.
- [x] 2026-08-09 - ran all 16 literal acceptance commands with zero failures, recorded evidence, and prepared the single frozen-parent remediation commit pending final clean-tree verification.

## MIN-007C - regularised role baseline

- Ticket/stage: `MIN-007C`, A7.
- Required branch/parent: `stage/A7/MIN-007-basic-minutes-model` from `d54eae162386901f9710d7212b5dfb89174cfa31`.
- Scope: fit frozen position START/BENCH/OUT priors and produce cutoff-safe internal role sampling utilities with explicit confidence metadata, manager/preseason weighting and trusted hard-ineligibility handling.
- Constraints: no PMFs, coherent lineup sampler, public coherent marginals, persistence/migration, CLI, evaluation, dependency, network/credential, or redesign of MIN-007A/MIN-007B.

### MIN-007C checkpoints

- [x] 2026-08-09 - validated Pack 007C (`21` manifest entries; frozen artifact and nine-canary oracle PASS), confirmed the exact MIN-007B parent and clean preflight, and read the frozen role contract/oracles.
- [x] 2026-08-09 - implemented the pure Decimal role baseline, reproduced the frozen artifact and nine canaries, passed the 13-command ledger, and prepared the exact bounded commit with clean-tree verification pending after commit.

## MIN-007B - cutoff-safe minutes training dataset builder

- Ticket/stage: `MIN-007B`, A7.
- Required branch/parent: `stage/A7/MIN-007-basic-minutes-model` from `84697a464af17a909e28a6870d764617098fc30a`.
- Scope: create the pure, deterministic, synthetic-history-to-TRAIN-dataset slice with explicit role/minutes labels, cutoff-safe eligibility, canonical ordering, duplicate rejection and semantic hashing.
- Constraints: no role model, PMFs, lineup sampler, persistence/migration, CLI, evaluation, dependency, network/credential, or MIN-007A market changes.

### MIN-007B checkpoints

- [x] 2026-08-09 - validated Pack 007B (`17` hashed files; frozen dataset oracle PASS), confirmed the exact MIN-007A parent and clean worktree, and read the D1-D9 contract and stop rules.
- [x] 2026-08-09 - implemented and verified the pure cutoff-safe builder against the frozen 368-row oracle, passed the literal acceptance ledger, and prepared the exact bounded commit with clean-tree verification pending after commit.

## MIN-007A - NRM public-contract and confidence hardening

- Ticket/stage: `MIN-007A`, A7.
- Required branch/parent: `stage/A7/MIN-007-basic-minutes-model` from `253baf3f19661a5704bb1fad2f7ac60e1db288eb`.
- Scope: install the three supplied superseding NRM public schemas, preserve the probability dependency, and separate ordinary degradation evidence from blocking confidence warnings without changing NRM math, policy, freshness, persistence, or database objects.
- Constraints: offline synthetic fixtures only; no provider/network/credential, dependency, migration, minutes model, broad refactor, push, merge, rebase, reset, tag, or amend.

### MIN-007A checkpoints

- [x] 2026-08-09 - validated Pack 007A (`23` hashed files), confirmed the exact branch/parent and clean worktree, read the frozen H1/H2 contracts, and passed the pre-edit focused NRM contract/unit/golden suite (`73 passed`).
- [ ] Final - install exact schemas, add negative and canary regressions, pass all literal commands, commit with the exact ticket message, and leave the worktree clean.

## NRM-006 - odds normalisation and consensus baseline

- Ticket/stage: `NRM-006`, A6.
- Required branch/baseline: `stage/A6/NRM-006-odds-normalisation` from `e36ea84cda9e80191a9160d037f8e7035477b9b1`.
- Outcome: close every frozen ODD-005 temporal/provenance finding, then transform complete operator-specific full-time 1X2 observations into exact raw implied, proportional, power, equal-operator consensus, uncertainty, freshness, confidence, and immutable as-of output.
- Constraints: offline synthetic/fake/scripted inputs only; no real credential, additional provider, raw odds redistribution, Shin production, exchange/player-prop/other market family, learned calibration, forecast, optimiser, scheduler, API/UI, new dependency, SQLite, push, merge, rebase, reset, tag, or amend.

### NRM-006 checkpoints

- [x] 2026-08-06 - validated corrected Pack 1.1 (79 manifest entries, 80 detached checksums, zero errors), exact branch/base and sole permitted Pack 1.0 blocker residue, complete corrected quota fixture, Docker/Compose/PostgreSQL 18.4, Alembic head `20260725_0004`, and the inherited suite at 882 passed with zero skips.
- [x] NRM-006.0 - preserved the Pack 1.0 blocker byte-for-byte and recorded Pack 1.1 quota and post-commit-attestation authority resolution.
- [x] NRM-006.1 - implemented post-commit publication attestation and cutoff-safe historical mapping across odds promotion and strict reads.
- [x] NRM-006.2 - closed 429 retry, synthetic provenance, duplicate-evidence, reobservation-lineage, and mapping-validity findings.
- [x] NRM-006.3 - implemented exact Decimal proportional/power normalisation, operator grouping, consensus, uncertainty, freshness, confidence, and frozen goldens.
- [x] NRM-006.4 - added immutable PostgreSQL persistence, reversible `20260803_0005` migration, as-of/cache/concurrency guarantees, CLI/API, wheel, and assurance tooling.
- [x] 2026-08-06 - passed pre-commit Ruff, strict mypy, PostgreSQL migration, golden, temporal, installed-wheel, security, critical-coverage, and full-suite gates; the final full regression recorded 1,056 passed with zero skips before the fail-closed Windows entry-point hardening, whose focused unit and installed-wheel checks also passed.
- [x] 2026-08-06 - closed the subsequent independent P1 audit findings: post-commit clock ownership, single-budget retry/quota behavior, canonical duplicate identity, historical mapping/rights/quality revalidation, operator/fixture grouping, policy-driven confidence, code/dependency identity, relational lineage, and correction concurrency. The post-remediation full suite, migration/concurrency matrix, static gates, and focused security/temporal checks passed with zero skips; a final independent read-only audit found no remaining P0/P1 issue.
- [x] 2026-08-06 - the first literal acceptance run passed commands 1-25, then command 26 exposed that its fresh wheel database seeded the FPL schedule after the requested market cutoff. Preserved the strict temporal rejection, changed only the verifier to import the approved synthetic schedule before the cutoff, and proved the isolated installed wheel end to end before restarting the complete ledger.
- [ ] Final - resolve independent P0/P1 review, commit the green ticket, run all 32 literal acceptance commands, and validate the capped root-only review ZIP.

### NRM-006 decision log

- Pack 1.1 preserves the inherited all-or-nothing quota-header rule and corrects the frozen retry fixture; partial evidence stays invalid.
- Strict eligibility requires an immutable post-commit attestation. Canonical activation and USABLE lifecycle commit atomically first; the injected clock is sampled only after acknowledgement, and failed attestation cannot backdate recovery.
- Strict replay uses one explicit mapping cutoff for valid/system-time mappings, aliases, and attested fixture schedule observations. Synthetic evidence is TEST_ONLY and cannot assert official-source verification.
- POWER is primary and PROPORTIONAL is retained baseline/fallback under local Decimal precision 60, HALF_EVEN, exactly 256 bisections, and exact 12-place public vector residual handling.
- Normalise complete operator books separately, then use equal canonical-operator consensus. No cross-operator book, stale fill, learned weight, or future-stage market/model capability is permitted.
- Exact dependency signatures and immutable source-observation IDs govern cache reuse; equal prices from a later retrieval retain distinct run/evidence lineage.

## ODD-005 - FPL remediation and odds-provider foundation

- Ticket/stage: `ODD-005`, A5.
- Required branch/baseline: `stage/A5/ODD-005-odds-provider-foundation` from `7034e38f32cd579c90d35c5fe3f10921c3656be0`.
- Outcome: close the frozen FPL-004 review findings, then ingest manifest-approved synthetic The-Odds-API-shaped EPL 1X2 books into immutable rights/quota/source evidence, explicit canonical mappings, exact Decimal observations, and cutoff-safe as-of queries.
- Constraints: no live provider request or real API key; one provider/competition/region/market only; no name-only merge, probabilities, normalisation, consensus, forecasts, scheduler, API/UI, betting action, new dependency, SQLite, push, merge, rebase, reset, tag, or amend.

### ODD-005 checkpoints

- [x] 2026-07-25 - verified the exact branch/base/clean-tree gates, all 63 detached pack hashes and 62 manifest entries, Docker Desktop/Compose/PostgreSQL 18.4, Alembic head/current `20260724_0002`, and the unchanged inherited suite at 589 passed with zero skips.
- [x] 2026-08-02 - resumed the preserved Pack 1.0 worktree under hash-validated corrected Pack 1.1, resolved the frozen decimal lexical-policy blocker, confirmed the exact branch/base, and passed 90 focused offline plus 19 PostgreSQL migration/ingestion tests before further implementation edits.
- [x] ODD-005.1 - installed the frozen ticket/contracts/schemas/fixtures and completed all six mandatory FPL-004 remediations with direct negative controls.
- [x] ODD-005.2 - implemented the strict provider/client/quota boundary, rights profiles, payload semantics, explicit mappings, and exact domain models.
- [x] ODD-005.3 - added the reversible PostgreSQL market schema, bundle publication guards, immutable persistence, idempotency/concurrency, and deterministic as-of query.
- [x] ODD-005.4 - exposed the approved CLI/public contracts and installed-wheel replay/query/refusal slice.
- [x] ODD-005.5 - passed focused, full, migration, coverage, security, and independent read-only review gates with no unresolved P0/P1 finding.
- [ ] Final - commit the accepted ticket, run all 28 literal commands from a clean commit, record measured evidence, and validate the root-only maximum-20-file review ZIP.

### ODD-005 decision log

- The Odds API v4 is the sole Stage A5 provider; `soccer_epl`, `uk`, and `h2h` are frozen, while all implementation and acceptance transport is fake/offline.
- Provider event and bookmaker keys require explicit provider-scoped mappings; raw labels validate an already resolved identity and never create one.
- Stage A5 stores offered Decimal odds only. Implied probabilities, margin removal, consensus, forecasting, and betting guidance remain excluded.
- `usable_at <= as_of` is the sole eligibility boundary; later retrievals and corrections append history and cannot alter an earlier query result.
- The repository stores Alembic revisions under the ticket-allowed `src/dmf_pulse/database/**` tree; add one ordered revision there and never rewrite a prior revision.
- The mandatory inherited FPL remediations extend existing shared ingestion primitives for rights-decision idempotency, source envelopes, fixture authority, and exit taxonomy. Those bounded shared edits, `PLANS.md` required by repository governance, and the exact-path security-fixture allowlist are contract-enabling changes; they introduce no new provider or future-stage surface.
- Final pre-commit verification: 882 tests passed with zero skips/warnings; combined coverage 93.44%, overall branch coverage 90.18%, and all critical ODD/FPL remediation branch gates 100%; the PostgreSQL 18.4 migration/preservation matrix, installed wheel, secret scan, repository validator, lint, formatting, typing, frozen-input validation, CLI replay/query/refusal, and three independent read-only audits passed.

## FPL-004 - rights-gated official FPL ingestion foundation

- Ticket/stage: `FPL-004`, A4.
- Required branch/baseline: `stage/A4/FPL-004-official-ingestion` from `9b3160a2574d2868b5f26e3a2d429924567510b0`.
- Outcome: remediate DAT-003 lifecycle and relational P1 findings, then ingest approved synthetic FPL-shaped bootstrap/fixtures into immutable retrieval evidence, season-scoped canonical mappings, typed observations, quality records, and a deterministic cutoff-safe source bundle.
- Constraints: no live FPL/provider request, real FPL payload, authenticated endpoint, automated polling, persistent official-profile raw/derived storage, name-only merge, new dependency without approval, SQLite, models, optimiser, API/UI, push, merge, rebase, reset, tag, or amend.

### FPL-004 checkpoints

- [x] 2026-07-24T20:43:21+01:00 - verified exact branch/baseline/clean-tree preconditions, Pack 004 hashes and synthetic fixture oracles, Docker/PostgreSQL 18.4, accepted DAT-003 head/schema, and the 279-test inherited baseline.
- [x] 2026-07-25T09:27:45+01:00 - FPL-004.0: closed every mandatory DAT-003 remediation with reversible PostgreSQL constraints and direct adversarial regression tests.
- [x] 2026-07-25T09:27:45+01:00 - FPL-004.1: implemented immutable versioned Rights Profiles, fail-closed decisions, isolated service-owned volatile copies for ordinary official manual-import paths, crash/concurrency-safe cleanup, and rights-before-transport behavior.
- [x] 2026-07-25T09:27:45+01:00 - FPL-004.2: implemented retrieval envelopes, append-only lifecycle, authority-bound suffix-only resume, pair locking, and derived usability.
- [x] 2026-07-25T09:27:45+01:00 - FPL-004.3: implemented strict bounded payload parsing, schema drift/missingness, season-scoped canonical mappings, immutable observations, quality records, atomic promotion, and cutoff-safe bundles.
- [x] 2026-07-25T09:27:45+01:00 - FPL-004.4: exposed the public CLI and frozen HTTP boundary; 524 tests, strict typing/lint, PostgreSQL migration/concurrency proofs, and 92.30% combined branch coverage pass locally.
- [x] 2026-07-25T12:18:12+01:00 - FPL-004.5 interruption recovery review: resolved installed exit-code propagation, immutable/strict rights parsing, actual system-time resume and bitemporal semantics, atomic honest promotion, A-B-A observation history, exact retrieval bundle manifests, ingestion run/attempt linkage, strict RFC3339 and transport failures, provider/effective configuration lineage, durable pre-parse raw read-back, and false-COMPLETE archive write-ahead evidence. Focused offline suites (178), unit suite (416), and lifecycle/bundle/security PostgreSQL suite (28) pass.
- [x] 2026-07-25T13:25:24+01:00 - FPL-004.6 final stabilization: made temporal canonical supersession source-time ordered, added transactional same-time semantic-observation claims, proved mixed-payload contradiction rollback and old-replay non-supersession, hardened error-body transport translation and installed-wheel fixture replay, and closed detached-log/teardown false-COMPLETE paths. Three independent read-only audits found no unresolved P0/P1. The 589-test preacceptance run exposed one evidence-script import defect; its regression now passes. Actual coverage evidence passes the authority-tiered gates at 91.42% combined, 98.33% critical deterministic, 94.44% rights, 84.62% provider, and 100% cutoff predicates.
- [x] 2026-07-25T13:40:01+01:00 - FPL-004.7 first literal-run finding: commands 1-23 and guaranteed teardown passed, but command 24 preparation failed closed because the privacy scanner found its own lowercase personal-data sentinel in the complete patch after title-case-only redaction. Redaction now removes the full owner name, username, surname, and Windows user paths case-insensitively, including self-referential scanner literals; the focused 17-test review-pack suite, Ruff, and strict mypy pass. A clean full rerun remains required.
- [x] 2026-07-25T13:44:32+01:00 - FPL-004.8 second literal-run finding: commands 1-10 passed, then the pre-PostgreSQL security partition exposed six database-dependent tests inheriting the module-wide `security` marker. The three offline rights/path tests now carry `security` explicitly, while the six already-`postgres` tests remain exercised by literal command 18 and the full suite after command 12. Exact command 11 passes with PostgreSQL down: 6 passed, 6 deselected, zero skips.
- [ ] Final - run all 25 literal acceptance commands, complete ordered self-review, record the final clean commit, and validate the exact 20-file review ZIP.

### FPL-004 decision log

- The supplied rights register is controlling engineering policy, not legal advice. Unknown rights deny; technical reachability never grants permission.
- Only `synthetic_test_v1` authorizes persistent FPL-004 promotion and bundle creation. `fpl_official_private_manual_v1` is bounded transient validation only and blocks transport before any live snapshot request.
- Every retrieval has one immutable envelope and append-only lifecycle. Current state and first `usable_at` are derived; legacy DAT-003 lifecycle columns are compatibility data only for new ingestion.
- Canonical IDs never derive from FPL IDs or names. Provider mappings are provider/resource/type/season scoped, and conflicts quarantine instead of guessing.
- Source-bundle membership is selected from derived `USABLE` state at or before the declared cutoff; provider-generated time is never a substitute.
- No real FPL body may enter Git, PostgreSQL, logs, evidence, or the review ZIP during this milestone.
- Provider and rights JSON are strict packaged runtime authorities. Resume and bundles bind their separate hashes plus one effective configuration hash.
- Equivalent payload pairs share a semantic bundle hash but retain separate immutable exact-manifest bundles and source snapshot membership.
- Commands 24-25 remain `PENDING` in a `BLOCKED` preliminary archive; only measured final records after guaranteed teardown may produce a detached-validator-accepted `COMPLETE` archive.

## DAT-003 - canonical temporal PostgreSQL foundation

- Ticket/stage: `DAT-003`, A3.
- Required branch/baseline: `stage/A3/DAT-003-canonical-foundation` from `f9b51e965aad1bc94796c17c897f0d99b4c16e1b`.
- Outcome: close all blocking RUL-002 findings and deliver a PostgreSQL 18.4 vertical slice for UUIDv7 canonical identity, bitemporal corrections/as-of reads, immutable provenance, rules activation registry, reversible migrations, deterministic CLI, and governed evidence.
- Constraints: disposable local PostgreSQL only; no provider/network access, SQLite, future ontology, models, optimiser, API/UI, account actions, push, merge, rebase, reset, tag, or amend.

### DAT-003 checkpoints

- [x] 2026-07-23T09:00:00Z - verified Pack 003 hashes and exact baseline/branch, captured context evidence, and passed the existing 200-test foundation/rules baseline.
- [x] 2026-07-23T12:00:00Z - closed RUL-002 P1 findings R1-R8 with direct regression tests while preserving corrected v1.1 goldens.
- [x] 2026-07-23T15:00:00Z - added the pinned PostgreSQL/SQLAlchemy/Alembic/Psycopg toolchain, exact 20-table migration, UUIDv7/temporal/provenance constraints, functions, triggers, views, schema fingerprint, and downgrade/re-upgrade checks.
- [x] 2026-07-23T18:00:00Z - implemented explicit repositories and deterministic doctor/schema/demo/as-of CLI with PostgreSQL boundary, concurrent overlap, immutability, rules-registry, clean-wheel, and negative error tests.
- [x] 2026-07-23T20:00:00Z - strengthened independent branch/mutation oracles to meet the 90% overall, 98% rules, and 92% combined data-model/database gates in focused measurement.
- [ ] Final - run the literal 23-command acceptance ledger with guaranteed teardown, generate actual-commit evidence, and validate the exact 20-file review ZIP.

### DAT-003 decision log

- PostgreSQL 18.4 server `uuidv7()` is authoritative for persisted identifiers; application code never manufactures persisted UUIDs.
- Valid time and system-known time are independent closed-open ranges. Corrections close only the superseded system interval and preserve historical rows.
- Source-less initial fixture assignments/revisions are permitted where the public contract makes provenance optional; every correction requires distinct usable provenance.
- `validation_status = USABLE` is equivalent to non-null `usable_at`, enforced in PostgreSQL and typed models.
- The test credential is the literal fake `changeme`; committed settings retain only the `env:DMF_TEST_DATABASE_URL` reference.
- The review command uses stable write-ahead records for commands 22-23, then refreshes the same deterministic archive after finally-guaranteed teardown without invoking command 22 twice.

## RUL-002 — governance remediation and rules foundation

- Ticket/stage: `RUL-002`, A2.
- Required branch/baseline: `stage/A2/RUL-002-rules-foundation` from `12049a7de23a4a8fcca3d219dbcab1bf5e1027ea`.
- Outcome: generic governed evidence, a strict split-YAML rules compiler and lifecycle, pure fixture/Gameweek scoring, deterministic CLI contracts, and a validated review ZIP capped at 20 root files.
- Authority: official target-season rules/provider terms; newest ACTIVE/ACCEPTED DMFP-20 decision; most-specific accepted module; DMFP-00; earlier research; implementation convenience. Ticket contracts are subordinate execution constraints.
- Constraints: offline; no new dependencies; no database/provider/model/optimiser/UI code; no activation or inferred completion of the partial 2026/27 ruleset; no push or merge.

### RUL-002 checkpoints

- [x] 2026-07-22T12:00:00Z — verified the v1.1 correction notice, all pack and fixture hashes, corrected independent oracles, exact baseline/branch/clean-tree preconditions, and the 104-test FND baseline.
- [x] 2026-07-22T14:28:55Z — RUL-002.0: generated the complete 94-entry DMFP-20 index, hash-pinned stage authority requirements, generic ticket/evidence/review contracts, and exact runtime lock graph; authority and assurance targeted tests pass.
- [x] 2026-07-22T14:28:55Z — RUL-002.1: implemented strict safe-subset YAML, exact typed authoring schemas and cross-file coherence, deterministic compilation/hash/diff, in-memory integrity revalidation, and atomic immutable lifecycle gates.
- [x] 2026-07-22T14:28:55Z — RUL-002.2: implemented pure configured scoring/BPS/competition-ranking/Gameweek aggregation; corrected v1.1 goldens plus boundary, property, lifecycle, schema, and false-success mutation probes pass with 98.84% rules branch coverage in the focused run.
- [x] 2026-07-22T15:14:18Z — RUL-002.3: exposed all rules CLI commands, updated package/docs/least-privilege CI, and passed the final precommit quality gate with 200 tests, zero skips, 90.81% overall branch coverage, 98.88% rules branch coverage, frozen-lock validation, clean-wheel verification, repository validation, and secret scanning. The exact 19-command final ledger, actual-commit evidence, and 20-file ZIP are deliberately generated from the clean committed tree into ignored evidence/review paths.
- [x] 2026-07-22T15:19:54Z — RUL-002.4: the first post-commit ledger run exposed a strict-prefix defect for otherwise successful rules commands; changed the generic success summary to the required `PASS:` form and added a focused false-failure regression test before rerunning acceptance from a new commit.

### RUL-002 decision log

- The v1.1 fixture family is immutable input. No v1.0 digest, expected output, or manifest is admissible.
- The checked 2026/27 deltas remain `CAPTURED_UNVERIFIED`; all unannounced rule families are typed blockers, so scoring/activation cannot guess.
- The reference/synthetic scorer consumes only compiled configuration and explicit aggregate scenario facts. Zero-minute Gameweek placeholders are excluded from BPS/bonus ranking.
- `payload_sha256` is the stable detached primary-payload digest. `archive_sha256` is reported only after ZIP creation and cannot be embedded as a self-hash.
- Command 19 is invoked exactly once against a write-ahead ledger; after the invocation, its measured duration replaces the provisional entry and the same assembler refreshes the final archive without rerunning the CLI command. Final archive digest/CRC evidence remains external to avoid self-reference.
- Two narrow ticket-required changes fall outside the enumerated `allowed_areas`: `src/dmf_pulse/__init__.py` is the existing canonical version source that must become `0.2.0`, and `.gitignore` must exclude regenerable RUL evidence so COMPLETE evidence can name the actual commit while the final tree remains clean. No other out-of-list path is changed.

---

# FND-001 historical execution plan

## Ticket and outcome

- Ticket: `FND-001`, Stage A0/A1 foundation milestone
- Branch: `stage/A1/FND-001-foundation`
- Owner: Sebastian Greenhalgh
- Implementation lead: Codex
- Independent reviewers: fresh read-only scope/security/test-gap review before acceptance
- Observable outcome: a governed, reproducible Python 3.13 workspace with an installed `dmf` CLI, strict configuration, diagnostics, first-party assurance tooling, CI, machine-valid evidence, and a review ZIP capped at 20 root files.

## Authority and decisions

- Precedence: accepted DMFP-20 decisions; FND-001 ticket/acceptance details; most-specific DMFP module; DMFP-00; implementation playbook/repository guidance.
- Controlling decisions: `ADR-PROD-004`, `ADR-GOV-001`, `ADR-GOV-002`, `ADR-GOV-004`, `ADR-RES-001`, `ADR-DATA-002`, `ADR-SRC-001`, `ADR-IMPL-001`, `ADR-IMPL-002` (provisional), and `ADR-IMPL-003`.
- Primary locators: DMFP-19 §7 Stage 1; DMFP-17 §§0.5, 0.8–0.9, and 4; DMFP-20 §0 and the decision blocks above; FND-001 acceptance and review-pack contracts.

## Baseline

- Captured before all other repository changes at `evidence/tickets/FND-001/baseline_manifest.json`.
- Existing Git HEAD: `44e63a9f2acf6627912f9a0b6d5173553db0895f` (empty initial commit).
- Existing non-`.git` files: zero.
- Remote owner parsed unambiguously as `sebgreenhalgh`; no remote mutation is authorised.
- Pack integrity: all 42 files listed by `PACK_MANIFEST.json` matched expected bytes and SHA-256.

## Ordered checkpoints

1. Install all 21 approved DMFP documents verbatim, install the implementation playbook, generate authority/document/decision manifests, and validate hashes/references/DMFP-04 edition.
2. Add concise governance, ticket records, schemas, security/contribution guidance, cross-platform operations documentation, and CODEOWNERS derived only from the remote.
3. Add the Python 3.13 `src/` package, Hatchling build, canonical `0.1.0` version, approved dependencies, exact uv lock, and clean-wheel verifier.
4. Implement and test strict Pydantic v2 configuration, deterministic overlays/redaction, Typer CLI, injected clock/process boundaries, and nonblocking hardware diagnostics.
5. Implement canonical JSON/hashing, typed evidence models/validation, manifest/repository validation, secret scanning, deterministic baseline diffing, and capped review-pack creation.
6. Complete unit/property/golden/integration coverage with offline/home isolation and achieve at least 90% branch coverage for `dmf_pulse`.
7. Add least-privilege Ubuntu CI plus scheduled/manual Windows smoke; mirror local uv/Python commands.
8. Run every mandatory command literally, record command/exit/duration evidence, conduct ordered read-only self-reviews, fix material findings, and generate/validate the final ZIP.

## Test map

- Package/CLI: installed version, installed module path, `py.typed`, JSON and human rendering, stable exit/error codes.
- Configuration: strict fields, required/malformed values, overlay precedence, path normalization, timezone/log/device validation, raw-secret rejection, deterministic/redacted output, no directory creation.
- Doctor/system: injected time/processes, safe write probe cleanup, timeout/truncation, GPU absence healthy, no identity/secret fields.
- Assurance: canonical hash stability, hash mismatch/missing/duplicate/stale reference/paid-DMFP-04 failures, schema failures, fake-secret shapes and allowlisting, review-pack 21-file refusal and detached-manifest hashes.
- Isolation: package imports cannot invoke network/subprocess/write/environment mutation; tests use no network or user home.

## Acceptance commands

The 13 literal commands in `03_ACCEPTANCE_CONTRACT.md` are mandatory, followed by installed-wheel `dmf --version` and `dmf doctor --json` in a fresh environment outside the repository. Every invocation will be recorded separately with command, exit code, duration, and concise result.

## Risks and safe fallback

- Local `python`/`uv` execution may require the approved absolute uv path because managed sandbox policy denied PATH-resolved executables; use the sanctioned uv installation and request only the narrow dependency/network permission if resolution fails.
- Zoneinfo data on Windows can vary; validation must use the Python 3.13 runtime’s available `zoneinfo` data and provide actionable failure output without adding an unapproved runtime dependency.
- Review ZIP output is requested both in-repository and beside the source pack; generate and validate in-repository first, then copy the final ZIP to the external requested destination without changing Git history.

## Progress

- [x] 2026-07-22T09:11:21Z — inspected Git status, remote, branches, HEAD, and empty tree.
- [x] 2026-07-22T09:11:21Z — captured deterministic empty-repository baseline as the first artifact.
- [x] 2026-07-22T09:11:21Z — read the controlling pack in the mandated order and verified all 42 pack hashes/byte counts.
- [x] 2026-07-22T09:20:00Z — Checkpoint 0 complete: installed 21 exact DMFP files plus playbook, generated three governed manifests, and passed the first-party validator with zero errors.
- [x] 2026-07-22T09:20:39Z — Checkpoint 1 complete: added governance, proprietary licensing, ticket records, Codex contracts, owner-derived CODEOWNERS, and cross-platform operational documentation; manifest validation remained green.
- [x] 2026-07-22T09:48:18Z — Checkpoint 2 complete: uv resolved 29 packages for Python 3.13.9, frozen sync passed, and the wheel verified `py.typed`, installed module provenance, version, doctor, and cleanup outside the source tree.
- [x] 2026-07-22T09:48:18Z — Checkpoint 3 complete: strict configuration, deterministic overlays/redaction, path/timezone/reference semantics, and no-create loading passed targeted unit/property tests.
- [x] 2026-07-22T10:50:31Z — Checkpoint 4 complete: deterministic CLI/doctor contracts, privacy-minimized bounded probes, missing-config blocking, safe CPU fallback, and installed default timezone validation passed.
- [x] 2026-07-22T10:50:31Z — Checkpoint 5 complete: canonical evidence/hashing, fail-closed secret scan, manifest integrity, detached primary-payload digest, atomic capped review ZIP, and negative tamper tests passed.
- [x] 2026-07-22T10:50:31Z — Checkpoint 6 complete: 103 offline tests passed with 288/318 branches covered (90.57%) and strengthened import/network/write/logging false-success traps.
- [x] 2026-07-22T10:50:31Z — Checkpoint 7 complete: least-privilege Ubuntu CI, scheduled/manual Windows smoke, exact frozen commands, cross-platform documentation, and clean-clone package verification are in place.
- [x] 2026-07-22T10:54:29Z — Checkpoint 8 complete: all 14 literal mandatory commands passed, three independent read-only reviews were resolved, machine evidence validated, and a root-only 20-file bootstrap review ZIP passed full detached hash validation before final clean-HEAD assembly.

## Decision log

- Use only ticket-sanctioned Python 3.13, uv, Hatchling, Pydantic v2, Typer, PyYAML, Ruff, mypy, pytest, Hypothesis, coverage, and build.
- Use a scheduled/manual Windows smoke workflow to conserve private-repository CI minutes.
- Install `DMFP-04_DATA_SOURCES_MARKETS_APIS_AND_LICENSING_ZERO_COST_v1.0.txt` only; the validator rejects any other DMFP-04 filename/version/hash.
- Use a detached review-manifest convention: the manifest hashes every ZIP member except itself; `SHA256SUMS` hashes all other members, including the manifest.
- Treat `pytest-cov` as the unavoidable development adapter implied by the mandatory `pytest --cov` acceptance command; it adds no runtime dependency and delegates measurement to the already sanctioned coverage.py.
- Include Hatchling in the locked development group as the sanctioned build backend so its exact resolved version and transitive build dependencies are captured in `uv.lock`.
- Pin the isolated build backend to uv-resolved Hatchling 1.31.0 and keep that exact version in the development lock, preventing build-environment drift.
- Bundle the single public-domain IANA tzdata 2025b `Europe/London` TZif payload with an enforced SHA-256 so stock Windows Python can validate the sanctioned default without an unapproved runtime dependency.
- Define `codex_result.review_pack.sha256` as the detached digest of stable primary review files 04-05 and 07-19; publish the separately validated final archive SHA-256 externally because an archive cannot contain its own digest.
- Read-only self-review found no authority/scope P0 issue and drove fixes for credential-shape leakage, CPU fallback coercion, fail-open scan coverage, PEM detection, missing-config doctor false health, Windows timezone portability, branch-metric reporting, clean-clone package provenance, evidence semantic checks, and atomic review placement.
