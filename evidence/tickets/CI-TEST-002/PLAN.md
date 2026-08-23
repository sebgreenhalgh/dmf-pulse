# CI-TEST-002 implementation plan

Status: `HISTORICAL_REVIEW_CLEAN_RESEAL_IN_PROGRESS`

Date: `2026-08-23`

Engineering target:
`TEST_FIX_READY_PENDING_INDEPENDENT_REVIEW_WITH_KNOWN_EXTERNAL_CI_ARCHITECTURE_BLOCKER`

## Frozen historical identities

- Architectural main: `baed47bce7a158d91afe38351a2c65be60444adf`.
- Original parent: `d550250836c9c39e6caebaa5f12ad94fec7e2b02`.
- Original reviewed head: `840b6b7150808f19a3c32171aea6846e55fa8554`.
- Original independent verdict: `REVIEW_CLEAN_PENDING_EXTERNAL_CI_GATE`.
- Diagnostic evidence commit: `6fdcad8153897e7485ac48fcc6409008a24e8274`, excluded
  from engineering ancestry.
- Immutable LIVE-ODDS head: `5e55cf3361a1abff4b2e32dcc30fe42900ea2e16`.

## Historical bounded execution

- [x] Confirm the ANSI-only observation defect with real `GITHUB_ACTIONS=true`.
- [x] Confirm Click is absent from the frozen graph and Rich 15 provides a public normalizer.
- [x] Normalize ANSI only at the semantic assertion boundary.
- [x] Complete Windows and Linux Python 3.13 acceptance.
- [x] Complete static, security, repository, manifest and scope validation.
- [x] Receive clean independent technical review on the original lineage.

## Lineage reseal

- [x] Verify corrected Layer A did not change the pre-C executable base.
- [x] Reapply the reviewed patch with exact blob and stable patch identity on rebuilt Layer B.
- [x] Pass final-stack correctness, PostgreSQL, static, security, and manifest gates.
- [ ] Seal direct-child Layer C, push once, and stop for independent lineage confirmation.
