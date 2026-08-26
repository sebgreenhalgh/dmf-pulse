# CURRENT-FPL-STATE-001B plan and preflight

- Exact parent: `ee16489054ff78c59eb67897e5e9e52f785ccd6e`.
- Branch: `integration/current-fpl/CURRENT-FPL-STATE-001B-fpl-odds-identity`.
- Donor branch: `readiness/GW1-2026-27-live-input-initial-squad` at
  `d4cc759d4600489c21ba738cfc9b357cc380554e`.
- Startup: `origin/main` matched the pinned parent; its first and second parents are the accepted
  LIVE-ODDS-001 and CURRENT-FPL-STATE-001A lineages; the worktree was clean.
- Authority: A3 data-foundation, A4 FPL-ingestion, and A5 Odds source boundaries from the canonical
  authority manifest, constrained by the accepted FPL manual profile and LIVE-ODDS rights object.
- Implementation: additive current mapping contracts in `mapping.py`, a new `identity.py`, and
  synthetic tests. The historical `OddsMappingPlan` remains unchanged.
- Verification: focused branch coverage at or above 90%, inherited source regressions, required
  PostgreSQL acceptance, Ruff, mypy, build/wheel checks, repository validation, secret scan, exact
  final-SHA push CI, and no post-CI commit.

No real current mapping data, provider request, official-FPL request, persistence, PR, merge,
activation, independent review, or human acceptance is part of this plan.

## Independent-review remediation

- Deficient reviewed SHA: `d59a105669f271dfe0cfcb9b31b28becc922a11a`.
- Finding: material-P2 `CFSB-REV-001`.
- Policy: the exact plan and resolved authority must equal participant strings observed across all
  supplied Odds events, including outside-target events used for collision checks.
- Validation: focused RED-to-GREEN, branch-aware coverage, inherited FPL/Odds/PostgreSQL gates,
  static/build/wheel/security gates, canonical manifests, and one automatic exact-SHA push CI.
- Final boundary: remediated pending independent re-review; no PR, merge, acceptance, or 001C.
