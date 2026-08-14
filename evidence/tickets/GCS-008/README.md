# GCS-008 evidence boundary

This directory reserves the governed evidence location. It contains no hand-authored PASS certificate and no claim of stage acceptance.

CI may write measured artifacts here, including `coverage.json`. A governed `evidence_manifest.json` must be assembled only after real command logs, exact commit and CI identities, package hashes, migration results, independent review, and human disposition exist.

Acceptance must be reconstructed from:

- required-parent and real Git-diff scope validation;
- CI run, job, and commit identities;
- raw command exits and logs;
- repository-wide pytest and coverage output;
- fixture, policy, public-contract, wheel, input, and result hashes;
- installed-wheel verification outside the source tree;
- inherited migration-matrix results;
- independent review and human approval.

Do not infer acceptance from this directory, generated JSON, or `IMPLEMENTATION_RESULT.md`.
