# NRM-006 Pack 1.1 authority resolution

Status: **RESOLVED BY PACK 1.1**

Recorded: 2026-08-06

Pack 1.1 supersedes Pack 1.0 for NRM-006. The original Pack 1.0 stop evidence
is preserved byte-for-byte at
`prior_blockers/PACK_1_0_BLOCKER.md` with SHA-256
`b034541a1d162219a375ff22ba0621d7dd0aa9b2793babbd26969c2fa933ea84`
and byte length 5,222.

## Quota-fixture resolution

The corrected frozen fixture
`fixtures/odds/NRM-006/rate_limit_retry.json` now contains
`x-requests-remaining`, `x-requests-used`, and `x-requests-last` on both fake
responses intended to carry valid quota evidence. Its Pack 1.1 SHA-256 is
`f5e85faa12fd1655f70b405c3ddd0cc801edca27c1b0607c5838af6bdeeb68e6`.
This resolves the Pack 1.0 contradiction without weakening the inherited
all-or-nothing quota-header rule or inventing evidence.

## Temporal resolution

Pack 1.1 freezes post-commit publication attestation. Parsing, mapping, rights,
quality, canonical observations, and USABLE lifecycle activation are committed
atomically under an immutable publication batch. Only after commit
acknowledgement is the injected UTC clock sampled once; the resulting
`usable_at` is persisted in a separate immutable attestation. Strict queries
require that attestation. A failed attestation keeps the batch ineligible until
a newly timed, never-backdated repair succeeds.

## Validation

- Pack manifest SHA-256:
  `6be2a825a90dfa89f7e5ce1da5475c144cb44cee265b33d75396cef3256966e4`.
- Manifest validation: 79/79 entries passed.
- Detached checksums: 80/80 entries passed.
- Actual pack files: 81; zero missing, unexpected, size, or hash failures.
- Required branch and baseline matched.
- PostgreSQL 18.4 and Alembic head `20260725_0004` matched.
- Inherited baseline: 882 passed in 131.77 seconds, zero skips.
- No live provider request or real credential was used.
