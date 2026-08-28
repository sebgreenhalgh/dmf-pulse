# CURRENT-FPL-STATE-001D plan and preflight

- Exact parent: `716ea3a90c8893081bfebce400020b07ce95a463`.
- Branch: `integration/current-fpl/CURRENT-FPL-STATE-001D-unified-current-state`.
- Authority: A2 rules, A4 FPL ingestion, A5 Odds manual import, A10 one-Gameweek tactics,
  B2 multi-Gameweek transfer state, and B4 chip scopes from the canonical authority manifest.
- Inputs: accepted in-memory `CurrentFplInputBundle`, `OddsProviderCurrentInput`,
  `FplOddsIdentityMap`, `CurrentManagerStateBundle`, ACTIVE ruleset, and exact FULL_SEASON
  capability artifact.
- Output: one immutable private current decision-source bundle with exact context, lineage,
  effective rights/runtime, safe summary, and deterministic composition identity.
- Verification: reconstruct 001B from its embedded exact plans and supplied FPL/Odds sources;
  invoke the accepted 001C verifier with exact FPL/rules/capability sources; independently compare
  the final composition with all external dependencies.
- Acceptance: GW2+, pre-deadline cutoff, two target fixtures plus an unrelated future event,
  source-substitution and nested-tamper matrices, at least 90% focused branch coverage, inherited
  predecessor/rules/chip suites, PostgreSQL, static/build/clean-wheel, repository, secret, and
  exact final-SHA CI gates.
- Independent remediation: preserve reviewed deficient SHA `049753...`; close
  `CFSC-001D-IR-001` with a complete materialized FPL representation digest at the 001D boundary;
  close `CFSC-001D-IR-002` with local detail-free identity/manager error translation; retain both
  findings as independent-review history and require a new independent re-review.

No source acquisition, provider call, real current data, database/persistence by 001D, fuzzy
mapping, market normalisation, modelling, optimisation, orchestration, Decision Bundle,
production activation, PR, merge, or human acceptance is part of this plan.
