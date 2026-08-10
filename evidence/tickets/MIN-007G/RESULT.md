# MIN-007G result

Status: **PASS**

- Required parent: `9ca984b785b681531b7c0648cfbbb45c436dc075`.
- No migration; Alembic parent and single head remain `20260807_0006`.
- Acceptance: 24/24 literal commands passed; PostgreSQL 18.4 was removed before handoff.
- Frozen artifact/evaluation/registry identities: `80d1aa4cfd4a80eb7f7b291899fd9cf6173b017e308ea3b41d450a7bc87e2aeb`, `f2d075a9497331b73bf896be4610b684f8a3ed41eb17248a27284c79556cd748`, and `895a7e2a870192ba3ab395d459235f5ed374a562acd5628121de30f8e8ea4c72`.
- Projection uses exact Decimal composition, 91-bin PMFs, deterministic HALF_EVEN rounding, and validated immutable public models.
- CLI dataset build, fit, evaluate, projected prediction, and blocked prediction passed; blocked prediction exits 42 and adds no rows.
- Frozen modelling identities and prior availability/markets regressions are unchanged.
- Final commit and clean worktree are verified separately.
