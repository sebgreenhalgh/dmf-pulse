# MIN-007F result

Status: **PASS**

- Required parent: `0e3b21a702fece94cb0ee6d61867e6fb17574d0a`.
- Migration: parent `20260803_0005`, revision/head `20260807_0006`.
- Acceptance: 22/22 commands passed; PostgreSQL 18.4 matrix and 63 migration tests passed.
- Registry hashes: dataset `5c76f5a41d9926dc0e4f0e15e2100c103d85768893c4ad8b52fe69a44d365da1`; model `724eecb596b09074b4014d82ec8d0831c4580751af1ad8cb3991f4704f553e9c`; prediction `5662bdec99552813e54453726c9ffdb30ef23365dab8548e78132a2c9d397ed6`.
- Idempotency, immutable rows, exact numeric rejection, atomic rollback, concurrency, and ambiguous as-of failure are covered by the focused integration suites.
- Frozen B/C/D/E identities are unchanged; R3D and R3E oracles pass.
- PostgreSQL is torn down before handoff; final worktree and required single commit are verified separately.
