# MIN-007F evidence plan

- Parent: `0e3b21a702fece94cb0ee6d61867e6fb17574d0a`.
- Migration: `20260803_0005` -> `20260807_0006` with one final head.
- Scope: immutable dataset/example lineage, model/evaluation registry, prediction bundles, exact PostgreSQL constraints, concurrency-safe idempotency, and historical as-of lookup.
- Exclusions: final role/minute mixture, evaluation calculation, CLI, providers, Stage 8, and Stage 9.
- Verification: literal acceptance commands, migration matrix, registry oracle, frozen R3D/R3E oracles, repository validator, and secret scan.
