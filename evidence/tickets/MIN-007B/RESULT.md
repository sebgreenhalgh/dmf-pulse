# MIN-007B result

- Ticket: `MIN-007B`; branch: `stage/A7/MIN-007-basic-minutes-model`.
- Accepted parent: `84697a464af17a909e28a6870d764617098fc30a`.
- Commit: pending the required exact-message commit (`MIN-007B add cutoff-safe minutes dataset builder`).
- Pack validation: Pack 007B `17` hashed files valid; frozen dataset oracle passed.
- Acceptance ledger: `13/13` literal commands passed; all availability tests passed with zero skips.

## Contract canaries

- Canonical history fixture SHA-256: `23cc133b26beba0455ca50e66cbd4fca5bde8b1b38a4b946b197d53039982096` (460 source rows).
- Frozen training dataset file SHA-256: `4f8624d95517e42cf4403e0356b28f6061f4d6c525f75bfff6d7ad07b9f5a6c5` (368 TRAIN rows).
- Semantic dataset SHA-256: `1466a5dcc9104a2d26f9c6b286d2717b6460423503026f05a58d3a26de040be3`.
- The builder excludes all 92 EVAL rows, future labels and post-cutoff feature rows; labels exactly at the cutoff remain included.
- Frozen role/minutes counts are START 176, BENCH 144 and OUT 48; no START has zero minutes and no OUT has positive minutes.

## Scope and risks

- Changed only the pure availability models/builder, synthetic MIN-007 fixtures, focused availability tests, plans and MIN-007B evidence.
- No database migration, dependency, CLI, model fitting, evaluation/calibration claim, network/provider request, credential, or MIN-007A market behavior changed.
- No unresolved risks; repository validation and secret scanning passed with zero findings. The final commit hash and clean-tree state are recorded in the handoff after the single bounded commit.
