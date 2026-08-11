# MIN-007R5F3 finalization and provenance plan

1. Harden migration `20260807_0006` with database-enforced dataset, core-graph,
   and final-output lifecycle boundaries.
2. Recompute persisted core/final identities and counts from canonical rows;
   preserve exact replay and collision behavior.
3. Require a strict model-bound evaluation publication envelope and persist its
   model semantic, artifact, and family binding.
4. Exercise direct SQL freeze probes, migration checks, all 24 acceptance
   commands, and the existing R5F/R5G regression suites.
5. Commit once with the required message and verify the final tree is clean.

All provider/network access is excluded; fixtures and the disposable local
PostgreSQL service are the only external execution dependencies.
