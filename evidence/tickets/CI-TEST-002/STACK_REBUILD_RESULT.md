# Downstream correctness stack rebuild result

Status:
`DOWNSTREAM_CORRECTNESS_STACK_REBUILT_PENDING_INDEPENDENT_LINEAGE_CONFIRMATION_WITH_KNOWN_EXTERNAL_CI_ARCHITECTURE_BLOCKER`.

## Linear boundaries

- Corrected Layer A: `d41be2df28e7a74b67563056adea4ccc963ac04c`.
- New Layer B: `af78cedc65bd043343825facae947b8aed5340a4`, direct child of Layer A.
- New Layer C: the direct-child commit containing this result; exact local/remote SHA is reported
  after the commit and single push because a commit cannot contain its own object ID.
- Branch: `rebuild/post-A-FPL-001-correctness-stack`.

## Mechanical identity

- CI-TEST-001 old/new blob:
  `ed97b7944a24eb1c7440f5a3f31cf524f38a7157`; stable patch ID
  `2e77cb8598a54ffaf138ab2bc669227f35e81398`; both `IDENTICAL`.
- CI-TEST-002 old/new blob:
  `1141bfb59b94901973241bede6f8cb601c63e0d9`; stable patch ID
  `318e4f84282bc5ed73a3270a8c1571aff81f8742`; both `IDENTICAL`.
- Production `src`, workflows, migrations, dependencies, lock, runtime configuration, timeout,
  sharding, and coverage configuration are byte-identical to corrected Layer A.
- CI-GOV and diagnostic executable artifacts are absent.

## Local validation

- CI-TEST-001 module: 11 passed.
- CI-TEST-002 module: 6 passed baseline and 6 passed with `GITHUB_ACTIONS=true`.
- FPL pair-context integrity: 8 passed.
- Focused FPL replay/lifecycle/temporal identity: 28 passed.
- PostgreSQL 18.4 integration: 126 passed, 140 deselected, zero failures.
- Optional non-performance run: 3090 passed and one expected pre-seal manifest-drift failure;
  after the canonical manifest refresh, that exact repository-manifest test passed.
- Ruff format/lint, strict mypy, repository validation, and secret scan passed; repository errors
  and secret findings were zero.

The old reviewed branches, corrected CI-FPL branch, LIVE-ODDS head, and PR #16 remain immutable.
Automatic GitHub CI, independent lineage confirmation, human acceptance, merge, and CI sharding
remain separate.
