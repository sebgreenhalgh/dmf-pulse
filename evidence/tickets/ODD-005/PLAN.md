# ODD-005 implementation plan

Updated: 2026-08-02

Current status: **IN PROGRESS** under corrected Pack 1.1. The Pack 1.0
decimal-string contradiction recorded in `evidence/tickets/ODD-005/BLOCKED.md`
was resolved by the new frozen lexical and semantic-hash policy.

## Frozen context

- Branch: `stage/A5/ODD-005-odds-provider-foundation`
- Required and observed baseline HEAD: `7034e38f32cd579c90d35c5fe3f10921c3656be0`
- External pack: `DMF_PULSE_CODEX_PACK_005_ODDS_PROVIDER_FOUNDATION_v1.1`
- Pack manifest SHA-256: `c030d775f2c4f5f68910ef443b1f0a86bc2a6e096299d448fbc0d81d48a62a20`
- Controlling prompt SHA-256: `c5c7679147d64ffa441160bc7c5bbd44b3c44822ebcede073b8ade46226a927b`
- Pack verification: 62 manifest entries and 62 detached checksums verified with zero errors.
- Corrected market-observation schema SHA-256: `be1e753ad192368fbd8a2b82383cd86e07be2104ba5595e1ea81b5581144f217`.
- Inherited regression: 589 tests passed with zero skips against local PostgreSQL 18.4 after applying the accepted baseline migrations.
- Inherited Alembic code head and database current: `20260724_0002`.
- Network/credential policy: synthetic fixtures and fake transports only; no live FPL, The Odds API, or other provider request and no real API key.

## Allowed change map

Changes remain bounded to the ODD-005 vertical slice: FPL remediation and odds/market/data-model/database/CLI/assurance code; provider and rights configuration; public contracts; supplied synthetic odds fixtures; tests; portable scripts; ticket evidence; and directly required packaging, Makefile, and CI files. The mandatory inherited FPL remediations necessarily extend three existing shared ingestion primitives for rights-decision idempotency, source envelopes, fixture authority, and exit taxonomy. Repository governance separately requires `PLANS.md`, while the security contract requires the exact-hash/path allowlist for its supplied fake credential and raw-body canary. These are contract-enabling shared/governance changes rather than a provider or future-stage expansion. The repository's Alembic revisions remain under the allowed `src/dmf_pulse/database/**` tree and all prior revisions are immutable. Unrelated providers, future market families, normalisation, models, optimisation, scheduling, API/UI, and public odds products remain read-only and out of scope.

## Checkpoints

1. **Frozen inputs and FPL remediation** - install the supplied ODD-005 ticket, acceptance contract, public schemas, manifest-approved fixtures, provider/rights authorities, and direct tests for wrapped TLS, authoritative bundle rights/quality, code commit, heterogeneous fingerprints, NFC, and canonical Decimal hashing.
2. **Provider boundary and parsing** - implement strict bounded The Odds API v4 parsing, exact Decimal prices, deterministic drift evidence, injected credentials/fake transport, allowlisted HTTPS GET construction, typed failures/retries, and immutable quota observations with pre-transport gates.
3. **Canonical market model and migration** - add the minimum operator/market/selection/mapping/observation schema plus relational bundle-rights and quality guards, reversible from `20260724_0002`, with database constraints, immutable triggers, deterministic fingerprinting, and clean downgrade/re-upgrade.
4. **Mapping, ingestion, and as-of** - resolve fixture/operator identities only through the supplied plan, validate labels after resolution, publish source-linked exact observations idempotently, append changed retrievals, retain incomplete/unsupported states, and query latest eligible observations using `usable_at <= as_of` with deterministic tie-breaking.
5. **Public CLI and wheel** - expose validate/import/replay/snapshot and market-observation commands with the contracted JSON schemas and exit taxonomy; prove the credential-unavailable command exits 4 before transport and the installed wheel works outside the source tree.
6. **Assurance and review** - run targeted unit/property/contract/security/PostgreSQL/concurrency tests, migration matrix, strict typing/lint, coverage gates, repository/evidence validation, secret/canary scans, and independent read-only audits; resolve every P0/P1 finding.
7. **Literal acceptance and archive** - commit the complete ticket, run all 28 literal commands from the clean final commit with guaranteed teardown, record actual code/duration/result evidence, and build/independently validate the maximum-20-root-file review ZIP including complete baseline patch, CRC, manifest, and detached checksums.

## Completed implementation and pre-commit verification

- All six mandatory FPL-004 findings are closed with negative oracles for wrapped TLS/certificate failures, authoritative persisted bundle rights, open P0/P1 bundle blocking, code-commit provenance, heterogeneous type fingerprints, NFC normalization, and canonical Decimal hashing.
- Pack 1.1's Decimal policy is independently proven: public JSON preserves the approved lexical scale (`"1.80"`), numeric validation rejects values at or below one, and semantic hashing treats `"1.80"` and `"1.8"` as numerically equivalent.
- The ODD provider/config/parser/client, immutable lifecycle, quota and rights evidence, explicit canonical mapping, exact market observations, as-of query, two ordered PostgreSQL revisions, CLI, public schemas, installed-wheel proof, and capped review-pack tooling are complete.
- Fresh full suite: **882 passed**, zero skipped and zero warnings. Repository combined coverage: **93.443518%**; overall branch coverage: **90.176751%** (2653/2942). Critical ODD ingestion, rights, quota, cutoff, TLS, and FPL remediation branch gates are each **100%**.
- PostgreSQL 18.4 base/head/downgrade/re-upgrade matrix passed with preserved inherited data and schema SHA-256 `6e49812511020b105e00b1b83f4cdf0caf83c7c936d76720e906732308fa18ad`.
- The isolated installed wheel passed inherited FPL replay, ODD validation/replay, six-observation as-of output with `"1.80"`, controlled credential refusal with zero network requests, CRC/resource checks, isolated database cleanup, and external temporary-environment cleanup.
- Formatting, lint, mypy, frozen specs, repository validation, secret/canary scan, focused category/integration/security tests, and three independent read-only audits passed with no unresolved P0/P1 finding.
- Final checkpoint remains: create the ordinary completion commit, run the literal 28-command ledger once from that clean commit, then independently validate the generated review archive and detached finalization record.

## Preflight evidence

- Exact branch, HEAD, and clean tree confirmed before repository writes.
- Docker Desktop 4.83.0, Docker Engine 29.6.2, Compose 5.3.1, and pinned `postgres:18.4-bookworm` image verified.
- Pack byte counts, manifest hashes, and detached checksum ledger passed independently.
- Fresh disposable PostgreSQL volume upgraded through `20260723_0001` and `20260724_0002`; `alembic current` reported `20260724_0002 (head)`.
- Initial inherited-suite attempts correctly exposed missing test environment/migration setup only; after setting the sanctioned `DMF_ENVIRONMENT=test` and fake local test DSN and applying baseline migrations, the unchanged repository completed `589 passed in 121.60s` with zero skips.

## Stop discipline

Stop and record exact evidence if an oracle conflicts, a right must be broadened, explicit identity mapping is absent, a real/live credential or request becomes necessary, an unapproved dependency is required, the migration cannot preserve prior data and downgrade/re-upgrade, exact as-of eligibility cannot be proven, or any required acceptance/archive check cannot pass honestly.
