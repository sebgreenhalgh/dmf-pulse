# MIN-007A result

- Ticket: `MIN-007A`; branch: `stage/A7/MIN-007-basic-minutes-model`.
- Accepted parent: `253baf3f19661a5704bb1fad2f7ac60e1db288eb`.
- Commit: pending the required exact-message commit (`MIN-007A harden NRM public contracts and confidence`).
- Pack validation: Pack 007A `23` hashed files valid.
- Acceptance ledger: `12/12` literal commands passed; broad gate `1054 passed, 128 deselected`.

## Contract canaries

- Supplied `normalised_operator_market.schema.json`: `c2851ca0c051c61aaa404fb290f6974640b2b1453f8c5a43e8d89502d0ee21fb` (exact byte match).
- Supplied `market_consensus.schema.json`: `60e59a14cb5c3a9abdbac5c7b4c929c9a38993a07a0b71cdc80704517fc56ad4` (exact byte match).
- Supplied `market_normalisation_result.schema.json`: `b9a39f8f2a612645ddde141f8e9c8df340d65d1b1a8a4e01b42bb2f64a1eb789` (exact byte match).
- Dependency `probability.schema.json`: unchanged byte-for-byte, SHA-256 `b2900cdbdb3c6d5dd4300eaa14508c8eb09852dc917d7fa95b5df15cfcba63df`.
- Accepted happy path remains confidence B with HOME `0.524978633868`, DRAW `0.257342673557`, AWAY `0.217678692575`, semantic hash `bd8840cceed27199e3b10945ef54529a517df68b522a82ab0c935c460116a499`.
- Two-clean-plus-stale remains `DEGRADED`, confidence B, eligible count 2, `book_gamma` excluded as `STALE`, semantic hash `84c22958b67d2f7d578460c018b71755ec23477f0cef1368a9f68732a00b0790`.

## Scope and risks

- Changed only the public schema contracts, explicit confidence-severity classification, inherited schema-hash metadata, focused synthetic fixtures/tests, plans and MIN-007A evidence.
- No NRM arithmetic, Decimal precision, policy thresholds/hashes, freshness, temporal mapping, persistence schema, migration, dependency, credential, or network behavior changed.
- No unresolved risks; temporary local venv shims used solely to execute literal Windows acceptance entry points were removed before final verification.
