# MIN-007D result

- Ticket: `MIN-007D`; branch: `stage/A7/MIN-007-basic-minutes-model`.
- Accepted parent: `6d31e3e46a9f3609efab9a2a9ca28f269b5ef6bb`.
- Required commit message: `MIN-007D add conditional minute distributions`.
- Pack validation: the supplied MIN-007D pack manifest and detached SHA-256 register passed before implementation.
- Acceptance ledger: all 15 literal commands passed with zero skipped tests.

## Frozen identities

- Minute-prior artifact SHA-256: `8e0b410e37d33127dc26937f9fe7c6ff60867b4f60f0f7a87679f951c5f7e422`.
- Accepted MIN-007B training semantic SHA-256: `1466a5dcc9104a2d26f9c6b286d2717b6460423503026f05a58d3a26de040be3`.
- Accepted MIN-007C role artifact SHA-256: `baf70ee76b8a51f4cf3bfda1a1cc33d6ba3f6c304617c8bc42aefdee2b2a1c96`.
- Independent MIN-007D oracle passed all nine conditional canaries, the mixed weighting case, fresh-player priors, and order-invariance check.

## Scope and security

- Implemented only conditional START/BENCH minute priors and cutoff-safe 91-bin Decimal PMFs; no overall player-minute mixture was added.
- Decimal precision is 60 with HALF_EVEN arithmetic; public JSON uses twelve-decimal residual correction without feeding rounded values back into arithmetic.
- Different-team rows are excluded before age assignment, all retained target-team rows consume age before role filtering, and future/not-yet-usable rows are excluded.
- No database, filesystem, network/provider request, subprocess, clock, RNG, or credential access was introduced. Secret scanning found zero findings.
- Repository validation passed with `error_count=0`; market regression passed with 75 tests.
