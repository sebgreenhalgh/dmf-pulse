# MIN-007A implementation plan

- Confirm the hash-validated Pack 007A contract, branch parent, and clean worktree.
- Install only the three supplied superseding NRM public schemas; preserve `probability.schema.json` byte-for-byte.
- Add contract regressions for every supplied negative schema case and duplicate/canonical-order constraints while retaining valid fixture coverage.
- Replace blanket exclusion-to-blocking confidence logic with a small explicit severity helper; preserve all NRM math, policy hashes, freshness and persistence behavior.
- Add the supplied two-clean-plus-stale canary regression and retain the accepted happy-path probabilities and semantic hash.
- Run the literal acceptance ledger, record measured results, create the exact bounded commit, and verify a clean worktree.

Expected implementation files are limited to the three public schemas, `consensus.py`, inherited NRM schema-hash metadata required by repository assurance, focused market contract/unit/golden tests, synthetic contract fixtures for reproducible canaries, `PLANS.md`, and MIN-007A evidence. The trusted NRM-006 fixture manifest remains unchanged.
