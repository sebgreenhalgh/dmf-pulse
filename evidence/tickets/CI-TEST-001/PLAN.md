# CI-TEST-001 implementation plan

Status: `HISTORICAL_REVIEW_CLEAN_RESEAL_IN_PROGRESS`

Date: `2026-08-23`

Engineering target:
`TEST_FIX_READY_PENDING_INDEPENDENT_REVIEW_WITH_KNOWN_EXTERNAL_CI_ARCHITECTURE_BLOCKER`

## Frozen historical identities

- Architectural main: `baed47bce7a158d91afe38351a2c65be60444adf`.
- Original stacked parent: `652bae84fba9bdfbf435367d6140270fa8378d57`.
- Original branch: `remediation/CI-TEST-001-cross-platform-canonical-fixture`.
- Original reviewed head: `d550250836c9c39e6caebaa5f12ad94fec7e2b02`.
- Original independent verdict: `REVIEW_CLEAN_PENDING_EXTERNAL_CI_GATE`.
- Immutable LIVE-ODDS head: `5e55cf3361a1abff4b2e32dcc30fe42900ea2e16`.

## Historical bounded execution

- [x] Confirm the inherited text-newline-dependent negative fixture.
- [x] Confirm the production loader and `CandidateSquad` behavior are correct and unchanged.
- [x] Add explicit canonical acceptance, invalid-model rejection, and valid-but-noncanonical byte
  rejection controls in the one authorized test file.
- [x] Pass the target and full module on Windows CPython 3.13.9.
- [x] Pass the target and full module on Debian Linux CPython 3.13.15.
- [x] Pass targeted coverage instrumentation without changing repository thresholds.
- [x] Pass diff, format, lint, and secret checks.
- [x] Receive clean independent technical review on the original lineage.

## Lineage reseal

- [x] Verify corrected Layer A does not change the executable base file.
- [x] Reapply the reviewed patch with exact blob and stable patch identity.
- [x] Seal direct-child Layer B as `af78cedc65bd043343825facae947b8aed5340a4`.
- [ ] Independent lineage confirmation remains separate.

No product, workflow, configuration, migration, dependency, CI-GOV, CI-FPL, LIVE-ODDS, PR #16,
or DIAG-02 change is authorized or implemented.
