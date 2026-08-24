# CI-COVERAGE-SHARD-001 final self-review

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

Automatic final-SHA CI and independent acceptance remain pending. This self-review does not claim
human acceptance, authorize merge, or alter LIVE-ODDS.
