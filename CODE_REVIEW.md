# DMF Pulse review standard

Review DAT-003 in this order:

1. Scope and authority: approved hashes/statuses, zero-cost DMFP-04, and no future-domain code.
2. RUL remediation: each independent-review P1 has a direct regression test and corrected v1.1 goldens remain byte-stable.
3. Schema and migration: PostgreSQL 18.4/`uuidv7()`, exact objects, fingerprint, clean upgrade, downgrade, and re-upgrade.
4. Temporal identity: UUIDv7 persistence, closed-open boundaries, bitemporal as-of semantics, database overlap rejection, and concurrent-writer behavior.
5. Provenance and immutability: usable-source gate, correction lineage, raw deduplication, immutable observations, and activation-bundle integrity.
6. Configuration and secrets: TEST-only URL resolution, reference-only committed configuration, deterministic redaction, and no leak in errors/evidence.
7. Packaging and portability: canonical version, `py.typed`, import purity, PostgreSQL-aware clean wheel outside the source tree, Windows pure smoke, and Ubuntu database gate.
8. Evidence and supply chain: exact command ledger, coverage/mutation oracles, approved pinned dependencies, lock/runtime graph, detached hashes, clean Git provenance, and exact 20-file cap.

P0/P1 findings block Codex completion. Passing tests alone is not acceptance, and human approval remains required before merge/tag.
