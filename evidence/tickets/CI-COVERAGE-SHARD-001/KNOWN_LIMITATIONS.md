# CI-COVERAGE-SHARD-001 known limitations

- The evidence is sealed before publication, so the automatic final-SHA Actions run ID, shard
  runtimes, and combined coverage percentages are intentionally not written into the branch.
  They remain pending at the evidence snapshot and are reported externally after the one push.
- The available Windows host cannot provide the required GitHub-hosted Ubuntu execution boundary
  or a PostgreSQL 18.4 service equivalent to the workflow. Local validation therefore proves the
  planner, exact real-repository partition, workflow contract, static/build/repository/security
  gates, and any practical shard execution; the automatic workflow is decisive for all eight
  PostgreSQL-backed shards and downstream acceptance.
- Balancing uses immutable repository-local weight overrides plus a deterministic fallback, not
  mutable runtime telemetry. This preserves reproducibility; later material changes to the test
  population or runtime profile require a separately reviewed weight update.
- The final status remains pending independent review. Human acceptance, merge, production
  activation, PR #16 changes, and LIVE-ODDS integration are not claimed or performed.
