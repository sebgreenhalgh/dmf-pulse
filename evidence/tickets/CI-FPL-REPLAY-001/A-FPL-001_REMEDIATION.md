# A-FPL-001 pair-context integrity remediation

Status: `REMEDIATION_READY_PENDING_INDEPENDENT_REREVIEW_WITH_KNOWN_EXTERNAL_CI_ARCHITECTURE_BLOCKER`

Finding: `A-FPL-001`

Severity: material P2

Previous independent verdict: `REMEDIATION_REQUIRED`

Implementation checkpoint: `6c5d73c56d8dcb39410da298d3068af38a9f50b8`

## Reproduction

The reproduction ran before the production edit on PostgreSQL 18.4. An authorized synthetic replay
was interrupted after `PARSED`. The exact counterpart `RECEIVED.safe_details` update was first
attempted normally and PostgreSQL rejected it with `IMMUTABLE_RECORD`.

For the isolated adversarial step only, test code disabled
`trg_source_processing_event_guard`, changed only the fixtures member's
`operation_time_policy` to `UNKNOWN_POLICY`, re-enabled and verified the guard, and called
production `resume()` through the unchanged bootstrap member.

Observed pre-fix result:

```text
FAILED: corrupt pair resumed: exit_code=0, bundle_present=True
1 failed, 7 deselected in 1.26s
```

This reproduced the independent finding without weakening production immutability or changing a
migration.

## Root cause

The old resume path loaded only `received_context(session, snapshot_id)`, took `pair_key` from that
one document, located two rows through the JSON key, recomputed only the initiating document's
hash, and selected its operation-time policy. The counterpart document was neither loaded nor
independently verified. Pair behavior could therefore depend on which member initiated resume.

## Bounded remediation

`service.py` now consumes the existing independent relational identity:

1. The initiating snapshot resolves its `ingestion_run_id` and strict
   `fpl004:<64-lowercase-hex>` logical run key without consulting either context.
2. The anchored key acquires the existing advisory pair lock; the run anchor is then row-locked and
   required to remain unchanged.
3. Membership is reconstructed from every snapshot attached to that ingestion run. Exactly two
   rows, the initiating ID, and exactly bootstrap plus fixtures are required.
4. `received_context()` is called for both IDs inside that locked transaction.
5. Each context must name the anchor, carry the correct resource role, contain every required
   common field, and independently hash its complete common material to the anchor.
6. Bootstrap and fixtures common dictionaries must be exactly equal.
7. Paths, profile, times, cutoff, competition, season, configuration hashes, contract version, and
   operation-time policy are interpreted only after all pair checks pass.
8. Missing and unknown policy fail `LIFECYCLE_INVARIANT`. Frozen policy with a non-synthetic
   profile remains `RIGHTS_BLOCKED`.

The ingestion-run row is independent of both context documents and defeats self-consistent
safe-details forgery. It has no immutable trigger of its own; simultaneous privileged corruption of
the run row plus both documents is outside this no-migration ticket and is disclosed rather than
overclaimed.

## Regression mapping

| Contract | Direct proof |
|---|---|
| PAIR-01 | Initiating stored policy corruption fails closed. |
| PAIR-02 | Counterpart unknown policy fails closed through the clean member. |
| PAIR-03 | Counterpart missing policy fails closed. |
| PAIR-04 | Counterpart RECEIVED context made unavailable fails closed. |
| PAIR-05 | Counterpart role mismatch fails closed. |
| PAIR-06 | Counterpart captured-time/common-material change fails closed. |
| PAIR-07 | Counterpart common hash mismatch fails closed. |
| PAIR-08/09 | Existing valid pair resumes through bootstrap and then fixtures with identical bundle identity and no duplicate effects. |
| PAIR-10 | Both safe-details documents forged consistently against a new key conflict with persisted logical-run identity and fail closed. |
| PAIR-11..15 | Existing STORED, PARSED, VALIDATED, MAPPED, and PROMOTED suffix matrix remains green. |
| PAIR-16 | Existing frozen `post_cutoff` controls remain ineligible. |
| PAIR-17 | Existing ordinary import and resume retain processing-time cutoff safety. |
| PAIR-18 | Existing cross-host-clock synthetic replay semantics remain identical. |

## Results

```text
PAIR direct corruption suite: 8 passed in 2.28s
Focused pair/temporal/lifecycle/idempotency/concurrency/boundary: 104 passed in 66.35s
PostgreSQL 18.4 integration: 126 passed, 140 deselected in 283.03s
Migration matrix: PASS; zero new operations
FPL replay CLI: exit 0; status USABLE; source bundle present
Ruff format/lint: PASS
mypy: 245 source files clean
secret scan: 0 findings
```

Automatic branch CI remains subject to the already established monolithic 35-minute coverage
timeout. Independent re-review of this remediation is pending. Human acceptance, merge, downstream
stack replay, CI sharding, and PR #16 modification are not claimed or authorized.
