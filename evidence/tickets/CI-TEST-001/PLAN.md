# CI-TEST-001 implementation plan

Status: `LOCAL_ACCEPTANCE_PASSED_PUSH_PENDING`

Date: `2026-08-23`

Engineering target:
`TEST_FIX_READY_PENDING_INDEPENDENT_REVIEW_WITH_KNOWN_EXTERNAL_CI_ARCHITECTURE_BLOCKER`

## Frozen identities

- Architectural main: `baed47bce7a158d91afe38351a2c65be60444adf`.
- Stacked technical parent: `652bae84fba9bdfbf435367d6140270fa8378d57`.
- Branch: `remediation/CI-TEST-001-cross-platform-canonical-fixture`.
- Immutable LIVE-ODDS head: `5e55cf3361a1abff4b2e32dcc30fe42900ea2e16`.
- PR #16 was verified open and unmerged before implementation.

## Bounded execution

- [x] Confirm the inherited text-newline-dependent negative fixture.
- [x] Confirm the production loader and `CandidateSquad` behavior are correct and unchanged.
- [x] Add explicit canonical acceptance, invalid-model rejection, and valid-but-noncanonical byte
  rejection controls in the one authorized test file.
- [x] Pass the target and full module on Windows CPython 3.13.9.
- [x] Pass the target and full module on Debian Linux CPython 3.13.15.
- [x] Pass targeted coverage instrumentation without changing repository thresholds.
- [x] Pass diff, format, lint, and secret checks.
- [ ] Push normally and observe the automatically triggered branch CI without rerunning it.
- [ ] Independent review and human acceptance remain separate.

No product, workflow, configuration, migration, dependency, CI-GOV, CI-FPL, LIVE-ODDS, PR #16,
or DIAG-02 change is authorized or implemented.
