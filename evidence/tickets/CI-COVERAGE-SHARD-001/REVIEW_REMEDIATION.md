# CI-COVERAGE-SHARD-001 review remediation

Status: `REVIEW_REMEDIATION_READY_PENDING_FINAL_SHA_CI_AND_INDEPENDENT_REREVIEW`

Reviewed engineering state: `b8ce5de612d835bee6721898cd57e46c133f90dd`

## Independent findings

The full independent review found no product, shard-runtime, partition, coverage, PostgreSQL,
artifact, downstream, or committed-workflow defect. It raised two material review findings:

- GOV-001 required explicit owner authority for the two existing ANSI observation changes.
- CI-REV-001 showed that both contract guards accepted an adversarial all-`&&` replacement of the
  sentinel's required OR predicate.

The owner supplied the exact post-review amendment recorded in `OWNER_SCOPE_AMENDMENT.md`. No
ratified ANSI test blob is changed by this remediation.

## CI-REV-001 remediation

`scripts/validate_repository.py` now extracts the shell condition specifically from the `quality`
job and structurally requires exactly four clauses. Each mandatory result variable must occur
exactly once, use `!= "success"`, and be joined only by logical OR. Logical AND is rejected, and
`exit 1` must occur inside the extracted failure branch. Existing exact-name, `always()`, direct
needs, prerequisite-result, timeout, masking, coverage, and historical compatibility controls are
preserved.

`tests/unit/scripts/test_ci_workflow_contract.py` independently parses the committed sentinel and
rejects all-AND, mixed AND/OR, missing-result, duplicate-result, inverted-comparison, and
missing-exit mutations. It also exercises repository validation against those mutations plus
missing-`always()` and missing-need cases.

The workflow itself remains byte-identical to reviewed state. Final population, digests, complete
local validation, manifests, and pre-push evidence are recorded after the implementation tree is
settled. The new automatic final-SHA Actions run remains external and pending at this tracked
evidence boundary; independent re-review, human acceptance, and merge are not claimed.

## Pre-publication validation

The settled worktree contains 3,147 eligible non-performance nodeids. All 3,133 nodeids from the
reviewed `b8ce5de` plan remain, and the 14 additions are exactly the parameterized workflow and
repository-validator mutation cases in `test_ci_workflow_contract.py`. Missing, duplicate, and
unexpected prior nodeids are zero. The new eligible population digest is
`05222e70da23f1aa432ba1f4a83d8ab77c82f09d2e3473855d94442acb645a67`; shard counts are
4, 161, 375, 492, 488, 479, 453, and 695 with estimated weights 1050 then seven times 963.

The canonical file-path planner initially exposed that a direct namespace import added by the new
test was incompatible with its in-process collection entry point. The test now loads the validator
by file location, following existing repository script-test convention. The unchanged canonical
planner command then passed with all 3,147 nodeids.

Focused results are 22 workflow-contract tests, 8 existing validator/GCS acceptance tests, 56
combined shard-helper/workflow tests, and 35 complete owner-ratified CLI module tests under
`GITHUB_ACTIONS=true`. Full Ruff format/lint and strict source typing pass. Manifest, repository,
security, and evidence results are sealed later in this same pre-push snapshot.
