# CI-TEST-001 acceptance contract

This contract authorizes only the cross-platform assurance-test correction for DIAG-01. It does
not authorize a production, workflow, dependency, DIAG-02, LIVE-ODDS, PR #16, merge, or human
acceptance change.

## A. Git and scope

1. The branch starts at exact parent `652bae84fba9bdfbf435367d6140270fa8378d57` and is named
   `remediation/CI-TEST-001-cross-platform-canonical-fixture`.
2. Architectural main remains `baed47bce7a158d91afe38351a2c65be60444adf`; PR #16 remains
   open and unmerged at `5e55cf3361a1abff4b2e32dcc30fe42900ea2e16`.
3. Production source, workflow, config, migrations, dependencies, CI-GOV, CI-FPL evidence/source,
   LIVE-ODDS, and the separate DIAG-02 test remain byte-identical to the parent.
4. Only the ticket allowlist changes, including the exact PRC-013 manifest exception if canonical
   repository tooling requires it.

## B. Artifact controls

1. Canonical bytes produced by `canonical_json_bytes` load successfully and equal the valid
   `CandidateSquad` model.
2. The negative fixture uses `Path.write_bytes` with explicit, platform-independent bytes.
3. The negative bytes are valid JSON and valid `CandidateSquad` input, but differ bytewise from
   canonical compact JSON only by insignificant formatting.
4. Loading those bytes raises `OptimisationError` through canonical byte enforcement.
5. Malformed JSON and valid JSON with an invalid model remain separate rejection controls.
6. Detached SHA mismatch and collision controls remain green.
7. The production loader, model validation, and canonical serializer are unchanged.

## C. Required validation

The exact target and complete `test_surface.py` module pass on Windows and Linux Python 3.13. The
module also passes under `--cov=dmf_pulse --cov-branch --cov-report=term-missing
--cov-fail-under=0`; this targeted command does not change repository coverage settings.

`git diff --check`, Ruff format/check, repository validation, secret scanning, ticket evidence
validation, repository manifests, and exact scope checks pass. The final worktree is clean and
local/remote branch heads match after a normal push.

## D. Truthful completion

The maximum bounded status is
`TEST_FIX_READY_PENDING_INDEPENDENT_REVIEW_WITH_KNOWN_EXTERNAL_CI_ARCHITECTURE_BLOCKER`.
DIAG-02 and the monolithic CI runtime architecture remain unresolved. No full-CI-green, independent
review, human acceptance, merge, or PR #16 modification may be claimed.
