# CI-COVERAGE-SHARD-001 final self-review

Current engineering status:
`REVIEW_REMEDIATION_READY_PENDING_FINAL_SHA_CI_AND_INDEPENDENT_REREVIEW`.

The full independent review at `b8ce5de` found GOV-001 and CI-REV-001 after the earlier engineering
review recorded below. This section preserves that chronology rather than treating the earlier
zero-finding snapshot as the final independent verdict.

## Review-remediation controls

- GOV-001: the owner supplied a post-review amendment ratifying only the exact unchanged ANSI
  observation deltas in `4da506d8`; independent confirmation remains pending.
- CI-REV-001: the validator now requires exactly four unique mandatory result clauses joined only
  by OR and rejects AND, missing, duplicate, or inverted clauses and missing in-branch `exit 1`.
- Workflow-contract tests independently parse the predicate instead of checking token presence.
- All-AND, one-AND, missing-result, duplicate-result, inverted-comparison, missing-exit,
  missing-`always()`, and missing-need mutations are required to fail.
- `.github/workflows/ci.yml`, both owner-ratified test blobs, product source, migrations, config,
  fixtures, and dependencies remain unchanged from `b8ce5de`.
- Final-SHA CI and independent re-review remain pending; no human acceptance or merge is claimed.

Current engineering self-assessment after focused remediation validation: P0 0; P1 0; unresolved
material P2 0; P3 0. This is not an independent closure claim.

## P0 controls

- Test omission: exact fresh pytest collection, canonical plan reconstruction, and union equality
  fail closed; real audit found zero missing nodeids.
- Branch coverage loss: every shard proves arcs before upload and the combined JSON must contain
  populated branch totals before the GCS gate.
- Final threshold bypass: per-shard zero is transport-only; the combination job independently runs
  both terminal and JSON coverage gates with `--fail-under=90`.
- False-green sentinel: `quality` uses `always()` and explicitly requires `success` from pre-flight,
  the complete matrix aggregate, combination, and post-coverage acceptance.
- Downstream command loss: structural tests compare every inherited command body and both existing
  GCS conditions; no command was removed.

## P1 controls

- Duplicate/overlapping selection, missing/extra artifacts, renamed payloads, commit/plan/assignment
  mismatches, byte/hash tampering, missing arcs, and fresh-collection drift all have negative tests.
- Assignment ordering, path normalization, module grouping, weight ordering, and tie-breaking are
  deterministic and platform-independent without changing parameter-id suffixes.
- Matrix `fail-fast: false` improves diagnosis only; all shards remain mandatory to combination and
  to the final sentinel.
- PostgreSQL remains pinned to 18.4 in pre-flight, every shard, and post-coverage, with Alembic
  initialization in each fresh database job.
- Coverage artifacts have unique names and immutable upload semantics; `overwrite` is forbidden.
- The exact stable job name remains `Python 3.13 / Ubuntu`.

## Material P2 controls

- Raw test count was rejected as a balancing signal. Static heavy-module weights produced estimated
  loads of 1050, then seven loads of 960-961; the heaviest estimated shard ran locally in 10m06.98s.
- The plan records population and assignment identities, while artifact metadata binds commit,
  plan, assignment, bytes, hash, branch arcs, and measured files.
- The implementation is confined to workflow/planner/tests, the narrowly necessary repository CI
  validator contract, and ticket/governance evidence. Product/runtime scope is untouched.

## Independent adversarial review

One material issue was found during review: artifact uploads initially allowed overwrite. It was
removed and regression-guarded so duplicate/colliding producers fail. The final review reports:

- P0: 0
- P1: 0
- Material P2: 0
- P3: 0

## First-run classification and correction review

- Run `32676529440` executed all 3,133 assignments exactly once: yes.
- Six shard transports passed and two failed only on 11 ANSI-sensitive assertions: yes.
- Maximum job runtime stayed below 25 and 35 minutes: yes; 13m16s.
- Missing/duplicate tests, timeout, cancellation, database, or artifact collision caused failure:
  no.
- Combined/post gates skipped and the sentinel failed instead of reporting green: yes.
- Raw output contained the required message and every expected exit code: yes.
- Correction follows the accepted CI-TEST-002 `Text.from_ansi(...).plain` pattern: yes.
- Commands, inputs, exit checks, wording, color behavior, product, workflow, and dependencies changed:
  no.
- Complete affected modules passed: yes; 35 passed.
- Independent correction review findings: P0 0; P1 0; material P2 0; P3 0.

Corrected automatic final-SHA CI and independent acceptance remain pending. This self-review does
not claim human acceptance, authorize merge, or alter LIVE-ODDS.
