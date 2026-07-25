# FPL-004 implementation plan

Updated: 2026-07-25T13:25:24+01:00

## Frozen context

- Branch: `stage/A4/FPL-004-official-ingestion`
- Required and observed baseline HEAD: `9b3160a2574d2868b5f26e3a2d429924567510b0`
- External pack: `DMF_PULSE_CODEX_PACK_004_FPL_INGESTION_FOUNDATION`
- Pack manifest SHA-256: `dbd177d9b2e9b3eb4f3235759661b0f7956c70061247a47d2ef2c11623e0dd60`
- Controlling prompt SHA-256: `61f2b7398c60495118286bfd7c75dc6998ca6d0eec368e5be15d107a67490809`
- Pack verification: 59 manifest entries and 60 detached checksums verified with zero errors.
- Inherited regression: 279 tests passed without coverage against local PostgreSQL 18.4.
- Inherited Alembic head: `20260723_0001`.
- Inherited schema manifest SHA-256: `b85e36bbc457054125df884b0ed107591a93182f20e6308fe1b9cb3d7a9bf7ea`.
- Network policy: no live FPL or provider requests; synthetic fixtures and local PostgreSQL only.

## Allowed change map

Changes remain confined to the FPL-004 ticket allowlist: the next Alembic revision and directly
required migration metadata; `config/providers/**`; `config/rights/**`;
`src/dmf_pulse/ingestion/**`; directly required `data_model`, `database`, and CLI integration;
FPL fixtures/tests; FPL-004 evidence and ticket documents; directly required ADR/manifests,
portable scripts, `Makefile`, `compose.test.yaml`, CI workflows, `pyproject.toml`, and `uv.lock`.
Unrelated modules and future-stage provider, scheduler, modelling, scoring, optimisation, UI, and
authenticated-manager functionality are read-only and out of scope.

## Checkpoints

1. **DAT-003 mandatory remediation** — add append-only processing events and derived lifecycle;
   enforce competition/season fixture coherence; make the schema hash semantic-only; strengthen
   ruleset identity and data-quality subjects; separate raw-content rights from metadata rights.
2. **Contracts, rights, and fixtures** — install the supplied FPL-004 ticket/contracts, public
   schemas, conservative rights profiles, provider configuration, and verified synthetic fixtures
   without importing persistent real payloads.
3. **Strict parsing and transport boundary** — implement byte/depth/duplicate-key safe JSON,
   bootstrap/fixture models, drift classification, deterministic fingerprints, allowlisted HTTP
   construction, typed failures, timeouts, bounded output, and an injected offline transport.
4. **Migration and persistence** — add one linear reversible migration for FPL season entities,
   lifecycle events, immutable observations, bundles/members, quality subjects, rights records,
   and database constraints/indexes required by the contracts.
5. **Mapping and ingestion service** — implement provider-season-scoped canonical mapping,
   raw-first and raw-forbidden paths, monotonic lifecycle/resume, idempotent semantic effects,
   changed-observation append behavior, cutoff-safe promotion, deterministic quality, and exact
   two-member source bundles.
6. **Public CLI** — add deterministic JSON/human commands for validate, import, replay, resume,
   bundle show, and fail-closed snapshot; preserve the contracted exit-code taxonomy and redact
   paths, payloads, URLs, credentials, and exception text.
7. **Assurance** — add unit/property/contract/security/PostgreSQL/concurrency/migration tests,
   installed-wheel replay, schema/oracle checks, repository validation, secret scanning, and CI
   parity. Run targeted checks after each implementation checkpoint.
8. **Acceptance and review** — execute every literal command in `22_ACCEPTANCE_COMMANDS.txt`, run
   migration upgrade/downgrade/re-upgrade and clean-wheel verification, capture exact command
   evidence, perform focused self-review and independent read-only review, fix all material
   findings, and build/validate the capped 20-file FPL-004 review ZIP.

## Progress

- 2026-07-25T09:27:45+01:00 - checkpoints 1-3 complete: installed the FPL contracts/configuration/fixtures; closed mandatory DAT-003 schema remediations; implemented strict payload parsing, frozen transport, immutable rights/envelopes, append-only lifecycle, and authority-bound suffix-only resume.
- 2026-07-25T09:27:45+01:00 - checkpoints 4-6 complete: implemented season-scoped mapping, immutable semantic observations, atomic quality/usability/bundle promotion, raw-forbidden temporary-file destruction, deterministic CLI errors, and first-party evidence/review validation.
- 2026-07-25T09:27:45+01:00 - checkpoint 7 verification: migration base/head and populated downgrade/re-upgrade matrix passed; all 524 tests passed with zero skips and 92.30% combined branch coverage; Ruff and strict mypy passed. Final literal acceptance ledger and clean-tree review archive remain pending.
- 2026-07-25T12:18:12+01:00 - interruption recovery review complete: reconstructed the work from repository evidence, reran the migration matrix, resolved lifecycle clock/promotion/history/bundle/run-linkage, rights/config/parser/client/manual-file/raw-readback, installed exit-code, CI/spec-validation, and review write-ahead findings. Focused offline tests (178), all unit tests (416), focused PostgreSQL lifecycle/bundle/security tests (28), Ruff, and strict mypy pass. Independent current-tree re-review, the clean ticket commit, literal 25-command ledger, and final ZIP validation remain pending.
- 2026-07-25T13:25:24+01:00 - final stabilization review complete: source-time temporal ordering and non-empty successor ranges now prevent stale replay supersession; immutable semantic-observation claims make same-time contradictions fail atomically before publication; installed-wheel fixture replay and HTTP error-body failures are typed; and COMPLETE evidence now requires exact measured command, teardown, detached-log, manifest, and checksum agreement. Independent ingestion, migration, acceptance, and coverage audits found no unresolved P0/P1. The ticket-specific coverage checker replaces the unsupported 95% whole-ingestion aggregate with the controlling tiered gates and records whole-ingestion coverage separately. A 589-test preacceptance run reached all suites; its sole evidence-script import failure was repaired and the focused regression passes. Current actual gates are 91.42% combined, 98.33% critical deterministic, 94.44% rights, 84.62% provider, and 100% cutoff-predicate branches. The clean ticket commit, literal 25-command ledger, and final ZIP validation remain pending.

- 2026-07-24T20:43:21+01:00 — preflight complete; implementation not yet started.
