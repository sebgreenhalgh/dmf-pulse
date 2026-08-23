# CI-TEST-001 implementation result

Local status:
`TEST_FIX_READY_PENDING_INDEPENDENT_REVIEW_WITH_KNOWN_EXTERNAL_CI_ARCHITECTURE_BLOCKER`

## Change

Only `tests/assurance/optimisation/test_surface.py` changes executable behavior. The affected test
now distinguishes four cases:

1. canonical valid model bytes are accepted;
2. malformed JSON raises `OptimisationError`;
3. valid JSON with an invalid `CandidateSquad` raises `OptimisationError`;
4. valid model input with explicitly noncanonical bytes raises `OptimisationError`.

The last case uses `Path.write_bytes`; it cannot vary with platform newline rules.

## Cross-platform results

- Windows 11 / CPython 3.13.9 target: `1 passed in 0.61s`.
- Windows 11 / CPython 3.13.9 module: `11 passed in 85.00s`.
- Windows coverage-instrumented module: `11 passed in 205.61s`, exit 0.
- Debian Linux / CPython 3.13.15 target: `1 passed in 2.51s`.
- Debian Linux / CPython 3.13.15 module: `11 passed in 95.68s`.

The Linux worktree mount was read-only. Hypothesis reported that its default example database was
unwritable and used an in-memory database; tests passed without repository writes.

## Confinement

- Production source changed: no.
- Workflow changed: no.
- Configuration changed: no.
- Migration changed: no.
- Dependency or lock changed: no.
- DIAG-02 changed: no.
- CI-GOV, CI-FPL, LIVE-ODDS, or PR #16 changed: no.

Repository validation completed through the validator's read-only function with `0` errors. The
literal CLI wrapper was not used because it would write an unauthorized GCS-008 report; validation
logic was not changed or bypassed.

Branch CI, independent review, human acceptance, and merge are not claimed by this local result.
