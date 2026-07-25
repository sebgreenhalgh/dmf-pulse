# FPL-004 definition of ready

- The branch is `stage/A4/FPL-004-official-ingestion` at required baseline `9b3160a2574d2868b5f26e3a2d429924567510b0`, and the initial worktree is clean.
- Pack 004, every detached hash, every synthetic fixture, and every expected oracle validate unchanged.
- The controlling rights register and both versioned Rights Profiles are present and consistent: only `synthetic_test_v1` permits the complete persistent pipeline.
- Docker Compose can run the pinned PostgreSQL 18.4 service; no SQLite substitute or live provider service is required.
- DAT-003 remediation, lifecycle/resume, payload, mapping, observation, bundle, HTTP, CLI, migration, security, and review-pack contracts are understood.
- The official profile permits bounded transient manual validation only. It denies automated access, raw storage, persistent derived storage, bundle creation, backup, training, display, and redistribution.
- No real FPL payload, credential, authenticated endpoint, name-only identity merge, new dependency, destructive migration decision, or live request is required.
- The exact 25-command acceptance sequence can run deterministically using synthetic fixtures and local PostgreSQL, with command 20 expected to exit 4 as `RIGHTS_BLOCKED` before transport.
