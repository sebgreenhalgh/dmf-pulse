# CURRENT-FPL-STATE-001C plan and preflight

- Exact parent: `e53ec45badcf00acfdad37dc51fd5d8572d7a505`.
- Branch: `integration/current-fpl/CURRENT-FPL-STATE-001C-operator-manager-state`.
- Startup: `origin/main` matched the pinned parent; first-parent history contained merged
  LIVE-ODDS-001, CURRENT-FPL-STATE-001A, and CURRENT-FPL-STATE-001B; the worktree was clean.
- Authority: A2 rules, A4 FPL ingestion, A10 one-Gameweek tactics, B2 multi-Gameweek transfer
  state, and B4 chip scopes from the canonical authority manifest.
- Inputs: one descriptor-bound operator-owned JSON declaration, the accepted immutable 001A
  bundle, one ACTIVE target ruleset, and its exact FULL_SEASON capability artifact.
- Output: one immutable private bundle with source/attestation class, resolved catalogue facts,
  rule-derived prices, legal current squad/tactics, exact configured chip-token inventory,
  rights/time boundaries, safe summary, and deterministic semantic lineage.
- Verification: focused branch coverage at or above 90%, inherited 001A/001B/Stage-11/Stage-14
  tests, required PostgreSQL acceptance, Ruff, mypy, build/wheel gates, repository validation,
  secret scan, exact final-SHA push CI, and no post-CI commit.

No real manager state, provider request, credential, account identifier, persistence, database
use by 001C, optimiser execution, PR, merge, human acceptance, or production activation is part
of this plan.
