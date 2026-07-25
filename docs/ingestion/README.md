# FPL ingestion foundation

FPL-004 adds a rights-gated ingestion foundation for the two unauthenticated reference resources `bootstrap-static` and `fixtures`. The accepted end-to-end path uses only the repository's synthetic fixtures. It creates immutable retrieval envelopes, append-only processing events, season-scoped canonical mappings, typed observations, quality evidence, and a cutoff-safe source bundle.

## Rights boundary

- `synthetic_test_v1` authorizes the synthetic fixture pipeline, including raw and derived test storage.
- `fpl_official_private_manual_v1` authorizes bounded transient manual validation only. It does not authorize automated access, persistent raw or derived storage, source bundles, backups, training, export, redistribution, or public display.
- An official-profile manual import accepts ordinary nonsymlink file paths without taking ownership of the caller's files. After the rights gate, the service copies the bounded bodies into a unique owner-only directory beneath its dedicated temporary root, verifies the copies, and destroys that service-owned directory in a `finally` path whether validation succeeds or fails. Crash recovery removes only operation directories whose creating process has ended; concurrent and unrelated files are never glob-deleted.
- Unknown rights deny the operation. A successful transport response can never override a rights decision.
- `dmf ingest fpl snapshot` checks rights before transport and is expected to return `RIGHTS_BLOCKED` with exit code 4 under the supplied official profile.

No FPL or provider request is part of deterministic implementation, tests, CI, or acceptance. Do not add authenticated manager endpoints, cookies, login state, arbitrary URLs, recurring polling, or a real provider payload.

## Public commands

Validation is database-free:

```text
dmf ingest fpl validate --resource bootstrap --input <path> --contract-version fpl-reference-v1 --output json
```

The database-backed surface is:

```text
dmf ingest fpl import --bootstrap <path> --fixtures <path> --competition-key <key> --season-code <code> --captured-at <utc> --information-cutoff <utc> --rights-profile <profile> --database-url-ref <reference> --output json
dmf ingest fpl replay --fixture-set <directory> --scenario <scenario> --database-url-ref <reference> --output json
dmf ingest fpl resume --snapshot-id <uuid> --database-url-ref <reference> --output json
dmf ingest fpl bundle show --bundle-id <uuid> --database-url-ref <reference> --output json
dmf ingest fpl snapshot --resource all --competition-key PL --season-code 2026/27 --rights-profile fpl_official_private_manual_v1 --database-url-ref <reference> --output json
```

A database URL reference names an approved secret source; it is never a literal credential-bearing URL. All timestamps must be timezone-aware and are normalized to UTC.

## Lifecycle and replay

One immutable source snapshot represents one retrieval/import. Processing history is append-only:

```text
RECEIVED -> STORED|RAW_DISCARDED -> PARSED -> VALIDATED -> MAPPED -> PROMOTED -> QUALITY_PASSED -> USABLE
```

Current state and `usable_at` are derived from the event sequence. Terminal quarantine/rejection cannot become usable. Resume executes only the incomplete suffix and must not duplicate a canonical entity, mapping, or unchanged semantic fact. Parsed artifacts contain declared contract fields only; they are hash-bound to the envelope, adapter, exact rights profile, provider configuration, effective configuration hash, and contract version so resume never trusts mutable authority or additive provider values. Each exact retrieval pair receives its own immutable bundle manifest, while semantically equivalent manifests share the same bundle semantic hash.

Observations are immutable semantic facts. Their hashes bind the canonical subject, competition, season, source role, contract, observed fields, and explicit source-time missingness. An older replay remains evidence but cannot supersede a newer current fixture revision or Gameweek assignment; an equal-time contradiction is quarantined as a mapping conflict.

Source bundles require exactly one usable `BOOTSTRAP` and one usable `FIXTURES` member for the same competition/season, each first usable at or before the declared information cutoff. Provider timestamps cannot substitute for `usable_at`.

Quality evidence uses explicit typed missingness such as `NOT_PUBLISHED`, `SOURCE_UNAVAILABLE`, and `MAPPING_FAILED`. Informational absence remains queryable and deterministic, while P0/P1 quality issues block promotion or quarantine the affected snapshots.

## Safe local acceptance

Use only `fixtures/fpl/FPL-004/` and the disposable PostgreSQL service from `compose.test.yaml`. The authoritative commands and expected controlled rejection are in `tickets/FPL-004/ACCEPTANCE.md`. Never point acceptance at a production database or provider endpoint, and never include raw real-provider bodies in Git, logs, evidence, or a review archive.
