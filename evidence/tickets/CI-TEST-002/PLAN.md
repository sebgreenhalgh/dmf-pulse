# CI-TEST-002 implementation plan

Status: `LOCAL_ACCEPTANCE_PASSED_PUSH_PENDING`

Date: `2026-08-23`

Engineering target:
`TEST_FIX_READY_PENDING_INDEPENDENT_REVIEW_WITH_KNOWN_EXTERNAL_CI_ARCHITECTURE_BLOCKER`

## Frozen identities

- Architectural main: `baed47bce7a158d91afe38351a2c65be60444adf`.
- Engineering parent: `d550250836c9c39e6caebaa5f12ad94fec7e2b02`.
- Diagnostic evidence commit: `6fdcad8153897e7485ac48fcc6409008a24e8274`, excluded
  from engineering ancestry.
- Immutable LIVE-ODDS head: `5e55cf3361a1abff4b2e32dcc30fe42900ea2e16`.

## Bounded execution

- [x] Verify refs, clean parent, diagnostic separation, PR #16 and baseline test structure.
- [x] Confirm the ANSI-only observation defect with real `GITHUB_ACTIONS=true`.
- [x] Confirm Click is absent from the frozen graph and Rich 15 provides a public normalizer.
- [x] Normalize ANSI only at the semantic assertion boundary.
- [x] Complete Windows and Linux Python 3.13 acceptance.
- [x] Complete static, security, repository, manifest and scope validation.
- [ ] Commit, push normally and observe automatic branch CI through the target modules.
- [ ] Independent review and human acceptance remain separate.
