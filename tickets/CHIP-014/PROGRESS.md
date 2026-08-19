# CHIP-014 Stage 14 progress

- Ticket: `CHIP-014`
- Immutable original parent: `a8796d4edacea4c87ee6461d381f4df87e1ef39c`
- Branch: `stage/A14/CHIP-014-chip-optimisation`
- Current engineering status: `INDEPENDENT REVIEW COMPLETE; FINAL PUBLICATION ACTIVE`
- Installed capability status: `ENGINEERING_READY_PENDING_TARGET_RULES`
- Production eligible: `false`
- Human acceptance: `false`
- Merged: `false`
- Accepted tag: none

## Verified lineage and recovery

- Actual starting remote Stage 14 SHA: `853142c84b909f1f22b6e31b657b21d990c331b1`.
- The merge base with the immutable parent is exactly the immutable parent.
- Checkpoint 14.07 product files were absent from the starting remote tree.
- Historical `recovery/` fragments were treated as untrusted source guidance. Only a strict
  allowlist of 25 product/test/fixture paths was materialised; stale plans, progress and evidence
  payloads were excluded. All recovered work was reviewed and tested before publication.
- Checkpoint 14.07 was published at
  `6583a0d8c7a69a07668cbd53db99b9119a7f89d5` and fetch-back verified.
- All Stage 14 recovery workflows, transport payloads, triggers and `recovery/` are absent from the
  final tree. Cleanup commit: `86bac6a`.

## Checkpoints

| Checkpoint | Status | Capability commit |
|---|---|---|
| 14.01 compiler/inventory | COMPLETE / REMOTE | `3173c97f5d04b3b0fe65c8e9b17876d257b233be` |
| 14.02 captain/vice/Triple Captain | COMPLETE / REMOTE | `8c135cba3efb6d64b9fed7f2bb2e06ebe28ae8f2` |
| 14.03 Bench Boost | COMPLETE / REMOTE | `f1c384972567befbe4713c56bfaaa4a481135687` |
| 14.04 Free Hit | COMPLETE / REMOTE | `ef3f5b2` |
| 14.05 Wildcard | COMPLETE / REMOTE | `0449dd7c47ae983a78fb8ef9098ce604ae3022db` |
| 14.06 scheduler/continuation | COMPLETE / REMOTE | `cc62e21a3a085fc6a5cec959881f075f6dfa13c1` |
| 14.07 service/replay/CLI/artifacts | COMPLETE / REMOTE | `6583a0d8c7a69a07668cbd53db99b9119a7f89d5` |
| Independent remediation | COMPLETE / REMOTE | `5cf5bc1` |
| Adversarial coverage proof | COMPLETE / REMOTE | `99d545d` |
| Repository static-gate cleanup | COMPLETE / REMOTE | `f8511b2` |

## Independent review outcome

- P0 findings: none.
- P1 findings: four related contract/integration groups, all remediated with regression tests:
  independent rules recompilation; legal inventory-history reconstruction; pending-activation
  legality; real chip-domain/scheduler scenario reconciliation.
- Material P2 findings: the purported exact oracle reused production search, plus portability,
  branch-proof and static-assurance debt. All were remediated.
- No Stage 15 rank/effective-ownership/rival logic was found or added.

## Final measured gates

- Complete Stage 14 matrix: `405 passed in 12.96s`.
- Raw Stage 14 branch coverage: `1142 / 1268 = 90.063091%`.
- Targeted inherited Stage 9-13/rules regressions: `127 passed in 84.05s`.
- Frozen sync: PASS (`Checked 40 packages`).
- Ruff format/lint: PASS across the repository.
- Strict mypy: PASS (`226 source files`).
- Canonical Hatchling build: PASS for sdist and wheel.
- Clean external installed-wheel Stage 14 CLI: PASS for version/help/rules validation/capability
  validation/schedule/compare/Triple Captain value with `PYTHONPATH` cleared.
- Secret scan: PASS, zero findings after exact path-and-fingerprint review of chip-domain token
  terminology.
- One canonical full-repository pytest attempt completed in 26:58 with `2579 passed, 1 skipped,
  2 failed, 205 errors`. The 205 setup errors and generic wheel verifier failure require the absent
  `DMF_TEST_DATABASE_URL`; the other failure was the pre-refresh repository manifest. This run is
  not labelled PASS and was not repeated unchanged.

## Remaining limitations

- The accepted 2026/27 rules manifest is `VERIFIED`, not human-approved `ACTIVE`; installed Stage
  14 capability therefore remains explicitly non-production-eligible.
- The transparent V1 continuation approximation remains provisional under DMFP-20.
- Stage 13 price paths remain uncalibrated/rights-gated and their statuses are propagated.
- Target-season chip-policy performance has not been prospectively validated.
- The repository-wide PostgreSQL/generic-wheel matrix needs an authorised
  `DMF_TEST_DATABASE_URL`; Stage 14's clean installed-wheel CLI path passed independently.
- Human review, acceptance and merge remain pending. No merge or tag has been created.

Detailed evidence: `evidence/tickets/CHIP-014/FINAL_REVIEW.md` and
`evidence/tickets/CHIP-014/COMMAND_LEDGER.txt`.
